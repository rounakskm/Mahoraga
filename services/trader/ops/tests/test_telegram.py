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


# --- extended commands: /regime /strategy /kb /report (Phase-6 Task 3) ---


def _ops_with(tmp_path: Path, **providers: object) -> TelegramOps:
    halt = HaltControl(tmp_path / "halt.flag")
    reporter = Reporter(None)
    return TelegramOps(halt, reporter, token=None, **providers)  # type: ignore[arg-type]


def test_regime_command_returns_provider_render(tmp_path: Path) -> None:
    ops = _ops_with(tmp_path, regime_provider=lambda: "regime: BULL (p_transition=0.12)")
    assert ops.handle("/regime") == "regime: BULL (p_transition=0.12)"


def test_regime_command_without_provider_says_not_wired(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    assert "not wired" in ops.handle("/regime")


def test_strategy_command_passes_hash_to_provider(tmp_path: Path) -> None:
    seen: list[str] = []

    def provider(strategy_hash: str) -> str:
        seen.append(strategy_hash)
        return f"strategy {strategy_hash}: momentum-v3"

    ops = _ops_with(tmp_path, strategy_provider=provider)
    reply = ops.handle("/strategy abc123")
    assert seen == ["abc123"]
    assert reply == "strategy abc123: momentum-v3"


def test_strategy_command_without_arg_returns_usage(tmp_path: Path) -> None:
    ops = _ops_with(tmp_path, strategy_provider=lambda h: h)
    reply = ops.handle("/strategy")
    assert "usage" in reply.lower()
    assert "/strategy" in reply


def test_strategy_command_without_provider_says_not_wired(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    assert "not wired" in ops.handle("/strategy abc123")


def test_kb_command_returns_provider_render(tmp_path: Path) -> None:
    ops = _ops_with(tmp_path, kb_provider=lambda: "KB: 3 recent highlights")
    assert ops.handle("/kb") == "KB: 3 recent highlights"


def test_kb_command_without_provider_says_not_wired(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    assert "not wired" in ops.handle("/kb")


def test_report_command_routes_daily_and_weekly(tmp_path: Path) -> None:
    ops = _ops_with(tmp_path, report_provider=lambda kind: f"{kind} report body")
    assert ops.handle("/report daily") == "daily report body"
    assert ops.handle("/report weekly") == "weekly report body"


def test_report_command_bad_or_missing_kind_returns_usage(tmp_path: Path) -> None:
    ops = _ops_with(tmp_path, report_provider=lambda kind: kind)
    for cmd in ("/report", "/report nonsense"):
        reply = ops.handle(cmd)
        assert "usage" in reply.lower()
        assert "/report" in reply


def test_report_command_without_provider_says_not_wired(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    assert "not wired" in ops.handle("/report daily")


def test_raising_provider_returns_error_reply_not_exception(tmp_path: Path) -> None:
    def boom() -> str:
        raise RuntimeError("hindsight down")

    def boom_arg(_: str) -> str:
        raise RuntimeError("registry down")

    ops = _ops_with(
        tmp_path,
        regime_provider=boom,
        strategy_provider=boom_arg,
        kb_provider=boom,
        report_provider=boom_arg,
    )
    for cmd in ("/regime", "/strategy abc", "/kb", "/report daily"):
        reply = ops.handle(cmd)
        assert "provider error" in reply
    assert "hindsight down" in ops.handle("/regime")


def test_help_lists_all_seven_commands(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    reply = ops.handle("/help")
    for cmd in ("/halt", "/resume", "/status", "/regime", "/strategy", "/kb", "/report"):
        assert cmd in reply


def _update(text: str | None = "/status", chat_id: object = 42) -> dict:
    message: dict = {}
    if text is not None:
        message["text"] = text
    if chat_id is not None:
        message["chat"] = {"id": chat_id}
    return {"update_id": 1, "message": message}


def test_should_act_open_when_no_allowlist(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    assert ops._should_act(_update()) is True


def test_should_act_allows_listed_chat(tmp_path: Path) -> None:
    ops = TelegramOps(
        HaltControl(tmp_path / "halt.flag"), Reporter(None),
        token=None, allowed_chat_ids={"42"},
    )
    assert ops._should_act(_update(chat_id=42)) is True


def test_should_act_ignores_unlisted_chat(tmp_path: Path) -> None:
    ops = TelegramOps(
        HaltControl(tmp_path / "halt.flag"), Reporter(None),
        token=None, allowed_chat_ids={"42"},
    )
    assert ops._should_act(_update(chat_id=666)) is False
    assert ops.halt.is_halted() is False  # ignored means no action, ever


def test_should_act_ignores_updates_without_text_or_chat(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    assert ops._should_act(_update(text=None)) is False
    assert ops._should_act(_update(chat_id=None)) is False
    assert ops._should_act({"update_id": 9}) is False


def test_poll_without_token_raises(tmp_path: Path) -> None:
    ops = _ops(tmp_path)
    try:
        ops.poll()
    except RuntimeError as exc:
        assert "token" in str(exc)
    else:  # pragma: no cover - poll must reject when offline
        raise AssertionError("poll() should raise without a token")
