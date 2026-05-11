"""RegimeStore — parquet writer + PIT reader for regime classifications.

Per `regime-detector-spec.md` §4. Layout mirrors `FeatureStore`:

    <root>/regime/<SCOPE>/<YEAR>.parquet

Schema is dynamic — one (label, conf) column pair per registered lens,
plus the composite columns + audit metadata. Idempotent re-runs dedupe
on `(scope, asof)` keeping the row with the latest `fetched_at`.

Vault enforcement reuses the shared `services/trader/data/storage/
vault.py` helpers — read-side only (writes always allowed).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from services.trader.data.storage.vault import VaultEmbargoError, assess_vault

logger = logging.getLogger(__name__)


def regime_frame_schema(lens_names: list[str]) -> pa.Schema:
    """Build the parquet schema for a regime frame given the active lens set."""
    fields: list[pa.Field] = [
        pa.field("scope", pa.string(), nullable=False),
        pa.field("asof", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
    for name in lens_names:
        fields.append(pa.field(f"{name}_label", pa.string(), nullable=False))
        fields.append(pa.field(f"{name}_conf", pa.float64(), nullable=False))
    fields.extend(
        [
            pa.field("composite_conf", pa.float64(), nullable=False),
            # `inputs` is the per-bar raw feature-value snapshot, JSON-encoded
            # so the schema doesn't need to know the feature universe.
            pa.field("inputs", pa.string(), nullable=True),
            pa.field("source", pa.string(), nullable=False),
            pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=False),
        ]
    )
    return pa.schema(fields)


class RegimeStore:
    """Append-only parquet store for regime classifications."""

    def __init__(
        self,
        root: Path | str,
        *,
        vault_cutoff_days: int | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if vault_cutoff_days is not None and vault_cutoff_days < 0:
            raise ValueError(
                f"vault_cutoff_days must be >= 0, got {vault_cutoff_days}"
            )
        self.vault_cutoff_days = vault_cutoff_days

    # --- write ----------------------------------------------------------

    def write(
        self,
        frame: pd.DataFrame,
        *,
        lens_names: list[str],
    ) -> int:
        """Append-write regime rows. Returns rows actually written after dedupe."""
        if frame.empty:
            return 0
        schema = regime_frame_schema(lens_names)
        missing = set(schema.names) - set(frame.columns)
        if missing:
            raise ValueError(f"regime frame missing columns: {sorted(missing)}")

        df = frame.loc[:, list(schema.names)].copy()
        df["__year"] = pd.to_datetime(df["asof"], utc=True).dt.year

        total_written = 0
        for (scope, year), part in df.groupby(["scope", "__year"]):
            partition_path = (
                self.root / "regime" / str(scope) / f"{int(year)}.parquet"
            )
            total_written += self._write_partition(
                partition_path, part.drop(columns="__year"), schema=schema
            )
        return total_written

    # --- read -----------------------------------------------------------

    def read(
        self,
        *,
        scopes: list[str],
        start: datetime,
        end: datetime,
        lens_names: list[str],
        asof: datetime | None = None,
        vault_override: bool = False,
        vault_override_reason: str | None = None,
    ) -> pd.DataFrame:
        """Return a PIT-correct regime frame for the requested scopes + window."""
        self._enforce_vault(
            start=start,
            end=end,
            asof=asof,
            vault_override=vault_override,
            vault_override_reason=vault_override_reason,
        )
        schema = regime_frame_schema(lens_names)
        frames: list[pd.DataFrame] = []
        for scope in scopes:
            base = self.root / "regime" / scope
            if not base.exists():
                continue
            for path in sorted(base.glob("*.parquet")):
                frames.append(pq.read_table(path, schema=schema).to_pandas())
        if not frames:
            return pd.DataFrame(columns=schema.names)
        combined = pd.concat(frames, ignore_index=True)
        return _pit_view_regime(combined, start=start, end=end, asof=asof)

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
                    "vault_override=True requires a non-empty "
                    "vault_override_reason"
                )
            logger.warning(
                "RegimeStore vault_override=True: window [%s, %s] overlaps "
                "vault (cutoff %s); reason=%r",
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
            combined = (
                combined.sort_values("fetched_at")
                .drop_duplicates(subset=["scope", "asof"], keep="last")
                .reset_index(drop=True)
            )
            new_rows_written = len(combined) - len(existing)
        else:
            combined = (
                new_df.sort_values("fetched_at")
                .drop_duplicates(subset=["scope", "asof"], keep="last")
                .reset_index(drop=True)
            )
            new_rows_written = len(combined)
        table = pa.Table.from_pandas(combined, schema=schema, preserve_index=False)
        pq.write_table(table, path, compression="snappy")
        return max(new_rows_written, 0)


def _pit_view_regime(
    df: pd.DataFrame,
    *,
    start: datetime,
    end: datetime,
    asof: datetime | None,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    asof_ts = _to_utc(asof if asof is not None else datetime.now(UTC))
    start_ts = _to_utc(start)
    end_ts = _to_utc(end)

    mask_window = (df["asof"] >= start_ts) & (df["asof"] <= end_ts)
    mask_fetched = df["fetched_at"] <= asof_ts
    filtered = df.loc[mask_window & mask_fetched].copy()
    if filtered.empty:
        return filtered
    return (
        filtered.sort_values("fetched_at")
        .drop_duplicates(subset=["scope", "asof"], keep="last")
        .sort_values(["scope", "asof"])
        .reset_index(drop=True)
    )


def _to_utc(value: datetime | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def encode_inputs(inputs: dict[str, float]) -> str:
    """JSON-encode the per-bar inputs snapshot for parquet storage."""
    return json.dumps(inputs, sort_keys=True)


def decode_inputs(payload: str | None) -> dict[str, float]:
    if not payload:
        return {}
    return json.loads(payload)
