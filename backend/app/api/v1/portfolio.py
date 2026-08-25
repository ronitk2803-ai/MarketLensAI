"""Portfolio holdings endpoints (Build_plan.md P1 build-sequence step 17).
Bare JSON responses, not the {data, meta} envelope — same reasoning as
theses.py: a holding's primary fields (quantity, avg_cost) are
user-authored, not market data with source/confidence to report, even
though a computed market_value/P&L rides alongside.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.models import AppUser
from app.db.session import get_db
from app.services.portfolio import (
    HoldingValuation,
    add_or_update_holding,
    delete_holding,
    get_valuation,
    import_holdings_csv,
    list_holdings,
    update_holding,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

# A 2000-row CSV export is at most a few hundred KB — 5MB is generous
# headroom, not a tight limit, just a sane ceiling against an accidental
# wrong-file upload.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class AddHoldingRequest(BaseModel):
    symbol: str
    quantity: float = Field(gt=0)
    avg_cost: float = Field(gt=0)


class UpdateHoldingRequest(BaseModel):
    quantity: float | None = Field(default=None, gt=0)
    avg_cost: float | None = Field(default=None, gt=0)


def _valuation_to_dict(v: HoldingValuation) -> dict:
    return {
        "id": v.holding_id,
        "symbol": v.symbol,
        "exchange": v.exchange,
        "asset_name": v.name,
        "quantity": v.quantity,
        "avg_cost": v.avg_cost,
        "source": v.source,
        "last_price": v.last_price,
        "as_of": v.as_of,
        "market_value": v.market_value,
        "cost_basis": v.cost_basis,
        "unrealized_pnl": v.unrealized_pnl,
        "unrealized_pnl_pct": v.unrealized_pnl_pct,
    }


def _totals(valuations: list[HoldingValuation]) -> dict:
    priced_values = [v.market_value for v in valuations if v.market_value is not None]
    priced = [v for v in valuations if v.market_value is not None]
    cost_basis = sum(v.cost_basis for v in valuations)
    priced_cost_basis = sum(v.cost_basis for v in priced)
    market_value = sum(priced_values) if priced_values else None
    unrealized_pnl = market_value - priced_cost_basis if market_value is not None else None
    unrealized_pnl_pct = (
        unrealized_pnl / priced_cost_basis * 100
        if unrealized_pnl is not None and priced_cost_basis
        else None
    )
    return {
        "cost_basis": cost_basis,
        "market_value": market_value,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "holdings_priced": len(priced),
        "holdings_total": len(valuations),
    }


@router.get("")
def get_portfolio(
    current_user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    valuations = list_holdings(db, current_user.id)
    return {
        "holdings": [_valuation_to_dict(v) for v in valuations],
        "totals": _totals(valuations),
    }


@router.post("")
def add_holding(
    payload: AddHoldingRequest,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    holding = add_or_update_holding(
        db,
        current_user.id,
        payload.symbol,
        quantity=payload.quantity,
        avg_cost=payload.avg_cost,
    )
    if holding is None:
        raise HTTPException(status_code=404, detail=f"unknown asset: {payload.symbol}")
    return _valuation_to_dict(get_valuation(db, holding))


@router.put("/{holding_id}")
def edit_holding(
    holding_id: int,
    payload: UpdateHoldingRequest,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    holding = update_holding(
        db,
        current_user.id,
        holding_id,
        quantity=payload.quantity,
        avg_cost=payload.avg_cost,
    )
    if holding is None:
        raise HTTPException(status_code=404, detail="holding not found")
    return _valuation_to_dict(get_valuation(db, holding))


@router.delete("/{holding_id}")
def remove_holding(
    holding_id: int,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    deleted = delete_holding(db, current_user.id, holding_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="holding not found")
    return {"status": "ok"}


@router.post("/import")
def import_csv(
    file: UploadFile = File(...),
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if file.filename and not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="please upload a .csv file")

    raw_bytes = file.file.read(MAX_UPLOAD_BYTES + 1)
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="the file is empty")
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"file too large — max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
        )
    try:
        raw_text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="couldn't read the file as UTF-8 text") from exc

    try:
        summary = import_holdings_csv(db, current_user.id, raw_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "imported": summary.imported,
        "skipped": summary.skipped,
        "rows": [
            {"row_number": r.row_number, "symbol": r.symbol, "status": r.status, "reason": r.reason}
            for r in summary.rows
        ],
    }
