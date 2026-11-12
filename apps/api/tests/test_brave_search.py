import asyncio
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from emporia_api.network.brave_search import (
    BraveSearchClient,
    ResearchNotConfigured,
    ResearchRateLimited,
    ResearchRequestError,
)


def make_config(key="brave-test-secret"):
    return SimpleNamespace(
        brave_search_api_key=SecretStr(key) if key is not None else None
    )


def test_brave_search_uses_official_endpoint_and_normalizes_sources():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["token"] = request.headers.get("x-subscription-token")
        seen["query"] = dict(request.url.params)
        return httpx.Response(
            200,
            headers={"x-request-id": "brave-request-123"},
            json={
                "grounding": {
                    "generic": [
                        {
                            "url": "https://official.example/report",
                            "title": "Official Market Report",
                            "snippets": ["Evidence passage one.", "Evidence passage two."],
                        },
                        {
                            "url": "ftp://unsupported.example/data",
                            "title": "Invalid scheme",
                            "snippets": ["Must be skipped"],
                        },
                        {
                            "url": "https://user:secret@credentialed.example/data",
                            "title": "Credentialed URL",
                            "snippets": ["Must be skipped"],
                        },
                    ],
                    "map": [],
                },
                "sources": {
                    "https://official.example/report": {
                        "title": "Official Market Report",
                        "hostname": "official.example",
                        "age": [
                            "Wednesday, November 11, 2026",
                            "2026-11-11",
                            "1 day ago",
                            "2026-11-11T08:00:00Z",
                        ],
                        "description": "Publisher description",
                    }
                },
            },
        )

    client = BraveSearchClient(
        config=make_config(),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        client.search(
            "ecommerce returns report",
            maximum_number_of_tokens=4096,
            country="PK",
            search_lang="en",
        )
    )

    assert seen["url"].startswith("https://api.search.brave.com/res/v1/llm/context?")
    assert seen["token"] == "brave-test-secret"
    assert seen["query"]["q"] == "ecommerce returns report"
    assert seen["query"]["country"] == "pk"
    assert seen["query"]["search_lang"] == "en"
    assert seen["query"]["maximum_number_of_tokens"] == "4096"
    assert seen["query"]["context_threshold_mode"] == "balanced"
    assert seen["query"]["safesearch"] == "strict"
    assert seen["query"]["enable_source_metadata"] == "true"
    assert result.request_id == "brave-request-123"
    assert len(result.sources) == 1
    source = result.sources[0]
    assert source.url == "https://official.example/report"
    assert source.hostname == "official.example"
    assert source.snippets == ("Evidence passage one.", "Evidence passage two.")
    assert len(source.age) == 4


def test_brave_search_accepts_language_tags():
    client = BraveSearchClient(
        config=make_config(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"grounding": {"generic": []}, "sources": {}},
            )
        ),
    )
    result = asyncio.run(client.search("shopify shipping", search_lang="zh-hans"))
    assert result.sources == ()


def test_brave_search_handles_empty_context_without_fabricating_sources():
    client = BraveSearchClient(
        config=make_config(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"grounding": {"generic": []}, "sources": {}},
            )
        ),
    )
    result = asyncio.run(client.search("nothing relevant"))
    assert result.sources == ()
    assert result.query == "nothing relevant"


def test_brave_search_requires_server_side_api_key():
    client = BraveSearchClient(config=make_config(None))
    with pytest.raises(ResearchNotConfigured):
        asyncio.run(client.search("test query"))


@pytest.mark.parametrize(
    "query,budget,country,language",
    [
        ("", 4096, "US", "en"),
        ("x" * 601, 4096, "US", "en"),
        ("valid query", 1023, "US", "en"),
        ("valid query", 32769, "US", "en"),
        ("valid query", 4096, "USA", "en"),
        ("valid query", 4096, "US", "e"),
        ("valid query", 4096, "US", "en-verylong"),
    ],
)
def test_brave_search_rejects_invalid_inputs_before_network(
    query, budget, country, language
):
    client = BraveSearchClient(config=make_config())
    with pytest.raises(ValueError):
        asyncio.run(
            client.search(
                query,
                maximum_number_of_tokens=budget,
                country=country,
                search_lang=language,
            )
        )


def test_brave_search_surfaces_upstream_rate_limit_and_retry_after():
    client = BraveSearchClient(
        config=make_config(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                429,
                headers={"Retry-After": "3"},
                json={"error": "sensitive vendor payload"},
            )
        ),
    )
    with pytest.raises(ResearchRateLimited) as error:
        asyncio.run(client.search("query"))
    assert error.value.retry_after == 3.0
    assert "sensitive vendor payload" not in str(error.value)


def test_brave_search_handles_http_date_retry_after():
    client = BraveSearchClient(
        config=make_config(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                429,
                headers={"Retry-After": "Wed, 21 Oct 2037 07:28:00 GMT"},
                json={},
            )
        ),
    )
    with pytest.raises(ResearchRateLimited) as error:
        asyncio.run(client.search("query"))
    assert error.value.retry_after > 1.0


def test_brave_search_surfaces_upstream_authentication_failure():
    client = BraveSearchClient(
        config=make_config(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"error": "unauthorized"})
        ),
    )
    with pytest.raises(ResearchRequestError, match="HTTP 401"):
        asyncio.run(client.search("query"))


@pytest.mark.parametrize(
    "payload",
    [
        {"grounding": "not-an-object"},
        {"grounding": {"generic": "not-an-array"}},
        ["unexpected", "root"],
    ],
)
def test_brave_search_rejects_malformed_grounding_shape(payload):
    client = BraveSearchClient(
        config=make_config(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        ),
    )
    with pytest.raises(ResearchRequestError, match="invalid response"):
        asyncio.run(client.search("query"))
