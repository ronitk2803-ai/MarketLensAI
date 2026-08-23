"""Layer 2 attention ranking (Build_plan.md §K) — pure, no IO.

Annotates Layer 1 hits with the Opportunity Score (computed elsewhere,
app/engines/scoring/ — this doesn't invent a new signal) and re-sorts so a
hit with stronger underlying fundamentals/valuation outranks a hit that
only "looks worse" by raw decline magnitude — the founder_vision.md
Stock-A/Stock-B distinction, applied across a whole screen's results
instead of one company at a time.

Hits with no available score are appended after every scored hit, in their
original (Layer 1) order — never assigned a fabricated middle score just
to participate in the sort.
"""

from dataclasses import dataclass

from app.engines.opportunity.base import Hit


@dataclass(frozen=True, slots=True)
class RankedHit:
    hit: Hit
    opportunity_score: float | None
    score_coverage: float | None
    rank: int


def apply_attention_ranking(
    hits: list[Hit], scores: dict[str, tuple[float | None, float | None]]
) -> list[RankedHit]:
    """`scores` maps "{exchange}:{symbol}" -> (opportunity_score, coverage)."""
    scored: list[tuple[Hit, float, float | None]] = []
    unscored: list[Hit] = []

    for hit in hits:
        key = f"{hit.asset.exchange}:{hit.asset.symbol}"
        score, coverage = scores.get(key, (None, None))
        if score is not None:
            scored.append((hit, score, coverage))
        else:
            unscored.append(hit)

    scored.sort(key=lambda t: -t[1])

    ranked = [
        RankedHit(hit=hit, opportunity_score=score, score_coverage=coverage, rank=i + 1)
        for i, (hit, score, coverage) in enumerate(scored)
    ]
    offset = len(ranked)
    ranked.extend(
        RankedHit(hit=hit, opportunity_score=None, score_coverage=None, rank=offset + i + 1)
        for i, hit in enumerate(unscored)
    )
    return ranked
