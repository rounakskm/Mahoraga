"""Public surface of the regime detector package.

Phase 1 sub-feature 5 (`docs/superpowers/specs/phase-1-foundation/
regime-detector-spec.md`). Re-exports the ABC + dataclasses + the
public orchestrator so callers can do:

    from services.trader.regime import (
        RegimeDetector, CompositeRegime, MesoLens,
    )
"""

from __future__ import annotations

from services.trader.regime.base import (
    ClassificationResult,
    CompositeRegime,
    Lens,
    RegimeRunResult,
)
from services.trader.regime.detector import RegimeDetector
from services.trader.regime.macro import MacroLens
from services.trader.regime.meso import MesoLens

__all__ = [
    "ClassificationResult",
    "CompositeRegime",
    "Lens",
    "MacroLens",
    "MesoLens",
    "RegimeDetector",
    "RegimeRunResult",
]
