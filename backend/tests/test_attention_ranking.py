from app.domain.models import AssetRef
from app.engines.opportunity.base import Hit
from app.engines.opportunity.ranking import apply_attention_ranking

STOCK_A = AssetRef(symbol="STOCKA", exchange="NSE")  # -30%, weak fundamentals
STOCK_B = AssetRef(symbol="STOCKB", exchange="NSE")  # -22%, strong fundamentals
STOCK_C = AssetRef(symbol="STOCKC", exchange="NSE")  # no score available


def _hit(asset: AssetRef, change_pct: float) -> Hit:
    return Hit(asset=asset, screen_id="down_30d", metrics={"change_pct": change_pct})


def test_founder_vision_stock_b_outranks_stock_a_despite_smaller_decline() -> None:
    """The exact scenario from founder_vision.md: a larger raw decline
    (Stock A) must NOT automatically outrank a smaller decline with
    stronger fundamentals (Stock B)."""
    hits = [_hit(STOCK_A, -30.0), _hit(STOCK_B, -22.0)]
    scores = {
        "NSE:STOCKA": (25.0, 1.0),  # weak fundamentals -> low opportunity score
        "NSE:STOCKB": (75.0, 1.0),  # stable fundamentals -> high opportunity score
    }

    ranked = apply_attention_ranking(hits, scores)

    assert [r.hit.asset for r in ranked] == [STOCK_B, STOCK_A]
    assert ranked[0].rank == 1
    assert ranked[0].opportunity_score == 75.0
    assert ranked[1].rank == 2


def test_unscored_hits_are_appended_after_all_scored_hits() -> None:
    hits = [_hit(STOCK_C, -40.0), _hit(STOCK_A, -30.0), _hit(STOCK_B, -22.0)]
    scores = {"NSE:STOCKA": (25.0, 1.0), "NSE:STOCKB": (75.0, 1.0)}

    ranked = apply_attention_ranking(hits, scores)

    assert [r.hit.asset for r in ranked] == [STOCK_B, STOCK_A, STOCK_C]
    assert ranked[-1].opportunity_score is None
    assert ranked[-1].score_coverage is None


def test_unscored_hits_keep_their_original_relative_order() -> None:
    stock_d = AssetRef(symbol="STOCKD", exchange="NSE")
    hits = [_hit(STOCK_C, -40.0), _hit(stock_d, -35.0)]  # neither has a score

    ranked = apply_attention_ranking(hits, {})

    assert [r.hit.asset for r in ranked] == [STOCK_C, stock_d]


def test_empty_hits_returns_empty() -> None:
    assert apply_attention_ranking([], {}) == []


def test_ranks_are_sequential_starting_at_one() -> None:
    hits = [_hit(STOCK_A, -30.0), _hit(STOCK_B, -22.0), _hit(STOCK_C, -40.0)]
    scores = {"NSE:STOCKA": (25.0, 1.0), "NSE:STOCKB": (75.0, 1.0)}

    ranked = apply_attention_ranking(hits, scores)

    assert [r.rank for r in ranked] == [1, 2, 3]
