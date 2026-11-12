from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

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
    """Brave LLM Context API adapter with fixed origin and bounded search context."""

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
        if len(normalized_country) != 2 or not normalized_country.isalpha():
            raise ValueError("Country must be a two-letter ISO country code")
        if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,4})?", normalized_language):
            raise ValueError("Search language must be a valid language code such as en or zh-hans")

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
                    response = await client.get(self.endpoint, headers=headers, params=params)
        except httpx.TimeoutException as exc:
            raise ResearchRequestError("Brave Search request timed out") from exc
        except httpx.RequestError as exc:
            raise ResearchRequestError("Could not connect to Brave Search") from exc

        if response.status_code == 429:
            retry_after = response.headers.get("retry-after", "1")
            try:
                retry_seconds = float(retry_after)
            except ValueError:
                retry_seconds = 1.0
            raise ResearchRateLimited(retry_seconds)
        if response.is_error:
            raise ResearchRequestError(f"Brave Search returned HTTP {response.status_code}")
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("response root must be an object")
            grounding = payload.get("grounding")
            source_metadata = payload.get("sources")
            if not isinstance(grounding, dict) or not isinstance(source_metadata, dict):
                raise TypeError("response grounding and sources must be objects")
            generic = grounding.get("generic")
            if not isinstance(generic, list):
                raise TypeError("grounding.generic must be a list")
            sources: list[ResearchSource] = []
            for item in generic:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                    continue
                metadata = source_metadata.get(url) or {}
                if not isinstance(metadata, dict):
                    metadata = {}
                snippets = item.get("snippets") or []
                if not isinstance(snippets, list):
                    snippets = []
                sources.append(ResearchSource(
                    index=len(sources) + 1,
                    url=url,
                    title=str(item.get("title") or metadata.get("title") or url)[:300],
                    hostname=str(metadata.get("hostname") or "")[:200],
                    snippets=tuple(
                        str(snippet)[:3000]
                        for snippet in snippets[:4]
                        if isinstance(snippet, str) and snippet.strip()
                    ),
                    age=tuple(
                        str(value)[:100]
                        for value in ((metadata.get("age") if isinstance(metadata.get("age"), list) else [metadata.get("age")]) or [])[:4]
                        if isinstance(value, str)
                    ),
                ))
                if len(sources) >= 8:
                    break
        except (ValueError, AttributeError, TypeError) as exc:
            raise ResearchRequestError("Brave Search returned an invalid response") from exc

        return WebResearchResult(
            query=normalized_query,
            sources=tuple(sources),
            request_id=response.headers.get("x-request-id") or response.headers.get("request-id"),
        )
