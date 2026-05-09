"""Manifest writer for universe-rebuild runs.

Mirrors the shape of `services/trader/data/audit.ManifestWriter` but for
universe-bootstrap output. Append-only `data/universe/manifests/universe-rebuilds.parquet`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


REBUILD_SCHEMA = pa.schema(
    [
        pa.field("run_id",       pa.string(), nullable=False),
        pa.field("source",       pa.string(), nullable=False),
        pa.field("started_at",   pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("finished_at",  pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("seed_size",    pa.int64(),  nullable=False),
        pa.field("events_count", pa.int64(),  nullable=False),
        pa.field("errors",       pa.list_(pa.string()), nullable=False),
    ]
)


@dataclass
class RebuildRun:
    run_id: str
    source: str
    started_at: datetime
    finished_at: datetime | None = None
    seed_size: int = 0
    events_count: int = 0
    errors: list[str] = field(default_factory=list)


class RebuildManifestWriter:
    """Append-only writer for `<root>/manifests/universe-rebuilds.parquet`."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.path = self.root / "manifests" / "universe-rebuilds.parquet"

    def append(self, run: RebuildRun) -> None:
        if run.finished_at is None:
            raise ValueError("run.finished_at must be set before appending")
        new_row = pd.DataFrame(
            [
                {
                    "run_id":       run.run_id,
                    "source":       run.source,
                    "started_at":   _utc(run.started_at),
                    "finished_at":  _utc(run.finished_at),
                    "seed_size":    int(run.seed_size),
                    "events_count": int(run.events_count),
                    "errors":       list(run.errors),
                }
            ]
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            existing = pq.read_table(self.path, schema=REBUILD_SCHEMA).to_pandas()
            combined = pd.concat([existing, new_row], ignore_index=True)
        else:
            combined = new_row
        table = pa.Table.from_pandas(combined, schema=REBUILD_SCHEMA, preserve_index=False)
        pq.write_table(table, self.path, compression="snappy")


def _utc(ts: datetime) -> pd.Timestamp:
    p = pd.Timestamp(ts)
    return p.tz_convert("UTC") if p.tzinfo else p.tz_localize("UTC")
