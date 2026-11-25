import asyncio

from emporia_api.network.brave_search import ResearchSource, WebResearchResult
from emporia_api.research.report import build_research_report, canonicalize_source_url


def test_canonicalize_source_url_removes_only_known_tracking_variants():
    canonical = canonicalize_source_url(
        "HTTPS://WWW.Example.com:443/products/sku-1/"
        "?utm_source=email&fbclid=click-id#details"
    )

    assert canonical == "https://example.com/products/sku-1"


def test_canonicalize_source_url_preserves_functional_source_and_ref_parameters():
    amazon = canonicalize_source_url(
        "https://shop.example/products/watch?source=amazon&ref=SKU-1"
    )
    ebay = canonicalize_source_url(
        "https://shop.example/products/watch?source=ebay&ref=SKU-1"
    )
    another_product = canonicalize_source_url(
        "https://shop.example/products/watch?source=amazon&ref=SKU-2"
    )

    assert amazon != ebay
    assert amazon != another_product


def test_canonicalize_source_url_preserves_blank_and_repeated_query_values():
    blank_filter = canonicalize_source_url(
        "https://shop.example/search?available=&tag=red&tag=blue"
    )
    without_filter = canonicalize_source_url(
        "https://shop.example/search?tag=red&tag=blue"
    )
    reversed_tags = canonicalize_source_url(
        "https://shop.example/search?available=&tag=blue&tag=red"
    )

    assert blank_filter != without_filter
    assert blank_filter != reversed_tags


def test_canonicalize_source_url_does_not_merge_http_and_https_resources():
    http_url = canonicalize_source_url("http://shop.example/products/watch")
    https_url = canonicalize_source_url("https://shop.example/products/watch")

    assert http_url != https_url


def test_canonicalize_source_url_rejects_unsupported_or_credentialed_urls():
    assert canonicalize_source_url("ftp://shop.example/products/watch") == ""
    assert canonicalize_source_url("https://user:secret@shop.example/products/watch") == ""
    assert canonicalize_source_url("https://shop.example:invalid/products/watch") == ""


def test_research_report_deduplicates_tracking_variants_but_keeps_distinct_products():
    queries = ["smart watch demand", "smart watch pricing"]
    first_result = WebResearchResult(
        query=queries[0],
        request_id="brave-request-1",
        sources=(
            ResearchSource(
                index=1,
                url=(
                    "https://www.shop.example/products/watch"
                    "?source=amazon&utm_campaign=first"
                ),
                title="Smart watch demand report",
                hostname="shop.example",
                snippets=("Smart watch demand is growing.",),
                age=("2026-11-20",),
            ),
            ResearchSource(
                index=2,
                url="https://shop.example/products/watch?source=ebay",
                title="Smart watch competitor pricing",
                hostname="shop.example",
                snippets=("Competitor prices are stable.",),
                age=(),
            ),
        ),
    )
    second_result = WebResearchResult(
        query=queries[1],
        request_id="brave-request-2",
        sources=(
            ResearchSource(
                index=1,
                url=(
                    "https://shop.example/products/watch"
                    "?source=amazon&utm_medium=email"
                ),
                title="Amazon smart watch pricing",
                hostname="shop.example",
                snippets=("Marketplace pricing evidence.",),
                age=("2026-11-21",),
            ),
            ResearchSource(
                index=2,
                url="https://shop.example/products/watch?source=ebay",
                title="Smart watch competitor prices",
                hostname="shop.example",
                snippets=("A second pricing observation.",),
                age=(),
            ),
        ),
    )

    class FakeSearchClient:
        def __init__(self):
            self.results = [first_result, second_result]
            self.calls = []

        async def search(self, query, **kwargs):
            self.calls.append((query, kwargs))
            return self.results.pop(0)

    client = FakeSearchClient()
    report = asyncio.run(
        build_research_report(
            client,
            queries=queries,
            country="US",
            search_lang="en",
            maximum_number_of_tokens=2048,
            max_sources=10,
        )
    )

    assert len(client.calls) == 2
    assert report["total_unique_sources"] == 2
    assert report["request_ids"] == ["brave-request-1", "brave-request-2"]
    assert report["query_coverage"] == [
        {"query": queries[0], "source_count": 2},
        {"query": queries[1], "source_count": 2},
    ]

    amazon_source = next(
        source for source in report["sources"] if "source=amazon" in source["url"]
    )
    ebay_source = next(
        source for source in report["sources"] if "source=ebay" in source["url"]
    )
    assert amazon_source["matched_queries"] == queries
    assert amazon_source["snippets"] == [
        "Smart watch demand is growing.",
        "Marketplace pricing evidence.",
    ]
    assert amazon_source["age"] == ["2026-11-20", "2026-11-21"]
    assert ebay_source["matched_queries"] == queries
    assert ebay_source["snippets"] == [
        "Competitor prices are stable.",
        "A second pricing observation.",
    ]
