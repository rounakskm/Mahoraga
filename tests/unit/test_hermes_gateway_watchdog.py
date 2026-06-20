"""Unit tests for the Hermes gateway watchdog (Mitigation 1, ADR 2026-06-12).

The watchdog lives in scripts/ (not a package), so we load it by path.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

_WATCHDOG_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "hermes_gateway_watchdog.py"
)


def _load_watchdog():
    spec = importlib.util.spec_from_file_location("hermes_gateway_watchdog", _WATCHDOG_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


watchdog = _load_watchdog()


class _FakeResp:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.mark.parametrize("status,expected", [(200, True), (204, True), (500, False)])
def test_gateway_healthy_on_status(status: int, expected: bool) -> None:
    with mock.patch.object(watchdog.urllib.request, "urlopen", return_value=_FakeResp(status)):
        assert watchdog.gateway_healthy("http://x/health", timeout=1) is expected


def test_gateway_healthy_false_on_connection_error() -> None:
    with mock.patch.object(
        watchdog.urllib.request, "urlopen", side_effect=ConnectionError("refused")
    ):
        assert watchdog.gateway_healthy("http://x/health", timeout=1) is False


def test_restart_gateway_true_on_zero_exit() -> None:
    fake = SimpleNamespace(returncode=0, stderr="", stdout="")
    with mock.patch.object(watchdog.subprocess, "run", return_value=fake):
        assert watchdog.restart_gateway("nemoclaw foo gateway start") is True


def test_restart_gateway_false_on_nonzero_exit() -> None:
    fake = SimpleNamespace(returncode=1, stderr="boom", stdout="")
    with mock.patch.object(watchdog.subprocess, "run", return_value=fake):
        assert watchdog.restart_gateway("nemoclaw foo gateway start") is False


def test_restart_gateway_false_when_command_missing() -> None:
    with mock.patch.object(watchdog.subprocess, "run", side_effect=FileNotFoundError):
        assert watchdog.restart_gateway("does-not-exist") is False


def test_restart_gateway_false_on_timeout() -> None:
    with mock.patch.object(
        watchdog.subprocess, "run", side_effect=subprocess.TimeoutExpired("cmd", 180)
    ):
        assert watchdog.restart_gateway("slow-cmd") is False


def test_paused_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAHORAGA_WATCHDOG_PAUSED", raising=False)
    assert watchdog._paused() is False
    monkeypatch.setenv("MAHORAGA_WATCHDOG_PAUSED", "1")
    assert watchdog._paused() is True
    monkeypatch.setenv("MAHORAGA_WATCHDOG_PAUSED", "no")
    assert watchdog._paused() is False
