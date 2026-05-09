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


class FeaturePipeline:
    """Orchestrate a single feature-pipeline run for a set of tickers + a window."""

    def __init__(
        self,
        *,
        adapter: ParquetAdapter,
        store: FeatureStore,
        features: list[Feature] | None = None,
        run_id: str | None = None,
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.features = list(features) if features is not None else list(BUILTIN_FEATURES)
        self.run_id = run_id or str(uuid.uuid4())
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

        finished_at = datetime.now(UTC)
        return FeatureRunResult(
            run_id=self.run_id,
            started_at=started_at,
            finished_at=finished_at,
            rows_written=rows_written,
            feature_columns=[f.name for f in self.features],
            per_feature_non_null=per_feature_non_null,
            failures=failures,
        )

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
        ctx = FeatureContext(ticker=ticker, frame=ordered, asof=asof)

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


def empty_feature_frame(features: list[Feature]) -> FeatureFrame:
    """Convenience for tests / call sites that want a zero-row, schema-correct frame."""
    cols = ["ticker", "bar_timestamp", *(f.name for f in features), "source", "fetched_at", "revision_at"]
    return FeatureFrame(frame=pd.DataFrame({c: [] for c in cols}), features=features)
