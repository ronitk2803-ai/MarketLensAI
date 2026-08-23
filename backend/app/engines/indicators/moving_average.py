"""Simple and exponential moving averages — pure, no IO (Build_plan.md §D).

Every function here takes a chronologically-ascending list of closes (or
other series) and returns a list of the same length, with `None` wherever
there isn't yet enough history for a value — never a fabricated number.
"""

def sma(values: list[float], window: int) -> list[float | None]:
    """Simple moving average. `output[i]` is the mean of `values[i-window+1:i+1]`."""
    if window < 1:
        raise ValueError("window must be >= 1")

    result: list[float | None] = [None] * len(values)
    running_sum = 0.0
    for i, value in enumerate(values):
        running_sum += value
        if i >= window:
            running_sum -= values[i - window]
        if i >= window - 1:
            result[i] = running_sum / window
    return result


def ema(values: list[float], window: int) -> list[float | None]:
    """Exponential moving average, SMA-seeded at index `window - 1` (standard
    convention): the first EMA value is the SMA of the first `window` values,
    then each subsequent value is `price * k + prev_ema * (1 - k)` with
    `k = 2 / (window + 1)`."""
    if window < 1:
        raise ValueError("window must be >= 1")

    result: list[float | None] = [None] * len(values)
    if len(values) < window:
        return result

    k = 2.0 / (window + 1)
    seed = sum(values[:window]) / window
    result[window - 1] = seed
    prev = seed
    for i in range(window, len(values)):
        prev = values[i] * k + prev * (1 - k)
        result[i] = prev
    return result
