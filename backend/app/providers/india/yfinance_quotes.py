"""Live NSE quotes via Yahoo Finance's batch quote API.

API_Sources.md §4 lists only broker feeds (Upstox/Angel/Fyers/Dhan) for
realtime, all of which need a demat account and a daily token. Yahoo's
`v7/finance/quote` needs neither, and measured against the live market on
2026-08-24 it was genuinely realtime, not the 15-minute delay usually
assumed for third-party India data: sampled 70s apart, bar timestamps
tracked ~5s behind wall clock, exactly one new 1-minute bar appeared, and
prices moved. Its `regularMarketPreviousClose` also matched our own stored
Bhavcopy close for the prior session exactly, which is a free correctness
cross-check on every poll.

One request covers every symbol, which is what makes polling a watchlist
viable at all — the per-symbol chart endpoint would be N requests a tick.

The tradeoff, and why this does NOT displace Bhavcopy as the source of
record: the endpoint is undocumented, has no SLA, and its rate limits are
unpublished. It is wired in as a quote provider only — EOD bars, screens,
and scores all still come from the Bhavcopy spine, so if Yahoo starts
throttling or changes shape, live prices degrade to last stored close and
nothing else in the product is affected.
"""

import datetime as dt

from app.domain.models import AssetRef, Quote
from app.providers.errors import ProviderError
from app.providers.india.yfinance_fundamentals import YahooSession

QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"

# Yahoo rejects very long symbol lists; chunking keeps each request well
# inside that limit while still being far fewer calls than one-per-symbol.
MAX_SYMBOLS_PER_REQUEST = 50


def _yahoo_symbol(asset: AssetRef) -> str:
    if asset.exchange != "NSE":
        raise ProviderError("yfinance_quotes", f"unsupported exchange: {asset.exchange}")
    return f"{asset.symbol}.NS"


def quote_key(exchange: str, symbol: str) -> str:
    """The dict key `get_quote` returns, matching the "{exchange}:{symbol}"
    convention already used for score lookups in services/opportunities.py."""
    return f"{exchange}:{symbol}"


def _chunks(items: list[AssetRef], size: int) -> list[list[AssetRef]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _opt_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _opt_int(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) else None


class YFinanceQuoteProvider:
    """Implements the `get_quote` half of `MarketDataProvider`.

    The other methods stay unimplemented on purpose: Yahoo is deliberately
    not a bar/universe source here (see module docstring), and silently
    offering those would invite it to become one.
    """

    def __init__(self, *, session: YahooSession | None = None) -> None:
        self._session = session or YahooSession()

    def get_quote(self, assets: list[AssetRef]) -> dict[str, Quote]:
        if not assets:
            return {}

        by_yahoo_symbol = {_yahoo_symbol(a): a for a in assets}
        quotes: dict[str, Quote] = {}

        for chunk in _chunks(assets, MAX_SYMBOLS_PER_REQUEST):
            symbols = [_yahoo_symbol(a) for a in chunk]
            response = self._session.get(QUOTE_URL, params={"symbols": ",".join(symbols)})
            if response.status_code != 200:
                raise ProviderError(
                    "yfinance_quotes", f"quote fetch failed: {response.status_code}"
                )

            rows = response.json().get("quoteResponse", {}).get("result", [])
            for row in rows:
                asset = by_yahoo_symbol.get(row.get("symbol", ""))
                ltp = row.get("regularMarketPrice")
                timestamp = row.get("regularMarketTime")
                # A row missing either of these is not a usable quote. Skip
                # it rather than substituting a stale or zero price — the
                # caller falls back to the stored close, which is at least
                # honestly labelled with its own date.
                if asset is None or ltp is None or timestamp is None:
                    continue

                quotes[quote_key(asset.exchange, asset.symbol)] = Quote(
                    asset=asset,
                    ltp=float(ltp),
                    as_of=dt.datetime.fromtimestamp(int(timestamp), dt.UTC),
                    previous_close=_opt_float(row.get("regularMarketPreviousClose")),
                    market_state=row.get("marketState"),
                    day_open=_opt_float(row.get("regularMarketOpen")),
                    day_high=_opt_float(row.get("regularMarketDayHigh")),
                    day_low=_opt_float(row.get("regularMarketDayLow")),
                    day_volume=_opt_int(row.get("regularMarketVolume")),
                )

        return quotes
