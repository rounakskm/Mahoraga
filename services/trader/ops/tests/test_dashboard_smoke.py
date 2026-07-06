"""Smoke tests for the ops dashboard shell (`scripts/dashboard.py`, Phase-6 Task 6).

The dashboard module must be importable WITHOUT streamlit installed — the
`import streamlit` lives lazily inside `main()`. To pin that contract, these
tests load the module by file path (scripts/ is not a package; same pattern as
`tests/unit/test_hermes_gateway_watchdog.py`) with a `sys.modules` blocker that
makes any module-level `import streamlit` raise immediately.

The pure builders (`build_panels`, `attribution_tables`) are exercised fully
offline: no DSN, no broker, no Hindsight, no SPY parquet — every panel must
return its typed-empty shape, never an `{"error": ...}` entry. Panel isolation
is pinned separately: one raising panel yields exactly one error entry and
leaves every other panel intact.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd

from services.trader.ops.attribution import AttributionReport
from services.trader.ops.dashboard_data import DashboardData
from services.trader.ops.halt import HaltControl

_DASHBOARD_PATH = Path(__file__).resolve().parents[4] / "scripts" / "dashboard.py"

_PANEL_KEYS = {"halt", "regime", "positions", "orders", "pnl", "fleet", "kb", "attribution"}


def _load_dashboard() -> ModuleType:
    """Load scripts/dashboard.py by path with streamlit import BLOCKED.

    Setting ``sys.modules["streamlit"] = None`` makes any ``import streamlit``
    raise ImportError, so a non-lazy import at module level fails this load —
    the smoke test proves streamlit stays inside `main()`.
    """
    blocked = "streamlit" not in sys.modules
    if blocked:
        sys.modules["streamlit"] = None  # type: ignore[assignment]
    try:
        spec = importlib.util.spec_from_file_location("mahoraga_dashboard", _DASHBOARD_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if blocked:
            del sys.modules["streamlit"]
    return module


dashboard = _load_dashboard()


def _offline_data(tmp_path: Path) -> DashboardData:
    """A fully-offline DashboardData, isolated from any live repo state
    (halt flag in tmp, no SPY parquet dir) so panel shapes are deterministic."""
    data = DashboardData(halt=HaltControl(tmp_path / "halt.flag"))
    data._spy_parquet_dir = tmp_path / "no-parquet"
    return data


def test_module_loads_without_streamlit() -> None:
    """The by-path load above succeeded with streamlit blocked; the pure
    builders and the (unexecuted) app entrypoint are all present."""
    assert callable(dashboard.build_panels)
    assert callable(dashboard.attribution_tables)
    assert callable(dashboard.main)


def test_build_panels_offline_returns_all_typed_empty(tmp_path: Path) -> None:
    panels = dashboard.build_panels(_offline_data(tmp_path))

    assert set(panels) == _PANEL_KEYS
    for name, panel in panels.items():
        assert not (isinstance(panel, dict) and "error" in panel), f"panel {name!r} errored"

    assert panels["halt"] == {"halted": False, "reason": None}
    assert panels["regime"] == {}
    assert panels["kb"] == []
    assert isinstance(panels["attribution"], AttributionReport)
    assert panels["attribution"].n_round_trips == 0
    for frame_key in ("positions", "orders", "pnl", "fleet"):
        frame = panels[frame_key]
        assert isinstance(frame, pd.DataFrame), frame_key
        assert frame.empty, frame_key
        assert list(frame.columns), frame_key  # typed-empty: named columns survive


def test_attribution_tables_empty_report() -> None:
    tables = dashboard.attribution_tables(AttributionReport())

    assert set(tables) == {"by_regime", "by_ticker", "by_side", "by_holding_period"}
    for name, frame in tables.items():
        assert isinstance(frame, pd.DataFrame), name
        assert frame.empty, name


def test_kill_switch_visible_within_one_second(tmp_path: Path) -> None:
    """halt() -> is_halted() flips within the same second — pins (trivially)
    the <10s kill-switch contract at the dashboard's control primitive."""
    control = HaltControl(tmp_path / "f")
    start = time.monotonic()
    control.halt("x")
    assert control.is_halted()
    assert time.monotonic() - start < 1.0
    assert control.reason() == "x"


def test_one_failing_panel_never_blanks_the_page(tmp_path: Path) -> None:
    class BrokenPositions(DashboardData):
        def positions(self, rows: list[dict[str, Any]] | None = None) -> pd.DataFrame:
            raise RuntimeError("boom")

    data = BrokenPositions(halt=HaltControl(tmp_path / "halt.flag"))
    data._spy_parquet_dir = tmp_path / "no-parquet"

    panels = dashboard.build_panels(data)

    assert panels["positions"] == {"error": "boom"}
    for name in _PANEL_KEYS - {"positions"}:
        panel = panels[name]
        assert not (isinstance(panel, dict) and "error" in panel), f"panel {name!r} errored"
