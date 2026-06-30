"""Phase-3 Layer-1 provenance — a durable, queryable record of the search.

Mirrors the Phase-1 `PostgresAuditWriter` pattern: lazy psycopg, `dsn=None` skips
all writes, so the loop stays runnable with no Postgres but captures full
provenance when a DSN is set (`MAHORAGA_DSN`). Two records:

- `experiments.iterations` — every candidate the loop evaluates (kept + discarded),
  with the gate reason. The auditable lineage of the search.
- `strategies.registry` — promoted survivors that ALSO hold on the vault
  (deployment-eligible). Idempotent on `candidate_hash`.

The compare-and-set serializer for race-free *parallel* Hunters is a Layer-3
concern (the amendment's promote_pipeline); Layer 1 is single-threaded, so this
appends.
"""

from __future__ import annotations

import hashlib
import json


def candidate_hash(params: dict) -> str:
    """Stable short hash of a candidate's parameters (the mutation surface)."""
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]


class ProvenanceWriter:
    def __init__(self, dsn: str | None) -> None:
        self.dsn = dsn
        self._conn = None

    def is_enabled(self) -> bool:
        return bool(self.dsn)

    def _cursor_conn(self):
        if self._conn is None:
            import psycopg  # noqa: PLC0415 (lazy: only when a DSN is set)

            self._conn = psycopg.connect(self.dsn, autocommit=True)
        return self._conn

    def write_iteration(
        self,
        *,
        run_id: str,
        iteration: int,
        params: dict,
        train_sharpe: float,
        promoted: bool,
        is_best: bool,
        reason: str,
        parent_hash: str | None = None,
    ) -> None:
        if not self.dsn:
            return
        self._cursor_conn().execute(
            "INSERT INTO experiments.iterations "
            "(run_id, iteration, candidate_hash, parent_hash, params, train_sharpe, "
            " promoted, is_best, reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (run_id, iteration, candidate_hash(params), parent_hash, json.dumps(params),
             train_sharpe, promoted, is_best, reason),
        )

    def register_strategy(
        self,
        *,
        run_id: str,
        params: dict,
        train_sharpe: float,
        vault_sharpe: float,
        vault_holds: bool,
        artifact_path: str | None = None,
    ) -> None:
        """Record a deployment-eligible strategy (promoted AND vault holds)."""
        if not self.dsn:
            return
        self._cursor_conn().execute(
            "INSERT INTO strategies.registry "
            "(run_id, candidate_hash, params, train_sharpe, vault_sharpe, vault_holds, "
            " deployment_eligible, artifact_path) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (candidate_hash) DO NOTHING",
            (run_id, candidate_hash(params), json.dumps(params), train_sharpe,
             vault_sharpe, vault_holds, vault_holds, artifact_path),
        )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> ProvenanceWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
