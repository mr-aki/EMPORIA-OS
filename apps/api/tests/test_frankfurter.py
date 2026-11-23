import asyncio
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from emporia_api.finance.frankfurter import (
    FrankfurterClient,
    FXProviderError,
    FXProviderUnavailable,
    FXRateNotFound,
)


def test_frankfurter_fetches_normalized_pair_and_parses_decimal_rate():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "date": "2026-11-11",
                "base": "USD",
                "quote": "PKR",
                "rate": 279.123456,
            },
        )

    client = FrankfurterClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(client.get_rate("usd", "pkr"))

    assert captured["url"] == "https://api.frankfurter.dev/v2/rate/USD/PKR"
    assert "authorization" not in captured["headers"]
    assert result.base == "USD"
    assert result.quote == "PKR"
    assert result.date == date(2026, 11, 11)
    assert result.rate == Decimal("279.123456")
    assert result.provider == "frankfurter"


def test_frankfurter_passes_historical_date_as_query_parameter():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "date": "2025-12-31",
                "base": "EUR",
                "quote": "USD",
                "rate": "1.1725",
            },
        )

    client = FrankfurterClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        client.get_rate("EUR", "USD", date(2025, 12, 31))
    )

    assert captured["url"] == (
        "https://api.frankfurter.dev/v2/rate/EUR/USD?date=2025-12-31"
    )
    assert result.rate == Decimal("1.1725")


def test_frankfurter_caches_latest_observation_and_avoids_duplicate_requests():
    call_count = 0

    def handler(_request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "date": "2026-11-11",
                "base": "USD",
                "quote": "EUR",
                "rate": 0.86,
            },
        )

    client = FrankfurterClient(transport=httpx.MockTransport(handler))
    async def fetch_twice():
        first = await client.get_rate("USD", "EUR")
        second = await client.get_rate("USD", "EUR")
        return first, second

    first, second = asyncio.run(fetch_twice())
    assert first == second
    assert call_count == 1


def test_frankfurter_converts_amount_using_decimal_arithmetic():
    client = FrankfurterClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "date": "2026-11-11",
                    "base": "USD",
                    "quote": "PKR",
                    "rate": 279.125,
                },
            )
        )
    )
    result = asyncio.run(
        client.convert(Decimal("12.50"), "USD", "PKR")
    )
    assert result.amount == Decimal("12.50")
    assert result.rate.rate == Decimal("279.125")
    assert result.converted_amount == Decimal("3489.062500")


def test_frankfurter_maps_missing_pair_to_rate_not_found():
    client = FrankfurterClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(404, json={"message": "not found"})
        )
    )
    with pytest.raises(FXRateNotFound):
        asyncio.run(client.get_rate("USD", "ZZZ"))


def test_frankfurter_maps_provider_outage_to_unavailable():
    client = FrankfurterClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"message": "down"})
        )
    )
    with pytest.raises(FXProviderUnavailable):
        asyncio.run(client.get_rate("USD", "EUR"))


def test_frankfurter_does_not_leak_upstream_error_body():
    client = FrankfurterClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                422,
                json={"message": "private upstream diagnostics"},
            )
        )
    )
    with pytest.raises(FXProviderError) as error:
        asyncio.run(client.get_rate("USD", "EUR"))
    assert "private upstream diagnostics" not in str(error.value)


def test_frankfurter_rejects_malformed_or_inconsistent_rate_response():
    cases = [
        {"date": "2026-11-11", "base": "EUR", "quote": "USD", "rate": 1.2},
        {"date": "not-a-date", "base": "USD", "quote": "EUR", "rate": 1.2},
        {"date": "2026-11-11", "base": "USD", "quote": "EUR", "rate": 0},
        {"date": "2026-11-11", "base": "USD", "quote": "EUR", "rate": "NaN"},
        [],
    ]

    for payload in cases:
        client = FrankfurterClient(
            transport=httpx.MockTransport(
                lambda request, payload=payload: httpx.Response(200, json=payload)
            )
        )
        with pytest.raises(FXProviderError):
            asyncio.run(client.get_rate("USD", "EUR"))


def test_frankfurter_rejects_invalid_same_or_future_pair_before_network():
    def unexpected_request(_request):
        raise AssertionError("No HTTP request should be made")

    client = FrankfurterClient(transport=httpx.MockTransport(unexpected_request))
    with pytest.raises(ValueError, match="three alphabetic"):
        asyncio.run(client.get_rate("US", "EUR"))
    with pytest.raises(ValueError, match="different"):
        asyncio.run(client.get_rate("USD", "usd"))
    with pytest.raises(ValueError, match="Future"):
        asyncio.run(client.get_rate("USD", "EUR", date.today() + timedelta(days=1)))


def test_frankfurter_rejects_invalid_amount_before_network():
    client = FrankfurterClient(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(AssertionError("Unexpected request"))
        )
    )
    with pytest.raises(ValueError, match="positive finite"):
        asyncio.run(client.convert(Decimal(0), "USD", "EUR"))



class _ConcurrentFXTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.calls = 0
        self.active = 0
        self.maximum_active = 0
        self.two_requests_started = asyncio.Event()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        if self.calls >= 2:
            self.two_requests_started.set()
        try:
            try:
                await asyncio.wait_for(self.two_requests_started.wait(), timeout=0.2)
            except TimeoutError:
                pass
            _, base, quote = request.url.path.rsplit("/", 2)
            return httpx.Response(
                200,
                json={
                    "date": "2026-11-20",
                    "base": base,
                    "quote": quote,
                    "rate": "1.25",
                },
                request=request,
            )
        finally:
            self.active -= 1


def test_frankfurter_fetches_different_pairs_without_global_serialization():
    transport = _ConcurrentFXTransport()
    client = FrankfurterClient(transport=transport)

    async def fetch_pairs():
        return await asyncio.gather(
            client.get_rate("USD", "EUR"),
            client.get_rate("GBP", "EUR"),
        )

    results = asyncio.run(fetch_pairs())

    assert {(item.base, item.quote) for item in results} == {
        ("USD", "EUR"),
        ("GBP", "EUR"),
    }
    assert transport.calls == 2
    assert transport.maximum_active == 2


def test_frankfurter_coalesces_concurrent_requests_for_the_same_pair():
    transport = _ConcurrentFXTransport()
    client = FrankfurterClient(transport=transport)

    async def fetch_same_pair():
        return await asyncio.gather(
            *(client.get_rate("USD", "EUR") for _ in range(8))
        )

    results = asyncio.run(fetch_same_pair())

    assert len(results) == 8
    assert all(item == results[0] for item in results)
    assert transport.calls == 1


def test_frankfurter_failed_shared_request_is_removed_so_later_call_can_retry():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "date": "2026-11-20",
                "base": "USD",
                "quote": "EUR",
                "rate": "0.92",
            },
        )

    client = FrankfurterClient(transport=httpx.MockTransport(handler))

    async def fail_then_retry():
        failures = await asyncio.gather(
            *(client.get_rate("USD", "EUR") for _ in range(4)),
            return_exceptions=True,
        )
        recovered = await client.get_rate("USD", "EUR")
        return failures, recovered

    failures, recovered = asyncio.run(fail_then_retry())

    assert len(failures) == 4
    assert all(isinstance(item, FXProviderUnavailable) for item in failures)
    assert recovered.rate == Decimal("0.92")
    assert calls == 2
