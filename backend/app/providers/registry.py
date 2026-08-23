"""(market, capability) -> ordered [primary, fallback, ...] provider list.

Services call `call_with_fallback` instead of a single provider directly, so
a dead/rate-limited source degrades to the next one automatically (§F/§G).
"""

from collections.abc import Callable
from enum import StrEnum

from app.providers.errors import ProviderError


class Capability(StrEnum):
    MARKET_DATA = "market_data"
    FUNDAMENTAL = "fundamental"
    NEWS = "news"
    COMPANY_DATA = "company_data"


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[tuple[str, Capability], list[object]] = {}

    def register(self, market: str, capability: Capability, provider: object) -> None:
        self._providers.setdefault((market, capability), []).append(provider)

    def resolve(self, market: str, capability: Capability) -> list[object]:
        return list(self._providers.get((market, capability), []))


registry = ProviderRegistry()


def call_with_fallback[T](providers: list[T], fn: Callable[[T], object]) -> object:
    """Try each provider in order; return the first success.

    Raises the last `ProviderError` if every provider fails, or one if the
    list is empty (nothing registered for this (market, capability)).
    """
    last_error: ProviderError | None = None
    for provider in providers:
        try:
            return fn(provider)
        except ProviderError as error:
            last_error = error
            continue
    raise last_error or ProviderError("registry", "no provider registered for this capability")
