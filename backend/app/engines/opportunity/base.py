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

    @abstractmethod
    def evaluate(self, universe: dict[AssetRef, list[Bar]]) -> list[Hit]:
        """`universe` maps each asset to its adjusted bars, ascending by date."""
