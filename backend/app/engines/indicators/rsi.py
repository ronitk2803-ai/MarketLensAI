"""Relative Strength Index — Wilder's original smoothing method."""


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """`output[i]` is undefined (`None`) until index `period` (inclusive),
    since it takes `period` daily changes — i.e. `period + 1` closes — to
    seed the first value."""
    if period < 1:
        raise ValueError("period must be >= 1")

    result: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return result

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        # deltas[i] feeds the value at closes index i + 1
        result[i + 1] = _rsi_from_averages(avg_gain, avg_loss)

    return result


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
