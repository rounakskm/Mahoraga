"""Backtest harness ABC + FitnessReport (P1.6 B1).

Per `backtest-harness-spec.md` §2, §5. Strategies are pure transforms
of (features, regime) → per-bar target weights. The engine (B2) owns
PnL math, risk-limit enforcement, and FitnessReport assembly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import ClassVar

import pandas as pd

from services.trader.features.base import Feature


class PlaceholderFeatureError(ValueError):
    """Raised when a strategy requires a placeholder feature without opt-in."""


class Strategy(ABC):
    """Abstract base for a backtestable trading strategy.

    Subclasses set `name`, `requires_features`, optionally
    `allow_placeholder_features=True`. `generate_signals` must be a
    pure function of the inputs — no filesystem / network reads — so
    the engine can swap reads/writes without strategy changes.
    """

    name: str
    requires_features: ClassVar[list[str]] = []
    allow_placeholder_features: ClassVar[bool] = False

    @abstractmethod
    def generate_signals(
        self,
        *,
        feature_frame: pd.DataFrame,
        regime_frame: pd.DataFrame,
    ) -> pd.DataFrame:
        """Return per-bar target weights in [-1, 1] per ticker.

        Output columns: `ticker`, `bar_timestamp`, `target_weight`.
        The engine applies a one-bar execution lag — weights at bar T
        become positions held at the close of bar T+1.
        """


@dataclass(frozen=True)
class FitnessReport:
    """Summary statistics for one `Backtest.run()` invocation.

    Frozen so it can be hashed + cached in the strategy registry.
    `per_regime` carries per-MESO-label sub-stats so Phase 3+ can
    select the best-fit strategy per regime without re-running the
    backtest. `rejected_reason` is set when the placeholder-feature
    gate rejects the strategy at validation time — the report is
    returned but every metric is zero.
    """

    strategy: str
    start: date
    end: date
    total_return: float
    sharpe: float
    max_drawdown: float
    num_trades: int
    win_rate: float
    halted_at: datetime | None = None
    per_regime: dict[str, dict[str, float]] = field(default_factory=dict)
    rejected_reason: str | None = None


def validate_strategy(
    strategy: Strategy,
    *,
    builtin_features: list[Feature],
) -> None:
    """Apply the P1.4 placeholder-feature gate to `strategy`.

    Raises `PlaceholderFeatureError` if the strategy requires any
    feature flagged `placeholder=True` and has not opted in via
    `allow_placeholder_features=True`. This is the boundary that
    forces Phase 4 to ship real sentiment before any
    sentiment-dependent strategy can train.
    """
    placeholder_names = {f.name for f in builtin_features if f.placeholder}
    if not placeholder_names:
        return
    needed_placeholders = [
        name for name in strategy.requires_features if name in placeholder_names
    ]
    if not needed_placeholders:
        return
    if strategy.allow_placeholder_features:
        return
    raise PlaceholderFeatureError(
        f"Strategy {strategy.name!r} requires placeholder features "
        f"{needed_placeholders!r} but did not set "
        f"allow_placeholder_features=True. Until Phase 4 ships real "
        f"sentiment, sentiment-dependent strategies must opt in "
        f"explicitly to acknowledge they're training on a placeholder."
    )
