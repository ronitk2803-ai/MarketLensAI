"""Fundamentals: cache-first reads from financial_statement/financial_metric,
fetched once (best-effort) and persisted — never fabricated, missing shown
as unavailable, never a guessed value (Build_plan.md §7/§H, decision D-002).

`confidence` is hardcoded "low" for everything here: this is a single,
uncross-checked source (Yahoo/yfinance tier) — Build_plan.md §6 reserves
"high" confidence for official/reconciled data. Never claim more certainty
than the source actually earns.
"""

from decimal import Decimal

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

    for metric, value in ratios.values.items():
        db.add(
            FinancialMetric(
                asset_id=asset.id,
                metric=metric,
                value=Decimal(str(value)),
                source=SOURCE,
                confidence=CONFIDENCE,
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

    for statement in statements:
        for line_item, value in statement.line_items.items():
            db.add(
                FinancialStatement(
                    asset_id=asset.id,
                    period_type=statement.period_type,
                    period_end=statement.period_end,
                    statement_type=statement.statement_type,
                    line_item=line_item,
                    value=Decimal(str(value)),
                    source=SOURCE,
                    confidence=CONFIDENCE,
                )
            )
    db.flush()
    return (
        db.query(FinancialStatement)
        .filter_by(asset_id=asset.id, statement_type=statement_type, period_type=period)
        .order_by(FinancialStatement.period_end.desc())
        .all()
    )
