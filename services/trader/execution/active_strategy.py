"""Conductor auto-adopt: pick the best vault-validated strategy to deploy.

This closes the train -> promote -> deploy handoff. Instead of a human pinning
`--strategy PATH`, the paper trader adopts the current "back pocket": the best
deployment-eligible row in `strategies.registry`.

Design fact (do not conflate): `strategies.master` names the best-*fitness*-
promoted candidate, which is NOT necessarily vault-validated. Auto-adopt MUST
select from `strategies.registry WHERE deployment_eligible = true` (the vault-
holding survivors), ordered `vault_sharpe DESC NULLS LAST, train_sharpe DESC`.
See `refresh_master.py` for the master pointer this deliberately does NOT use.

Lazy `import psycopg` inside the query path (the `refresh_master` / `provenance`
pattern) keeps this module importable with no psycopg installed, and `dsn=None`
with no injected `rows` is a graceful None — so the runner degrades to a clean
no-op skip offline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: The deployment-eligible back pocket, best-first. `NULLS LAST` keeps a
#: vault-validated row (a real `vault_sharpe`) ahead of one that was never
#: vault-scored; `train_sharpe DESC` breaks ties (incl. the all-NULL-vault case).
_SELECT_ACTIVE_SQL = (
    "SELECT candidate_hash, params, train_sharpe, vault_sharpe "
    "FROM strategies.registry "
    "WHERE deployment_eligible = true "
    "ORDER BY vault_sharpe DESC NULLS LAST, train_sharpe DESC "
    "LIMIT 1"
)


@dataclass(frozen=True)
class ActiveStrategy:
    """The strategy the conductor has selected to deploy.

    `params` is the artifact shape stored in `strategies.registry.params` (JSONB):
    ``{"windows": {...}, "adx_threshold": ..., "vol_threshold": ...}``.
    """

    candidate_hash: str
    params: dict
    train_sharpe: float | None
    vault_sharpe: float | None


def _rank_key(row: dict) -> tuple[bool, float, float]:
    """Sort key mirroring `vault_sharpe DESC NULLS LAST, train_sharpe DESC`.

    Sorted ascending, the smallest key must be the winner. A present
    `vault_sharpe` beats NULL (`has_vault=False` sorts before True), then higher
    `vault_sharpe`, then higher `train_sharpe` — all negated so DESC becomes ASC.
    """
    vault = row.get("vault_sharpe")
    train = row.get("train_sharpe")
    has_vault_null = vault is None
    return (
        has_vault_null,  # False (real vault Sharpe) sorts before True (NULL last)
        -(float(vault) if vault is not None else 0.0),
        -(float(train) if train is not None else float("-inf")),
    )


def _from_row(row: dict) -> ActiveStrategy:
    """Build an `ActiveStrategy` from a registry-row-shaped dict."""
    return ActiveStrategy(
        candidate_hash=row["candidate_hash"],
        params=row["params"],
        train_sharpe=row.get("train_sharpe"),
        vault_sharpe=row.get("vault_sharpe"),
    )


def select_active_strategy(
    dsn: str | None, *, rows: list[dict] | None = None
) -> ActiveStrategy | None:
    """Return the best deployment-eligible registry strategy, or None.

    Two sources, in order:

    * `rows` injected (tests / offline) — filter to `deployment_eligible` and
      rank in Python with `_rank_key` (identical ordering to the SQL). `dsn` is
      ignored.
    * else `dsn` set — run `_SELECT_ACTIVE_SQL` via a lazy `psycopg` connection.

    `dsn=None` with no injected `rows` -> None (graceful: no DB, no adopt).
    """
    if rows is not None:
        eligible = [r for r in rows if r.get("deployment_eligible")]
        if not eligible:
            return None
        return _from_row(min(eligible, key=_rank_key))

    if dsn is None:
        return None

    import psycopg  # noqa: PLC0415 (lazy: only when actually querying the registry)

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(_SELECT_ACTIVE_SQL)
        row = cur.fetchone()
    if row is None:
        return None
    candidate_hash, params, train_sharpe, vault_sharpe = row
    return ActiveStrategy(
        candidate_hash=candidate_hash,
        params=params,
        train_sharpe=train_sharpe,
        vault_sharpe=vault_sharpe,
    )


def write_active(
    strat: ActiveStrategy, out_path: Path = Path("strategies/active.json")
) -> dict:
    """Write the selected strategy as an artifact JSON and return its params.

    The on-disk file spreads `params` at the top level so the existing
    `run_paper._load_artifact` reads it as a plain artifact (it looks up
    ``windows`` / ``adx_threshold`` / ``vol_threshold`` directly), and carries
    `candidate_hash` / `train_sharpe` / `vault_sharpe` alongside for provenance.
    Returns the `params` dict (the artifact the runner then loads).
    """
    artifact = {
        **strat.params,
        "candidate_hash": strat.candidate_hash,
        "train_sharpe": strat.train_sharpe,
        "vault_sharpe": strat.vault_sharpe,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return strat.params
