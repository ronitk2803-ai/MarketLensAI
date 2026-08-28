import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset
from app.domain.models import Bar, CorporateActionEvent
from app.providers.errors import ProviderError
from app.providers.india.nse_actions import NSECorporateActionsProvider
from app.providers.india.nse_bhavcopy import NSEBhavcopyProvider
from app.providers.india.yfinance_actions import YFinanceCorporateActionsProvider
from app.services.historical_episodes import get_historical_falls


def _nse_unavailable(*args: object, **kwargs: object) -> list[CorporateActionEvent]:
    # This suite controls actions via the yfinance stub below.
    raise ProviderError("nse_actions", "simulated outage")


def _make_asset(db: Session, *, symbol: str = "ZZHIST1", asset_class: str = "EQUITY") -> Asset:
    asset = Asset(
        symbol=symbol,
        exchange="NSE",
        market="IN",
        name="Test Historical Co",
        asset_class=asset_class,
    )
    db.add(asset)
    db.flush()
    return asset


def _bars(closes: list[float]) -> list[Bar]:
    today = dt.date.today()
    n = len(closes)
    return [
        Bar(date=today - dt.timedelta(days=n - 1 - i), open=c, high=c, low=c, close=c, volume=1000)
        for i, c in enumerate(closes)
    ]


def _stub_providers(
    monkeypatch: pytest.MonkeyPatch,
    bars: list[Bar],
    actions: list[CorporateActionEvent] | None = None,
) -> None:
    monkeypatch.setattr(NSEBhavcopyProvider, "get_ohlcv", lambda *a, **k: bars)
    # NSE is tried first (app/services/corporate_actions.py); failing it
    # here keeps this whole suite's actions controlled by the `actions`
    # param via the yfinance fallback, unchanged from before NSE existed.
    monkeypatch.setattr(NSECorporateActionsProvider, "get_corporate_actions", _nse_unavailable)
    monkeypatch.setattr(
        YFinanceCorporateActionsProvider, "get_corporate_actions", lambda *a, **k: actions or []
    )


def test_service_returns_the_open_episode_as_current(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    _stub_providers(monkeypatch, _bars([95, 100, 60]))

    result = get_historical_falls(db, asset)

    assert result.current is not None
    assert result.current.episode.decline_pct == pytest.approx(-40.0)
    assert result.current.episode.recovered is False
    assert result.past_count == 0
    assert result.comparable == []


def test_current_drawdown_is_measured_to_the_latest_close_not_the_trough(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unfinished fall has two honest numbers: how far it fell, and how
    far down it still is. Collapsing them into one would misreport a stock
    that has bounced off its low."""
    asset = _make_asset(db)
    _stub_providers(monkeypatch, _bars([95, 100, 60, 80]))

    result = get_historical_falls(db, asset)

    assert result.current is not None
    assert result.current.episode.decline_pct == pytest.approx(-40.0)
    assert result.current.current_drawdown_pct == pytest.approx(-20.0)
    assert result.current.trough_is_latest_bar is False


def test_trough_is_flagged_when_the_stock_is_still_making_new_lows(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    _stub_providers(monkeypatch, _bars([95, 100, 80, 60]))

    result = get_historical_falls(db, asset)

    assert result.current is not None
    assert result.current.trough_is_latest_bar is True


def test_service_returns_no_current_when_price_is_back_at_its_high(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The past fall is still returned — a stock near its high is exactly
    the case where "what did previous falls do?" is worth reading."""
    asset = _make_asset(db)
    _stub_providers(monkeypatch, _bars([95, 100, 60, 105]))

    result = get_historical_falls(db, asset)

    assert result.current is None
    assert result.past_count == 1
    assert len(result.comparable) == 1
    assert result.comparable[0].decline_gap_pp is None


def test_service_caps_comparables_but_reports_the_full_past_count(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    closes = [95, 100, 60, 105, 63, 110, 66, 115, 69, 120, 72, 125, 75, 130, 78, 135, 81]
    _stub_providers(monkeypatch, _bars(closes))

    result = get_historical_falls(db, asset)

    assert result.current is not None
    assert result.past_count == 7
    assert len(result.comparable) == 5
    assert result.excluded_left_censored == 0


def test_service_applies_corporate_action_adjustment_so_a_bonus_is_not_a_fall(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 1:1 bonus halves the quoted price overnight. Unadjusted that reads
    as a -50% collapse that never recovers — a fabricated event on a stock
    that did not move. This is the single reason the service must go
    through get_adjusted_bars and never load bars itself."""
    asset = _make_asset(db)
    today = dt.date.today()
    ex_date = today - dt.timedelta(days=9)
    raw = _bars([100.0] * 20 + [50.0] * 10)
    bonus = CorporateActionEvent(type="bonus", ex_date=ex_date, ratio=2.0)

    _stub_providers(monkeypatch, raw, [bonus])
    assert get_historical_falls(db, asset).current is None

    # Same bars with the action missing: the drop is read as a real fall,
    # which is what proves the assertion above is actually load-bearing.
    unadjusted = _make_asset(db, symbol="ZZHIST2")
    _stub_providers(monkeypatch, raw, [])
    assert get_historical_falls(db, unadjusted).current is not None


def test_service_empty_when_no_price_data(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    _stub_providers(monkeypatch, [])

    result = get_historical_falls(db, asset)

    assert result.as_of is None
    assert result.history_start is None
    assert result.current is None
    assert result.comparable == []
    assert result.past_count == 0


def test_service_returns_nothing_for_a_non_equity_asset(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Our corporate-actions source doesn't track ETF unit consolidations,
    so one reads as a ~90% crash that never recovers — the same live-
    verified reason the universe loader filters to EQUITY."""
    etf = _make_asset(db, asset_class="ETF")
    _stub_providers(monkeypatch, _bars([95, 100, 60]))

    result = get_historical_falls(db, etf)

    assert result.current is None
    assert result.past_count == 0
