"""Postgres-backed integration test for vault_override audit-events.

Verifies that a real `vault_override=True` call produces exactly one row
in `audit.events` with `action='vault_override'` and the expected payload
shape.

Skipped when `MAHORAGA_TEST_DSN` is not set (CI's integration-smoke job
exports it).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import psycopg
import pytest

from services.trader.data.audit import PostgresAuditWriter
from services.trader.data.connectors.base import ConnectorResult
from services.trader.data.storage import ParquetAdapter
from services.trader.data.storage.tests.conftest import make_ohlcv_frame


@pytest.fixture(autouse=True)
def _require_dsn() -> None:
    if not os.environ.get("MAHORAGA_TEST_DSN"):
        pytest.skip("MAHORAGA_TEST_DSN not set; vault audit integration requires Postgres")


def _result(frame: pd.DataFrame, source: str = "yfinance") -> ConnectorResult:
    return ConnectorResult(
        frame=frame,
        source=source,
        fetched_at=datetime.now(UTC),
        rows=len(frame),
    )


def test_vault_override_writes_postgres_row(tmp_path: Path) -> None:
    dsn = os.environ["MAHORAGA_TEST_DSN"]
    adapter = ParquetAdapter(
        tmp_path,
        vault_cutoff_days=180,
        audit_writer=PostgresAuditWriter(dsn=dsn),
        audit_actor="test-vault-audit",
    )

    # Write a row inside the vault window
    df = make_ohlcv_frame(
        ticker="SPY", start=datetime(2026, 5, 1, tzinfo=UTC), bars=3
    )
    adapter.write(_result(df), kind="ohlcv")

    # Snapshot the chain head
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM audit.events ORDER BY id DESC LIMIT 1")
        head_row = cur.fetchone()
        pre_id = head_row[0] if head_row else 0

    # Trigger the override
    adapter.read(
        kind="ohlcv",
        keys=["SPY"],
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 5, 9, tzinfo=UTC),
        asof=datetime(2026, 5, 9, tzinfo=UTC),
        vault_override=True,
        vault_override_reason="phase-1 vault-audit integration test",
    )

    # Exactly one new audit row, action='vault_override', from our actor
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT actor, action, payload FROM audit.events "
            "WHERE id > %s AND actor = 'test-vault-audit' "
            "ORDER BY id ASC",
            (pre_id,),
        )
        rows = cur.fetchall()

    assert len(rows) == 1
    actor, action, payload = rows[0]
    assert actor == "test-vault-audit"
    assert action == "vault_override"
    # psycopg returns jsonb as a dict already
    body = payload if isinstance(payload, dict) else json.loads(payload)
    assert body["kind"] == "ohlcv"
    assert body["keys_count"] == 1
    assert body["keys_sample"] == ["SPY"]
    assert body["reason"] == "phase-1 vault-audit integration test"
    # cutoff is set when enforced
    assert body["vault_cutoff"] is not None
