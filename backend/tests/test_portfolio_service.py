import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import AppUser, Asset, Holding, PriceOHLCV
from app.services.portfolio import (
    add_or_update_holding,
    delete_holding,
    get_holding,
    import_holdings_csv,
    list_holdings,
    update_holding,
)

_STANDARD_HEADER = "Instrument,Qty.,Avg. cost"


def _user(db: Session, email: str) -> AppUser:
    user = AppUser(email=email, hashed_password="not-a-real-hash")
    db.add(user)
    db.flush()
    return user


def _asset(db: Session, symbol: str) -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.")
    db.add(asset)
    db.flush()
    return asset


def _price(db: Session, asset: Asset, close: float, *, days_ago: int = 0) -> None:
    db.add(
        PriceOHLCV(
            asset_id=asset.id,
            date=dt.date.today() - dt.timedelta(days=days_ago),
            open=Decimal(str(close)),
            high=Decimal(str(close)),
            low=Decimal(str(close)),
            close=Decimal(str(close)),
            volume=1000,
            source="test",
        )
    )
    db.flush()


def test_add_or_update_holding_returns_none_for_unresolvable_symbol(db: Session) -> None:
    user = _user(db, "unresolvable@example.com")
    assert add_or_update_holding(db, user.id, "ZZDOESNOTEXIST", quantity=1, avg_cost=1) is None


def test_add_or_update_holding_upserts_in_place(db: Session) -> None:
    user = _user(db, "upsert@example.com")
    asset = _asset(db, "ZZPF1")

    first = add_or_update_holding(db, user.id, "ZZPF1", quantity=10, avg_cost=100)
    second = add_or_update_holding(db, user.id, "ZZPF1", quantity=15, avg_cost=110)

    assert first.id == second.id
    assert db.query(Holding).filter_by(user_id=user.id, asset_id=asset.id).count() == 1
    assert second.quantity == Decimal("15")
    assert second.avg_cost == Decimal("110")
    assert second.source == "manual"


def test_update_holding_supports_partial_update(db: Session) -> None:
    user = _user(db, "partial@example.com")
    _asset(db, "ZZPF2")
    holding = add_or_update_holding(db, user.id, "ZZPF2", quantity=10, avg_cost=100)

    updated = update_holding(db, user.id, holding.id, quantity=20)

    assert updated.quantity == Decimal("20")
    assert updated.avg_cost == Decimal("100")  # untouched


def test_get_update_delete_are_ownership_scoped(db: Session) -> None:
    alice = _user(db, "alice_pf@example.com")
    bob = _user(db, "bob_pf@example.com")
    _asset(db, "ZZPF3")
    holding = add_or_update_holding(db, alice.id, "ZZPF3", quantity=10, avg_cost=100)

    assert get_holding(db, bob.id, holding.id) is None
    assert get_holding(db, alice.id, holding.id) is not None
    assert update_holding(db, bob.id, holding.id, quantity=1) is None
    assert delete_holding(db, bob.id, holding.id) is False
    assert delete_holding(db, alice.id, holding.id) is True


def test_list_holdings_computes_pnl_from_stored_prices(db: Session) -> None:
    user = _user(db, "pnl@example.com")
    asset = _asset(db, "ZZPF4")
    _price(db, asset, 150.0)
    add_or_update_holding(db, user.id, "ZZPF4", quantity=10, avg_cost=100)

    [valuation] = list_holdings(db, user.id)

    assert valuation.last_price == 150.0
    assert valuation.cost_basis == 1000.0
    assert valuation.market_value == 1500.0
    assert valuation.unrealized_pnl == 500.0
    assert valuation.unrealized_pnl_pct == 50.0


def test_list_holdings_handles_zero_price_history(db: Session) -> None:
    user = _user(db, "nohistory@example.com")
    _asset(db, "ZZPF5")
    add_or_update_holding(db, user.id, "ZZPF5", quantity=10, avg_cost=100)

    [valuation] = list_holdings(db, user.id)

    assert valuation.last_price is None
    assert valuation.market_value is None
    assert valuation.unrealized_pnl is None
    assert valuation.cost_basis == 1000.0  # pure user input, always computable


def test_import_full_replace_removes_stale_csv_rows(db: Session) -> None:
    user = _user(db, "importreplace2@example.com")
    _asset(db, "ZZPF8")  # manual, must survive
    _asset(db, "ZZPF9")  # stale csv, must be removed since absent from new file
    _asset(db, "ZZPF10")  # new csv row
    add_or_update_holding(db, user.id, "ZZPF8", quantity=1, avg_cost=1)
    stale = add_or_update_holding(db, user.id, "ZZPF9", quantity=1, avg_cost=1)
    stale.source = "csv"
    db.flush()

    csv_text = _STANDARD_HEADER + "\nZZPF10,5,50\n"
    summary = import_holdings_csv(db, user.id, csv_text)

    assert summary.imported == 1
    remaining_symbols = {h.symbol for h in list_holdings(db, user.id)}
    assert remaining_symbols == {"ZZPF8", "ZZPF10"}


def test_import_skips_unresolvable_symbol_with_reason(db: Session) -> None:
    user = _user(db, "importskip@example.com")
    csv_text = _STANDARD_HEADER + "\nZZDOESNOTEXIST,5,50\n"

    summary = import_holdings_csv(db, user.id, csv_text)

    assert summary.imported == 0
    assert summary.skipped == 1
    assert "unknown symbol" in summary.rows[0].reason


def test_import_with_all_unresolvable_rows_does_not_delete_existing(db: Session) -> None:
    user = _user(db, "importguard@example.com")
    _asset(db, "ZZPF11")
    existing = add_or_update_holding(db, user.id, "ZZPF11", quantity=1, avg_cost=1)
    existing.source = "csv"
    db.flush()

    csv_text = _STANDARD_HEADER + "\nZZDOESNOTEXIST,5,50\n"
    summary = import_holdings_csv(db, user.id, csv_text)

    assert summary.imported == 0
    assert len(list_holdings(db, user.id)) == 1  # untouched


def test_import_takes_over_a_manual_holding_for_the_same_asset(db: Session) -> None:
    user = _user(db, "importtakeover@example.com")
    _asset(db, "ZZPF12")
    manual = add_or_update_holding(db, user.id, "ZZPF12", quantity=1, avg_cost=1)
    assert manual.source == "manual"

    csv_text = _STANDARD_HEADER + "\nZZPF12,7,77\n"
    summary = import_holdings_csv(db, user.id, csv_text)

    assert summary.imported == 1
    row = next(r for r in summary.rows if r.symbol == "ZZPF12")
    assert row.status == "imported"
    assert "replaced your manual entry" in row.reason

    [holding] = list_holdings(db, user.id)
    assert holding.source == "csv"
    assert holding.quantity == 7
    assert holding.avg_cost == 77


def test_import_is_scoped_to_the_importing_user_only(db: Session) -> None:
    alice = _user(db, "alice_import@example.com")
    bob = _user(db, "bob_import@example.com")
    _asset(db, "ZZPF13")
    bob_holding = add_or_update_holding(db, bob.id, "ZZPF13", quantity=1, avg_cost=1)
    bob_holding.source = "csv"
    db.flush()

    csv_text = _STANDARD_HEADER + "\nZZPF13,9,99\n"
    import_holdings_csv(db, alice.id, csv_text)

    # Bob's csv-sourced holding for the same asset is untouched by Alice's import.
    db.refresh(bob_holding)
    assert bob_holding.quantity == Decimal("1")
    assert len(list_holdings(db, alice.id)) == 1
