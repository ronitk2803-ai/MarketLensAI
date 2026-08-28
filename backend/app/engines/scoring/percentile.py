"""Peer-percentile normalization (Build_plan.md §L/§X.4, the "genuine gap"
`registry.py` documented as still-unbuilt) — pure, no IO.

The absolute-threshold components in `components.py` compare every company
against the same fixed bands regardless of industry — a trailing P/E of 25
scores identically whether the company is an IT services firm (Nifty 500
median ~28) or a PSU bank (median nearer 8). `app/services/fundamentals.py`'s
`get_sector_ratio_values` gathers the peer group; this turns a value plus
that peer group into a 0-100 rank the aggregator can use exactly like any
other normalized component score.
"""


def percentile_rank(value: float, peers: list[float]) -> float:
    """0-100: the percentage of `peers` at or below `value`. Standard
    rank-based percentile (not a parametric one assuming a normal
    distribution) — Nifty 500 fundamentals are exactly the kind of skewed,
    small-sample distribution that assumption would misrepresent.

    Direction-agnostic on purpose: this reports *where* `value` sits, not
    whether that's attractive. The caller (app/services/scoring.py) knows
    whether higher or lower is more attractive for a given metric and
    orients the result (this rank directly, or `100 - rank`) before it
    ever reaches `ScoreInputs` — by the time a percentile lands there, it
    already means "higher = more attractive," same as every other
    normalized component value.

    `peers` should include `value` itself if the asset being scored has a
    stored value for this metric (it does, by construction — see
    gather_score_inputs) — that's what makes "50th percentile" mean
    "typical for this peer group" rather than something subtly off by one.
    """
    if not peers:
        raise ValueError("percentile_rank needs a non-empty peer list")
    at_or_below = sum(1 for p in peers if p <= value)
    return 100 * at_or_below / len(peers)
