"""Parquet-backed storage adapter.

`ParquetAdapter` is the single read/write entry point for Phase 1 data. It
writes append-only parquet files partitioned by symbol/year (OHLCV) or
indicator/release-year (macro), and serves PIT-correct reads via
`storage.pit`.

See `docs/superpowers/specs/phase-1-foundation/data-foundation-spec.md` §6.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from services.trader.data.connectors.base import ConnectorResult, HealthStatus
from services.trader.data.storage.pit import pit_view_macro, pit_view_ohlcv
from services.trader.data.storage.schema import (
    natural_key_for,
    schema_for,
)

logger = logging.getLogger(__name__)

Kind = Literal["ohlcv", "macro"]


class ParquetAdapter:
    """Append-only parquet storage with PIT-correct reads.

    The on-disk layout matches the spec:

        <root>/ohlcv/<TICKER>/<YEAR>.parquet
        <root>/macro/<INDICATOR>/<YEAR>.parquet     (year of release_date)

    Rewriting an existing partition file is allowed *only* to add new rows;
    the natural key (per `schema.natural_key_for`) deduplicates idempotent
    re-runs and lets restatements coexist with originals.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # --- public ----------------------------------------------------------

    def write(self, result: ConnectorResult, *, kind: Kind) -> int:
        """Append rows from a ConnectorResult to the appropriate partitions.

        Returns the number of rows actually written (after dedupe against
        existing partition contents).
        """
        if result.frame.empty:
            return 0

        df = self._normalize_in(result.frame, kind=kind)
        partitions = self._partition_iter(df, kind=kind)

        total_written = 0
        for partition_path, partition_df in partitions:
            written = self._write_partition(partition_path, partition_df, kind=kind)
            total_written += written
        return total_written

    def read(
        self,
        *,
        kind: Kind,
        keys: Iterable[str],
        start: datetime,
        end: datetime,
        asof: datetime | None = None,
    ) -> pd.DataFrame:
        """Return a PIT-correct DataFrame for the requested keys + window."""
        keys_list = list(keys)
        frames: list[pd.DataFrame] = []
        for key in keys_list:
            files = self._partition_files(kind, key)
            if not files:
                continue
            for f in files:
                table = pq.read_table(f, schema=schema_for(kind))
                frames.append(table.to_pandas())

        if not frames:
            return pd.DataFrame(columns=schema_for(kind).names)

        combined = pd.concat(frames, ignore_index=True)
        if kind == "ohlcv":
            return pit_view_ohlcv(combined, start=start, end=end, asof=asof)
        return pit_view_macro(combined, start=start, end=end, asof=asof)

    def list_partitions(self, *, kind: Kind, key: str) -> list[Path]:
        """List partition files on disk for a given key, ordered by name."""
        return sorted(self._partition_files(kind, key))

    def gaps(
        self,
        *,
        kind: Kind,
        key: str,
        expected: pd.DatetimeIndex,
    ) -> list[pd.Timestamp]:
        """Return timestamps in `expected` that are missing from storage.

        Caller supplies the expected calendar so the adapter is calendar-agnostic
        (chunk 4's coverage monitor wires in `pandas_market_calendars`).
        """
        if kind != "ohlcv":
            raise NotImplementedError("gaps() currently supports kind='ohlcv' only")
        files = self._partition_files(kind, key)
        if not files:
            return list(expected)
        present_frames = [pq.read_table(f, columns=["bar_timestamp"]).to_pandas() for f in files]
        present = pd.concat(present_frames, ignore_index=True)["bar_timestamp"]
        present_idx = pd.DatetimeIndex(pd.to_datetime(present, utc=True)).normalize()
        expected_norm = pd.DatetimeIndex(pd.to_datetime(expected, utc=True)).normalize()
        missing = expected_norm.difference(present_idx)
        return list(missing)

    def health(self) -> HealthStatus:
        if not self.root.exists():
            return HealthStatus(healthy=False, detail=f"root missing: {self.root}")
        if not self.root.is_dir():
            return HealthStatus(healthy=False, detail=f"root not a dir: {self.root}")
        return HealthStatus(healthy=True, detail=f"root={self.root}")

    # --- internals -------------------------------------------------------

    def _normalize_in(self, df: pd.DataFrame, *, kind: Kind) -> pd.DataFrame:
        schema = schema_for(kind)
        missing = set(schema.names) - set(df.columns)
        if missing:
            raise ValueError(f"input dataframe missing columns: {sorted(missing)}")
        # Keep only schema columns, in schema order.
        return df.loc[:, list(schema.names)].copy()

    def _partition_iter(
        self, df: pd.DataFrame, *, kind: Kind
    ) -> Iterable[tuple[Path, pd.DataFrame]]:
        if kind == "ohlcv":
            df = df.copy()
            df["__year"] = pd.to_datetime(df["bar_timestamp"], utc=True).dt.year
            for (ticker, year), part in df.groupby(["ticker", "__year"]):
                path = self.root / "ohlcv" / str(ticker) / f"{int(year)}.parquet"
                yield path, part.drop(columns="__year")
        elif kind == "macro":
            df = df.copy()
            df["__year"] = pd.to_datetime(df["as_of_release_date"]).dt.year
            for (indicator, year), part in df.groupby(["indicator", "__year"]):
                path = self.root / "macro" / str(indicator) / f"{int(year)}.parquet"
                yield path, part.drop(columns="__year")
        else:
            raise ValueError(f"unknown kind: {kind!r}")

    def _write_partition(
        self, path: Path, new_df: pd.DataFrame, *, kind: Kind
    ) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        schema = schema_for(kind)
        key_cols = list(natural_key_for(kind))

        if path.exists():
            existing_df = pq.read_table(path, schema=schema).to_pandas()
            combined = pd.concat([existing_df, new_df], ignore_index=True)
            before = len(combined)
            # `revision_at` (or `as_of_release_date`) being part of the natural key
            # means two rows with the same content but different revision/release
            # keep both; identical duplicates collapse to one.
            combined = combined.drop_duplicates(subset=key_cols, keep="first").reset_index(
                drop=True
            )
            after = len(combined)
            new_rows_written = after - len(existing_df)
            if before != after:
                logger.debug("dedupe: %s collapsed %d duplicate rows", path, before - after)
        else:
            combined = new_df.drop_duplicates(subset=key_cols, keep="first").reset_index(
                drop=True
            )
            new_rows_written = len(combined)

        # Coerce types according to the Arrow schema (handles e.g. tz-naive timestamps).
        table = pa.Table.from_pandas(combined, schema=schema, preserve_index=False)
        pq.write_table(table, path, compression="snappy")
        return new_rows_written

    def _partition_files(self, kind: Kind, key: str) -> list[Path]:
        if kind == "ohlcv":
            base = self.root / "ohlcv" / key
        elif kind == "macro":
            base = self.root / "macro" / key
        else:
            raise ValueError(f"unknown kind: {kind!r}")
        if not base.exists():
            return []
        return sorted(base.glob("*.parquet"))
