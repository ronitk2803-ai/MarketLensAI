import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, Company, FinancialMetric, Industry, PriceOHLCV
from app.engines.opportunity.conditions import Condition, Group
from app.engines.opportunity.registry import SCREENS
from app.services.opportunities import run_screen
from app.services.screener import CUSTOM_SCREEN_ID, run_condition_screen


def _asset(db: Session, symbol: str) -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.")
    db.add(asset)
    db.flush()
    return asset


def _add_bars(
    db: Session, asset: Asset, closes: list[float], *, volumes: list[int] | None = None
) -> None:
    today = dt.date.today()
    n = len(closes)
    for i, close in enumerate(closes):
        db.add(
            PriceOHLCV(
                asset_id=asset.id,
                date=today - dt.timedelta(days=n - 1 - i),
                open=Decimal(str(close)),
                high=Decimal(str(close)),
                low=Decimal(str(close)),
                close=Decimal(str(close)),
                volume=volumes[i] if volumes else 1000,
                source="test",
            )
        )
    db.flush()


def _ratio(db: Session, asset: Asset, metric: str, value: float) -> None:
    db.add(
        FinancialMetric(
            asset_id=asset.id, metric=metric, value=Decimal(str(value)),
            source="test", confidence="low",
        )
    )
    db.flush()


def _cond(metric: str, operator: str, threshold: float) -> Condition:
    return Condition(metric=metric, operator=operator, threshold=threshold)  # type: ignore[arg-type]


def test_custom_screen_id_never_collides_with_a_registered_screen() -> None:
    assert CUSTOM_SCREEN_ID not in SCREENS


def test_and_tree_returns_only_assets_matching_every_condition(db: Session) -> None:
    both = _asset(db, "ZZSC1")
    only_one = _asset(db, "ZZSC2")
    _add_bars(db, both, [100.0] * 25 + [60.0], volumes=[1000] * 25 + [9000])
    _add_bars(db, only_one, [100.0] * 25 + [60.0], volumes=[1000] * 26)

    tree = Group(
        op="and",
        children=[_cond("change_5d_pct", "lt", -10), _cond("relative_volume", "gte", 2.0)],
    )
    result = run_condition_screen(db, tree)

    symbols = {r.hit.asset.symbol for r in result.ranked}
    assert "ZZSC1" in symbols
    assert "ZZSC2" not in symbols


def test_or_tree_returns_assets_matching_either_condition(db: Session) -> None:
    fell = _asset(db, "ZZSC3")
    surged = _asset(db, "ZZSC4")
    neither = _asset(db, "ZZSC5")
    _add_bars(db, fell, [100.0] * 25 + [60.0], volumes=[1000] * 26)
    _add_bars(db, surged, [100.0] * 26, volumes=[1000] * 25 + [9000])
    _add_bars(db, neither, [100.0] * 26, volumes=[1000] * 26)

    tree = Group(
        op="or",
        children=[_cond("change_5d_pct", "lt", -10), _cond("relative_volume", "gte", 2.0)],
    )
    symbols = {r.hit.asset.symbol for r in run_condition_screen(db, tree).ranked}

    assert {"ZZSC3", "ZZSC4"} <= symbols
    assert "ZZSC5" not in symbols


def test_nested_group_a_and_b_or_c(db: Session) -> None:
    """Matching only the inner OR's second branch is still a match — the
    case a flat AND-only model could not express."""
    asset = _asset(db, "ZZSC6")
    _add_bars(db, asset, [100.0] * 25 + [60.0], volumes=[1000] * 26)

    tree = Group(
        op="and",
        children=[
            _cond("close", "lt", 200),
            Group(
                op="or",
                children=[_cond("relative_volume", "gte", 99.0), _cond("change_5d_pct", "lt", -10)],
            ),
        ],
    )
    symbols = {r.hit.asset.symbol for r in run_condition_screen(db, tree).ranked}
    assert "ZZSC6" in symbols


def test_missing_metric_excludes_but_is_reported_as_coverage(db: Session) -> None:
    """Excluding on missing data is right; leaving it invisible is not.
    An empty result has to be explicable."""
    asset = _asset(db, "ZZSC7")
    _add_bars(db, asset, [100.0] * 30)
    # No FinancialMetric row at all for this asset, so it can never match
    # however permissive the threshold is.

    tree = Group(op="and", children=[_cond("return_on_equity", "gt", -999.0)])
    result = run_condition_screen(db, tree)

    assert "ZZSC7" not in {r.hit.asset.symbol for r in result.ranked}
    coverage = {c.metric: c for c in result.coverage}
    # Reported, not silent: the caller can see how much of the universe
    # was even evaluable for this condition.
    assert coverage["return_on_equity"].total == result.universe_size > 0
    assert coverage["return_on_equity"].available < coverage["return_on_equity"].total


