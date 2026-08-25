import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import AppUser, Asset, Holding, PriceOHLCV
from app.services.portfolio import (
    add_or_update_holding,
    delete_holding,
    get_holding,
    get_valuation_for_asset,
    import_holdings_file,
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


def _lot(
    db: Session, user: AppUser, asset: Asset, broker: str, *, quantity: float, avg_cost: float
) -> Holding:
    holding = Holding(
        user_id=user.id,
        asset_id=asset.id,
        broker=broker,
        quantity=Decimal(str(quantity)),
        avg_cost=Decimal(str(avg_cost)),
    )
    db.add(holding)
    db.flush()
    return holding


def _to_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def test_add_or_update_holding_returns_none_for_unresolvable_symbol(db: Session) -> None:
    user = _user(db, "unresolvable@example.com")
    assert add_or_update_holding(db, user.id, "ZZDOESNOTEXIST", quantity=1, avg_cost=1) is None


def test_add_or_update_holding_upserts_the_manual_lot_in_place(db: Session) -> None:
    user = _user(db, "upsert@example.com")
    asset = _asset(db, "ZZPF1")

    first = add_or_update_holding(db, user.id, "ZZPF1", quantity=10, avg_cost=100)
    second = add_or_update_holding(db, user.id, "ZZPF1", quantity=15, avg_cost=110)

    assert first.id == second.id
    assert db.query(Holding).filter_by(user_id=user.id, asset_id=asset.id).count() == 1
    assert second.quantity == Decimal("15")
    assert second.avg_cost == Decimal("110")
    assert second.broker == "manual"


def test_add_or_update_holding_creates_a_separate_lot_from_an_existing_broker_lot(
    db: Session,
) -> None:
    """The bug the multi-broker schema change would otherwise introduce:
    a manual add must never find/overwrite a different broker's lot for
    the same asset, and must not crash when two lots already exist."""
    user = _user(db, "coexist@example.com")
    asset = _asset(db, "ZZPF2")
    zerodha_lot = _lot(db, user, asset, "zerodha", quantity=10, avg_cost=3000)

    manual_holding = add_or_update_holding(db, user.id, "ZZPF2", quantity=5, avg_cost=3200)

    assert manual_holding.id != zerodha_lot.id
    assert manual_holding.broker == "manual"
    db.refresh(zerodha_lot)
    assert zerodha_lot.quantity == Decimal("10")  # untouched
    assert zerodha_lot.avg_cost == Decimal("3000")  # untouched

    # And with lots from two brokers already present, manual add must not
    # raise MultipleResultsFound.
    upstox_lot = _lot(db, user, asset, "upstox", quantity=3, avg_cost=3100)
    updated_manual = add_or_update_holding(db, user.id, "ZZPF2", quantity=7, avg_cost=3300)
    assert updated_manual.id == manual_holding.id
    assert updated_manual.quantity == Decimal("7")
    db.refresh(upstox_lot)
    assert upstox_lot.quantity == Decimal("3")  # still untouched


def test_update_holding_supports_partial_update(db: Session) -> None:
    user = _user(db, "partial@example.com")
    _asset(db, "ZZPF3")
    holding = add_or_update_holding(db, user.id, "ZZPF3", quantity=10, avg_cost=100)

    updated = update_holding(db, user.id, holding.id, quantity=20)

    assert updated.quantity == Decimal("20")
    assert updated.avg_cost == Decimal("100")  # untouched


def test_get_update_delete_are_ownership_scoped(db: Session) -> None:
    alice = _user(db, "alice_pf@example.com")
    bob = _user(db, "bob_pf@example.com")
    _asset(db, "ZZPF4")
    holding = add_or_update_holding(db, alice.id, "ZZPF4", quantity=10, avg_cost=100)

    assert get_holding(db, bob.id, holding.id) is None
    assert get_holding(db, alice.id, holding.id) is not None
    assert update_holding(db, bob.id, holding.id, quantity=1) is None
    assert delete_holding(db, bob.id, holding.id) is False
    assert delete_holding(db, alice.id, holding.id) is True


def test_list_holdings_computes_pnl_for_a_single_lot(db: Session) -> None:
    user = _user(db, "pnl@example.com")
    asset = _asset(db, "ZZPF5")
    _price(db, asset, 150.0)
    add_or_update_holding(db, user.id, "ZZPF5", quantity=10, avg_cost=100)

    [valuation] = list_holdings(db, user.id)

    assert valuation.last_price == 150.0
    assert valuation.cost_basis == 1000.0
    assert valuation.market_value == 1500.0
    assert valuation.unrealized_pnl == 500.0
    assert valuation.unrealized_pnl_pct == 50.0
    assert [lot.broker for lot in valuation.lots] == ["manual"]


def test_list_holdings_handles_zero_price_history(db: Session) -> None:
    user = _user(db, "nohistory@example.com")
    _asset(db, "ZZPF6")
    add_or_update_holding(db, user.id, "ZZPF6", quantity=10, avg_cost=100)

    [valuation] = list_holdings(db, user.id)

    assert valuation.last_price is None
    assert valuation.market_value is None
    assert valuation.unrealized_pnl is None
    assert valuation.cost_basis == 1000.0  # pure user input, always computable


def test_list_holdings_consolidates_multiple_broker_lots_with_weighted_average_cost(
    db: Session,
) -> None:
    user = _user(db, "consolidate@example.com")
    asset = _asset(db, "ZZPF7")
    _price(db, asset, 200.0)
    _lot(db, user, asset, "zerodha", quantity=10, avg_cost=100)
    _lot(db, user, asset, "upstox", quantity=5, avg_cost=160)
    _lot(db, user, asset, "manual", quantity=1, avg_cost=190)

    [valuation] = list_holdings(db, user.id)

    # total qty = 16, total cost basis = 1000 + 800 + 190 = 1990
    assert valuation.quantity == 16.0
    assert valuation.cost_basis == 1990.0
    assert valuation.avg_cost == 1990.0 / 16.0
    assert valuation.market_value == 16.0 * 200.0
    assert valuation.unrealized_pnl == 16.0 * 200.0 - 1990.0
    assert len(valuation.lots) == 3
    assert {lot.broker for lot in valuation.lots} == {"zerodha", "upstox", "manual"}


def test_get_valuation_for_asset_matches_list_holdings(db: Session) -> None:
    user = _user(db, "singleasset@example.com")
    asset = _asset(db, "ZZPF8")
    _price(db, asset, 100.0)
    _lot(db, user, asset, "zerodha", quantity=10, avg_cost=90)
    _lot(db, user, asset, "upstox", quantity=5, avg_cost=95)

    from_list = list_holdings(db, user.id)[0]
    from_single = get_valuation_for_asset(db, user.id, asset.id)

    assert from_single.quantity == from_list.quantity
    assert from_single.avg_cost == from_list.avg_cost
    assert from_single.cost_basis == from_list.cost_basis
    assert len(from_single.lots) == len(from_list.lots) == 2


def test_import_replaces_only_this_broker_s_lots(db: Session) -> None:
    user = _user(db, "importreplace@example.com")
    manual_asset = _asset(db, "ZZPF9")  # manual, must survive any import
    stale_asset = _asset(db, "ZZPF10")  # stale zerodha lot, absent from new file -> removed
    upstox_asset = _asset(db, "ZZPF11")  # upstox lot, must survive a zerodha import
    _asset(db, "ZZPF12")  # new zerodha row
    _lot(db, user, manual_asset, "manual", quantity=1, avg_cost=1)
    _lot(db, user, stale_asset, "zerodha", quantity=1, avg_cost=1)
    upstox_lot = _lot(db, user, upstox_asset, "upstox", quantity=2, avg_cost=2)

    csv_text = _STANDARD_HEADER + "\nZZPF12,5,50\n"
    summary = import_holdings_file(
        db, user.id, _to_bytes(csv_text), "holdings.csv", broker="zerodha"
    )

    assert summary.imported == 1
    symbols_present = {v.symbol for v in list_holdings(db, user.id)}
    assert symbols_present == {"ZZPF9", "ZZPF11", "ZZPF12"}
    db.refresh(upstox_lot)
    assert upstox_lot.quantity == Decimal("2")  # untouched by the zerodha import


def test_import_zerodha_then_upstox_consolidates_instead_of_wiping(db: Session) -> None:
    user = _user(db, "twobrokers@example.com")
    asset = _asset(db, "ZZPF13")
    _price(db, asset, 250.0)

    zerodha_csv = _STANDARD_HEADER + "\nZZPF13,10,200\n"
    upstox_csv = _STANDARD_HEADER + "\nZZPF13,5,220\n"
    import_holdings_file(db, user.id, _to_bytes(zerodha_csv), "z.csv", broker="zerodha")
    import_holdings_file(db, user.id, _to_bytes(upstox_csv), "u.csv", broker="upstox")

    [valuation] = list_holdings(db, user.id)
    assert valuation.quantity == 15.0
    assert valuation.cost_basis == 10 * 200 + 5 * 220
    assert len(valuation.lots) == 2
    assert {lot.broker for lot in valuation.lots} == {"zerodha", "upstox"}


def test_import_skips_unresolvable_symbol_with_reason(db: Session) -> None:
    user = _user(db, "importskip@example.com")
    csv_text = _STANDARD_HEADER + "\nZZDOESNOTEXIST,5,50\n"

    summary = import_holdings_file(db, user.id, _to_bytes(csv_text), "h.csv", broker="zerodha")

    assert summary.imported == 0
    assert summary.skipped == 1
    assert "unknown symbol" in summary.rows[0].reason


def test_import_with_all_unresolvable_rows_does_not_delete_existing_lots_for_that_broker(
    db: Session,
) -> None:
    user = _user(db, "importguard@example.com")
    asset = _asset(db, "ZZPF14")
    _lot(db, user, asset, "zerodha", quantity=1, avg_cost=1)

    csv_text = _STANDARD_HEADER + "\nZZDOESNOTEXIST,5,50\n"
    summary = import_holdings_file(db, user.id, _to_bytes(csv_text), "h.csv", broker="zerodha")

    assert summary.imported == 0
    assert len(list_holdings(db, user.id)) == 1  # untouched


def test_import_is_scoped_to_the_importing_user_only(db: Session) -> None:
    alice = _user(db, "alice_import@example.com")
    bob = _user(db, "bob_import@example.com")
    asset = _asset(db, "ZZPF15")
    bob_lot = _lot(db, bob, asset, "zerodha", quantity=1, avg_cost=1)

    csv_text = _STANDARD_HEADER + "\nZZPF15,9,99\n"
    import_holdings_file(db, alice.id, _to_bytes(csv_text), "h.csv", broker="zerodha")

    db.refresh(bob_lot)
    assert bob_lot.quantity == Decimal("1")
    assert len(list_holdings(db, alice.id)) == 1


def test_reimport_dropping_a_symbol_removes_only_that_broker_s_position(db: Session) -> None:
    user = _user(db, "reimport@example.com")
    zerodha_asset = _asset(db, "ZZPF16")
    upstox_asset = _asset(db, "ZZPF17")
    _lot(db, user, zerodha_asset, "zerodha", quantity=1, avg_cost=1)
    upstox_lot = _lot(db, user, upstox_asset, "upstox", quantity=2, avg_cost=2)

    # Re-import zerodha with an unrelated file that no longer has ZZPF16 at all.
    csv_text = _STANDARD_HEADER + "\nZZPF17,1,1\n"
    import_holdings_file(db, user.id, _to_bytes(csv_text), "h.csv", broker="zerodha")

    symbols = {v.symbol for v in list_holdings(db, user.id)}
    assert "ZZPF16" not in symbols  # the old zerodha lot is gone
    db.refresh(upstox_lot)
    assert upstox_lot.quantity == Decimal("2")  # the upstox lot is untouched
