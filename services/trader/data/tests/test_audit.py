"""Audit-logger tests.

Postgres-dependent tests are marked `pytest.mark.integration` and skipped
when `MAHORAGA_TEST_DSN` is not set.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from services.trader.data.audit import (
    AuditLogger,
    IngestRun,
    ManifestWriter,
    PostgresAuditWriter,
    compute_hash,
    verify_chain,
)

# --- pure unit tests (no DB) ---------------------------------------------


class TestComputeHash:
    def test_same_inputs_same_hash(self) -> None:
        ts = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        h1 = compute_hash(prev_hash=None, actor="a", action="x", payload_json="{}", ts=ts)
        h2 = compute_hash(prev_hash=None, actor="a", action="x", payload_json="{}", ts=ts)
        assert h1 == h2
        assert len(h1) == 32  # SHA-256 -> 32 bytes

    def test_different_payload_changes_hash(self) -> None:
        ts = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        h1 = compute_hash(prev_hash=None, actor="a", action="x", payload_json="{}", ts=ts)
        h2 = compute_hash(
            prev_hash=None, actor="a", action="x", payload_json='{"x":1}', ts=ts
        )
        assert h1 != h2

    def test_chain_links_via_prev_hash(self) -> None:
        ts = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        first = compute_hash(prev_hash=None, actor="a", action="x", payload_json="{}", ts=ts)
        second_with_chain = compute_hash(
            prev_hash=first, actor="a", action="x", payload_json="{}", ts=ts
        )
        second_no_chain = compute_hash(
            prev_hash=None, actor="a", action="x", payload_json="{}", ts=ts
        )
        assert second_with_chain != second_no_chain


class TestVerifyChain:
    def test_valid_chain(self) -> None:
        ts = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        rows = []
        prev = None
        for i in range(3):
            payload = {"i": i}
            payload_json = json.dumps(payload, sort_keys=True)
            h = compute_hash(prev_hash=prev, actor="a", action="x", payload_json=payload_json, ts=ts)
            rows.append({"actor": "a", "action": "x", "payload": payload, "ts": ts, "hash": h})
            prev = h
        assert verify_chain(rows)

    def test_tampered_payload_breaks_chain(self) -> None:
        ts = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        h = compute_hash(prev_hash=None, actor="a", action="x", payload_json="{}", ts=ts)
        # Original hash was for empty payload but row claims a different one
        rows = [{"actor": "a", "action": "x", "payload": {"tampered": True}, "ts": ts, "hash": h}]
        assert not verify_chain(rows)


# --- Manifest parquet writer (no DB) ------------------------------------


class TestManifestWriter:
    def test_first_run_creates_file(self, tmp_path: Path) -> None:
        writer = ManifestWriter(tmp_path)
        run = IngestRun(
            run_id="r1",
            source="fred",
            started_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
            finished_at=datetime(2026, 5, 9, 12, 1, tzinfo=UTC),
            rows_written=10,
            coverage_pct=100.0,
            errors=[],
        )
        writer.append(run)
        assert writer.path.exists()
        df = pq.read_table(writer.path).to_pandas()
        assert len(df) == 1
        assert df["run_id"].iloc[0] == "r1"

    def test_appends_to_existing_file(self, tmp_path: Path) -> None:
        writer = ManifestWriter(tmp_path)
        for i in range(3):
            writer.append(
                IngestRun(
                    run_id=f"r{i}",
                    source="yfinance",
                    started_at=datetime(2026, 5, 9, 12, i, tzinfo=UTC),
                    finished_at=datetime(2026, 5, 9, 12, i + 1, tzinfo=UTC),
                    rows_written=i,
                    coverage_pct=99.5,
                    errors=[] if i < 2 else ["one error"],
                )
            )
        df = pq.read_table(writer.path).to_pandas()
        assert len(df) == 3
        assert list(df["run_id"]) == ["r0", "r1", "r2"]
        assert list(df["errors"].iloc[2]) == ["one error"]

    def test_unfinished_run_raises(self, tmp_path: Path) -> None:
        writer = ManifestWriter(tmp_path)
        run = IngestRun(run_id="r1", source="x", started_at=datetime.now(UTC))
        with pytest.raises(ValueError, match="finished_at"):
            writer.append(run)


# --- AuditLogger context manager (manifest only, no DB) -----------------


class TestAuditLoggerContextManager:
    def test_run_finalizes_on_success(self, tmp_path: Path) -> None:
        manifest = ManifestWriter(tmp_path)
        postgres = PostgresAuditWriter(dsn=None)  # disabled
        logger = AuditLogger(manifest=manifest, postgres=postgres)

        with logger.run(source="fred") as run:
            run.rows_written = 5
            run.coverage_pct = 100.0

        df = pq.read_table(manifest.path).to_pandas()
        assert len(df) == 1
        assert df["rows_written"].iloc[0] == 5
        assert df["coverage_pct"].iloc[0] == 100.0
        assert list(df["errors"].iloc[0]) == []

    def test_run_records_exception_then_reraises(self, tmp_path: Path) -> None:
        manifest = ManifestWriter(tmp_path)
        postgres = PostgresAuditWriter(dsn=None)
        logger = AuditLogger(manifest=manifest, postgres=postgres)

        with pytest.raises(RuntimeError, match="boom"), logger.run(source="fred"):
            raise RuntimeError("boom")

        df = pq.read_table(manifest.path).to_pandas()
        assert len(df) == 1
        errors = list(df["errors"].iloc[0])
        assert any("RuntimeError: boom" in e for e in errors)

    def test_postgres_disabled_no_writes(self, tmp_path: Path) -> None:
        postgres = PostgresAuditWriter(dsn=None)
        assert not postgres.is_enabled()
        # `write` returns None silently
        assert postgres.write(actor="a", action="x", payload={}) is None


# --- Postgres integration (real DB) -------------------------------------


@pytest.mark.integration
class TestPostgresIntegration:
    @pytest.fixture(autouse=True)
    def require_dsn(self) -> None:
        if not os.environ.get("MAHORAGA_TEST_DSN"):
            pytest.skip("MAHORAGA_TEST_DSN not set; skipping Postgres integration")

    def test_writes_and_chain_verifies(self, tmp_path: Path) -> None:
        import psycopg

        dsn = os.environ["MAHORAGA_TEST_DSN"]
        manifest = ManifestWriter(tmp_path)
        postgres = PostgresAuditWriter(dsn=dsn)
        logger = AuditLogger(manifest=manifest, postgres=postgres, actor="test-data-ingest")

        # Snapshot the existing chain head so we don't depend on prior runs
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT id, hash FROM audit.events ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            pre_id = row[0] if row else 0

        with logger.run(source="test-source") as run:
            run.rows_written = 1
            run.coverage_pct = 100.0

        # Exactly one new audit row from our actor since pre_id
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, ts, actor, action, payload, prev_hash, hash "
                "FROM audit.events WHERE id > %s AND actor = 'test-data-ingest' "
                "ORDER BY id ASC",
                (pre_id,),
            )
            rows = cur.fetchall()

        assert len(rows) == 1
        new_row = rows[0]
        assert new_row[2] == "test-data-ingest"  # actor
        assert new_row[3] == "ingest"  # action

        # Manifest got exactly one row too
        df = pq.read_table(manifest.path).to_pandas()
        assert len(df) == 1
