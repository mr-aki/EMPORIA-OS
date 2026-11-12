"""Research orchestration and evidence consolidation."""
# ruff: noqa: I001

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from emporia_api.network.brave_search import BraveSearchClient


_TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}


def canonicalize_source_url(url: str) -> str:
    """Normalize common URL variants for deduplication without changing display URLs."""
    parts = urlsplit(url)
    hostname = (parts.hostname or "").lower().rstrip(".")
    hostname = hostname.removeprefix("www.")
    try:
        port = parts.port
    except ValueError:
        port = None
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if port and not (
        (parts.scheme.lower() == "https" and port == 443)
        or (parts.scheme.lower() == "http" and port == 80)
    ):
        netloc = f"{netloc}:{port}"
    path = parts.path.rstrip("/") or "/"
    query_items = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if not key.lower().startswith("utm_")
        and key.lower() not in _TRACKING_PARAMETERS
    ]
    normalized_query = urlencode(sorted(query_items))
    return urlunsplit(("https", netloc, path, normalized_query, ""))


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", value.casefold()))


def _lexical_relevance(query: str, title: str, snippets: list[str]) -> float:
    terms = _tokens(query)
    if not terms:
        return 0.0
    evidence_terms = _tokens(" ".join([title, *snippets]))
    return round(len(terms & evidence_terms) / len(terms), 3)


async def build_research_report(
    client: BraveSearchClient,
    *,
    queries: list[str],
    country: str,
    search_lang: str,
    maximum_number_of_tokens: int,
    max_sources: int,
) -> dict[str, object]:
    """Run bounded searches sequentially and consolidate duplicate source evidence.

    Only explicit query strings are sent to external search. Private task, workspace,
    and customer data are never accepted by or forwarded from this function.
    """
    grouped: dict[str, dict[str, object]] = {}
    coverage: dict[str, set[str]] = {query: set() for query in queries}
    request_ids: list[str] = []

    for query in queries:
        result = await client.search(
            query,
            maximum_number_of_tokens=maximum_number_of_tokens,
            country=country,
            search_lang=search_lang,
        )
        if result.request_id and result.request_id not in request_ids:
            request_ids.append(result.request_id)

        for source in result.sources:
            canonical_url = canonicalize_source_url(source.url)
            if not canonical_url:
                continue
            coverage[query].add(canonical_url)
            item = grouped.get(canonical_url)
            if item is None:
                item = {
                    "url": source.url,
                    "title": source.title,
                    "hostname": source.hostname,
                    "snippets": [],
                    "age": [],
                    "matched_queries": [],
                }
                grouped[canonical_url] = item

            if not item["title"] and source.title:
                item["title"] = source.title
            for snippet in source.snippets:
                if snippet not in item["snippets"]:
                    item["snippets"].append(snippet)
            for age in source.age:
                if age not in item["age"]:
                    item["age"].append(age)
            matched_queries = item["matched_queries"]
            if query not in matched_queries:
                matched_queries.append(query)

    ranked: list[dict[str, object]] = []
    for item in grouped.values():
        matched_queries = item["matched_queries"]
        snippets = item["snippets"]
        score = max(
            (
                _lexical_relevance(query, item["title"], snippets)
                for query in matched_queries
            ),
            default=0.0,
        )
        ranked.append({**item, "lexical_relevance_score": score})

    ranked.sort(
        key=lambda item: (
            -len(item["matched_queries"]),
            -item["lexical_relevance_score"],
            item["hostname"].casefold(),
            item["title"].casefold(),
        )
    )
    selected = ranked[:max_sources]
    sources = [
        {
            "index": index,
            "url": item["url"],
            "title": item["title"],
            "hostname": item["hostname"],
            "snippets": item["snippets"][:8],
            "age": item["age"][:8],
            "matched_queries": item["matched_queries"],
            "lexical_relevance_score": item["lexical_relevance_score"],
        }
        for index, item in enumerate(selected, start=1)
    ]

    return {
        "queries": queries,
        "request_ids": request_ids,
        "query_coverage": [
            {"query": query, "source_count": len(coverage[query])}
            for query in queries
        ],
        "total_unique_sources": len(grouped),
        "sources": sources,
        "relevance_method": "lexical_overlap",
        "limitations": [
            "Lexical relevance is a transparent term-overlap heuristic, not an AI quality score.",
            "Source authority and factual correctness are not independently verified.",
            "Published-age metadata is provider-supplied and may be missing or approximate.",
        ],
    }
