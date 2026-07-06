"""Hash-chained audit log over `audit.events` (Phase 6, Task 1).

Schema: `infra/postgres/migrations/003_audit.sql` —
`audit.events(id BIGSERIAL, ts TIMESTAMPTZ DEFAULT NOW(), actor TEXT,
action TEXT, payload JSONB, prev_hash BYTEA, hash BYTEA)`.

Hash scheme
-----------
``hash = sha256(prev_hash_hex + event_type + canonical_json(payload))`` where
``prev_hash_hex`` is the hex digest of the latest row (or ``GENESIS_HASH`` for
the first row) and ``canonical_json`` is
``json.dumps(payload, sort_keys=True, separators=(",", ":"))``.

The DB timestamp (`ts`) is stored but deliberately NOT hashed: `ts` is
server-assigned (`DEFAULT NOW()`), so its value isn't known before the INSERT —
hashing it would require an insert-then-read-back round-trip per event. Chain
integrity comes from the prev_hash linkage plus the hashed event_type/payload;
a tampered `ts` cannot forge or reorder events, it can only lie about wall-clock
time, which the append-only chain order already bounds.

Mirrors the `TradeStore` graceful-no-DSN idiom: lazy `psycopg`, `dsn=None`
makes every method a safe no-op. Autocommit per row — crash-safe in the sense
that a torn write is simply absent from the chain, never a corrupt link.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

#: prev_hash for the first row of the chain. 64 zero-hex-chars — the width of a
#: sha256 hex digest — so genesis is impossible to confuse with a real digest's
#: preimage while keeping `compute_hash` inputs uniform.
GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class ChainVerdict:
    """Result of a chain verification walk.

    `first_bad` is the 0-indexed position (in id order) of the first row whose
    stored hash does not match the recomputed one; None when the chain is intact.
    """

    ok: bool
    rows: int
    first_bad: int | None


def canonical_json(payload: dict) -> str:
    """Deterministic JSON encoding: sorted keys, no whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_hash(prev_hash: str, event_type: str, payload: dict) -> str:
    """sha256 hex digest chaining `prev_hash` to this event (see module docstring)."""
    material = prev_hash + event_type + canonical_json(payload)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def verify_rows(rows: list[tuple[str, str, dict]]) -> ChainVerdict:
    """Verify a chain of `(hash, event_type, payload)` rows in chain order.

    Recomputes each hash from the *stored* previous hash (genesis for row 0),
    so a tampered payload and a tampered hash are both flagged at their own
    0-indexed position. Empty chain → ok.
    """
    prev = GENESIS_HASH
    for i, (row_hash, event_type, payload) in enumerate(rows):
        if row_hash != compute_hash(prev, event_type, payload):
            return ChainVerdict(ok=False, rows=len(rows), first_bad=i)
        prev = row_hash
    return ChainVerdict(ok=True, rows=len(rows), first_bad=None)


class AuditLog:
    """Append-only, hash-chained writer/verifier for `audit.events`.

    No-op without a DSN (returns None / empty-ok verdicts, never raises).
    """

    def __init__(self, dsn: str | None = None, actor: str = "mahoraga") -> None:
        self.dsn = dsn
        self.actor = actor  # `audit.events.actor` is NOT NULL
        self._conn = None

    def is_enabled(self) -> bool:
        return self.dsn is not None

    def _conn_for_test(self):  # noqa: ANN202 (test helper returning a psycopg conn)
        """Return the live connection (opening it if needed). Used by tests."""
        return self._get_conn()

    def _get_conn(self):  # noqa: ANN202
        if self._conn is None:
            import psycopg  # noqa: PLC0415 (lazy: only when a DSN is set)

            self._conn = psycopg.connect(self.dsn, autocommit=True)
        return self._conn

    def append(self, event_type: str, payload: dict) -> str | None:
        """INSERT one chained event; return its hex hash (None when disabled).

        `event_type` maps to the `action` column. `prev_hash`/`hash` are stored
        as raw 32-byte digests (BYTEA); the chain math runs over hex strings.
        """
        if self.dsn is None:
            return None
        from psycopg.types.json import Jsonb  # noqa: PLC0415 (lazy, see _get_conn)

        conn = self._get_conn()
        row = conn.execute("SELECT hash FROM audit.events ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = bytes(row[0]).hex() if row is not None else GENESIS_HASH
        new_hash = compute_hash(prev_hash, event_type, payload)
        conn.execute(
            "INSERT INTO audit.events (actor, action, payload, prev_hash, hash) "
            "VALUES (%s,%s,%s,%s,%s)",
            (
                self.actor,
                event_type,
                Jsonb(payload),
                bytes.fromhex(prev_hash),
                bytes.fromhex(new_hash),
            ),
        )
        return new_hash

    def verify_chain(self) -> ChainVerdict:
        """Walk all rows in id order and recompute every hash.

        Empty chain (or disabled log) → ok with rows=0.
        """
        if self.dsn is None:
            return ChainVerdict(ok=True, rows=0, first_bad=None)
        fetched = self._get_conn().execute(
            "SELECT hash, action, payload FROM audit.events ORDER BY id"
        ).fetchall()
        rows = [(bytes(h).hex(), action, payload) for h, action, payload in fetched]
        return verify_rows(rows)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> AuditLog:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
