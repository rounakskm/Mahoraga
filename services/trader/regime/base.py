"""Regime-detector ABC + composite dataclasses.

See `docs/superpowers/specs/phase-1-foundation/regime-detector-spec.md`
§5 for the contract. Lenses are pure functions of pre-fetched feature
rows; the orchestrator handles I/O.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

UNDEFINED_LABEL = "undefined"


@dataclass(frozen=True)
class ClassificationResult:
    """One lens's verdict for a single `(scope, asof)` bar.

    `confidence` is `0.0` when the lens cannot classify (NaN inputs,
    insufficient feature warmup). `inputs` is the audit snapshot of
    the raw feature values that drove the decision.
    """

    label: str
    confidence: float
    inputs: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0, 1], got {self.confidence!r}"
            )


@dataclass(frozen=True)
class CompositeRegime:
    """The composite label across all active lenses for one bar.

    Phase 1 ships MACRO + MESO. MICRO is reserved for Phase 4 — the
    dataclass keeps the slot present so storage/audit schemas don't
    break when it arrives.
    """

    macro: str
    meso: str
    macro_conf: float
    meso_conf: float
    composite_conf: float
    micro: str | None = None
    micro_conf: float | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("macro_conf", self.macro_conf),
            ("meso_conf", self.meso_conf),
            ("composite_conf", self.composite_conf),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {value!r}")


@dataclass
class RegimeRunResult:
    """One `RegimeDetector.classify()` invocation's structured output."""

    run_id: str
    started_at: datetime
    finished_at: datetime
    scope: str
    rows: list[CompositeRegime] = field(default_factory=list)
    inputs_by_bar: list[dict[str, float]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


class Lens(ABC):
    """Abstract base for one regime lens (MACRO / MESO / MICRO).

    Subclasses set class-level `name` and implement `required_features`
    + `classify`. Lenses must be pure functions of the inputs passed
    in — no filesystem / network reads — so they can be exercised by
    fixture-driven unit tests without standing up the parquet stores.
    """

    name: str

    @abstractmethod
    def required_features(self) -> list[str]:
        """Feature column names this lens needs from the feature row."""

    @abstractmethod
    def classify(
        self,
        *,
        feature_row: pd.Series,
        macro_row: pd.Series | None,
    ) -> ClassificationResult:
        """Classify one `(scope, asof)` bar.

        Returns `ClassificationResult(label=UNDEFINED_LABEL,
        confidence=0.0, inputs={})` when required inputs are NaN /
        missing — the orchestrator surfaces undefined rows in the
        manifest.
        """
