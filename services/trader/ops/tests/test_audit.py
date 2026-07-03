"""Tests for `AuditLog` — hash-chained append + chain verification (Phase 6, Task 1).

Pure hash-logic tests always run (no DB). The append+verify round-trip is gated
on `MAHORAGA_DSN` and cleans up after itself (test rows use an event_type with
the 'test-' prefix so they can be deleted from the chain tail).
"""

from __future__ import annotations

import os

import pytest

from services.trader.ops.audit import (
    GENESIS_HASH,
    AuditLog,
    ChainVerdict,
    compute_hash,
    verify_rows,
)

# ---------------------------------------------------------------------------
# Pure hash logic (always run)
# ---------------------------------------------------------------------------

EVENTS: list[tuple[str, dict]] = [
    ("halt", {"reason": "operator", "source": "dashboard"}),
    ("order", {"ticker": "SPY", "qty": 10, "side": "BUY"}),
    ("resume", {"reason": "all clear"}),
]


def _build_chain(events: list[tuple[str, dict]]) -> list[tuple[str, str, dict]]:
    """Build (hash, event_type, payload) rows the way `append` chains them."""
    rows: list[tuple[str, str, dict]] = []
    prev = GENESIS_HASH
    for event_type, payload in events:
        h = compute_hash(prev, event_type, payload)
        rows.append((h, event_type, payload))
        prev = h
    return rows


def test_compute_hash_deterministic() -> None:
    a = compute_hash(GENESIS_HASH, "halt", {"reason": "operator", "source": "dashboard"})
    b = compute_hash(GENESIS_HASH, "halt", {"source": "dashboard", "reason": "operator"})
    assert a == b  # canonical JSON: key order must not matter
    assert len(a) == 64
    assert a != compute_hash(GENESIS_HASH, "halt", {"reason": "other", "source": "dashboard"})


def test_chain_of_three_has_deterministic_linked_hashes() -> None:
    rows = _build_chain(EVENTS)
    again = _build_chain(EVENTS)
    assert [h for h, _, _ in rows] == [h for h, _, _ in again]
    # Each hash depends on the previous one: same event under a different
    # prev_hash produces a different hash.
    assert rows[1][0] != compute_hash(GENESIS_HASH, EVENTS[1][0], EVENTS[1][1])


def test_verify_rows_intact_chain_ok() -> None:
    verdict = verify_rows(_build_chain(EVENTS))
    assert verdict == ChainVerdict(ok=True, rows=3, first_bad=None)


def test_verify_rows_empty_chain_ok() -> None:
    assert verify_rows([]) == ChainVerdict(ok=True, rows=0, first_bad=None)


def test_verify_rows_tampered_payload_detected_at_index_1() -> None:
    rows = _build_chain(EVENTS)
    h, event_type, _ = rows[1]
    rows[1] = (h, event_type, {"ticker": "SPY", "qty": 9999, "side": "BUY"})
    verdict = verify_rows(rows)
    assert not verdict.ok
    assert verdict.rows == 3
    assert verdict.first_bad == 1  # 0-indexed: row 2 of the chain


def test_verify_rows_tampered_hash_detected() -> None:
    rows = _build_chain(EVENTS)
    _, event_type, payload = rows[2]
    rows[2] = ("0" * 64, event_type, payload)
    verdict = verify_rows(rows)
    assert not verdict.ok
    assert verdict.first_bad == 2


def test_disabled_audit_log_noops() -> None:
    log = AuditLog(None)
    assert not log.is_enabled()
    assert log.append("test-noop", {"x": 1}) is None
    assert log.verify_chain() == ChainVerdict(ok=True, rows=0, first_bad=None)


# ---------------------------------------------------------------------------
# DSN-gated round-trip (requires a live Postgres with migration 003 applied)
# ---------------------------------------------------------------------------

DSN = os.environ.get("MAHORAGA_DSN")


@pytest.fixture()
def audit_log() -> AuditLog:
    log = AuditLog(DSN)
    yield log
    # Cleanup: test rows are appended at the chain tail, so deleting them
    # leaves any pre-existing chain intact.
    log._conn_for_test().execute("DELETE FROM audit.events WHERE action LIKE 'test-%'")
    log.close()


@pytest.mark.skipif(not DSN, reason="MAHORAGA_DSN not set")
def test_append_three_events_then_verify_chain(audit_log: AuditLog) -> None:
    hashes = [
        audit_log.append("test-halt", {"reason": "operator"}),
        audit_log.append("test-order", {"ticker": "SPY", "qty": 10}),
        audit_log.append("test-resume", {"reason": "all clear"}),
    ]
    assert all(isinstance(h, str) and len(h) == 64 for h in hashes)
    assert len(set(hashes)) == 3
    verdict = audit_log.verify_chain()
    assert verdict.ok
    assert verdict.rows >= 3
    assert verdict.first_bad is None
