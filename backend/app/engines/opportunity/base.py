"""Layer 1 opportunity screens (Build_plan.md §K) — pure, no IO.

Each screen is a small, parameterized, registered unit (registry.py) that
implements `evaluate(universe) -> list[Hit]` over data the caller already
holds. "New screen = new class, zero core changes" — a new screen *type*
is a new class; a new period/threshold variant of an existing type is one
new registry line.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.domain.models import AssetRef, Bar


@dataclass(frozen=True, slots=True)
class Hit:
    asset: AssetRef
    screen_id: str
    metrics: dict[str, float] = field(default_factory=dict)


class Screen(ABC):
    screen_id: str

    @property
    @abstractmethod
    def required_bars(self) -> int:
        """Minimum trading sessions this screen needs to produce any hit.

        The loader has to size its history window from this rather than from
        one flat default: a fixed 120-*calendar*-day lookback is only ~82
        trading sessions, so `below_dma100` and `below_dma200` silently
        returned zero hits forever — they were listed in the UI and could
        never match, because `sma()` yields None until it has a full window.
        Sizing per screen also keeps the cheap screens cheap instead of
        making every one of them load the deepest screen's history.
        """

    @abstractmethod
    def evaluate(self, universe: dict[AssetRef, list[Bar]]) -> list[Hit]:
        """`universe` maps each asset to its adjusted bars, ascending by date."""
