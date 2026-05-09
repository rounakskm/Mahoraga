"""Ingest-run audit logger.

Every ingest run produces exactly one row in two places:

1. `data/parquet/manifests/ingest-runs.parquet` — append-only manifest with
   per-run metadata (id, source, timing, rows-written, coverage).
2. Postgres `audit.events` — hash-chained audit row consumed by the broader
   audit infrastructure from Phase 0.

The hash chain links each row to the previous row's hash so the chain is
verifiable end-to-end. We compute the hash app-side rather than via a
trigger so the same logic works against test Postgres instances and
fixtures without DB-side state.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


MANIFEST_SCHEMA = pa.schema(
    [
        pa.field("run_id",       pa.string(), nullable=False),
        pa.field("source",       pa.string(), nullable=False),
        pa.field("started_at",   pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("finished_at",  pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("rows_written", pa.int64(),  nullable=False),
        pa.field("coverage_pct", pa.float64(),  nullable=True),
        pa.field("errors",       pa.list_(pa.string()), nullable=False),
    ]
)


@dataclass
class IngestRun:
    """Mutable bookkeeping object passed from `begin()` to `end()`."""

    run_id: str
    source: str
    started_at: datetime
    finished_at: datetime | None = None
    rows_written: int = 0
    coverage_pct: float | None = None
    errors: list[str] = field(default_factory=list)


class ManifestWriter:
    """Append-only manifests/ingest-runs.parquet writer."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.path = self.root / "manifests" / "ingest-runs.parquet"

    def append(self, run: IngestRun) -> None:
        if run.finished_at is None:
            raise ValueError("run.finished_at must be set before appending")
        new_row = pd.DataFrame(
            [
                {
                    "run_id": run.run_id,
                    "source": run.source,
                    "started_at": pd.Timestamp(run.started_at).tz_convert("UTC")
                        if pd.Timestamp(run.started_at).tzinfo
                        else pd.Timestamp(run.started_at).tz_localize("UTC"),
                    "finished_at": pd.Timestamp(run.finished_at).tz_convert("UTC")
                        if pd.Timestamp(run.finished_at).tzinfo
                        else pd.Timestamp(run.finished_at).tz_localize("UTC"),
                    "rows_written": int(run.rows_written),
                    "coverage_pct": run.coverage_pct,
                    "errors": list(run.errors),
                }
            ]
        )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            existing = pq.read_table(self.path, schema=MANIFEST_SCHEMA).to_pandas()
            combined = pd.concat([existing, new_row], ignore_index=True)
        else:
            combined = new_row
        table = pa.Table.from_pandas(combined, schema=MANIFEST_SCHEMA, preserve_index=False)
        pq.write_table(table, self.path, compression="snappy")


class PostgresAuditWriter:
    """Writer for hash-chained rows in Postgres `audit.events`.

    The class is import-safe even when psycopg isn't available — the actual
    connection is opened lazily inside `write()`. Tests that don't have a
    Postgres handy can pass `dsn=None` to skip Postgres writes entirely
    (the manifest still records the run).
    """

    def __init__(self, dsn: str | None) -> None:
        self.dsn = dsn

    def is_enabled(self) -> bool:
        return bool(self.dsn)

    def write(self, *, actor: str, action: str, payload: dict[str, Any]) -> bytes | None:
        """Append one hash-chained row; return the new hash bytes (or None if disabled)."""
        if not self.is_enabled():
            return None

        import psycopg  # noqa: PLC0415  (lazy: only needed when DSN is set)

        with psycopg.connect(self.dsn, autocommit=False) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT hash FROM audit.events ORDER BY id DESC LIMIT 1"
                )
                row = cur.fetchone()
                prev_hash = row[0] if row else None

                ts = datetime.now(UTC)
                payload_json = json.dumps(payload, sort_keys=True, default=_json_default)
                new_hash = compute_hash(
                    prev_hash=prev_hash,
                    actor=actor,
                    action=action,
                    payload_json=payload_json,
                    ts=ts,
                )
                cur.execute(
                    "INSERT INTO audit.events (ts, actor, action, payload, prev_hash, hash) "
                    "VALUES (%s, %s, %s, %s::jsonb, %s, %s)",
                    (ts, actor, action, payload_json, prev_hash, new_hash),
                )
            conn.commit()
        return new_hash


def compute_hash(
    *,
    prev_hash: bytes | None,
    actor: str,
    action: str,
    payload_json: str,
    ts: datetime,
) -> bytes:
    """SHA-256 over (prev_hash || actor || action || payload || ts.iso)."""
    h = hashlib.sha256()
    h.update(prev_hash or b"")
    h.update(b"\x00")
    h.update(actor.encode("utf-8"))
    h.update(b"\x00")
    h.update(action.encode("utf-8"))
    h.update(b"\x00")
    h.update(payload_json.encode("utf-8"))
    h.update(b"\x00")
    h.update(ts.isoformat().encode("utf-8"))
    return h.digest()


def verify_chain(rows: Iterable[dict[str, Any]]) -> bool:
    """Verify every row's hash matches sha256(prev_hash || actor || action || payload || ts).

    `rows` is expected in id-order (oldest first).
    """
    prev = None
    for row in rows:
        payload_json = json.dumps(row["payload"], sort_keys=True, default=_json_default)
        expected = compute_hash(
            prev_hash=prev,
            actor=row["actor"],
            action=row["action"],
            payload_json=payload_json,
            ts=row["ts"],
        )
        if expected != row["hash"]:
            return False
        prev = row["hash"]
    return True


class AuditLogger:
    """Combined ingest-run logger (manifest + Postgres)."""

    def __init__(
        self,
        *,
        manifest: ManifestWriter,
        postgres: PostgresAuditWriter,
        actor: str = "data-ingest",
    ) -> None:
        self.manifest = manifest
        self.postgres = postgres
        self.actor = actor

    @contextmanager
    def run(self, source: str):  # type: ignore[no-untyped-def]
        """Context manager: yields an `IngestRun`; finalizes both sinks on exit."""
        run = IngestRun(
            run_id=str(uuid.uuid4()),
            source=source,
            started_at=datetime.now(UTC),
        )
        try:
            yield run
        except Exception as exc:  # noqa: BLE001  (we re-raise after logging)
            run.errors.append(f"{type(exc).__name__}: {exc}")
            self._finalize(run)
            raise
        else:
            self._finalize(run)

    # --- internals -------------------------------------------------------

    def _finalize(self, run: IngestRun) -> None:
        run.finished_at = datetime.now(UTC)
        # 1. manifest first (always succeeds locally)
        self.manifest.append(run)
        # 2. postgres next (best-effort; if it fails we still kept the manifest)
        try:
            self.postgres.write(
                actor=self.actor,
                action="ingest",
                payload={
                    "run_id": run.run_id,
                    "source": run.source,
                    "started_at": run.started_at.isoformat(),
                    "finished_at": run.finished_at.isoformat(),
                    "rows_written": run.rows_written,
                    "coverage_pct": run.coverage_pct,
                    "errors": run.errors,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("audit-event write to Postgres failed: %s", exc)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def make_audit_logger_from_env(*, parquet_root: str | Path) -> AuditLogger:
    """Convenience builder for production use; reads MAHORAGA_TEST_DSN/POSTGRES_* env."""
    dsn = os.environ.get("MAHORAGA_AUDIT_DSN") or os.environ.get("MAHORAGA_TEST_DSN")
    return AuditLogger(
        manifest=ManifestWriter(parquet_root),
        postgres=PostgresAuditWriter(dsn=dsn),
    )
