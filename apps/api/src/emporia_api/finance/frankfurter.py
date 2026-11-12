from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx


class FXRateNotFound(Exception):
    """Raised when a valid currency pair has no observation for the requested date."""


class FXProviderUnavailable(Exception):
    """Raised when the reference-rate provider is temporarily unavailable."""


class FXProviderError(Exception):
    """Raised when the provider returns invalid data or a transport error."""


@dataclass(frozen=True)
class FXRate:
    base: str
    quote: str
    rate: Decimal
    date: date
    provider: str = "frankfurter"


@dataclass(frozen=True)
class FXConversion:
    amount: Decimal
    converted_amount: Decimal
    rate: FXRate


class FrankfurterClient:
    """Keyless daily reference-rate client with a bounded in-process cache."""

    endpoint = "https://api.frankfurter.dev/v2"
    latest_cache_seconds = 6 * 60 * 60
    historical_cache_seconds = 24 * 60 * 60
    maximum_cache_entries = 2048

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 15.0,
        latest_cache_seconds: int = 6 * 60 * 60,
        historical_cache_seconds: int = 24 * 60 * 60,
    ) -> None:
        self.transport = transport
        self.timeout = httpx.Timeout(timeout_seconds, connect=5.0)
        self.latest_cache_seconds = max(60, latest_cache_seconds)
        self.historical_cache_seconds = max(60, historical_cache_seconds)
        self._cache: dict[tuple[str, str, date | None], tuple[float, FXRate]] = {}
        self._cache_lock = asyncio.Lock()

    @staticmethod
    def _currency(value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("Currency codes must be three alphabetic characters")
        return normalized

    async def get_rate(
        self,
        base: str,
        quote: str,
        on_date: date | None = None,
    ) -> FXRate:
        normalized_base = self._currency(base)
        normalized_quote = self._currency(quote)
        if normalized_base == normalized_quote:
            raise ValueError("Base and quote currencies must be different")
        if on_date is not None and on_date > datetime.now().date():
            raise ValueError("Future exchange-rate dates are not supported")

        key = (normalized_base, normalized_quote, on_date)
        async with self._cache_lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]

            url = (
                f"{self.endpoint}/rate/"
                f"{normalized_base}/{normalized_quote}"
            )
            params = {"date": on_date.isoformat()} if on_date else None
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    transport=self.transport,
                    follow_redirects=False,
                ) as client:
                    response = await client.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise FXProviderUnavailable("Frankfurter request timed out") from exc
            except httpx.RequestError as exc:
                raise FXProviderUnavailable("Could not connect to Frankfurter") from exc

            if response.status_code == 404:
                raise FXRateNotFound(
                    f"No {normalized_base}/{normalized_quote} rate was found"
                    + (f" for {on_date.isoformat()}" if on_date else "")
                )
            if response.status_code in {429, 502, 503, 504}:
                raise FXProviderUnavailable(
                    f"Frankfurter returned HTTP {response.status_code}"
                )
            if response.is_error:
                raise FXProviderError(
                    f"Frankfurter rejected the request with HTTP {response.status_code}"
                )

            try:
                payload: Any = response.json()
                if not isinstance(payload, dict):
                    raise TypeError("Rate response must be a JSON object")
                returned_base = str(payload["base"]).upper()
                returned_quote = str(payload["quote"]).upper()
                if returned_base != normalized_base or returned_quote != normalized_quote:
                    raise ValueError("Provider returned a different currency pair")
                rate = Decimal(str(payload["rate"]))
                observation_date = date.fromisoformat(str(payload["date"]))
                if not rate.is_finite() or rate <= 0:
                    raise ValueError("Provider rate must be a positive finite decimal")
                if on_date is not None and observation_date > on_date:
                    raise ValueError("Provider returned an observation after the requested date")
                if observation_date > datetime.now().date():
                    raise ValueError("Provider returned a future observation")
                result = FXRate(
                    base=returned_base,
                    quote=returned_quote,
                    rate=rate,
                    date=observation_date,
                )
            except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                raise FXProviderError("Frankfurter returned an invalid rate response") from exc

            ttl = (
                self.historical_cache_seconds
                if on_date is not None
                else self.latest_cache_seconds
            )
            now = time.monotonic()
            self._cache[key] = (now + ttl, result)
            if len(self._cache) > self.maximum_cache_entries:
                expired = [
                    cache_key
                    for cache_key, (expires, _) in self._cache.items()
                    if expires <= now
                ]
                for cache_key in expired:
                    self._cache.pop(cache_key, None)
                while len(self._cache) > self.maximum_cache_entries:
                    self._cache.pop(next(iter(self._cache)))
            return result

    async def convert(
        self,
        amount: Decimal,
        base: str,
        quote: str,
        on_date: date | None = None,
    ) -> FXConversion:
        if not amount.is_finite() or amount <= 0:
            raise ValueError("Amount must be a positive finite decimal")
        rate = await self.get_rate(base, quote, on_date)
        return FXConversion(
            amount=amount,
            converted_amount=amount * rate.rate,
            rate=rate,
        )
