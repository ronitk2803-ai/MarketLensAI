"""Technical indicators — pure, deterministic, no IO (Build_plan.md §D/§K).

Computed on the corporate-action-adjusted series (app.engines.adjustment),
never on raw stored bars, so a split/bonus never shows up as a false
crossover or momentum signal.
"""

from app.engines.indicators.drawdown import drawdown_series, max_drawdown
from app.engines.indicators.macd import MACDResult, macd
from app.engines.indicators.moving_average import ema, sma
from app.engines.indicators.relative import relative_strength, relative_volume
from app.engines.indicators.rsi import rsi
from app.engines.indicators.volatility import historical_volatility

__all__ = [
    "sma",
    "ema",
    "rsi",
    "macd",
    "MACDResult",
    "historical_volatility",
    "drawdown_series",
    "max_drawdown",
    "relative_strength",
    "relative_volume",
]
