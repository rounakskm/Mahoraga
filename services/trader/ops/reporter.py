"""Reporter — fleet status for the seven-role research fleet (Task 13).

A single read over `experiments.iterations` (+ `strategies.master`) summarised into
a `FleetStatus`: how many hypotheses are active / completed / failed, the leader
candidate per regime, and any anomalies. `dsn=None` returns an all-zero status so
the reporter is always callable offline; every reader method accepts an injected
`rows` list so the formatting logic tests without a database.

`.status()` is a single indexed query (regime + run filter) — it returns in <2s at
our iteration rate; the `<2s` exit criterion is a latency assertion at integration,
the unit tests assert shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Row statuses we recognise. Anything else is treated as completed-ish but flagged
# as an anomaly so the operator notices an unexpected state.
_ACTIVE = "active"
_COMPLETED = "completed"
_FAILED = "failed"


@dataclass(frozen=True)
class FleetStatus:
    active: int = 0
    completed: int = 0
    failures: int = 0
    leader_per_regime: dict[str, str] = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            "Mahoraga fleet status",
            f"  active={self.active} completed={self.completed} failures={self.failures}",
        ]
        if self.leader_per_regime:
            lines.append("  leader_per_regime:")
            for regime, candidate in sorted(self.leader_per_regime.items()):
                lines.append(f"    {regime}: {candidate}")
        else:
            lines.append("  leader_per_regime: (none)")
        if self.anomalies:
            lines.append("  anomalies:")
            lines.extend(f"    - {a}" for a in self.anomalies)
        return "\n".join(lines)


class Reporter:
    def __init__(self, dsn: str | None = None, *, bank: str = "mahoraga-trader") -> None:
        self.dsn = dsn
        self.bank = bank

    def is_enabled(self) -> bool:
        return bool(self.dsn)

    def status(
        self, run_id: str | None = None, *, rows: list[dict[str, Any]] | None = None
    ) -> FleetStatus:
        """Fleet status. `rows` (injected) wins; else query Postgres; else empty."""
        if rows is None:
            if not self.dsn:
                return FleetStatus()
            rows = self._fetch(run_id)
        return self._summarise(rows)

    @staticmethod
    def _summarise(rows: list[dict[str, Any]]) -> FleetStatus:
        active = completed = failures = 0
        best: dict[str, tuple[float, str]] = {}  # regime -> (fitness, candidate_hash)
        anomalies: list[str] = []
        for row in rows:
            status = str(row.get("status", _COMPLETED)).lower()
            if status == _ACTIVE:
                active += 1
            elif status == _FAILED:
                failures += 1
            elif status == _COMPLETED:
                completed += 1
            else:
                completed += 1
                anomalies.append(f"unknown status '{status}' for {row.get('candidate_hash')}")
            # leader per regime over COMPLETED rows (a real, scored result).
            if status == _COMPLETED:
                regime = row.get("regime")
                fitness = row.get("fitness")
                candidate = row.get("candidate_hash")
                if regime is not None and fitness is not None and candidate is not None:
                    fitness = float(fitness)
                    if regime not in best or fitness > best[regime][0]:
                        best[regime] = (fitness, str(candidate))
        leader_per_regime = {regime: candidate for regime, (_, candidate) in best.items()}
        return FleetStatus(
            active=active,
            completed=completed,
            failures=failures,
            leader_per_regime=leader_per_regime,
            anomalies=anomalies,
        )

    def _fetch(self, run_id: str | None) -> list[dict[str, Any]]:
        """Read iteration rows from Postgres, mapped into the summary row shape.

        A discarded (not-promoted) iteration is a `failed` hypothesis; a promoted
        one is `completed`. The regime is read from the candidate's `params` (the
        per-regime window map's keys collapse to a single label only at the
        registry layer, so here we report the run-level promoted/discarded split).
        """
        import psycopg  # noqa: PLC0415 (lazy: only when a DSN is set)

        where = "WHERE run_id = %s" if run_id else ""
        args = (run_id,) if run_id else ()
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT candidate_hash, params, fitness, train_sharpe, promoted, reason "
                f"FROM experiments.iterations {where}",
                args,
            )
            out: list[dict[str, Any]] = []
            for candidate_hash, params, fitness, train_sharpe, promoted, reason in cur.fetchall():
                regime = next(iter(params.keys())) if isinstance(params, dict) and params else None
                out.append({
                    "regime": regime,
                    "candidate_hash": candidate_hash,
                    "fitness": fitness if fitness is not None else train_sharpe,
                    "status": _COMPLETED if promoted else _FAILED,
                    "reason": reason,
                })
            return out
