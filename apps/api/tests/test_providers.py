import asyncio
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from emporia_api.providers import (
    ProviderGateway,
    ProviderNotConfigured,
    ProviderRequestError,
)
from emporia_api.schemas import ChatCompletionRequest


def make_config(**overrides):
    values = {
        "openai_api_key": None,
        "anthropic_api_key": None,
        "gemini_api_key": None,
        "openai_compatible_base_url": None,
        "openai_compatible_api_key": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_openai_gateway_uses_server_secret_and_normalizes_response():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["authorization"]
        seen["body"] = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Hello from OpenAI"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            },
            headers={"x-request-id": "req_openai_test"},
        )

    config = make_config(openai_api_key=SecretStr("server-only-secret"))
    gateway = ProviderGateway(config, transport=httpx.MockTransport(handler))
    request = ChatCompletionRequest(
        provider="openai",
        model="gpt-5",
        messages=[
            {"role": "system", "content": "Be useful"},
            {"role": "user", "content": "Hello"},
        ],
        max_tokens=50,
    )

    reply = asyncio.run(gateway.complete(request))

    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["authorization"] == "Bearer server-only-secret"
    assert seen["body"]["max_completion_tokens"] == 50
    assert reply.content == "Hello from OpenAI"
    assert reply.total_tokens == 10
    assert reply.request_id == "req_openai_test"


def test_anthropic_gateway_builds_messages_and_system_prompt():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "Claude says hello"}],
                "usage": {"input_tokens": 11, "output_tokens": 4},
            },
        )

    config = make_config(anthropic_api_key=SecretStr("anthropic-secret"))
    gateway = ProviderGateway(config, transport=httpx.MockTransport(handler))
    request = ChatCompletionRequest(
        provider="anthropic",
        model="claude-sonnet",
        messages=[
            {"role": "system", "content": "Act as a helpful assistant"},
            {"role": "user", "content": "Hello"},
        ],
    )

    reply = asyncio.run(gateway.complete(request))

    assert seen["headers"]["x-api-key"] == "anthropic-secret"
    assert seen["headers"]["anthropic-version"] == "2026-10-21"
    assert seen["body"]["system"] == "Act as a helpful assistant"
    assert reply.content == "Claude says hello"
    assert reply.total_tokens == 15


def test_gemini_gateway_builds_generate_content_request():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "Gemini response"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 9,
                    "candidatesTokenCount": 5,
                    "totalTokenCount": 14,
                },
            },
        )

    config = make_config(gemini_api_key=SecretStr("gemini-secret"))
    gateway = ProviderGateway(config, transport=httpx.MockTransport(handler))
    request = ChatCompletionRequest(
        provider="gemini",
        model="gemini-3.5-flash",
        messages=[
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "Hello"},
        ],
        max_tokens=64,
    )

    reply = asyncio.run(gateway.complete(request))

    assert seen["url"].endswith("/models/gemini-3.5-flash:generateContent")
    assert seen["headers"]["x-goog-api-key"] == "gemini-secret"
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "Be concise"
    assert reply.content == "Gemini response"
    assert reply.total_tokens == 14


def test_openai_compatible_gateway_calls_only_operator_configured_url():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Local model response"}}]},
        )

    config = make_config(
        openai_compatible_base_url="http://model-server:11434/v1",
        openai_compatible_api_key=SecretStr("local-key"),
    )
    gateway = ProviderGateway(config, transport=httpx.MockTransport(handler))
    request = ChatCompletionRequest(
        provider="openai-compatible",
        model="qwen-local",
        messages=[{"role": "user", "content": "Hello"}],
    )

    reply = asyncio.run(gateway.complete(request))

    assert seen["url"] == "http://model-server:11434/v1/chat/completions"
    assert seen["authorization"] == "Bearer local-key"
    assert reply.content == "Local model response"


def test_gateway_refuses_unconfigured_provider():
    gateway = ProviderGateway(make_config())
    request = ChatCompletionRequest(
        provider="openai",
        model="gpt-5",
        messages=[{"role": "user", "content": "Hello"}],
    )

    with pytest.raises(ProviderNotConfigured):
        asyncio.run(gateway.complete(request))


def test_compatible_gateway_rejects_credentialed_base_url():
    config = make_config(
        openai_compatible_base_url="http://user:password@untrusted.example/v1"
    )
    gateway = ProviderGateway(config)
    request = ChatCompletionRequest(
        provider="openai-compatible",
        model="local-model",
        messages=[{"role": "user", "content": "Hello"}],
    )

    with pytest.raises(ProviderRequestError, match="absolute HTTP"):
        asyncio.run(gateway.complete(request))
