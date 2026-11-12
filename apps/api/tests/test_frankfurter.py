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
