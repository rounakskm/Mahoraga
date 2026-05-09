"""Feature parquet store.

Writes per-ticker per-year parquet files under `<root>/features/<TICKER>/<YEAR>.parquet`
and serves PIT-correct reads. Mirrors the on-disk layout and vault-enforcement
posture of `services/trader/data/storage/parquet_adapter.ParquetAdapter`, but
carries a dynamic schema (one column per feature in the registry).

Vault enforcement uses the shared `services/trader/data/storage/vault.py`
helpers, so the audit posture is identical to the OHLCV / macro path.

See `docs/superpowers/specs/phase-1-foundation/feature-pipeline-spec.md` §3, §8.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from services.trader.data.storage.vault import VaultEmbargoError, assess_vault
from services.trader.features.base import Feature, feature_frame_schema

logger = logging.getLogger(__name__)


class FeatureStore:
    """Append-only parquet store for feature frames.

    Idempotent re-runs of the pipeline overwrite the prior content for the
    same (ticker, bar_timestamp) keys: dedupe keeps the row with the latest
    `fetched_at`. Phase 1 does not model feature-value restatements
    independently — a recompute IS a restatement; the latest one wins.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        vault_cutoff_days: int | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if vault_cutoff_days is not None and vault_cutoff_days < 0:
            raise ValueError(f"vault_cutoff_days must be >= 0, got {vault_cutoff_days}")
        self.vault_cutoff_days = vault_cutoff_days

    # --- write ----------------------------------------------------------

    def write(
        self,
        frame: pd.DataFrame,
        *,
        features: list[Feature],
    ) -> int:
        """Append-write feature rows. Returns rows actually written (after dedupe)."""
        if frame.empty:
            return 0
        schema = feature_frame_schema(features)
        missing = set(schema.names) - set(frame.columns)
        if missing:
            raise ValueError(f"feature frame missing columns: {sorted(missing)}")

        # Keep schema-ordered columns only
        df = frame.loc[:, list(schema.names)].copy()
        df["__year"] = pd.to_datetime(df["bar_timestamp"], utc=True).dt.year

        total_written = 0
        for (ticker, year), part in df.groupby(["ticker", "__year"]):
            partition_path = self.root / "features" / str(ticker) / f"{int(year)}.parquet"
            total_written += self._write_partition(
                partition_path, part.drop(columns="__year"), schema=schema
            )
        return total_written

    # --- read -----------------------------------------------------------

    def read(
        self,
        *,
        keys: list[str],
        start: datetime,
        end: datetime,
        asof: datetime | None = None,
        features: list[Feature],
        vault_override: bool = False,
        vault_override_reason: str | None = None,
    ) -> pd.DataFrame:
        """Return a PIT-correct feature frame for the requested keys + window."""
        self._enforce_vault(
            start=start,
            end=end,
            asof=asof,
            vault_override=vault_override,
            vault_override_reason=vault_override_reason,
        )
        schema = feature_frame_schema(features)
        frames: list[pd.DataFrame] = []
        for key in keys:
            base = self.root / "features" / key
            if not base.exists():
                continue
            for path in sorted(base.glob("*.parquet")):
                frames.append(pq.read_table(path, schema=schema).to_pandas())
        if not frames:
            return pd.DataFrame(columns=schema.names)
        combined = pd.concat(frames, ignore_index=True)
        return _pit_view_features(combined, start=start, end=end, asof=asof)

    # --- internals ------------------------------------------------------

    def _enforce_vault(
        self,
        *,
        start: datetime,
        end: datetime,
        asof: datetime | None,
        vault_override: bool,
        vault_override_reason: str | None,
    ) -> None:
        asof_resolved = asof or datetime.now(UTC)
        decision = assess_vault(
            start=start,
            end=end,
            asof=asof_resolved,
            vault_cutoff_days=self.vault_cutoff_days,
        )
        if not decision.enforced or not decision.overlaps_vault:
            return
        if vault_override:
            if not vault_override_reason or not vault_override_reason.strip():
                raise ValueError(
                    "vault_override=True requires a non-empty vault_override_reason"
                )
            logger.warning(
                "FeatureStore vault_override=True: window [%s, %s] overlaps vault "
                "(cutoff %s); reason=%r",
                start.isoformat(),
                end.isoformat(),
                decision.cutoff_dt.isoformat() if decision.cutoff_dt else "<n/a>",
                vault_override_reason,
            )
            return
        assert decision.cutoff_dt is not None
        raise VaultEmbargoError(
            start=start,
            end=end,
            asof=asof_resolved,
            vault_cutoff=decision.cutoff_dt,
        )

    def _write_partition(
        self, path: Path, new_df: pd.DataFrame, *, schema: pa.Schema
    ) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = pq.read_table(path, schema=schema).to_pandas()
            combined = pd.concat([existing, new_df], ignore_index=True)
            # Dedupe on (ticker, bar_timestamp) keeping the row with the latest fetched_at
            combined = combined.sort_values("fetched_at").drop_duplicates(
                subset=["ticker", "bar_timestamp"], keep="last"
            ).reset_index(drop=True)
            new_rows_written = len(combined) - len(existing)
        else:
            combined = new_df.sort_values("fetched_at").drop_duplicates(
                subset=["ticker", "bar_timestamp"], keep="last"
            ).reset_index(drop=True)
            new_rows_written = len(combined)
        table = pa.Table.from_pandas(combined, schema=schema, preserve_index=False)
        pq.write_table(table, path, compression="snappy")
        return max(new_rows_written, 0)


def _pit_view_features(
    df: pd.DataFrame,
    *,
    start: datetime,
    end: datetime,
    asof: datetime | None,
) -> pd.DataFrame:
    """Filter feature rows to those public at `asof`, in `[start, end]`.

    For each `(ticker, bar_timestamp)`, keep the row with the latest
    `fetched_at` such that `fetched_at <= asof`. Treats `revision_at` like
    OHLCV (not currently populated by the pipeline but reserved).
    """
    if df.empty:
        return df.copy()
    asof_ts = _to_utc(asof if asof is not None else datetime.now(UTC))
    start_ts = _to_utc(start)
    end_ts = _to_utc(end)

    mask_window = (df["bar_timestamp"] >= start_ts) & (df["bar_timestamp"] <= end_ts)
    mask_fetched = df["fetched_at"] <= asof_ts
    mask_revision = df["revision_at"].isna() | (df["revision_at"] <= asof_ts)
    filtered = df.loc[mask_window & mask_fetched & mask_revision].copy()
    if filtered.empty:
        return filtered
    return (
        filtered.sort_values("fetched_at")
        .drop_duplicates(subset=["ticker", "bar_timestamp"], keep="last")
        .sort_values(["ticker", "bar_timestamp"])
        .reset_index(drop=True)
    )


def _to_utc(value: datetime | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
