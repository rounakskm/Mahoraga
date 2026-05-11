"""Regime detector orchestrator.

Reads pre-computed feature rows + (optional) macro rows at `asof`,
dispatches to every registered `Lens`, composes the per-bar result,
and (when configured) persists to a `RegimeStore` + emits manifest +
hash-chained `audit.events` rows.

R1 shipped the in-memory dispatch. R3 wires storage / manifest / audit
through the same `IngestRun` shape the data foundation + feature
pipeline use.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

import pandas as pd

from services.trader.data.audit import (
    IngestRun,
    ManifestWriter,
    PostgresAuditWriter,
)
from services.trader.regime.base import (
    ClassificationResult,
    CompositeRegime,
    Lens,
    RegimeRunResult,
)
from services.trader.regime.store import RegimeStore, encode_inputs

logger = logging.getLogger(__name__)

DETECTOR_SOURCE = "regime-detector"


class RegimeDetector:
    """Orchestrate one regime classification over a span of bars.

    Phase 1 R3: in-memory dispatch + optional storage / manifest /
    audit. The caller still supplies `feature_frame` + `macro_frame`
    (R4 wires the live `FeatureStore` + `ParquetAdapter` reads).
    """

    def __init__(
        self,
        *,
        lenses: list[Lens],
        run_id: str | None = None,
        store: RegimeStore | None = None,
        manifest_root: str | None = None,
        audit_writer: PostgresAuditWriter | None = None,
        audit_actor: str = "regime-detector",
    ) -> None:
        if not lenses:
            raise ValueError("RegimeDetector requires at least one Lens")
        self.lenses = list(lenses)
        self.run_id = run_id or str(uuid.uuid4())
        self.store = store
        self.manifest_writer = ManifestWriter(manifest_root) if manifest_root else None
        self.audit_writer = audit_writer
        self.audit_actor = audit_actor

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
        rows_written = self._persist(
            scope=scope,
            feature_frame=feature_frame,
            rows=rows,
            inputs_by_bar=inputs_by_bar,
            fetched_at=finished_at,
        )
        self._finalize_audit(
            started_at=started_at,
            finished_at=finished_at,
            scope=scope,
            rows_written=rows_written,
            failures=failures,
        )
        return RegimeRunResult(
            run_id=self.run_id,
            started_at=started_at,
            finished_at=finished_at,
            scope=scope,
            rows=rows,
            inputs_by_bar=inputs_by_bar,
            failures=failures,
        )

    # --- persistence ----------------------------------------------------

    def _persist(
        self,
        *,
        scope: str,
        feature_frame: pd.DataFrame,
        rows: list[CompositeRegime],
        inputs_by_bar: list[dict[str, float]],
        fetched_at: datetime,
    ) -> int:
        if self.store is None or not rows:
            return 0
        try:
            frame = self._build_storage_frame(
                scope=scope,
                feature_frame=feature_frame,
                rows=rows,
                inputs_by_bar=inputs_by_bar,
                fetched_at=fetched_at,
            )
            return self.store.write(
                frame, lens_names=[lens.name for lens in self.lenses]
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("RegimeStore write failed: %s", exc)
            return 0

    def _build_storage_frame(
        self,
        *,
        scope: str,
        feature_frame: pd.DataFrame,
        rows: list[CompositeRegime],
        inputs_by_bar: list[dict[str, float]],
        fetched_at: datetime,
    ) -> pd.DataFrame:
        out = pd.DataFrame(
            {
                "scope": [scope] * len(rows),
                "asof": pd.to_datetime(
                    feature_frame.reset_index(drop=True)["bar_timestamp"], utc=True
                ).reset_index(drop=True),
            }
        )
        for lens in self.lenses:
            label_col = f"{lens.name}_label"
            conf_col = f"{lens.name}_conf"
            out[label_col] = [getattr(r, lens.name, "undefined") for r in rows]
            out[conf_col] = [
                getattr(r, f"{lens.name}_conf", 0.0) for r in rows
            ]
        out["composite_conf"] = [r.composite_conf for r in rows]
        out["inputs"] = [encode_inputs(s) for s in inputs_by_bar]
        out["source"] = DETECTOR_SOURCE
        out["fetched_at"] = pd.Timestamp(fetched_at)
        return out

    def _finalize_audit(
        self,
        *,
        started_at: datetime,
        finished_at: datetime,
        scope: str,
        rows_written: int,
        failures: list[str],
    ) -> None:
        if self.manifest_writer is not None:
            try:
                self.manifest_writer.append(
                    IngestRun(
                        run_id=self.run_id,
                        source=DETECTOR_SOURCE,
                        started_at=started_at,
                        finished_at=finished_at,
                        rows_written=rows_written,
                        coverage_pct=None,
                        errors=list(failures),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("regime manifest write failed: %s", exc)

        if self.audit_writer is not None and self.audit_writer.is_enabled():
            try:
                self.audit_writer.write(
                    actor=self.audit_actor,
                    action="classify",
                    payload={
                        "run_id": self.run_id,
                        "source": DETECTOR_SOURCE,
                        "scope": scope,
                        "started_at": started_at.isoformat(),
                        "finished_at": finished_at.isoformat(),
                        "rows_written": rows_written,
                        "lens_count": len(self.lenses),
                        "lens_names": [lens.name for lens in self.lenses],
                        "errors": failures,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("regime audit-events write failed: %s", exc)

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
            return ordered.iloc[int(mask.sum()) - 1]

        return lookup


def empty_regime_frame(lens_names: Iterable[str]) -> pd.DataFrame:
    """Convenience for tests / call sites that want a zero-row frame."""
    cols = ["scope", "asof"]
    for name in lens_names:
        cols.extend([f"{name}_label", f"{name}_conf"])
    cols.extend(["composite_conf", "inputs", "source", "fetched_at"])
    return pd.DataFrame({c: [] for c in cols})
