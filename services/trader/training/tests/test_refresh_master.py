"""DSN-gated tests for refresh_master — restore strategies/master.json from the
registry's current master pointer. SKIPs with no MAHORAGA_DSN (local); CI's
integration-smoke runs it against a fresh migrated DB."""
from __future__ import annotations

import json
import os

import psycopg
import pytest

from services.trader.training.refresh_master import refresh_master

DSN = os.environ.get("MAHORAGA_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="no MAHORAGA_DSN")

CH = "refresh-test-hash"
PARAMS = {"windows": {"bull": [10, 20]}, "threshold": 0.5}


def _seed(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO strategies.registry "
            "(run_id, candidate_hash, params, train_sharpe, vault_sharpe, vault_holds, "
            " deployment_eligible, artifact_path) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (candidate_hash) DO NOTHING",
            ("test-refresh", CH, json.dumps(PARAMS), 1.0, 0.8, True, True, None),
        )
        cur.execute(
            "UPDATE strategies.master SET candidate_hash=%s, fitness=%s, run_id=%s, "
            "ts=NOW() WHERE id=1",
            (CH, 1.0, "test-refresh"),
        )


def _clear(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE strategies.master SET candidate_hash=NULL, fitness='-Infinity', "
            "run_id=NULL, ts=NOW() WHERE id=1"
        )
        cur.execute("DELETE FROM strategies.registry WHERE candidate_hash=%s", (CH,))


@pytest.fixture()
def dsn() -> str:
    _clear(DSN)
    yield DSN
    _clear(DSN)


def test_refresh_writes_master_params(dsn: str, tmp_path) -> None:
    _seed(dsn)
    out = tmp_path / "nested" / "master.json"
    params = refresh_master(dsn, out)

    assert params == PARAMS
    assert out.exists()
    written = json.loads(out.read_text())
    assert written["candidate_hash"] == CH
    assert written["params"] == PARAMS


def test_refresh_returns_none_when_master_unset(dsn: str, tmp_path) -> None:
    # master.candidate_hash is NULL (cleared by fixture); no write, no row.
    out = tmp_path / "master.json"
    result = refresh_master(dsn, out)

    assert result is None
    assert not out.exists()
