"""Live quote lookup, with a short shared cache in front of the provider.

The cache is the load-bearing part. A quote endpoint gets polled — every
open tab, every user, every few seconds — so without it the upstream
request rate scales with viewers rather than with symbols. Yahoo's rate
limits are unpublished (see the provider docstring), and the fastest way to
find them would be to let a couple of open dashboards hammer it. A few
seconds of staleness is invisible on screen and collapses N pollers into
one upstream call per symbol per window.

In-process and per-worker, which is right for the single-container MVP and
the same tradeoff UpstoxTokenManager already makes. A multi-instance deploy
would want this in Redis; the interface wouldn't change.
"""

import datetime as dt
import logging
import threading

from sqlalchemy.orm import Session

from app.db.models import Asset
from app.domain.models import AssetRef, Quote
from app.providers.errors import ProviderError
from app.providers.india.yfinance_quotes import YFinanceQuoteProvider, quote_key

logger = logging.getLogger(__name__)

CACHE_TTL = dt.timedelta(seconds=10)

_provider = YFinanceQuoteProvider()
_cache: dict[str, tuple[dt.datetime, Quote]] = {}
_lock = threading.Lock()


def _cached(keys: list[str], now: dt.datetime) -> tuple[dict[str, Quote], list[str]]:
    """Split requested keys into (fresh hits, keys needing a fetch)."""
    hits: dict[str, Quote] = {}
    misses: list[str] = []
    with _lock:
        for key in keys:
            entry = _cache.get(key)
            if entry is not None and now - entry[0] < CACHE_TTL:
                hits[key] = entry[1]
            else:
                misses.append(key)
    return hits, misses


def _store(quotes: dict[str, Quote], now: dt.datetime) -> None:
    with _lock:
        for key, quote in quotes.items():
            _cache[key] = (now, quote)


def get_live_quotes(db: Session, symbols: list[str]) -> dict[str, Quote]:
    """Live quotes keyed "{exchange}:{symbol}".

    A symbol with no quote — unknown, or the provider being down — is simply
    absent from the result. Callers render the stored close instead, which
    carries its own date, rather than showing a stale price as if it were
    current.
    """
    wanted = [s.strip().upper() for s in symbols if s.strip()]
    if not wanted:
        return {}

    assets = (
        db.query(Asset)
        .filter(Asset.symbol.in_(wanted), Asset.market == "IN", Asset.exchange == "NSE")
        .all()
    )
    if not assets:
        return {}

    now = dt.datetime.now(dt.UTC)
    by_key = {quote_key(a.exchange, a.symbol): a for a in assets}
    hits, misses = _cached(list(by_key), now)
    if not misses:
        return hits

    refs = [
        AssetRef(symbol=by_key[k].symbol, exchange=by_key[k].exchange, market=by_key[k].market)
        for k in misses
    ]
    try:
        fetched = _provider.get_quote(refs)
    except ProviderError:
        # Degrading to whatever is still cached (and, above that, to stored
        # closes) is the whole point of keeping this off the EOD path.
        logger.warning("live quotes unavailable; falling back to stored closes", exc_info=True)
        return hits

    _store(fetched, now)
    return {**hits, **fetched}


def clear_cache() -> None:
    """Test hook — the module-level cache would otherwise leak between tests."""
    with _lock:
        _cache.clear()
