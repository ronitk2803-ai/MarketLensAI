from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import AppUser, Asset, FinancialMetric, ThesisEvent, ThesisTrigger
from app.services.thesis import (
    TriggerInput,
    create_thesis,
    delete_thesis,
    find_asset_by_symbol,
    get_thesis,
    list_theses,
    run_thesis_eval,
    update_thesis,
)


def _user(db: Session, email: str) -> AppUser:
    user = AppUser(email=email, hashed_password="not-a-real-hash")
    db.add(user)
    db.flush()
    return user


def _asset(db: Session, symbol: str, *, active: bool = True) -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.", active=active)
    db.add(asset)
    db.flush()
    return asset


def _ratio(db: Session, asset: Asset, metric: str, value: float) -> None:
    db.add(
        FinancialMetric(
            asset_id=asset.id, metric=metric, value=Decimal(str(value)),
            source="test", confidence="low",
        )
    )
    db.flush()


def _thesis_with_trigger(
    db: Session,
    user: AppUser,
    asset: Asset,
    *,
    metric: str = "debt_to_equity",
    operator: str = "gt",
    threshold: float = 1.5,
):
    return create_thesis(
        db,
        user_id=user.id,
        asset=asset,
        title="Test thesis",
        body="Because reasons.",
        stance="bull",
        conviction=3,
        triggers=[TriggerInput(metric=metric, operator=operator, threshold=threshold)],
    )


def test_find_asset_by_symbol_is_case_insensitive(db: Session) -> None:
    _asset(db, "ZZTS1")
    assert find_asset_by_symbol(db, "zzts1") is not None


def test_find_asset_by_symbol_includes_inactive_assets(db: Session) -> None:
    """A thesis on a delisted asset is explicitly in scope (Build_plan.md
    §X.1's edge cases) — this must not filter to active=True."""
    _asset(db, "ZZTS2", active=False)
    assert find_asset_by_symbol(db, "ZZTS2") is not None


def test_create_thesis_persists_trigger(db: Session) -> None:
    user = _user(db, "create@example.com")
    asset = _asset(db, "ZZTS3")

    thesis = _thesis_with_trigger(db, user, asset)

    assert thesis.status == "active"
    assert len(thesis.triggers) == 1
    assert thesis.triggers[0].metric == "debt_to_equity"
    assert thesis.triggers[0].currently_breached is False


def test_list_theses_only_returns_the_caller_s_own(db: Session) -> None:
    alice = _user(db, "alice@example.com")
    bob = _user(db, "bob@example.com")
    asset = _asset(db, "ZZTS4")
    _thesis_with_trigger(db, alice, asset)
    _thesis_with_trigger(db, bob, asset)

    assert len(list_theses(db, alice.id)) == 1
    assert len(list_theses(db, bob.id)) == 1


def test_get_thesis_returns_none_for_another_user_s_thesis(db: Session) -> None:
    alice = _user(db, "alice2@example.com")
    bob = _user(db, "bob2@example.com")
    asset = _asset(db, "ZZTS5")
    thesis = _thesis_with_trigger(db, alice, asset)

    assert get_thesis(db, bob.id, thesis.id) is None
    assert get_thesis(db, alice.id, thesis.id) is not None


def test_update_thesis_changes_only_given_fields(db: Session) -> None:
    user = _user(db, "update@example.com")
    asset = _asset(db, "ZZTS6")
    thesis = _thesis_with_trigger(db, user, asset)

    updated = update_thesis(db, user.id, thesis.id, status="invalidated")

    assert updated is not None
    assert updated.status == "invalidated"
    assert updated.title == "Test thesis"  # untouched


def test_update_thesis_returns_none_for_another_user_s_thesis(db: Session) -> None:
    alice = _user(db, "alice3@example.com")
    bob = _user(db, "bob3@example.com")
    asset = _asset(db, "ZZTS7")
    thesis = _thesis_with_trigger(db, alice, asset)

    assert update_thesis(db, bob.id, thesis.id, status="closed") is None


def test_delete_thesis_removes_triggers_too(db: Session) -> None:
    user = _user(db, "delete@example.com")
    asset = _asset(db, "ZZTS8")
    thesis = _thesis_with_trigger(db, user, asset)
    thesis_id = thesis.id

    assert delete_thesis(db, user.id, thesis_id) is True

    assert get_thesis(db, user.id, thesis_id) is None
    assert db.query(ThesisTrigger).filter_by(thesis_id=thesis_id).count() == 0


