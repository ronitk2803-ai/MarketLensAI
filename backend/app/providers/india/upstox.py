"""Upstox market-data provider (Build_plan.md §F/§G — verified against live
endpoints 2026-08-23).

The instruments dump is a public, unauthenticated static file (refreshed
daily ~06:00 IST) — no token needed. Historical candles require a live
access token from `UpstoxTokenManager`.

`get_quote`/`get_corporate_actions` are deliberately unimplemented: Upstox
quotes/intraday are P2 (not needed for EOD MVP), and corporate actions come
from NSE/BSE per the provider responsibility matrix, not Upstox.
"""

import datetime as dt
import gzip
import json
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.domain.models import AssetRef, Bar, CorporateActionEvent, Quote
from app.providers.auth.upstox_token_manager import UpstoxTokenManager
from app.providers.errors import ProviderError

INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"
HISTORICAL_CANDLE_URL = (
    "https://api.upstox.com/v2/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}"
)

_SUPPORTED_INTERVALS = {"day", "week", "month"}


@dataclass(frozen=True, slots=True)
class UpstoxInstrument:
    """Raw Upstox equity instrument, trimmed to what asset/instrument_map seeding needs."""

    instrument_key: str
    trading_symbol: str
    name: str
    isin: str | None
    exchange: str


def fetch_instruments_raw(exchange: str = "NSE", *, client: httpx.Client | None = None) -> bytes:
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        response = client.get(INSTRUMENTS_URL.format(exchange=exchange))
    finally:
        if owns_client:
            client.close()
    if response.status_code != 200:
        raise ProviderError("upstox", f"instruments dump fetch failed: {response.status_code}")
    return gzip.decompress(response.content)


def parse_equity_instruments(raw_json: bytes | str) -> list[UpstoxInstrument]:
    records = json.loads(raw_json)
    instruments = []
    for record in records:
        if record.get("segment") != "NSE_EQ" or record.get("instrument_type") != "EQ":
            continue
        instruments.append(
            UpstoxInstrument(
                instrument_key=record["instrument_key"],
                trading_symbol=record["trading_symbol"],
                name=record["name"],
                isin=record.get("isin"),
                exchange=record["exchange"],
            )
        )
    return instruments


def _parse_candle(candle: list) -> Bar:
    timestamp, open_, high, low, close, volume, oi = candle
    return Bar(
        date=dt.datetime.fromisoformat(timestamp).date(),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        oi=oi or None,
    )


class UpstoxMarketDataProvider:
    """Implements `MarketDataProvider` for Upstox."""

    name = "upstox"

    def __init__(
        self,
        token_manager: UpstoxTokenManager,
        resolve_instrument_key: Callable[[AssetRef], str],
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._token_manager = token_manager
        self._resolve_instrument_key = resolve_instrument_key
        self._client = client

    def get_universe(self, index: str) -> list[AssetRef]:
        """Upstox has no concept of index membership — this returns all NSE
        equities. Nifty-500 filtering is layered on by the NSE index CSV
        provider (Build_plan.md §2), not here."""
        raw = fetch_instruments_raw("NSE", client=self._client)
        instruments = parse_equity_instruments(raw)
        return [
            AssetRef(symbol=i.trading_symbol, exchange="NSE", market="IN", name=i.name, isin=i.isin)
            for i in instruments
        ]

    def get_ohlcv(self, asset: AssetRef, start: dt.date, end: dt.date, interval: str) -> list[Bar]:
        if interval not in _SUPPORTED_INTERVALS:
            raise ProviderError("upstox", f"unsupported interval: {interval!r}")

        instrument_key = self._resolve_instrument_key(asset)
        token = self._token_manager.get_token()
        url = HISTORICAL_CANDLE_URL.format(
            instrument_key=instrument_key,
            interval=interval,
            to_date=end.isoformat(),
            from_date=start.isoformat(),
        )

        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=15.0)
        try:
            response = client.get(
                url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
            )
        finally:
            if owns_client:
                client.close()

        if response.status_code != 200:
            raise ProviderError(
                "upstox", f"historical candle fetch failed: {response.status_code} {response.text}"
            )

        candles = response.json().get("data", {}).get("candles", [])
        return [_parse_candle(candle) for candle in candles]

    def get_quote(self, assets: list[AssetRef]) -> dict[str, Quote]:
        raise NotImplementedError(
            "Upstox quotes are P2 — not needed for EOD MVP (Build_plan.md §G)"
        )

    def get_corporate_actions(self, asset: AssetRef) -> list[CorporateActionEvent]:
        raise NotImplementedError(
            "Corporate actions come from NSE/BSE, not Upstox (Build_plan.md §G provider matrix)"
        )
