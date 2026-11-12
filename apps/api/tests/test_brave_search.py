import asyncio
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from emporia_api.network.brave_search import (
    BraveSearchClient,
    ResearchNotConfigured,
    ResearchRequestError,
)


def make_config(api_key=None):
    return SimpleNamespace(brave_search_api_key=api_key)


def test_brave_context_search_sends_key_and_normalizes_grounding_sources():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["auth"] = request.headers.get("x-subscription-token")
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            headers={"x-request-id": "brave-req-123"},
            json={
                "grounding": {
                    "generic": [
                        {
                            "url": "https://example.com/market-report",
                            "title": "Market report",
                            "snippets": [
                                "The report describes a customer segment.",
                                "It explains category growth drivers.",
                            ],
                        }
                    ]
                },
                "sources": {
                    "https://example.com/market-report": {
                        "title": "Market report",
                        "hostname": "example.com",
                        "age": ["Published 2 weeks ago"],
                    }
                },
            },
        )

    client = BraveSearchClient(
        make_config(SecretStr("brave-private-key")),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(client.search("home organization ecommerce", 3000))

    assert captured["method"] == "GET"
    assert captured["url"].startswith(BraveSearchClient.endpoint)
    assert captured["auth"] == "brave-private-key"
    assert captured["params"]["q"] == "home organization ecommerce"
    assert captured["params"]["maximum_number_of_tokens"] == "3000"
    assert captured["params"]["safesearch"] == "strict"
    assert captured["params"]["enable_source_metadata"] == "true"
    assert result.request_id == "brave-req-123"
    assert result.query == "home organization ecommerce"
    assert len(result.sources) == 1
    source = result.sources[0]
    assert source.index == 1
    assert source.url == "https://example.com/market-report"
    assert source.hostname == "example.com"
    assert source.age == ("Published 2 weeks ago",)
    assert source.snippets[0].startswith("The report")


def test_brave_context_search_rejects_missing_credentials():
    client = BraveSearchClient(make_config())

    with pytest.raises(ResearchNotConfigured):
        asyncio.run(client.search("market research"))


@pytest.mark.parametrize(
    ("query", "budget"),
    [
        ("", 4000),
        ("x" * 601, 4000),
        ("valid query", 999),
        ("valid query", 8193),
    ],
)
def test_brave_context_search_rejects_invalid_query_or_context_budget(query, budget):
    client = BraveSearchClient(make_config(SecretStr("brave-key")))

    with pytest.raises(ValueError):
        asyncio.run(client.search(query, budget))


def test_brave_context_search_sanitizes_upstream_http_errors():
    def handler(_request):
        return httpx.Response(429, json={"error": "sensitive vendor payload"})

    client = BraveSearchClient(
        make_config(SecretStr("brave-key")),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ResearchRequestError, match="HTTP 429") as exc:
        asyncio.run(client.search("market research"))

    assert "sensitive vendor payload" not in str(exc.value)


def test_brave_context_search_rejects_malformed_payload():
    def handler(_request):
        return httpx.Response(200, json={"unexpected": "shape"})

    client = BraveSearchClient(
        make_config(SecretStr("brave-key")),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(client.search("market research"))
    assert result.sources == ()
