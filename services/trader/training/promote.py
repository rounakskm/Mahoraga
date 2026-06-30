"""Atomic record-and-promote (amendment §4 item 13). Always records the iteration;
promotes only a strictly-better promoted candidate, serialized on strategies.master
so parallel Hunters can't both win. Ported-in-spirit from multiautoresearch
submit_patch.py; the Postgres SERIALIZABLE serializer replaces its file lock."""
from __future__ import annotations

import json
from dataclasses import dataclass

import psycopg

from services.trader.training.parse_metric import FitnessReport


@dataclass(frozen=True)
class PromoteResult:
    recorded: bool
    promoted: bool
    reason: str


def promote_pipeline(
    dsn: str,
    run_id: str,
    iteration: int,
    report: FitnessReport,
    parent_hash: str | None = None,
) -> PromoteResult:
    """Record `report` as an iteration and conditionally promote it to master.

    Always inserts the iteration row. Promotes (updates strategies.master + marks
    the iteration is_best) iff `report.promoted` AND `report.fitness` is strictly
    greater than the current master fitness, under SERIALIZABLE isolation with a
    `FOR UPDATE` lock on the singleton master row — so concurrent winners serialize
    and exactly one promotes. A losing transaction may raise
    `psycopg.errors.SerializationFailure`; the caller retries (correct client
    behavior under SERIALIZABLE).
    """
    with psycopg.connect(dsn) as conn:
        conn.isolation_level = psycopg.IsolationLevel.SERIALIZABLE
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO experiments.iterations (run_id, iteration, candidate_hash, "
                "parent_hash, params, train_sharpe, fitness, promoted, is_best, reason) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
            if not report.promoted:
                return PromoteResult(True, False, "recorded (fortress rejected)")
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
            cur.execute(
                "UPDATE experiments.iterations SET is_best=TRUE "
                "WHERE run_id=%s AND iteration=%s",
                (run_id, iteration),
            )
            return PromoteResult(
                True, True, f"promoted (fitness {report.fitness:.4f} > {master_fitness:.4f})"
            )
