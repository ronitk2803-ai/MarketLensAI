import statistics

TRADING_DAYS_PER_YEAR = 252


def daily_returns(closes: list[float]) -> list[float]:
    """Simple (not log) day-over-day percentage returns."""
    return [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]


def historical_volatility(
    closes: list[float], window: int = 20, *, annualize: bool = True
) -> list[float | None]:
    """Rolling sample-stdev of daily returns over `window` days, optionally
    annualized (`* sqrt(252)`). `output[i]` covers the `window` returns
    ending at `closes[i]` — needs `window + 1` closes to seed."""
    if window < 2:
        raise ValueError("window must be >= 2 (stdev needs at least 2 samples)")

    returns = daily_returns(closes)
    result: list[float | None] = [None] * len(closes)
    scale = TRADING_DAYS_PER_YEAR**0.5 if annualize else 1.0

    for end in range(window, len(returns) + 1):
        window_returns = returns[end - window : end]
        result[end] = statistics.stdev(window_returns) * scale
    return result