def test_delete_thesis_returns_false_for_another_user_s_thesis(db: Session) -> None:
    alice = _user(db, "alice4@example.com")
    bob = _user(db, "bob4@example.com")
    asset = _asset(db, "ZZTS9")
    thesis = _thesis_with_trigger(db, alice, asset)

    assert delete_thesis(db, bob.id, thesis.id) is False
    assert get_thesis(db, alice.id, thesis.id) is not None


def test_eval_writes_an_event_and_challenges_the_thesis_on_breach(db: Session) -> None:
    user = _user(db, "eval1@example.com")
    asset = _asset(db, "ZZTS10")
    _ratio(db, asset, "debtToEquity", 2.0)  # breaches "> 1.5"
    thesis = _thesis_with_trigger(db, user, asset)

    result = run_thesis_eval(db)

    assert result.events_created == 1
    assert result.errors == 0
    db.refresh(thesis)
    assert thesis.status == "challenged"
    events = db.query(ThesisEvent).filter_by(thesis_id=thesis.id).all()
    assert len(events) == 1
    assert events[0].observed_value == Decimal("2.0")


def test_eval_does_not_duplicate_events_for_a_still_breached_trigger(db: Session) -> None:
    user = _user(db, "eval2@example.com")
    asset = _asset(db, "ZZTS11")
    _ratio(db, asset, "debtToEquity", 2.0)
    _thesis_with_trigger(db, user, asset, metric="debt_to_equity", operator="gt", threshold=1.5)

    first = run_thesis_eval(db)
    second = run_thesis_eval(db)

    assert first.events_created == 1
    assert second.events_created == 0


def test_eval_does_not_fire_when_condition_is_not_met(db: Session) -> None:
    user = _user(db, "eval3@example.com")
    asset = _asset(db, "ZZTS12")
    _ratio(db, asset, "debtToEquity", 0.5)  # does not breach "> 1.5"
    thesis = _thesis_with_trigger(db, user, asset)

    result = run_thesis_eval(db)

    assert result.events_created == 0
    db.refresh(thesis)
    assert thesis.status == "active"


def test_eval_does_not_touch_state_when_metric_is_unresolvable(db: Session) -> None:
    """No FinancialMetric row stored at all — must not fabricate a result."""
    user = _user(db, "eval4@example.com")
    asset = _asset(db, "ZZTS13")
    thesis = _thesis_with_trigger(db, user, asset)

    result = run_thesis_eval(db)

    assert result.events_created == 0
    assert result.triggers_evaluated == 1
    db.refresh(thesis)
    assert thesis.status == "active"


def test_eval_re_fires_after_un_breaching_and_breaching_again(db: Session) -> None:
    user = _user(db, "eval5@example.com")
    asset = _asset(db, "ZZTS14")
    _ratio(db, asset, "debtToEquity", 2.0)
    _thesis_with_trigger(db, user, asset, metric="debt_to_equity", operator="gt", threshold=1.5)

    run_thesis_eval(db)  # first breach -> 1 event

    # Un-breach: update the stored ratio directly (mirrors a fresh fetch
    # landing a healthier number).
    row = db.query(FinancialMetric).filter_by(asset_id=asset.id, metric="debtToEquity").one()
    row.value = Decimal("0.5")
    db.flush()
    healed = run_thesis_eval(db)
    assert healed.events_created == 0  # recovery is silent, no event

    row.value = Decimal("3.0")
    db.flush()
    re_breached = run_thesis_eval(db)

    assert re_breached.events_created == 1  # breaching again produces a new event


def test_eval_skips_invalidated_and_closed_theses(db: Session) -> None:
    user = _user(db, "eval6@example.com")
    asset = _asset(db, "ZZTS15")
    _ratio(db, asset, "debtToEquity", 2.0)
    thesis = _thesis_with_trigger(db, user, asset)
    update_thesis(db, user.id, thesis.id, status="invalidated")

    result = run_thesis_eval(db)

    assert result.triggers_evaluated == 0
    assert result.events_created == 0


def test_eval_includes_theses_on_inactive_assets(db: Session) -> None:
    """The whole reason this doesn't reuse daily_ingestion's active-equity
    universe helper — a delisted asset's thesis must still get evaluated."""
    user = _user(db, "eval7@example.com")
    asset = _asset(db, "ZZTS16", active=False)
    _ratio(db, asset, "debtToEquity", 2.0)
    _thesis_with_trigger(db, user, asset, metric="debt_to_equity", operator="gt", threshold=1.5)

    result = run_thesis_eval(db)

    assert result.events_created == 1
