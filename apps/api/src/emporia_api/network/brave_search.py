from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import SecretStr

from emporia_api.config import settings


class ResearchNotConfigured(Exception):
    """Raised when Brave Search credentials are not configured."""


class ResearchRequestError(Exception):
    """Raised when the upstream search API fails or returns invalid data."""


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
    ) -> None:
        self.config = config
        self.transport = transport
        self.timeout = httpx.Timeout(timeout_seconds, connect=8.0)

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
    ) -> WebResearchResult:
        if not self.configured():
            raise ResearchNotConfigured("Brave Search is not configured on this server")
        normalized_query = query.strip()
        if not normalized_query or len(normalized_query) > 600:
            raise ValueError("Search query must contain 1 to 600 characters")
        if not 1000 <= maximum_number_of_tokens <= 8192:
            raise ValueError("Search context budget must be between 1000 and 8192 tokens")

        key = self._secret(self.config.brave_search_api_key)
        headers = {
            "X-Subscription-Token": key or "",
            "Accept": "application/json",
        }
        params = {
            "q": normalized_query,
            "maximum_number_of_tokens": maximum_number_of_tokens,
            "context_threshold_mode": "balanced",
            "safesearch": "strict",
            "enable_source_metadata": "true",
        }
        try:
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

        if response.is_error:
            raise ResearchRequestError(f"Brave Search returned HTTP {response.status_code}")
        try:
            payload = response.json()
            generic = payload.get("grounding", {}).get("generic", [])
            source_metadata = payload.get("sources", {})
            sources: list[ResearchSource] = []
            for item in generic:
                url = item.get("url")
                if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                    continue
                metadata = source_metadata.get(url, {})
                snippets = item.get("snippets", [])
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
                        for value in (metadata.get("age") or [])[:4]
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
