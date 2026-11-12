from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from emporia_api.config import settings


class ResearchNotConfigured(Exception):
    """Raised when Brave Search credentials are not configured."""


class ResearchRequestError(Exception):
    """Raised when the upstream search API fails or returns invalid data."""


class ResearchRateLimited(Exception):
    """Raised when Brave Search signals that its request budget is exhausted."""

    def __init__(self, retry_after: float = 1.0) -> None:
        self.retry_after = max(1.0, min(retry_after, 60.0))
        super().__init__("Brave Search rate limit reached")


@dataclass(frozen=True)
class ResearchSource:
    index: int
    url: str
    title: str
    hostname: str
    snippets: tuple[str, ...]
    age: tuple[str, ...]


@dataclass(frozen=True)
class WebResearchResult:
    query: str
    sources: tuple[ResearchSource, ...]
    request_id: str | None


class BraveSearchClient:
    """Brave LLM Context API adapter with bounded, rate-aware, fixed-origin requests."""

    endpoint = "https://api.search.brave.com/res/v1/llm/context"

    def __init__(
        self,
        config: Any = settings,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 30.0,
        minimum_interval_seconds: float = 1.0,
    ) -> None:
        self.config = config
        self.transport = transport
        self.timeout = httpx.Timeout(timeout_seconds, connect=8.0)
        self.minimum_interval_seconds = max(1.0, minimum_interval_seconds)
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0

    @staticmethod
    def _secret(value: SecretStr | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, SecretStr):
            return value.get_secret_value() or None
        return value or None

    def configured(self) -> bool:
        return bool(self._secret(self.config.brave_search_api_key))

    @staticmethod
    def _retry_after(value: str | None) -> float:
        if not value:
            return 1.0
        try:
            return max(1.0, min(float(value), 60.0))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                return max(1.0, min((retry_at - datetime.now(UTC)).total_seconds(), 60.0))
            except (TypeError, ValueError, OverflowError):
                return 1.0

    async def search(
        self,
        query: str,
        maximum_number_of_tokens: int = 4000,
        country: str = "US",
        search_lang: str = "en",
    ) -> WebResearchResult:
        if not self.configured():
            raise ResearchNotConfigured("Brave Search is not configured on this server")

        normalized_query = query.strip()
        if not normalized_query or len(normalized_query) > 600:
            raise ValueError("Search query must contain 1 to 600 characters")
        if not 1024 <= maximum_number_of_tokens <= 8192:
            raise ValueError("Search context budget must be between 1024 and 8192 tokens")

        normalized_country = country.strip().upper()
        normalized_language = search_lang.strip().lower()
        if not re.fullmatch(r"[A-Z]{2}", normalized_country):
            raise ValueError("Country must be a two-letter ISO country code")
        if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,4})?", normalized_language):
            raise ValueError("Search language must be a valid language tag such as en or zh-hans")

        key = self._secret(self.config.brave_search_api_key)
        headers = {
            "X-Subscription-Token": key or "",
            "Accept": "application/json",
        }
        params = {
            "q": normalized_query,
            "country": normalized_country.lower(),
            "search_lang": normalized_language,
            "maximum_number_of_tokens": maximum_number_of_tokens,
            "context_threshold_mode": "balanced",
            "safesearch": "strict",
            "enable_source_metadata": "true",
        }

        try:
            async with self._request_lock:
                elapsed = time.monotonic() - self._last_request_at
                if elapsed < self.minimum_interval_seconds:
                    await asyncio.sleep(self.minimum_interval_seconds - elapsed)
                self._last_request_at = time.monotonic()
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    transport=self.transport,
                    follow_redirects=False,
                ) as client:
                    response = await client.get(
                        self.endpoint,
                        headers=headers,
                        params=params,
                    )
        except httpx.TimeoutException as exc:
            raise ResearchRequestError("Brave Search request timed out") from exc
        except httpx.RequestError as exc:
            raise ResearchRequestError("Could not connect to Brave Search") from exc

        if response.status_code == 429:
            raise ResearchRateLimited(self._retry_after(response.headers.get("retry-after")))
        if response.is_error:
            raise ResearchRequestError(f"Brave Search returned HTTP {response.status_code}")

        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("Response root must be an object")
            grounding = payload.get("grounding") or {}
            if not isinstance(grounding, dict):
                raise TypeError("Grounding must be an object")
            generic = grounding.get("generic") or []
            if not isinstance(generic, list):
                raise TypeError("Grounding generic field must be an array")
            source_metadata = payload.get("sources") or {}
            if not isinstance(source_metadata, dict):
                source_metadata = {}

            sources: list[ResearchSource] = []
            for item in generic:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                if not isinstance(url, str):
                    continue
                parts = urlsplit(url)
                if (
                    parts.scheme not in {"https", "http"}
                    or not parts.hostname
                    or parts.username
                    or parts.password
                ):
                    continue

                metadata = source_metadata.get(url) or {}
                if not isinstance(metadata, dict):
                    metadata = {}
                raw_snippets = item.get("snippets")
                if not isinstance(raw_snippets, list):
                    raw_snippets = []
                raw_age = metadata.get("age")
                if not isinstance(raw_age, list):
                    raw_age = [raw_age] if raw_age is not None else []

                sources.append(
                    ResearchSource(
                        index=len(sources) + 1,
                        url=url,
                        title=str(item.get("title") or metadata.get("title") or url)[:300],
                        hostname=str(metadata.get("hostname") or parts.hostname)[:200],
                        snippets=tuple(
                            snippet[:3000]
                            for snippet in raw_snippets[:4]
                            if isinstance(snippet, str) and snippet.strip()
                        ),
                        age=tuple(
                            value[:100]
                            for value in raw_age[:4]
                            if isinstance(value, str)
                        ),
                    )
                )
                if len(sources) >= 8:
                    break
        except (ValueError, AttributeError, TypeError) as exc:
            raise ResearchRequestError("Brave Search returned an invalid response") from exc

        return WebResearchResult(
            query=normalized_query,
            sources=tuple(sources),
            request_id=response.headers.get("x-request-id") or response.headers.get("request-id"),
        )
