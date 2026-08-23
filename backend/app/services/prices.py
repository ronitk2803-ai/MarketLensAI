"""Price history: cache-first reads from `price_ohlcv`, refreshing from
providers only when stale (Build_plan.md §I — request -> cache lookup ->
freshness check -> serve if valid -> refresh only if stale).

Upstox is tried first (preferred feed), NSE Bhavcopy is the auth-free
fallback that guarantees this never hard-fails just because the Upstox
token lapsed (Build_plan.md §G). If both fail, whatever's already stored is
returned rather than raising — a request should degrade gracefully, not
break the page.
"""

import datetime as dt
import time
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Asset, PriceOHLCV, ProviderFetchLog
from app.domain.models import AssetRef, Bar
from app.providers.auth.upstox_token_manager import token_manager as upstox_token_manager
from app.providers.base import MarketDataProvider
from app.providers.errors import ProviderError
from app.providers.fetch_log import record_fetch
from app.providers.india.nse_bhavcopy import NSEBhavcopyProvider
from app.providers.india.upstox import UpstoxMarketDataProvider
from app.services.universe import resolve_upstox_instrument_key

PRICES_REFRESH_ENDPOINT = "prices_refresh"


def _stored_bars(db: Session, asset_id: int, start: dt.date, end: dt.date) -> list[PriceOHLCV]:
    return (
        db.query(PriceOHLCV)
        .filter(PriceOHLCV.asset_id == asset_id, PriceOHLCV.date >= start, PriceOHLCV.date <= end)
        .order_by(PriceOHLCV.date)
        .all()
    )


def row_to_bar(row: PriceOHLCV) -> Bar:
    return Bar(
        date=row.date,
        open=float(row.open),
        high=float(row.high),
        low=float(row.low),
        close=float(row.close),
        volume=row.volume,
        oi=row.oi,
        delivery_qty=row.delivery_qty,
        delivery_pct=float(row.delivery_pct) if row.delivery_pct is not None else None,
    )


def persist_bars(db: Session, asset_id: int, bars: list[Bar], source: str) -> None:
    if not bars:
        return

    # One SELECT for this asset's overlapping rows, not one per bar. The
    # per-bar lookup was an N+1: tolerable for the ~300-asset dev universe
    # (~21k queries) but fatal against the real 2.6k-asset NSE universe,
    # where a one-year backfill became ~650k sequential round trips and
    # effectively never finished (observed live: Postgres idle, Python
    # pegged, no progress after 25 minutes).
    existing: dict[dt.date, PriceOHLCV] = {
        row.date: row
        for row in db.query(PriceOHLCV).filter(
            PriceOHLCV.asset_id == asset_id,
            PriceOHLCV.date.in_([bar.date for bar in bars]),
        )
    }

    for bar in bars:
        row = existing.get(bar.date)
        if row is None:
            row = PriceOHLCV(asset_id=asset_id, date=bar.date, source=source)
            db.add(row)
            # Keep the map authoritative so a repeated date within `bars`
            # updates the pending row instead of inserting a duplicate —
            # the old code got this via autoflush on the per-bar query.
            existing[bar.date] = row
        row.open = Decimal(str(bar.open))
        row.high = Decimal(str(bar.high))
        row.low = Decimal(str(bar.low))
        row.close = Decimal(str(bar.close))
        row.volume = bar.volume
        row.oi = bar.oi
        row.delivery_qty = bar.delivery_qty
        row.delivery_pct = Decimal(str(bar.delivery_pct)) if bar.delivery_pct is not None else None
        row.source = source
    db.flush()


def _fetch_from_providers(
    db: Session, asset_ref: AssetRef, start: dt.date, end: dt.date
) -> tuple[list[Bar], str | None]:
    upstox = UpstoxMarketDataProvider(
        upstox_token_manager, resolve_instrument_key=lambda a: resolve_upstox_instrument_key(db, a)
    )
    bhavcopy = NSEBhavcopyProvider()
    providers: list[tuple[str, MarketDataProvider]] = [
        ("upstox", upstox),
        ("nse_bhavcopy", bhavcopy),
    ]

    for name, provider in providers:
        try:
            return provider.get_ohlcv(asset_ref, start, end, "day"), name
        except ProviderError:
            continue
    return [], None


# A live request only ever catches up a *recent* gap on demand — never a
# deep historical backfill. NSE Bhavcopy has no "one symbol over a year"
# endpoint; its per-symbol get_ohlcv necessarily loops one HTTP request per
# day (verified live: a naive 1-year request made ~365 sequential calls to
# NSE and never returned in reasonable time). Populating deep history for
# the whole universe is a batch job's responsibility (get_day_bars, one
# request per day covering every symbol), not something a page load should
# trigger. If older history isn't already stored, the API just returns
# whatever's available rather than blocking on it.
MAX_ON_DEMAND_FETCH_DAYS = 10

# Without a trading calendar, "stored data is older than `end`" is true on
# every single request across a weekend/holiday (there's genuinely no newer
# session yet) — verified live: every request re-ran the full ~10-day
# Bhavcopy loop, adding seconds of latency forever, for no new data. This
# cooldown (backed by `provider_fetch_log`, built in step 3 for exactly
# this) bounds retries to once per window regardless of the date gap, which
# is the "Trading-calendar aware" freshness policy's cheap approximation
# (Build_plan.md §I) — a real calendar can replace this later without
# changing the interface.
FETCH_RETRY_COOLDOWN = dt.timedelta(minutes=15)


def _recently_attempted(db: Session, asset_id: int) -> bool:
    last = (
        db.query(ProviderFetchLog)
        .filter_by(asset_id=asset_id, endpoint=PRICES_REFRESH_ENDPOINT)
        .order_by(ProviderFetchLog.fetched_at.desc())
        .first()
    )
    if last is None:
        return False
    fetched_at = last.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=dt.UTC)
    return (dt.datetime.now(dt.UTC) - fetched_at) < FETCH_RETRY_COOLDOWN


def get_price_history(
    db: Session, asset: Asset, start: dt.date, end: dt.date
) -> tuple[list[Bar], str]:
    """Returns (bars, source). `source` is "cache" when nothing needed
    fetching, otherwise the provider that supplied the freshest data."""
    stored = _stored_bars(db, asset.id, start, end)
    latest_stored_date = stored[-1].date if stored else None
    source = "cache"

    is_stale = latest_stored_date is None or latest_stored_date < end
    if is_stale and not _recently_attempted(db, asset.id):
        fetch_start = latest_stored_date + dt.timedelta(days=1) if latest_stored_date else start
        fetch_start = max(fetch_start, end - dt.timedelta(days=MAX_ON_DEMAND_FETCH_DAYS))
        asset_ref = AssetRef(symbol=asset.symbol, exchange=asset.exchange, market=asset.market)

        started_at = time.monotonic()
        bars, fetched_source = _fetch_from_providers(db, asset_ref, fetch_start, end)
        latency_ms = round((time.monotonic() - started_at) * 1000)
        record_fetch(
            db,
            provider=fetched_source or "none",
            endpoint=PRICES_REFRESH_ENDPOINT,
            asset_id=asset.id,
            status="success" if bars else "empty",
            latency_ms=latency_ms,
        )

        if bars and fetched_source:
            persist_bars(db, asset.id, bars, fetched_source)
            stored = _stored_bars(db, asset.id, start, end)
            source = fetched_source

    return [row_to_bar(row) for row in stored], source
