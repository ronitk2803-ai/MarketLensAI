"""Peak-to-recovery falls in a company's own price history (Build_plan.md
§S.21, Screener.md §10). Pure, deterministic, no IO.

Computed on corporate-action-adjusted closes only. Adjustment covers splits
and bonuses but deliberately not rights issues or demergers (see
app/engines/adjustment.py), so a mechanical drop from one of those can
still surface here as a fall that never recovered. This package does not
guess about that; `Episode.worst_session_pct` is the tell, and surfacing it
against the company's corporate actions is the caller's job.

Context, never a prediction (Screener.md:477-479). Nothing here computes an
expected recovery, a probability, a projected date, or **any aggregate
across episodes** — a marginal new high can legitimately split one long
fall into two, which is harmless for a dated list and wrong for a mean.
"""

from app.engines.historical.compare import (
    DEFAULT_COMPARABLE_LIMIT,
    DIMENSIONS_COMPARED,
    DIMENSIONS_UNAVAILABLE,
    SPEC_DIMENSIONS,
    Comparable,
    ComparisonResult,
    rank_comparables,
)
from app.engines.historical.episodes import (
    DEFAULT_MIN_DECLINE_PCT,
    Episode,
    detect_episodes,
)

__all__ = [
    "Episode",
    "detect_episodes",
    "DEFAULT_MIN_DECLINE_PCT",
    "Comparable",
    "ComparisonResult",
    "rank_comparables",
    "DEFAULT_COMPARABLE_LIMIT",
    "SPEC_DIMENSIONS",
    "DIMENSIONS_COMPARED",
    "DIMENSIONS_UNAVAILABLE",
]
