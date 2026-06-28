"""Unit tests for Wall ABC, WallReport, EvaluationContext, and test doubles.

All tests are pure-Python — no Postgres, no parquet.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pandas as pd
import pytest

from services.trader.backtest.base import FitnessReport, Strategy
from services.trader.walls import EvaluationContext, Wall, WallReport
from services.trader.walls.doubles import AlwaysFailWall, AlwaysPassWall

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _StubStrategy(Strategy):
    name = "stub"

    def generate_signals(self, *, feature_frame, regime_frame):
        return pd.DataFrame()


def _stub_fitness() -> FitnessReport:
    return FitnessReport(
        strategy="stub",
        start=date(2020, 1, 1),
        end=date(2020, 12, 31),
        total_return=0.10,
        sharpe=1.2,
        max_drawdown=-0.05,
        num_trades=50,
        win_rate=0.54,
    )


def _stub_ctx() -> EvaluationContext:
    returns = pd.Series(
        [0.001, -0.002, 0.003],
        index=pd.date_range("2020-01-02", periods=3),
    )
    return EvaluationContext(
        strategy=_StubStrategy(),
        backtest_result=_stub_fitness(),
        returns=returns,
        universe=["SPY"],
    )


# ---------------------------------------------------------------------------
# WallReport
# ---------------------------------------------------------------------------


def test_wall_report_frozen():
    report = WallReport(wall_name="x", passed=True, score=0.9, reason="ok")
    with pytest.raises((dataclasses.FrozenInstanceError, TypeError)):
        report.passed = False  # type: ignore[misc]


def test_wall_report_defaults():
    report = WallReport(wall_name="x", passed=True, score=0.5, reason="ok")
    assert report.sub_results == {}
    assert report.metadata == {}


# ---------------------------------------------------------------------------
# EvaluationContext
# ---------------------------------------------------------------------------


def test_evaluation_context_frozen():
    ctx = _stub_ctx()
    with pytest.raises((dataclasses.FrozenInstanceError, TypeError)):
        ctx.universe = ["QQQ"]  # type: ignore[misc]


def test_evaluation_context_metadata_defaults_empty():
    ctx = _stub_ctx()
    assert ctx.metadata == {}


# ---------------------------------------------------------------------------
# Wall ABC
# ---------------------------------------------------------------------------


def test_wall_abc_requires_evaluate():
    class _NoEvaluate(Wall):
        name = "no_evaluate"

    with pytest.raises(TypeError):
        _NoEvaluate()


def test_wall_abc_requires_name_classvar():
    # name is a ClassVar — subclasses that set it are fine; we just
    # verify the ABC itself doesn't define a concrete evaluate().
    class _GoodWall(Wall):
        name = "good"

        def evaluate(self, ctx):
            return WallReport(wall_name=self.name, passed=True, score=1.0, reason="")

    w = _GoodWall()
    report = w.evaluate(_stub_ctx())
    assert report.wall_name == "good"


# ---------------------------------------------------------------------------
# AlwaysPassWall
# ---------------------------------------------------------------------------


def test_always_pass_wall_passes():
    ctx = _stub_ctx()
    report = AlwaysPassWall().evaluate(ctx)
    assert report.passed is True


def test_always_pass_wall_score():
    report = AlwaysPassWall().evaluate(_stub_ctx())
    assert report.score == 1.0


def test_always_pass_wall_name():
    w = AlwaysPassWall()
    report = w.evaluate(_stub_ctx())
    assert report.wall_name == w.name == "always_pass"


# ---------------------------------------------------------------------------
# AlwaysFailWall
# ---------------------------------------------------------------------------


def test_always_fail_wall_fails():
    ctx = _stub_ctx()
    report = AlwaysFailWall().evaluate(ctx)
    assert report.passed is False


def test_always_fail_wall_score():
    report = AlwaysFailWall().evaluate(_stub_ctx())
    assert report.score == 0.0


def test_always_fail_wall_name():
    w = AlwaysFailWall()
    report = w.evaluate(_stub_ctx())
    assert report.wall_name == w.name == "always_fail"


# ---------------------------------------------------------------------------
# WallReport is returned (not mutated by Wall)
# ---------------------------------------------------------------------------


def test_doubles_return_frozen_report():
    ctx = _stub_ctx()
    for wall in (AlwaysPassWall(), AlwaysFailWall()):
        report = wall.evaluate(ctx)
        with pytest.raises((dataclasses.FrozenInstanceError, TypeError)):
            report.passed = not report.passed  # type: ignore[misc]
