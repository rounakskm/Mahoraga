"""Tests for TelegramOps — offline command routing (Task 14).

All tests run with `token=None` (no real bot) so `.handle()` is exercised without
any network. `HaltControl` points at a tmp flag file; `Reporter(None)` returns an
empty (but renderable) fleet status.
"""

from __future__ import annotations

from pathlib import Path

from services.trader.ops.halt import HaltControl
from services.trader.ops.reporter import Reporter
from services.trader.ops.telegram import TelegramOps


def _ops(tmp_path: Path) -> TelegramOps:
    halt = HaltControl(tmp_path / "halt.flag")
    reporter = Reporter(None)
    return TelegramOps(halt, reporter, token=None)


def test_halt_command_trips_kill_switch_and_carries_reason(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    reply = ops.handle("/halt stop now")
    assert ops.halt.is_halted() is True
    assert ops.halt.reason() == "stop now"
    assert "stop now" in reply
    assert "halt" in reply.lower()


def test_halt_command_without_reason_uses_default(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    ops.handle("/halt")
    assert ops.halt.is_halted() is True
    assert ops.halt.reason() == "operator halt"


def test_resume_command_clears_halt(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    ops.handle("/halt because")
    assert ops.halt.is_halted() is True
    reply = ops.handle("/resume")
    assert ops.halt.is_halted() is False
    assert "resume" in reply.lower()


def test_status_command_returns_reporter_render(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    reply = ops.handle("/status")
    assert isinstance(reply, str)
    assert reply
    assert reply == ops.reporter.status().render()


def test_unknown_command_returns_help(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    reply = ops.handle("/frobnicate")
    assert "/halt" in reply
    assert "/resume" in reply
    assert "/status" in reply


def test_poll_without_token_raises(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    try:
        ops.poll()
    except RuntimeError as exc:
        assert "token" in str(exc)
    else:  # pragma: no cover - poll must reject when offline
        raise AssertionError("poll() should raise without a token")
