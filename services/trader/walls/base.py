from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

import pandas as pd

if TYPE_CHECKING:
    from services.trader.backtest.base import FitnessReport, Strategy


@dataclass(frozen=True)
class WallReport:
    wall_name: str
    passed: bool
    score: float  # 0.0–1.0; higher = more confidence
    reason: str
    sub_results: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationContext:
    strategy: Strategy
    backtest_result: FitnessReport
    returns: pd.Series  # per-bar portfolio returns; DatetimeIndex
    feature_frame: pd.DataFrame  # PIT-correct feature matrix
    regime_frame: pd.DataFrame  # PIT-correct regime classifications
    universe: list[str]  # ordered ticker list
    metadata: dict[str, object] = field(default_factory=dict)


class Wall(ABC):
    name: ClassVar[str]

    @abstractmethod
    def evaluate(self, ctx: EvaluationContext) -> WallReport:
        """Evaluate the strategy against this wall.

        Must be deterministic, complete in < 5 s, and never raise —
        return passed=False with a descriptive reason on error instead.
        """
