def drawdown_series(closes: list[float]) -> list[float]:
    """`output[i]` = (closes[i] - running_peak) / running_peak, in [-1, 0].
    0 means `closes[i]` is a new (or tied) all-time high so far."""
    result = []
    peak = float("-inf")
    for close in closes:
        peak = max(peak, close)
        result.append((close - peak) / peak if peak != 0 else 0.0)
    return result


def max_drawdown(closes: list[float]) -> float:
    """The single worst peak-to-trough decline over the whole series (<=0; 0 if empty)."""
    series = drawdown_series(closes)
    return min(series) if series else 0.0
