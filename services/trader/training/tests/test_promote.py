"""DSN-gated tests for promote_pipeline — atomic record + SERIALIZABLE conditional
promote. SKIPs with no MAHORAGA_DSN (local); CI's integration-smoke runs it against
a fresh migrated DB."""
from __future__ import annotations

import os
import threading

import psycopg
import pytest

from services.trader.training.parse_metric import FitnessReport
from services.trader.training.promote import PromoteResult, promote_pipeline

DSN = os.environ.get("MAHORAGA_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="no MAHORAGA_DSN")


def _report(fitness: float, ch: str) -> FitnessReport:
    return FitnessReport(
        candidate_hash=ch,
        params={"hash": ch},
        sharpe=fitness,
        fitness=fitness,
        quarterly_win_rate=0.0,
        max_drawdown=0.0,
        promoted=True,
        reason="test",
    )


def _master_hash(dsn: str) -> str | None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT candidate_hash FROM strategies.master WHERE id=1")
        return cur.fetchone()[0]


def _reset_master(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE strategies.master SET candidate_hash=NULL, fitness='-Infinity', "
            "run_id=NULL, ts=NOW() WHERE id=1"
        )
        cur.execute("DELETE FROM experiments.iterations WHERE run_id LIKE 'test-%'")


@pytest.fixture()
def dsn() -> str:
    _reset_master(DSN)
    yield DSN
    _reset_master(DSN)


def test_only_strictly_better_fitness_promotes(dsn: str) -> None:
    lo = _report(fitness=0.5, ch="lo")
    hi = _report(fitness=0.9, ch="hi")
    assert promote_pipeline(dsn, "test-r1", 0, lo).promoted is True   # beats -inf
    assert promote_pipeline(dsn, "test-r1", 1, hi).promoted is True   # strictly better
    assert promote_pipeline(dsn, "test-r1", 2, lo).promoted is False  # 0.5 < 0.9
    assert _master_hash(dsn) == "hi"


def test_records_but_does_not_promote_when_fortress_rejected(dsn: str) -> None:
    rej = FitnessReport(
        candidate_hash="rej",
        params={"hash": "rej"},
        sharpe=9.0,
        fitness=9.0,
        quarterly_win_rate=0.0,
        max_drawdown=0.0,
        promoted=False,
        reason="fortress rejected",
    )
    res = promote_pipeline(dsn, "test-r1", 0, rej)
    assert isinstance(res, PromoteResult)
    assert res.recorded is True
    assert res.promoted is False
    assert _master_hash(dsn) is None


def _promote_with_retry(
    dsn: str, run_id: str, iteration: int, report: FitnessReport
) -> PromoteResult:
    # Correct client behavior under SERIALIZABLE: retry on serialization failure.
    for _ in range(20):
        try:
            return promote_pipeline(dsn, run_id, iteration, report)
        except psycopg.errors.SerializationFailure:
            continue
    raise AssertionError("exceeded serialization retries")


def test_concurrent_winners_exactly_one_master(dsn: str) -> None:
    # Two threads each submit a candidate that beats the current (-inf) master.
    # Under SERIALIZABLE, the conflicting promotes serialize: the loser either
    # records a no-promote (it now sees the winner's higher fitness) or hits a
    # serialization failure the client retries. No exception leaks; one final master.
    n = 2
    barrier = threading.Barrier(n)
    results: list[PromoteResult] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker(idx: int) -> None:
        report = _report(fitness=0.5 + 0.1 * idx, ch=f"c{idx}")
        barrier.wait()
        try:
            res = _promote_with_retry(dsn, "test-conc", idx, report)
        except Exception as exc:  # pragma: no cover - failure path
            with lock:
                errors.append(exc)
            return
        with lock:
            results.append(res)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"exceptions leaked: {errors}"
    assert len(results) == n
    promoted = [r for r in results if r.promoted]
    assert len(promoted) >= 1, "at least one candidate promotes"
    # A single final master, and it is the highest-fitness candidate.
    assert _master_hash(dsn) == "c1"
