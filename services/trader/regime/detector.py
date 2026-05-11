"""Regime detector orchestrator (in-memory skeleton for R1).

Reads pre-computed feature rows + (optional) macro rows at `asof`,
dispatches to every registered `Lens`, composes the per-bar result.

R1 ships the in-memory shape only — no `RegimeStore`, no manifest /
audit. R3 wires those.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

import pandas as pd

from services.trader.regime.base import (
    ClassificationResult,
    CompositeRegime,
    Lens,
    RegimeRunResult,
)

logger = logging.getLogger(__name__)

DETECTOR_SOURCE = "regime-detector"


class RegimeDetector:
    """Orchestrate one regime classification over a span of bars.

    Phase 1 R1: pure in-memory dispatch. The caller supplies a
    `feature_frame` (one row per bar, columns include every
    `lens.required_features()`) and optionally a `macro_frame`
    aligned by `asof`. R3 adds the feature-store / macro-adapter
    reads + storage / audit.
    """

    def __init__(
        self,
        *,
        lenses: list[Lens],
        run_id: str | None = None,
    ) -> None:
        if not lenses:
            raise ValueError("RegimeDetector requires at least one Lens")
        self.lenses = list(lenses)
        self.run_id = run_id or str(uuid.uuid4())

    def classify(
        self,
        *,
        scope: str,
        feature_frame: pd.DataFrame,
        macro_frame: pd.DataFrame | None = None,
    ) -> RegimeRunResult:
        started_at = datetime.now(UTC)
        rows: list[CompositeRegime] = []
        inputs_by_bar: list[dict[str, float]] = []
        failures: list[str] = []

        macro_lookup = self._macro_lookup(macro_frame)

        for idx, feature_row in feature_frame.reset_index(drop=True).iterrows():
            macro_row = macro_lookup(feature_row.get("bar_timestamp"))
            results = self._classify_bar(int(idx), feature_row, macro_row, failures)
            inputs: dict[str, float] = {}
            for r in results.values():
                inputs.update(r.inputs)
            inputs_by_bar.append(inputs)
            rows.append(self._compose(results))

        finished_at = datetime.now(UTC)
        return RegimeRunResult(
            run_id=self.run_id,
            started_at=started_at,
            finished_at=finished_at,
            scope=scope,
            rows=rows,
            inputs_by_bar=inputs_by_bar,
            failures=failures,
        )

    # --- internals ------------------------------------------------------

    def _classify_bar(
        self,
        idx: int,
        feature_row: pd.Series,
        macro_row: pd.Series | None,
        failures: list[str],
    ) -> dict[str, ClassificationResult]:
        out: dict[str, ClassificationResult] = {}
        for lens in self.lenses:
            try:
                out[lens.name] = lens.classify(
                    feature_row=feature_row, macro_row=macro_row
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"bar {idx}/{lens.name}: {exc}")
                logger.error("lens %s failed at bar %d: %s", lens.name, idx, exc)
                out[lens.name] = ClassificationResult(
                    label="undefined", confidence=0.0, inputs={}
                )
        return out

    def _compose(self, results: dict[str, ClassificationResult]) -> CompositeRegime:
        meso = results.get("meso")
        macro = results.get("macro")
        meso_label = meso.label if meso else "undefined"
        macro_label = macro.label if macro else "undefined"
        meso_conf = meso.confidence if meso else 0.0
        macro_conf = macro.confidence if macro else 0.0
        # Composite = min of present lenses; if MACRO is absent (R1
        # ships MESO only), composite collapses to MESO confidence so
        # the R1 in-memory path is testable end-to-end.
        present = [r.confidence for r in (meso, macro) if r is not None]
        composite_conf = min(present) if present else 0.0
        return CompositeRegime(
            macro=macro_label,
            meso=meso_label,
            macro_conf=macro_conf,
            meso_conf=meso_conf,
            composite_conf=composite_conf,
        )

    def _macro_lookup(
        self, macro_frame: pd.DataFrame | None
    ):  # type: ignore[no-untyped-def]
        if macro_frame is None or macro_frame.empty:
            return lambda _ts: None
        # Build a (bar_timestamp -> row) index keyed by UTC-normalized
        # timestamp; lookup falls back to the latest row at-or-before
        # the requested bar.
        if "bar_timestamp" not in macro_frame.columns:
            return lambda _ts: None
        ordered = macro_frame.sort_values("bar_timestamp").reset_index(drop=True)
        timestamps = pd.to_datetime(ordered["bar_timestamp"], utc=True)

        def lookup(ts: object) -> pd.Series | None:
            if ts is None:
                return None
            target = pd.Timestamp(ts)
            target = (
                target.tz_localize("UTC")
                if target.tzinfo is None
                else target.tz_convert("UTC")
            )
            mask = (timestamps <= target).to_numpy()
            if not mask.any():
                return None
            # timestamps is sorted ascending → mask is a True-prefix,
            # so the last True position is at index `mask.sum() - 1`.
            return ordered.iloc[int(mask.sum()) - 1]

        return lookup


def empty_regime_frame(lens_names: Iterable[str]) -> pd.DataFrame:
    """Convenience for tests / call sites that want a zero-row frame."""
    cols = ["scope", "asof"]
    for name in lens_names:
        cols.extend([f"{name}_label", f"{name}_conf"])
    cols.extend(["composite_conf", "inputs", "source", "fetched_at"])
    return pd.DataFrame({c: [] for c in cols})
