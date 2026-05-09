"""Halt smoke for the audit-poll-path mechanism.

Phase 0 verifies the substrate-side halt protocol: any actor (a future
trader-halt CLI, an operator-direct INSERT, a Telegram bridge in Phase 6)
writes a row to `audit.events` with `action='halt'`, and the polling check
used by trade-execution tools sees it within the 2 s tolerance window.

The user-facing CLI halt command (`nemoclaw stop --name ...`) and the
matching `halt_clear`/`resume` flow live at `services/trader/` and are a
Phase 5+ deliverable. NemoClaw v0.1.0 does not ship a per-sandbox halt
CLI — the only sandbox-lifecycle primitive is `nemoclaw <name> destroy`,
which is destructive and not what the trading-halt protocol wants.
"""
import os
import time

import psycopg
import pytest

DSN = os.environ.get(
    "MAHORAGA_TEST_DSN",
    "postgresql://postgres:change_me_locally@localhost:5432/postgres",
)


@pytest.mark.integration
def test_audit_poll_path_visible():
    """A halt row inserted to audit.events is observable within 2s (the poll fallback)."""
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(
            "INSERT INTO audit.events (actor, action, payload, hash) "
            "VALUES (%s, %s, %s::jsonb, decode(%s,'hex'))",
            ("phase-0-test", "halt", '{"reason":"poll-path-check"}', "00" * 32),
        )

    deadline = time.monotonic() + 2.0
    seen = False
    with psycopg.connect(DSN) as c:
        while time.monotonic() < deadline and not seen:
            cur = c.execute(
                "SELECT 1 FROM audit.events "
                "WHERE action = 'halt' AND payload->>'reason' = 'poll-path-check'"
            )
            seen = cur.fetchone() is not None
            if not seen:
                time.sleep(0.1)
    assert seen, "halt event not visible to poll path within 2s"


@pytest.mark.integration
def test_audit_hash_chain_initialized():
    """The audit table's hash-chain column rejects NULL — every event must be hashed."""
    with psycopg.connect(DSN) as c:
        cur = c.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema='audit' AND table_name='events' AND column_name='hash'"
        )
        row = cur.fetchone()
    assert row is not None and row[0] == "NO", (
        f"audit.events.hash must be NOT NULL; got is_nullable={row}"
    )
