"""Tests for NewsShockProtocol — CRITICAL news trips the Layer-3 kill-switch."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from services.trader.news.classifier import Classification
from services.trader.news.shock import NewsShockProtocol, ShockAction
from services.trader.ops.halt import HaltControl


def _classification(level: str) -> Classification:
    return Classification(level=level, sentiment=0.0, impact=0.0, rationale="test")


def test_critical_trips_halt_and_tightens_stops(tmp_path: Path) -> None:
    halt = HaltControl(tmp_path / "halt.flag")
    protocol = NewsShockProtocol(halt)
    now = pd.Timestamp("2024-01-02T15:30:00Z")
    headline = "Fed announces emergency rate hike; markets halted"

    action = protocol.on_classified(_classification("CRITICAL"), headline, now)

    assert isinstance(action, ShockAction)
    assert action.halted is True
    assert action.tightened_stops is True
    assert action.hold_until == now + pd.Timedelta(minutes=10)
    assert headline in action.reason

    # Kill-switch integration: the isolated HaltControl is actually tripped.
    assert halt.is_halted() is True
    assert halt.reason() is not None
    assert headline in halt.reason()

    # /resume clears it — the Layer-3 kill-switch, not a new mechanism.
    halt.resume()
    assert halt.is_halted() is False


def test_background_is_a_noop(tmp_path: Path) -> None:
    halt = HaltControl(tmp_path / "halt.flag")
    protocol = NewsShockProtocol(halt)
    now = pd.Timestamp("2024-01-02T15:30:00Z")

    action = protocol.on_classified(_classification("BACKGROUND"), "company names new CFO", now)

    assert action.halted is False
    assert action.tightened_stops is False
    assert action.hold_until is None
    assert action.reason == "no shock"
    assert halt.is_halted() is False


def test_material_is_a_noop(tmp_path: Path) -> None:
    halt = HaltControl(tmp_path / "halt.flag")
    protocol = NewsShockProtocol(halt)
    now = pd.Timestamp("2024-01-02T15:30:00Z")

    action = protocol.on_classified(_classification("MATERIAL"), "earnings beat estimates", now)

    assert action.halted is False
    assert halt.is_halted() is False


def test_hold_minutes_is_configurable(tmp_path: Path) -> None:
    halt = HaltControl(tmp_path / "halt.flag")
    protocol = NewsShockProtocol(halt, hold_minutes=30)
    now = pd.Timestamp("2024-01-02T15:30:00Z")

    action = protocol.on_classified(_classification("CRITICAL"), "war breaks out", now)

    assert action.hold_until == now + pd.Timedelta(minutes=30)
