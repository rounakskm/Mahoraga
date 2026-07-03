"""HaltControl — the cross-process file-flag kill-switch (Task 11)."""

from __future__ import annotations

from pathlib import Path

from services.trader.ops.halt import HaltControl


def test_halt_sets_flag_and_reason(tmp_path: Path) -> None:
    h = HaltControl(flag_path=tmp_path / "control" / "halt.flag")
    assert h.is_halted() is False
    assert h.reason() is None

    h.halt("x")
    assert h.is_halted() is True
    assert h.reason() == "x"


def test_resume_clears_flag_and_reason(tmp_path: Path) -> None:
    h = HaltControl(flag_path=tmp_path / "control" / "halt.flag")
    h.halt("stop now")
    assert h.is_halted() is True

    h.resume()
    assert h.is_halted() is False
    assert h.reason() is None


def test_resume_is_idempotent_when_not_halted(tmp_path: Path) -> None:
    h = HaltControl(flag_path=tmp_path / "control" / "halt.flag")
    h.resume()  # no flag yet — must not raise
    assert h.is_halted() is False


def test_env_var_overrides_default_flag_path(tmp_path: Path, monkeypatch) -> None:
    flag = tmp_path / "env" / "halt.flag"
    monkeypatch.setenv("MAHORAGA_HALT_FLAG", str(flag))
    h = HaltControl()
    assert h.flag_path == flag
    h.halt("via env")
    assert flag.exists()
    assert HaltControl().is_halted() is True


def test_default_path_anchors_to_repo_root_not_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MAHORAGA_HALT_FLAG", raising=False)
    monkeypatch.chdir(tmp_path)  # a stray cwd must not move the kill-switch
    h = HaltControl()
    repo_root = Path(__file__).resolve().parents[4]
    assert h.flag_path == repo_root / "data" / "control" / "halt.flag"
    assert h.flag_path.is_absolute()
    assert tmp_path not in h.flag_path.parents


def test_flag_is_visible_to_a_second_process_view(tmp_path: Path) -> None:
    flag = tmp_path / "control" / "halt.flag"
    writer = HaltControl(flag_path=flag)
    writer.halt("catastrophic drawdown")
    # a separately-constructed control (different process) sees the same flag.
    reader = HaltControl(flag_path=flag)
    assert reader.is_halted() is True
    assert reader.reason() == "catastrophic drawdown"
