import datetime as dt

import pytest

from app.domain.models import AssetRef, Bar
from app.providers.errors import ProviderError
from app.providers.registry import Capability, ProviderRegistry, call_with_fallback

RELIANCE = AssetRef(symbol="RELIANCE", exchange="NSE")


class FakeMarketDataProvider:
    """Minimal stand-in implementing MarketDataProvider's shape for registry tests."""

    def __init__(self, name: str, *, fails: bool = False) -> None:
        self.name = name
        self.fails = fails

    def get_ohlcv(
        self, asset: AssetRef, start: dt.date, end: dt.date, interval: str
    ) -> list[Bar]:
        if self.fails:
            raise ProviderError(self.name, "upstream unavailable", retryable=True)
        return [Bar(date=start, open=1, high=1, low=1, close=1, volume=1)]


def test_resolve_returns_registered_order() -> None:
    registry = ProviderRegistry()
    primary = FakeMarketDataProvider("primary")
    fallback = FakeMarketDataProvider("fallback")

    registry.register("IN", Capability.MARKET_DATA, primary)
    registry.register("IN", Capability.MARKET_DATA, fallback)

    assert registry.resolve("IN", Capability.MARKET_DATA) == [primary, fallback]


def test_resolve_unregistered_capability_returns_empty() -> None:
    registry = ProviderRegistry()
    assert registry.resolve("US", Capability.NEWS) == []


def test_call_with_fallback_uses_primary_when_it_succeeds() -> None:
    primary = FakeMarketDataProvider("primary")
    fallback = FakeMarketDataProvider("fallback", fails=True)

    result = call_with_fallback(
        [primary, fallback],
        lambda p: p.get_ohlcv(RELIANCE, dt.date(2026, 1, 1), dt.date(2026, 1, 2), "day"),
    )

    assert result == [Bar(date=dt.date(2026, 1, 1), open=1, high=1, low=1, close=1, volume=1)]


def test_call_with_fallback_falls_through_on_provider_error() -> None:
    primary = FakeMarketDataProvider("primary", fails=True)
    fallback = FakeMarketDataProvider("fallback")

    result = call_with_fallback(
        [primary, fallback],
        lambda p: p.get_ohlcv(RELIANCE, dt.date(2026, 1, 1), dt.date(2026, 1, 2), "day"),
    )

    assert result == [Bar(date=dt.date(2026, 1, 1), open=1, high=1, low=1, close=1, volume=1)]


def test_call_with_fallback_raises_when_every_provider_fails() -> None:
    a = FakeMarketDataProvider("a", fails=True)
    b = FakeMarketDataProvider("b", fails=True)

    with pytest.raises(ProviderError):
        call_with_fallback(
            [a, b],
            lambda p: p.get_ohlcv(RELIANCE, dt.date(2026, 1, 1), dt.date(2026, 1, 2), "day"),
        )


def test_call_with_fallback_raises_when_no_providers_registered() -> None:
    with pytest.raises(ProviderError):
        call_with_fallback([], lambda p: p)
