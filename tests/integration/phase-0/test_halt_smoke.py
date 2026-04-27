"""Halt smoke for the consolidated-assistant model.

Phase 0 verifies two things:
1. CLI-fallback halt: `nemoclaw stop` suspends the assistant; the audit log
   records a halt event with `actor='operator-cli'`.
2. Audit-log halt-poll path: a halt row inserted directly into `audit.events`
   is visible to the polling check used by trade-execution tools (Phase 5+).

Telegram-based halt is verified in Phase 6 governance once the operator's
bot is set up.
"""
import os
import subprocess
import time

import psycopg
import pytest

DSN = os.environ.get("MAHORAGA_TEST_DSN",
                     "postgresql://postgres:change_me_locally@localhost:5432/postgres")


def _audit_count(action: str) -> int:
    with psycopg.connect(DSN) as c:
        cur = c.execute("SELECT COUNT(*) FROM audit.events WHERE action = %s", (action,))
        return cur.fetchone()[0]


@pytest.mark.integration
def test_cli_halt_suspends_and_audits():
    """`nemoclaw stop` halts the assistant and writes a halt event."""
    pre = _audit_count("halt")
    out = subprocess.run(
        ["nemoclaw", "stop", "--name", "mahoraga-trader",
         "--reason", "phase-0-halt-smoke"],
        capture_output=True, text=True, timeout=10,
    )
    assert out.returncode == 0, f"nemoclaw stop failed: {out.stderr}"

    # Allow up to 2s for the halt event to be written
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if _audit_count("halt") > pre:
            break
        time.sleep(0.1)
    post = _audit_count("halt")
    assert post == pre + 1, f"halt event not recorded ({pre} -> {post})"


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
def test_resume_clears_halt():
    """`nemoclaw resume` records a `halt_clear` event."""
    pre = _audit_count("halt_clear")
    out = subprocess.run(
        ["nemoclaw", "resume", "--name", "mahoraga-trader"],
        capture_output=True, text=True, timeout=10,
    )
    assert out.returncode == 0, f"nemoclaw resume failed: {out.stderr}"
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if _audit_count("halt_clear") > pre:
            break
        time.sleep(0.1)
    assert _audit_count("halt_clear") == pre + 1
