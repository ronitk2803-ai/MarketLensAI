"""Fundamentals: cache-first reads from financial_statement/financial_metric,
fetched once (best-effort) and persisted — never fabricated, missing shown
as unavailable, never a guessed value (Build_plan.md §7/§H, decision D-002).

`confidence` is hardcoded "low" for everything here: this is a single,
uncross-checked source (Yahoo/yfinance tier) — Build_plan.md §6 reserves
"high" confidence for official/reconciled data. Never claim more certainty
than the source actually earns.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import Asset, FinancialMetric, FinancialStatement
from app.domain.models import AssetRef
from app.providers.errors import ProviderError
from app.providers.india.yfinance_fundamentals import YFinanceFundamentalDataProvider

SOURCE = "yfinance_fundamentals"
CONFIDENCE = "low"

# Build_plan.md §I's documented TTL table: "fundamentals quarterly." The
# original cache had no expiry at all (`if rows: return rows`, forever) —
# found live: several of these ratios are price-dependent (P/E, P/B, market
# cap) and move every session, yet a company viewed once kept showing the
# ratios from that first view indefinitely, and a code fix that corrected
# what gets fetched (e.g. adding a missing field) would never reach an
# already-cached company without a manual cache clear.
FUNDAMENTALS_TTL = dt.timedelta(days=90)


def _is_stale(rows: list[FinancialMetric] | list[FinancialStatement]) -> bool:
    if not rows:
        return True
    newest = max(r.as_of for r in rows)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=dt.UTC)
    return (dt.datetime.now(dt.UTC) - newest) >= FUNDAMENTALS_TTL


def get_or_fetch_ratios(db: Session, asset: Asset) -> list[FinancialMetric]:
    rows = db.query(FinancialMetric).filter_by(asset_id=asset.id).all()
    if rows and not _is_stale(rows):
        return rows

    asset_ref = AssetRef(symbol=asset.symbol, exchange=asset.exchange, market=asset.market)
    try:
        ratios = YFinanceFundamentalDataProvider().get_ratios(asset_ref)
    except ProviderError:
        # Stale-but-real beats nothing: a transient Yahoo outage on the
        # refresh attempt must not blank out ratios that were fine an hour
        # ago. Only a genuine first-ever fetch failure (no rows at all)
        # legitimately returns empty.
        return rows

    rows_to_write = [
        {
            "asset_id": asset.id,
            "metric": metric,
            "value": Decimal(str(value)),
            "source": SOURCE,
            "confidence": CONFIDENCE,
        }
        for metric, value in ratios.values.items()
    ]
    if rows_to_write:
        # Upsert rather than insert: the check above and this write are not
        # atomic, so two callers that miss the cache together both fetch and
        # both write. That is not hypothetical — the nightly scoring job and
        # a page request raced on RELIANCE during deployment and the loser
        # got a 500 from uq_financial_metric_asset_metric. This is the
        # "upserted per (asset, metric)" the model docstring already claims.
        statement = pg_insert(FinancialMetric).values(rows_to_write)
        db.execute(
            statement.on_conflict_do_update(
                constraint="uq_financial_metric_asset_metric",
                set_={
                    "value": statement.excluded.value,
                    "source": statement.excluded.source,
                    "confidence": statement.excluded.confidence,
                    "as_of": func.now(),
                },
            )
        )
        db.flush()
        # The upsert above is a raw SQL statement, not an ORM update — it
        # never touches the identity map, so any FinancialMetric object
        # already loaded into this session (a metric that existed and just
        # got refreshed, not one being inserted for the first time) still
        # holds its pre-refresh attribute values. Only became reachable
        # once rows could actually be refreshed at all (added alongside
        # FUNDAMENTALS_TTL) — verified live: a stale `beta` upsert to a new
        # value came back from this function as the old value, silently.
        db.expire_all()
    return db.query(FinancialMetric).filter_by(asset_id=asset.id).all()


def get_or_fetch_statements(
    db: Session, asset: Asset, statement_type: str = "income", period: str = "FY"
) -> list[FinancialStatement]:
    rows = (
        db.query(FinancialStatement)
        .filter_by(asset_id=asset.id, statement_type=statement_type, period_type=period)
        .order_by(FinancialStatement.period_end.desc())
        .all()
    )
    if rows and not _is_stale(rows):
        return rows

    asset_ref = AssetRef(symbol=asset.symbol, exchange=asset.exchange, market=asset.market)
    try:
        statements = YFinanceFundamentalDataProvider().get_all_statements(
            asset_ref, statement_type, period
        )
    except ProviderError:
        # Stale-but-real beats nothing — see get_or_fetch_ratios.
        return rows

    rows_to_write = [
        {
            "asset_id": asset.id,
            "period_type": statement.period_type,
            "period_end": statement.period_end,
            "statement_type": statement.statement_type,
            "line_item": line_item,
            "value": Decimal(str(value)),
            "source": SOURCE,
            "confidence": CONFIDENCE,
        }
        for statement in statements
        for line_item, value in statement.line_items.items()
    ]
    if rows_to_write:
        # Same race as get_or_fetch_ratios — concurrent cache misses on the
        # same asset would collide on uq_financial_statement_line.
        insert_stmt = pg_insert(FinancialStatement).values(rows_to_write)
        db.execute(
            insert_stmt.on_conflict_do_update(
                constraint="uq_financial_statement_line",
                set_={
                    "value": insert_stmt.excluded.value,
                    "source": insert_stmt.excluded.source,
                    "confidence": insert_stmt.excluded.confidence,
                    "as_of": func.now(),
                },
            )
        )
        db.flush()
        # See the matching comment in get_or_fetch_ratios — the raw-SQL
        # upsert bypasses the identity map, so an already-loaded row that
        # just got refreshed would otherwise come back with its stale
        # pre-refresh value.
        db.expire_all()
    return (
        db.query(FinancialStatement)
        .filter_by(asset_id=asset.id, statement_type=statement_type, period_type=period)
        .order_by(FinancialStatement.period_end.desc())
        .all()
    )
