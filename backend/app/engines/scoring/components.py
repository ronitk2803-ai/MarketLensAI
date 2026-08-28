"""Component normalization functions — each maps a raw input to a 0-100
"attractiveness" score (higher = more attractive), or `None` if its input
is unavailable. Thresholds are rule-based judgment calls, not derived from
data (see base.py's module docstring)."""

from collections.abc import Callable

from app.engines.scoring.base import ScoreInputs, clip


def valuation(inputs: ScoreInputs) -> float | None:
    """Cheaper P/B (relative to industry peers, when enough exist —
    §L/§X.4) = more attractive. Falls back to the absolute band (P/B<=1
    scores 100, trading near/below book value; P/B>=6 scores 0) when the
    peer group is too small — see ScoreInputs' docstring for the exact
    condition. Both branches share one convention: higher output = more
    attractive, so the aggregator never has to know which one fired."""
    if inputs.price_to_book_percentile is not None:
        return inputs.price_to_book_percentile
    if inputs.price_to_book is None:
        return None
    return clip(100 - (inputs.price_to_book - 1) * (100 / 5))


def fundamental_quality(inputs: ScoreInputs) -> float | None:
    """Blends balance-sheet leverage (lower D/E better) and gross margin
    (higher better). Needs at least one of the two. Each leg independently
    prefers its industry-peer percentile (§L/§X.4) over the absolute band
    below, falling back leg-by-leg — a company with enough D/E peers but
    too few gross-margin peers still gets a peer-relative leverage read
    blended with an absolute-band margin read, rather than losing peer
    treatment entirely because one leg couldn't use it.

    Not used by every profile: `financials` drops this component outright,
    because neither leg means for a lender what it means elsewhere (see
    registry.py).
    """
    scores = []
    if inputs.debt_to_equity_percentile is not None:
        scores.append(inputs.debt_to_equity_percentile)
    elif inputs.debt_to_equity is not None:
        # Yahoo reports debtToEquity as a PERCENTAGE (live Nifty 500 median
        # ~23.8 = 0.24x), so it has to be divided by 100 before comparing
        # against ratio thresholds. Reading it as a ratio was a real bug:
        # it made D/E >= 3% score zero, which pinned 379 of 458 companies
        # (82.8% of everything we had a value for) at 0 on this leg.
        debt_ratio = inputs.debt_to_equity / 100
        # 0.1x (or less) -> 100; 1.5x (or more) -> 0. Calibrated against
        # observed Nifty 500 industry medians (IT/capital goods ~0.08x,
        # healthcare 0.17x, metals 0.41x, power 1.51x) rather than left as
        # the arbitrary band the ratio-unit version happened to use.
        scores.append(clip(100 - (debt_ratio - 0.1) * (100 / 1.4)))
    if inputs.gross_margins_percentile is not None:
        scores.append(inputs.gross_margins_percentile)
    elif inputs.gross_margins is not None:
        # 40%+ gross margin -> 100; scales down linearly to 0%.
        scores.append(clip(inputs.gross_margins / 0.40 * 100))
    if not scores:
        return None
    return sum(scores) / len(scores)


def earnings_valuation(inputs: ScoreInputs) -> float | None:
    """Cheaper trailing P/E relative to industry peers (§L/§X.4), when
    enough exist, else the absolute band: P/E<=15 scores 100; P/E>=60
    scores 0 (the live Nifty 500 median is ~36).

    A non-positive P/E is never scored via either path — a loss-making
    company doesn't have a cheap multiple, it has no multiple. The peer
    percentile already excludes it for the same reason (see
    get_sector_ratio_values's positive_only default), so checking
    trailing_pe here too keeps this function correct even if it's ever
    called with a percentile computed some other way."""
    if inputs.trailing_pe is not None and inputs.trailing_pe <= 0:
        return None
    if inputs.trailing_pe_percentile is not None:
        return inputs.trailing_pe_percentile
    if inputs.trailing_pe is None:
        return None
    return clip(100 - (inputs.trailing_pe - 15) * (100 / 45))


def growth(inputs: ScoreInputs) -> float | None:
    """Blends revenue and earnings growth, each independently preferring
    its industry-peer percentile (§L/§X.4) over the absolute band: 0%
    growth is neutral (50); +50% or more is maximally attractive; -50% or
    worse is 0. Peer comparison for growth is unfiltered by sign
    (get_sector_ratio_values(..., positive_only=False)) — a company with
    declining revenue is exactly the case peer ranking should be able to
    place near the bottom, not exclude from the comparison."""
    scores = []
    if inputs.revenue_growth_percentile is not None:
        scores.append(inputs.revenue_growth_percentile)
    elif inputs.revenue_growth is not None:
        scores.append(clip(50 + inputs.revenue_growth * 100))
    if inputs.earnings_growth_percentile is not None:
        scores.append(inputs.earnings_growth_percentile)
    elif inputs.earnings_growth is not None:
        scores.append(clip(50 + inputs.earnings_growth * 100))
    if not scores:
        return None
    return sum(scores) / len(scores)


def technical_setup(inputs: ScoreInputs) -> float | None:
    """How much of a decline has already happened (drawdown) and how
    oversold RSI looks. This is deliberately just "how strongly does this
    meet the Opportunity Finder's own screening logic" — it does NOT mean
    "this will recover"; that distinction is the whole point of
    founder_vision.md's Paytm/Ola Electric framing, and nothing here
    resolves it. A larger drawdown and a lower RSI both score higher."""
    scores = []
    if inputs.drawdown_pct is not None:
        # drawdown_pct is <= 0. -40% or worse -> 100; 0% -> 0.
        scores.append(clip(-inputs.drawdown_pct / 40 * 100))
    if inputs.rsi14 is not None:
        # RSI 20 (oversold) -> 100; RSI 70+ (overbought) -> 0.
        scores.append(clip(100 - (inputs.rsi14 - 20) * (100 / 50)))
    if not scores:
        return None
    return sum(scores) / len(scores)


def participation(inputs: ScoreInputs) -> float | None:
    """Volume Philosophy (Build_plan.md §9): normalized participation, not
    raw volume. Higher relative volume and higher delivery % both suggest
    more genuine (non-speculative) interest."""
    scores = []
    if inputs.relative_volume is not None:
        # 1x (average) -> 50; 3x+ -> 100; 0x -> 0.
        scores.append(clip(inputs.relative_volume / 3 * 100))
    if inputs.delivery_pct is not None:
        scores.append(clip(inputs.delivery_pct))
    if not scores:
        return None
    return sum(scores) / len(scores)


COMPONENT_FUNCS: dict[str, Callable[[ScoreInputs], float | None]] = {
    "valuation": valuation,
    "fundamental_quality": fundamental_quality,
    "earnings_valuation": earnings_valuation,
    "growth": growth,
    "technical_setup": technical_setup,
    "participation": participation,
}
