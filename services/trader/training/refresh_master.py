"""Restore the workspace's strategies/master.json from the promoted master.

The atomic master pointer (`strategies.master`, Task 2) names the current
deployment-best candidate_hash; its full params live in `strategies.registry`
(Task 3). `refresh_master` joins the two and materializes them to a JSON file so
a fresh worktree / Hunter starts from the current promoted-best.

Lazy `import psycopg` inside the function (the provenance.py pattern) keeps this
module importable with no psycopg installed.
"""
from __future__ import annotations

import json
from pathlib import Path


def refresh_master(dsn: str, out_path: Path = Path("strategies/master.json")) -> dict | None:
    """Write the current master's params to `out_path` and return them.

    Joins `strategies.master` to `strategies.registry` on candidate_hash. Returns
    None (and writes nothing) when master.candidate_hash is NULL or no registry
    row matches. Otherwise writes `{"candidate_hash", "params"}` JSON (creating
    the parent dir) and returns the params dict.
    """
    import psycopg  # noqa: PLC0415 (lazy: only when actually restoring)

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT r.params, r.candidate_hash FROM strategies.master m "
            "JOIN strategies.registry r ON r.candidate_hash = m.candidate_hash"
        )
        row = cur.fetchone()
    if row is None:
        return None
    params, candidate_hash = row
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"candidate_hash": candidate_hash, "params": params}, indent=2)
    )
    return params
