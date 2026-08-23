"""Registered Layer 1 screens (Build_plan.md §6/§K).

Thresholds are a starting point, not tuned against real outcomes — there's
no backtesting yet (that's P2, §L). Adding a new screen *type* means a new
`Screen` subclass in screens.py; adding a new period/threshold variant of
an existing type means one new line here — no other code changes.
"""

from app.engines.opportunity.base import Screen
from app.engines.opportunity.screens import BelowDMA, DownOverPeriod, UnusualVolume

SCREENS: dict[str, Screen] = {
    "down_5d": DownOverPeriod("down_5d", period_days=5, min_decline_pct=5.0),
    "down_10d": DownOverPeriod("down_10d", period_days=10, min_decline_pct=7.0),
    "down_15d": DownOverPeriod("down_15d", period_days=15, min_decline_pct=8.0),
    "down_30d": DownOverPeriod("down_30d", period_days=30, min_decline_pct=10.0),
    "down_60d": DownOverPeriod("down_60d", period_days=60, min_decline_pct=15.0),
    "down_90d": DownOverPeriod("down_90d", period_days=90, min_decline_pct=20.0),
    "below_dma50": BelowDMA("below_dma50", dma_period=50),
    "below_dma100": BelowDMA("below_dma100", dma_period=100),
    "below_dma200": BelowDMA("below_dma200", dma_period=200),
    "unusual_volume": UnusualVolume("unusual_volume", window=20, min_multiplier=2.0),
}

SCREEN_LABELS: dict[str, str] = {
    "down_5d": "Down 5%+ in 5 days",
    "down_10d": "Down 7%+ in 10 days",
    "down_15d": "Down 8%+ in 15 days",
    "down_30d": "Down 10%+ in 30 days",
    "down_60d": "Down 15%+ in 60 days",
    "down_90d": "Down 20%+ in 90 days",
    "below_dma50": "Below 50-day average",
    "below_dma100": "Below 100-day average",
    "below_dma200": "Below 200-day average",
    "unusual_volume": "Unusual volume (2x+ average)",
}