def test_ratio_conditions_resolve_from_stored_metrics(db: Session) -> None:
    cheap = _asset(db, "ZZSC8")
    pricey = _asset(db, "ZZSC9")
    _add_bars(db, cheap, [100.0] * 30)
    _add_bars(db, pricey, [100.0] * 30)
    _ratio(db, cheap, "trailingPE", 8.0)
    _ratio(db, pricey, "trailingPE", 90.0)

    tree = Group(op="and", children=[_cond("trailing_pe", "lt", 15)])
    symbols = {r.hit.asset.symbol for r in run_condition_screen(db, tree).ranked}

    assert "ZZSC8" in symbols
    assert "ZZSC9" not in symbols


def test_hit_metrics_carry_every_screened_value(db: Session) -> None:
    asset = _asset(db, "ZZSC10")
    _add_bars(db, asset, [100.0] * 25 + [60.0], volumes=[1000] * 26)

    tree = Group(
        op="and", children=[_cond("change_5d_pct", "lt", -10), _cond("close", "lt", 200)]
    )
    hit = run_condition_screen(db, tree).ranked[0].hit

    assert set(hit.metrics) == {"change_5d_pct", "close"}
    assert hit.screen_id == CUSTOM_SCREEN_ID


def test_ranks_are_contiguous_after_an_industry_filter(db: Session) -> None:
    """The preset path ranks first and filters after, so a filtered list
    reads 7, 19, 44. New code filters first."""
    industry = Industry(code="zz-fin", name="ZZ Financials", score_profile_key="default")
    other = Industry(code="zz-other", name="ZZ Other", score_profile_key="default")
    db.add_all([industry, other])
    db.flush()

    for i in range(6):
        asset = _asset(db, f"ZZSCIND{i}")
        _add_bars(db, asset, [100.0] * 25 + [60.0], volumes=[1000] * 26)
        db.add(
            Company(asset_id=asset.id, industry_id=industry.id if i % 2 == 0 else other.id)
        )
    db.flush()

    tree = Group(op="and", children=[_cond("change_5d_pct", "lt", -10)])
    result = run_condition_screen(db, tree, industry="zz-fin")

    assert [r.rank for r in result.ranked] == list(range(1, len(result.ranked) + 1))
    assert all(r.hit.asset.symbol.startswith("ZZSCIND") for r in result.ranked)


@pytest.mark.parametrize(
    ("screen_id", "tree"),
    [
        (
            "below_dma200",
            Group(op="and", children=[Condition("dma200_gap_pct", "lt", 0.0)]),
        ),
        (
            "down_30d",
            Group(op="and", children=[Condition("change_30d_pct", "lte", -10.0)]),
        ),
        (
            "unusual_volume",
            Group(op="and", children=[Condition("relative_volume", "gte", 2.0)]),
        ),
    ],
)
def test_preset_screens_are_expressible_as_condition_trees(
    db: Session, screen_id: str, tree: Group
) -> None:
    """Proves the metric vocabulary actually covers the registered
    screens, and pins the registry's frozen thresholds against drift. If
    a preset's threshold changes without its metric equivalent changing,
    this fails."""
    falling = _asset(db, "ZZPRESET1")
    steady = _asset(db, "ZZPRESET2")
    heavy = _asset(db, "ZZPRESET3")
    # ~250 sessions so dma200 is defined; a long decline so the down and
    # below-DMA screens both have something real to find.
    _add_bars(db, falling, [200.0] * 220 + [100.0] * 40, volumes=[1000] * 260)
    _add_bars(db, steady, [100.0] * 260, volumes=[1000] * 260)
    _add_bars(db, heavy, [100.0] * 260, volumes=[1000] * 259 + [9000])

    preset_symbols = {h.asset.symbol for h in run_screen(db, screen_id)}
    tree_symbols = {r.hit.asset.symbol for r in run_condition_screen(db, tree).ranked}

    assert preset_symbols == tree_symbols
