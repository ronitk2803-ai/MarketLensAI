from dataclasses import dataclass

from app.engines.indicators.moving_average import ema


@dataclass(frozen=True, slots=True)
class MACDResult:
    macd_line: list[float | None]
    signal_line: list[float | None]
    histogram: list[float | None]


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> MACDResult:
    if fast >= slow:
        raise ValueError("fast window must be shorter than slow window")

    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)

    macd_line: list[float | None] = [
        None if f is None or s is None else f - s for f, s in zip(fast_ema, slow_ema, strict=True)
    ]

    # EMA the defined tail of macd_line, then map back onto the full-length series.
    first_defined = next((i for i, v in enumerate(macd_line) if v is not None), None)
    if first_defined is None:
        return MACDResult(macd_line, [None] * len(closes), [None] * len(closes))

    macd_tail = [v for v in macd_line[first_defined:] if v is not None]
    signal_tail = ema(macd_tail, signal)

    signal_line: list[float | None] = [None] * len(closes)
    signal_line[first_defined : first_defined + len(signal_tail)] = signal_tail

    histogram: list[float | None] = [
        None if m is None or s is None else m - s
        for m, s in zip(macd_line, signal_line, strict=True)
    ]

    return MACDResult(macd_line=macd_line, signal_line=signal_line, histogram=histogram)
