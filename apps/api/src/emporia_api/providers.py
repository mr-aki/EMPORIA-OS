from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from pydantic import SecretStr

from emporia_api.config import settings
from emporia_api.schemas import ChatCompletionRequest


class ProviderNotConfigured(Exception):
    """Raised when the selected provider has no server-side credentials."""


class ProviderRequestError(Exception):
    """Raised for a rejected or failed upstream provider request."""


@dataclass(frozen=True)
class ProviderDescriptor:
    id: str
    name: str
    protocol: str
    docs_url: str


PROVIDER_CATALOG = (
    ProviderDescriptor(
        "openai", "OpenAI", "openai-chat-completions",
        "https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create",
    ),
    ProviderDescriptor(
        "anthropic", "Anthropic Claude", "anthropic-messages",
        "https://platform.claude.com/docs/en/api/overview",
    ),
    ProviderDescriptor(
        "gemini", "Google Gemini", "gemini-generate-content",
        "https://ai.google.dev/api",
    ),
    ProviderDescriptor(
        "openai-compatible", "OpenAI-compatible / local model server", "openai-compatible-chat",
        "https://github.com/ollama/ollama/blob/main/docs/openai.md",
    ),
)


@dataclass(frozen=True)
class ProviderReply:
    provider: str
    model: str
    content: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    request_id: str | None


class ProviderGateway:
    """Server-side provider adapter. Callers cannot supply arbitrary upstream URLs."""

    def __init__(
        self,
        config: Any = settings,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.config = config
        self.transport = transport
        self.timeout = httpx.Timeout(timeout_seconds, connect=10.0)

    @staticmethod
    def _secret(value: SecretStr | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, SecretStr):
            return value.get_secret_value() or None
        return value or None

    def configured(self, provider_id: str) -> bool:
        if provider_id == "openai":
            return bool(self._secret(self.config.openai_api_key))
        if provider_id == "anthropic":
            return bool(self._secret(self.config.anthropic_api_key))
        if provider_id == "gemini":
            return bool(self._secret(self.config.gemini_api_key))
        if provider_id == "openai-compatible":
            return bool(self.config.openai_compatible_base_url)
        return False

    def catalog(self) -> list[dict[str, str | bool]]:
        return [
            {
                "id": item.id,
                "name": item.name,
                "configured": self.configured(item.id),
                "protocol": item.protocol,
                "docs_url": item.docs_url,
            }
            for item in PROVIDER_CATALOG
        ]

    async def complete(self, request: ChatCompletionRequest) -> ProviderReply:
        provider = request.provider
        if not self.configured(provider):
            raise ProviderNotConfigured(f"{provider} is not configured on this server")

        if provider == "openai":
            url, headers, body = self._openai_request(request)
        elif provider == "anthropic":
            url, headers, body = self._anthropic_request(request)
        elif provider == "gemini":
            url, headers, body = self._gemini_request(request)
        else:
            url, headers, body = self._compatible_request(request)

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise ProviderRequestError(f"{provider} request timed out") from exc
        except httpx.RequestError as exc:
            raise ProviderRequestError(f"Could not connect to {provider}") from exc

        if response.is_error:
            raise ProviderRequestError(
                f"{provider} returned HTTP {response.status_code}"
            )
        try:
            data = response.json()
            content, prompt_tokens, completion_tokens, total_tokens = self._parse(
                provider, data
            )
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderRequestError(f"{provider} returned an invalid response") from exc

        if not content.strip():
            raise ProviderRequestError(f"{provider} returned an empty response")

        return ProviderReply(
            provider=provider,
            model=request.model,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            request_id=(
                response.headers.get("request-id")
                or response.headers.get("x-request-id")
            ),
        )

    def _openai_request(self, request: ChatCompletionRequest):
        key = self._secret(self.config.openai_api_key)
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
            "max_completion_tokens": request.max_tokens,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        return (
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            body,
        )

    def _anthropic_request(self, request: ChatCompletionRequest):
        key = self._secret(self.config.anthropic_api_key)
        system_parts = [
            message.content for message in request.messages if message.role == "system"
        ]
        messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages if message.role != "system"
        ]
        body: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }
        if system_parts:
            body["system"] = "\n\n".join(system_parts)
        if request.temperature is not None:
            body["temperature"] = request.temperature
        return (
            "https://api.anthropic.com/v1/messages",
            {
                "x-api-key": key or "",
                "anthropic-version": "2026-10-21",
                "Content-Type": "application/json",
            },
            body,
        )

    def _gemini_request(self, request: ChatCompletionRequest):
        key = self._secret(self.config.gemini_api_key)
        model = quote(request.model, safe="-._:")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        contents = [
            {
                "role": "model" if message.role == "assistant" else "user",
                "parts": [{"text": message.content}],
            }
            for message in request.messages if message.role != "system"
        ]
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": request.max_tokens},
        }
        system_parts = [
            message.content for message in request.messages if message.role == "system"
        ]
        if system_parts:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        if request.temperature is not None:
            body["generationConfig"]["temperature"] = request.temperature
        return (
            url,
            {"x-goog-api-key": key or "", "Content-Type": "application/json"},
            body,
        )

    def _compatible_request(self, request: ChatCompletionRequest):
        base_url = self.config.openai_compatible_base_url
        parts = urlsplit(base_url or "")
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ProviderRequestError(
                "OpenAI-compatible base URL must be an absolute HTTP(S) URL without credentials"
            )
        key = self._secret(self.config.openai_compatible_api_key)
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
            "max_tokens": request.max_tokens,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        return f"{base_url.rstrip('/')}/chat/completions", headers, body

    @staticmethod
    def _parse(provider: str, data: dict[str, Any]):
        if provider in {"openai", "openai-compatible"}:
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if isinstance(content, list):
                content = "".join(
                    block.get("text", "") for block in content
                    if isinstance(block, dict)
                )
            usage = data.get("usage") or {}
            prompt = usage.get("prompt_tokens")
            completion = usage.get("completion_tokens")
            total = usage.get("total_tokens")
        elif provider == "anthropic":
            content = "".join(
                block.get("text", "") for block in data["content"]
                if block.get("type") == "text"
            )
            usage = data.get("usage") or {}
            prompt = usage.get("input_tokens")
            completion = usage.get("output_tokens")
            total = (
                prompt + completion
                if isinstance(prompt, int) and isinstance(completion, int)
                else None
            )
        else:
            candidate = data["candidates"][0]
            content = "".join(
                part.get("text", "") for part in candidate["content"]["parts"]
                if isinstance(part, dict)
            )
            usage = data.get("usageMetadata") or {}
            prompt = usage.get("promptTokenCount")
            completion = usage.get("candidatesTokenCount")
            total = usage.get("totalTokenCount")
        return content, prompt, completion, total
