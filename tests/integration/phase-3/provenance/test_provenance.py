"""Postgres-backed provenance: experiments.iterations + strategies.registry.

Requires a Postgres DSN (MAHORAGA_TEST_DSN), like the Phase-1 audit integration
test. Applies migration 005 idempotently so the test is self-contained, writes a
couple of iterations + one registered strategy, and reads them back.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from services.trader.training.provenance import ProvenanceWriter, candidate_hash

pytestmark = pytest.mark.integration

DSN = os.environ.get("MAHORAGA_TEST_DSN")
MIGRATIONS = Path(__file__).resolve().parents[4] / "infra/postgres/migrations"


@pytest.fixture
def conn():
    if not DSN:
        pytest.skip("MAHORAGA_TEST_DSN not set; provenance integration test needs Postgres")
    import psycopg

    with psycopg.connect(DSN, autocommit=True) as c:
        for mig in ("002_schemas.sql", "005_experiments.sql"):
            c.execute((MIGRATIONS / mig).read_text())
        # isolate: candidate_hash is globally unique, so clear prior test rows
        # (a strategy registers once ever — re-running would otherwise hit ON CONFLICT)
        c.execute("DELETE FROM experiments.iterations WHERE run_id LIKE 'test-%'")
        c.execute("DELETE FROM strategies.registry WHERE run_id LIKE 'test-%'")
        yield c


def test_iterations_and_registry_round_trip(conn):
    run_id = f"test-{os.getpid()}"
    w = ProvenanceWriter(DSN)
    params_a = {"trending_low_vol": 200, "ranging_high_vol": 30}
    params_b = {"trending_low_vol": 180, "ranging_high_vol": 30}

    w.write_iteration(run_id=run_id, iteration=0, params=params_a, train_sharpe=0.05,
                      promoted=True, is_best=True, reason="promoted")
    w.write_iteration(run_id=run_id, iteration=1, params=params_b, train_sharpe=0.03,
                      promoted=False, is_best=False, reason="rejected by gates: fitness")
    w.register_strategy(run_id=run_id, params=params_a, train_sharpe=0.05,
                        vault_sharpe=0.06, vault_holds=True, artifact_path="strategies/x.json")
    w.register_strategy(run_id=run_id, params=params_a, train_sharpe=0.05,  # idempotent
                        vault_sharpe=0.06, vault_holds=True)
    w.close()

    cur = conn.execute(
        "SELECT iteration, promoted, candidate_hash, reason FROM experiments.iterations "
        "WHERE run_id = %s ORDER BY iteration", (run_id,))
    rows = cur.fetchall()
    assert len(rows) == 2
    assert rows[0][1] is True and rows[1][1] is False           # promoted flags recorded
    assert rows[0][2] == candidate_hash(params_a)               # hash matches
    assert "fitness" in rows[1][3]                              # discard reason kept

    cur = conn.execute(
        "SELECT count(*), bool_and(deployment_eligible) FROM strategies.registry "
        "WHERE run_id = %s", (run_id,))
    n, eligible = cur.fetchone()
    assert n == 1 and eligible is True                          # idempotent: one row, eligible
