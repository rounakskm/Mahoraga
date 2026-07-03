"""Atomic record-and-promote (amendment §4 item 13). Always records the iteration;
promotes only a strictly-better promoted candidate, serialized on strategies.master
so parallel Hunters can't both win. Ported-in-spirit from multiautoresearch
submit_patch.py; the Postgres SERIALIZABLE serializer replaces its file lock."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

import psycopg

from services.trader.training.parse_metric import FitnessReport

_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class PromoteResult:
    recorded: bool
    promoted: bool
    reason: str


def _can_promote(report: FitnessReport) -> bool:
    """Promotion eligibility (pure): fortress-promoted AND finite fitness.
    A NaN/inf fitness records (auditable lineage) but must never win a
    `>` compare against master — NaN comparisons are always False-ish traps."""
    return bool(report.promoted) and math.isfinite(report.fitness)


def promote_pipeline(
    dsn: str,
    run_id: str,
    iteration: int,
    report: FitnessReport,
    parent_hash: str | None = None,
) -> PromoteResult:
    """Record `report` as an iteration and conditionally promote it to master.

    Always inserts the iteration row. Promotes (updates strategies.master + marks
    the iteration is_best by its inserted row id) iff `_can_promote(report)` AND
    `report.fitness` is strictly greater than the current master fitness, under
    SERIALIZABLE isolation with a `FOR UPDATE` lock on the singleton master row —
    so concurrent winners serialize and exactly one promotes. A losing transaction
    raising `psycopg.errors.SerializationFailure` is retried here (bounded,
    3 attempts) — correct client behavior under SERIALIZABLE, so callers never
    see a serialization failure unless the contention is pathological.
    """
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return _promote_once(dsn, run_id, iteration, report, parent_hash)
        except psycopg.errors.SerializationFailure:
            if attempt == _MAX_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


def _promote_once(
    dsn: str,
    run_id: str,
    iteration: int,
    report: FitnessReport,
    parent_hash: str | None,
) -> PromoteResult:
    with psycopg.connect(dsn) as conn:
        conn.isolation_level = psycopg.IsolationLevel.SERIALIZABLE
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO experiments.iterations (run_id, iteration, candidate_hash, "
                "parent_hash, params, train_sharpe, fitness, promoted, is_best, reason) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (
                    run_id,
                    iteration,
                    report.candidate_hash,
                    parent_hash,
                    json.dumps(report.params),
                    report.sharpe,
                    report.fitness,
                    report.promoted,
                    False,
                    report.reason,
                ),
            )
            row_id = cur.fetchone()[0]
            if not _can_promote(report):
                reason = (
                    "recorded (fortress rejected)"
                    if not report.promoted
                    else f"recorded (non-finite fitness {report.fitness})"
                )
                return PromoteResult(True, False, reason)
            cur.execute("SELECT fitness FROM strategies.master WHERE id=1 FOR UPDATE")
            master_fitness = cur.fetchone()[0]
            if report.fitness <= master_fitness:
                return PromoteResult(
                    True,
                    False,
                    f"recorded (fitness {report.fitness:.4f} <= master {master_fitness:.4f})",
                )
            cur.execute(
                "UPDATE strategies.master SET candidate_hash=%s, fitness=%s, run_id=%s, "
                "ts=NOW() WHERE id=1",
                (report.candidate_hash, report.fitness, run_id),
            )
            # Mark is_best by the row we just inserted — (run_id, iteration) is not
            # unique across replay steps, the RETURNING id is.
            cur.execute(
                "UPDATE experiments.iterations SET is_best=TRUE WHERE id=%s",
                (row_id,),
            )
            return PromoteResult(
                True, True, f"promoted (fitness {report.fitness:.4f} > {master_fitness:.4f})"
            )
