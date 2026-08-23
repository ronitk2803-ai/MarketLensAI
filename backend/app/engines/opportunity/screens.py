from app.domain.models import AssetRef, Bar
from app.engines.indicators import relative_volume, sma
from app.engines.opportunity.base import Hit, Screen


class DownOverPeriod(Screen):
    """Stocks down at least `min_decline_pct` over the last `period_days`
    trading sessions (Build_plan.md §6/§K)."""

    def __init__(self, screen_id: str, *, period_days: int, min_decline_pct: float) -> None:
        self.screen_id = screen_id
        self.period_days = period_days
        self.min_decline_pct = min_decline_pct

    def evaluate(self, universe: dict[AssetRef, list[Bar]]) -> list[Hit]:
        hits = []
        for asset, bars in universe.items():
            if len(bars) <= self.period_days:
                continue
            start_close = bars[-(self.period_days + 1)].close
            end_close = bars[-1].close
            if start_close <= 0:
                continue
            change_pct = (end_close - start_close) / start_close * 100
            if change_pct <= -self.min_decline_pct:
                hits.append(
                    Hit(
                        asset=asset,
                        screen_id=self.screen_id,
                        metrics={
                            "change_pct": change_pct,
                            "period_days": float(self.period_days),
                            "close": end_close,
                        },
                    )
                )
        return sorted(hits, key=lambda h: h.metrics["change_pct"])


class BelowDMA(Screen):
    """Stocks trading below their N-day moving average (Build_plan.md §K)."""

    def __init__(self, screen_id: str, *, dma_period: int) -> None:
        self.screen_id = screen_id
        self.dma_period = dma_period

    def evaluate(self, universe: dict[AssetRef, list[Bar]]) -> list[Hit]:
        hits = []
        for asset, bars in universe.items():
            closes = [b.close for b in bars]
            if not closes:
                continue
            dma_series = sma(closes, self.dma_period)
            dma_latest = dma_series[-1]
            if dma_latest is None:
                continue
            latest_close = closes[-1]
            if latest_close < dma_latest:
                pct_below = (latest_close - dma_latest) / dma_latest * 100
                hits.append(
                    Hit(
                        asset=asset,
                        screen_id=self.screen_id,
                        metrics={
                            "close": latest_close,
                            "dma": dma_latest,
                            "pct_below": pct_below,
                        },
                    )
                )
        return sorted(hits, key=lambda h: h.metrics["pct_below"])


class UnusualVolume(Screen):
    """Stocks trading at `min_multiplier`x (or more) their trailing average
    volume (Build_plan.md §6/§9 volume philosophy)."""

    def __init__(self, screen_id: str, *, window: int = 20, min_multiplier: float = 2.0) -> None:
        self.screen_id = screen_id
        self.window = window
        self.min_multiplier = min_multiplier

    def evaluate(self, universe: dict[AssetRef, list[Bar]]) -> list[Hit]:
        hits = []
        for asset, bars in universe.items():
            volumes = [b.volume for b in bars]
            if not volumes:
                continue
            rv_series = relative_volume(volumes, self.window)
            rv_latest = rv_series[-1]
            if rv_latest is None or rv_latest < self.min_multiplier:
                continue
            hits.append(
                Hit(
                    asset=asset,
                    screen_id=self.screen_id,
                    metrics={"relative_volume": rv_latest, "volume": float(volumes[-1])},
                )
            )
        return sorted(hits, key=lambda h: -h.metrics["relative_volume"])
