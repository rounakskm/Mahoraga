"""Feature pipeline orchestrator.

Reads PIT-correct OHLCV via `ParquetAdapter`, runs every registered feature
through `Feature.compute(ctx)`, and writes the assembled feature frame to
`FeatureStore`.

See `docs/superpowers/specs/phase-1-foundation/feature-pipeline-spec.md` §5.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time

import pandas as pd

from services.trader.data.audit import (
    IngestRun,
    ManifestWriter,
    PostgresAuditWriter,
)
from services.trader.data.coverage import (
    FeatureCoverageReport,
    report_features,
)
from services.trader.data.storage.parquet_adapter import ParquetAdapter
from services.trader.features.base import (
    BUILTIN_FEATURES,
    Feature,
    FeatureContext,
    FeatureFrame,
)
from services.trader.features.store import FeatureStore

logger = logging.getLogger(__name__)

PIPELINE_SOURCE = "feature-pipeline"


@dataclass
class FeatureRunResult:
    run_id: str
    started_at: datetime
    finished_at: datetime
    rows_written: int
    feature_columns: list[str]
    per_feature_non_null: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    coverage: list[FeatureCoverageReport] = field(default_factory=list)


class FeaturePipeline:
    """Orchestrate a single feature-pipeline run for a set of tickers + a window."""

    def __init__(
        self,
        *,
        adapter: ParquetAdapter,
        store: FeatureStore,
        features: list[Feature] | None = None,
        run_id: str | None = None,
        macro_adapter: ParquetAdapter | None = None,
        manifest_root: str | None = None,
        audit_writer: PostgresAuditWriter | None = None,
        audit_actor: str = "feature-pipeline",
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.features = list(features) if features is not None else list(BUILTIN_FEATURES)
        self.run_id = run_id or str(uuid.uuid4())
        # Macro adapter is optional. Macro-category features fall back to a
        # `null` series if no macro adapter is provided; the coverage report
        # surfaces the resulting null columns.
        self.macro_adapter = macro_adapter
        # When manifest_root is set, each pipeline run appends a row to
        # <manifest_root>/manifests/ingest-runs.parquet (same shape as the
        # data-foundation manifest from chunk P1.1.D). When `audit_writer` is
        # provided AND enabled, a hash-chained `audit.events` row is also
        # written with `actor=audit_actor`, `action='compute'`.
        self.manifest_writer = ManifestWriter(manifest_root) if manifest_root else None
        self.audit_writer = audit_writer
        self.audit_actor = audit_actor
        if not self.features:
            raise ValueError("FeaturePipeline requires at least one Feature")

    # --- public ----------------------------------------------------------

    def compute(
        self,
        *,
        tickers: Iterable[str],
        start: date,
        end: date,
        asof: datetime | None = None,
        vault_override: bool = False,
        vault_override_reason: str | None = None,
    ) -> FeatureRunResult:
        started_at = datetime.now(UTC)
        rows_written = 0
        per_feature_non_null: dict[str, int] = {f.name: 0 for f in self.features}
        failures: list[str] = []
        all_frames: list[pd.DataFrame] = []

        start_dt = datetime.combine(start, time.min, tzinfo=UTC)
        end_dt = datetime.combine(end, time.max, tzinfo=UTC)
        asof_dt = asof or datetime.now(UTC)

        for ticker in tickers:
            try:
                df = self.adapter.read(
                    kind="ohlcv",
                    keys=[ticker],
                    start=start_dt,
                    end=end_dt,
                    asof=asof_dt,
                    vault_override=vault_override,
                    vault_override_reason=vault_override_reason,
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{ticker}: read failed: {exc}")
                logger.error("read failed for %s: %s", ticker, exc)
                continue

            if df.empty:
                logger.warning("no OHLCV for %s in [%s, %s]", ticker, start, end)
                continue

            frame = self._compute_for_ticker(ticker, df, asof=asof_dt, failures=failures)
            if frame.empty:
                continue

            for f in self.features:
                per_feature_non_null[f.name] += int(frame[f.name].notna().sum())

            rows_written += self.store.write(frame, features=self.features)
            all_frames.append(frame)

        finished_at = datetime.now(UTC)

        # Per-feature null-rate coverage, computed across all tickers in this run.
        coverage: list[FeatureCoverageReport] = []
        if all_frames:
            combined = pd.concat(all_frames, ignore_index=True)
            placeholder_cols = {f.name for f in self.features if f.placeholder}
            coverage = report_features(
                combined,
                feature_columns=[f.name for f in self.features],
                placeholder_columns=placeholder_cols,
            )

        avg_coverage_pct = (
            sum(100.0 - r.null_rate_pct for r in coverage) / len(coverage)
            if coverage
            else None
        )

        self._finalize_audit(
            started_at=started_at,
            finished_at=finished_at,
            rows_written=rows_written,
            avg_coverage_pct=avg_coverage_pct,
            failures=failures,
        )

        return FeatureRunResult(
            run_id=self.run_id,
            started_at=started_at,
            finished_at=finished_at,
            rows_written=rows_written,
            feature_columns=[f.name for f in self.features],
            per_feature_non_null=per_feature_non_null,
            failures=failures,
            coverage=coverage,
        )

    # --- audit / manifest finalize ---------------------------------------

    def _finalize_audit(
        self,
        *,
        started_at: datetime,
        finished_at: datetime,
        rows_written: int,
        avg_coverage_pct: float | None,
        failures: list[str],
    ) -> None:
        if self.manifest_writer is not None:
            try:
                self.manifest_writer.append(
                    IngestRun(
                        run_id=self.run_id,
                        source=PIPELINE_SOURCE,
                        started_at=started_at,
                        finished_at=finished_at,
                        rows_written=rows_written,
                        coverage_pct=avg_coverage_pct,
                        errors=list(failures),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("feature manifest write failed: %s", exc)

        if self.audit_writer is not None and self.audit_writer.is_enabled():
            try:
                self.audit_writer.write(
                    actor=self.audit_actor,
                    action="compute",
                    payload={
                        "run_id": self.run_id,
                        "source": PIPELINE_SOURCE,
                        "started_at": started_at.isoformat(),
                        "finished_at": finished_at.isoformat(),
                        "rows_written": rows_written,
                        "coverage_pct": avg_coverage_pct,
                        "feature_count": len(self.features),
                        "errors": failures,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("feature-pipeline audit-events write failed: %s", exc)

    # --- internals -------------------------------------------------------

    def _compute_for_ticker(
        self,
        ticker: str,
        ohlcv: pd.DataFrame,
        *,
        asof: datetime,
        failures: list[str],
    ) -> pd.DataFrame:
        """Compute every feature for one ticker; return a feature frame."""
        ordered = ohlcv.sort_values("bar_timestamp").reset_index(drop=True)
        ctx = FeatureContext(
            ticker=ticker,
            frame=ordered,
            asof=asof,
            macro_fetcher=self._build_macro_fetcher(asof),
            ohlcv_fetcher=self._build_ohlcv_fetcher(asof),
        )

        out = pd.DataFrame(
            {
                "ticker": ticker,
                "bar_timestamp": pd.to_datetime(ordered["bar_timestamp"], utc=True),
            }
        )

        for f in self.features:
            try:
                series = f.compute(ctx)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{ticker}/{f.name}: {exc}")
                logger.error("feature %s failed for %s: %s", f.name, ticker, exc)
                out[f.name] = pd.Series([pd.NA] * len(ordered), dtype="float64")
                continue

            if len(series) != len(ordered):
                failures.append(
                    f"{ticker}/{f.name}: length mismatch ({len(series)} vs {len(ordered)})"
                )
                logger.error(
                    "feature %s length mismatch for %s: %d vs %d",
                    f.name, ticker, len(series), len(ordered),
                )
                out[f.name] = pd.Series([pd.NA] * len(ordered), dtype="float64")
                continue

            out[f.name] = series.astype("float64").reset_index(drop=True)

        fetched_at = datetime.now(UTC)
        out["source"] = PIPELINE_SOURCE
        out["fetched_at"] = pd.Timestamp(fetched_at)
        out["revision_at"] = pd.NaT
        return out

    # --- macro / ohlcv fetcher factories --------------------------------

    def _build_macro_fetcher(self, asof: datetime):  # type: ignore[no-untyped-def]
        if self.macro_adapter is None:
            return None

        def fetcher(indicator: str) -> pd.DataFrame:
            try:
                return self.macro_adapter.read(  # type: ignore[union-attr]
                    kind="macro",
                    keys=[indicator],
                    start=datetime(2000, 1, 1, tzinfo=UTC),
                    end=asof,
                    asof=asof,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("macro fetch %s failed: %s", indicator, exc)
                return pd.DataFrame()

        return fetcher

    def _build_ohlcv_fetcher(self, asof: datetime):  # type: ignore[no-untyped-def]
        def fetcher(ticker: str) -> pd.DataFrame:
            try:
                return self.adapter.read(
                    kind="ohlcv",
                    keys=[ticker],
                    start=datetime(2000, 1, 1, tzinfo=UTC),
                    end=asof,
                    asof=asof,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ohlcv fetch %s failed: %s", ticker, exc)
                return pd.DataFrame()

        return fetcher


def empty_feature_frame(features: list[Feature]) -> FeatureFrame:
    """Convenience for tests / call sites that want a zero-row, schema-correct frame."""
    cols = ["ticker", "bar_timestamp", *(f.name for f in features), "source", "fetched_at", "revision_at"]
    return FeatureFrame(frame=pd.DataFrame({c: [] for c in cols}), features=features)
