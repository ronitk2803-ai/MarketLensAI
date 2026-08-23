"""Component normalization functions — each maps a raw input to a 0-100
"attractiveness" score (higher = more attractive), or `None` if its input
is unavailable. Thresholds are rule-based judgment calls, not derived from
data (see base.py's module docstring)."""

from collections.abc import Callable

from app.engines.scoring.base import ScoreInputs, clip


def valuation(inputs: ScoreInputs) -> float | None:
    """Lower price-to-book = more attractive. P/B<=1 scores 100 (trading
    near/below book value); P/B>=6 scores 0."""
    if inputs.price_to_book is None:
        return None
    return clip(100 - (inputs.price_to_book - 1) * (100 / 5))


def fundamental_quality(inputs: ScoreInputs) -> float | None:
    """Blends balance-sheet leverage (lower D/E better) and gross margin
    (higher better). Needs at least one of the two."""
    scores = []
    if inputs.debt_to_equity is not None:
        # D/E of 0.5 (or less) -> 100; D/E of 3.0 (or more) -> 0.
        scores.append(clip(100 - (inputs.debt_to_equity - 0.5) * (100 / 2.5)))
    if inputs.gross_margins is not None:
        # 40%+ gross margin -> 100; scales down linearly to 0%.
        scores.append(clip(inputs.gross_margins / 0.40 * 100))
    if not scores:
        return None
    return sum(scores) / len(scores)


def growth(inputs: ScoreInputs) -> float | None:
    """Blends revenue and earnings growth. 0% growth is neutral (50);
    +50% or more is maximally attractive; -50% or worse is 0."""
    scores = []
    if inputs.revenue_growth is not None:
        scores.append(clip(50 + inputs.revenue_growth * 100))
    if inputs.earnings_growth is not None:
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
    "growth": growth,
    "technical_setup": technical_setup,
    "participation": participation,
}
