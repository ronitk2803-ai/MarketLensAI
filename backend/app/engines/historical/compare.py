"""Ranking a company's past falls against the one it is in now.

Pure, no IO. Deliberately produces NO blended "similarity" number, for
three reasons:

1. Only three of the seven dimensions Screener.md §10 asks us to compare
   are computable from the data we hold (see DIMENSIONS_UNAVAILABLE), so a
   composite reported as "similarity" overstates what was compared.
2. Blending would need per-dimension weights, and those would be
   unversioned code constants — exactly what Build_plan.md §L forbids
   ("Weights are versioned configuration, never code constants"), with no
   score_profile behind them.
3. Screener.md:477-479 is explicit that historical recovery is context and
   never a prediction. A single "87% similar" is the artifact that gets
   read as *this is the analog, so expect the analog's outcome*.

So the ordering key is one plainly-stated quantity — how far each past
fall's depth is from the current one, in percentage points — and it is
returned on every row rather than hidden, the same way apply_attention_
ranking exposes the opportunity_score it sorts by. Duration and volatility
travel alongside as facts, untransformed.
"""

from dataclasses import dataclass

from app.engines.historical.episodes import Episode

# The seven comparison dimensions named at Screener.md:465-473. Kept as one
# list so the split below is a reviewable declaration rather than a silent
# gap, and so adding a dimension forces its test to be updated.
SPEC_DIMENSIONS = (
    "magnitude",
    "duration",
    "volatility",
    "news_event_type",
    "fundamentals",
    "valuation",
    "sector_environment",
)

# Everything derivable from adjusted closes alone.
DIMENSIONS_COMPARED = ("magnitude", "duration", "volatility")

# Not compared, and not guessed at. There is no multi-year news archive
# (news_article holds ~1 month and every event_type is NULL), and no
# point-in-time fundamentals, valuation or sector history to read a
# years-old fall against. Declared here so the gap is part of the API
# contract instead of an undocumented omission.
DIMENSIONS_UNAVAILABLE = tuple(d for d in SPEC_DIMENSIONS if d not in DIMENSIONS_COMPARED)

DEFAULT_COMPARABLE_LIMIT = 5


@dataclass(frozen=True, slots=True)
class Comparable:
    episode: Episode
    # Unsigned percentage POINTS between this fall's depth and the current
    # one's — `pp`, not `pct`, because it is a distance on a percentage
    # scale, not a percentage of anything. None when there is no current
    # fall to measure against.
    decline_gap_pp: float | None


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    comparable: list[Comparable]
    # Every past fall over the threshold, before exclusion or the cap — so
    # the caller can say "5 of 9" rather than implying there were only 5.
    past_count: int
    excluded_left_censored: int


def rank_comparables(
    current: Episode | None,
    past: list[Episode],
    *,
    limit: int = DEFAULT_COMPARABLE_LIMIT,
) -> ComparisonResult:
    """Past falls ordered by how close their depth is to the current fall's.

    Left-censored past falls are excluded and counted separately: their
    depth is a lower bound, so ranking one against measured depths would
    compare a truncated number to a real one. (A left-censored *current*
    fall is still worth comparing against — it is the thing the reader is
    living through — so only `past` is filtered here.)

    With no current fall there is nothing to measure distance from, so the
    ordering falls back to most recent first and every gap is None. The
    list is still returned: past falls are useful context on their own,
    which is the whole point of the feature.
    """
    excluded = sum(1 for episode in past if episode.left_censored)
    usable = [episode for episode in past if not episode.left_censored]

    if current is None:
        ordered = sorted(usable, key=lambda e: e.peak_date, reverse=True)
        comparable = [Comparable(episode=e, decline_gap_pp=None) for e in ordered]
    else:
        # Ties break towards the more recent fall.
        ordered = sorted(
            usable,
            key=lambda e: (abs(e.decline_pct - current.decline_pct), -e.peak_date.toordinal()),
        )
        comparable = [
            Comparable(episode=e, decline_gap_pp=abs(e.decline_pct - current.decline_pct))
            for e in ordered
        ]

    return ComparisonResult(
        comparable=comparable[:limit],
        past_count=len(past),
        excluded_left_censored=excluded,
    )
