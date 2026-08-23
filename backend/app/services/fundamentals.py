"""Fundamentals: cache-first reads from financial_statement/financial_metric,
fetched once (best-effort) and persisted — never fabricated, missing shown
as unavailable, never a guessed value (Build_plan.md §7/§H, decision D-002).

`confidence` is hardcoded "low" for everything here: this is a single,
uncross-checked source (Yahoo/yfinance tier) — Build_plan.md §6 reserves
"high" confidence for official/reconciled data. Never claim more certainty
than the source actually earns.
"""

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


def get_or_fetch_ratios(db: Session, asset: Asset) -> list[FinancialMetric]:
    rows = db.query(FinancialMetric).filter_by(asset_id=asset.id).all()
    if rows:
        return rows

    asset_ref = AssetRef(symbol=asset.symbol, exchange=asset.exchange, market=asset.market)
    try:
        ratios = YFinanceFundamentalDataProvider().get_ratios(asset_ref)
    except ProviderError:
        return []

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
    if rows:
        return rows

    asset_ref = AssetRef(symbol=asset.symbol, exchange=asset.exchange, market=asset.market)
    try:
        statements = YFinanceFundamentalDataProvider().get_all_statements(
            asset_ref, statement_type, period
        )
    except ProviderError:
        return []

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
    return (
        db.query(FinancialStatement)
        .filter_by(asset_id=asset.id, statement_type=statement_type, period_type=period)
        .order_by(FinancialStatement.period_end.desc())
        .all()
    )
