"""Relative strength vs a benchmark, and relative (participation) volume."""


def relative_strength(
    asset_closes: list[float], benchmark_closes: list[float]
) -> list[float | None]:
    """Indexed-to-100 ratio of cumulative return vs a benchmark (e.g. Nifty
    500 or a sector index) over the same period. Both series must be
    aligned 1:1 by date and start at the same index; a rising line means
    the asset is outperforming the benchmark, regardless of the market's
    own direction."""
    if len(asset_closes) != len(benchmark_closes):
        raise ValueError("asset_closes and benchmark_closes must be the same length")
    if not asset_closes:
        return []

    asset_base = asset_closes[0]
    benchmark_base = benchmark_closes[0]
    if asset_base == 0 or benchmark_base == 0:
        return [None] * len(asset_closes)

    result: list[float | None] = []
    for asset_close, benchmark_close in zip(asset_closes, benchmark_closes, strict=True):
        if benchmark_close == 0:
            result.append(None)
            continue
        asset_index = asset_close / asset_base
        benchmark_index = benchmark_close / benchmark_base
        result.append((asset_index / benchmark_index) * 100.0)
    return result


def relative_volume(volumes: list[int], window: int = 20) -> list[float | None]:
    """`output[i]` = volumes[i] / mean(volumes[i-window:i]) — today's volume
    against the average of the preceding `window` days (today excluded, so
    a genuine spike isn't diluted by including itself in its own average)."""
    if window < 1:
        raise ValueError("window must be >= 1")

    result: list[float | None] = [None] * len(volumes)
    for i in range(window, len(volumes)):
        prior_avg = sum(volumes[i - window : i]) / window
        result[i] = None if prior_avg == 0 else volumes[i] / prior_avg
    return result
