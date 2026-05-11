"""Public surface of the backtest harness package.

Phase 1 sub-feature 6 (`docs/superpowers/specs/phase-1-foundation/
backtest-harness-spec.md`). Re-exports the ABC + dataclasses + the
stub strategy + (after B2) the engine.
"""

from __future__ import annotations

from services.trader.backtest.base import (
    FitnessReport,
    PlaceholderFeatureError,
    Strategy,
    validate_strategy,
)
from services.trader.backtest.engine import Backtest
from services.trader.backtest.strategies import BuyAndHold

__all__ = [
    "Backtest",
    "BuyAndHold",
    "FitnessReport",
    "PlaceholderFeatureError",
    "Strategy",
    "validate_strategy",
]
