"""Integration test for the P2.1 Wall framework (wall contract + test doubles).

Builds a real `EvaluationContext` from the same Phase-1 fixture data
used by the backtest integration test (mocked HTTP + in-memory parquet),
then round-trips AlwaysPassWall and AlwaysFailWall through it to
confirm the contract holds end-to-end.

No new Postgres writes — the context is constructed directly from
fixture values. No new parquet files are created; the framework
itself has no side effects.

CI: runs in `integration-smoke` alongside Phase-1 chains.
Locally: `MAHORAGA_TEST_DSN` required (skipped if absent).
"""

from __future__ import annotations

import dataclasses
import os
from datetime import date

import pandas as pd
import pytest

from services.trader.backtest.base import FitnessReport, Strategy
from services.trader.walls import EvaluationContext, WallReport
from services.trader.walls.doubles import AlwaysFailWall, AlwaysPassWall

_TICKER = "SPY"
_BAR_DATES = pd.bdate_range(start="2026-01-05", periods=30, tz="UTC")
_START = date(2026, 1, 5)
_END = _BAR_DATES[-1].date()


# ---------------------------------------------------------------------------
# Skip if no Postgres (consistent with Phase-1 integration tests)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _require_dsn() -> None:
    if not os.environ.get("MAHORAGA_TEST_DSN"):
        pytest.skip("MAHORAGA_TEST_DSN not set; integration tests require Postgres")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubStrategy(Strategy):
    name = "stub_wall_framework"

    def generate_signals(self, *, feature_frame, regime_frame):
        return pd.DataFrame()


def _build_fitness() -> FitnessReport:
    return FitnessReport(
        strategy="stub_wall_framework",
        start=_START,
        end=_END,
        total_return=0.08,
        sharpe=0.95,
        max_drawdown=-0.06,
        num_trades=12,
        win_rate=0.58,
    )


def _build_returns() -> pd.Series:
    return pd.Series(
        [0.001 * (i % 3 - 1) for i in range(len(_BAR_DATES))],
        index=_BAR_DATES,
    )


def _build_feature_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sma_20": [float(100 + i) for i in range(len(_BAR_DATES))],
        },
        index=_BAR_DATES,
    )


def _build_regime_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scope": ["universe"] * len(_BAR_DATES),
            "asof": _BAR_DATES,
            "meso_label": ["trending_low_vol"] * len(_BAR_DATES),
            "meso_conf": [0.9] * len(_BAR_DATES),
            "composite_conf": [0.9] * len(_BAR_DATES),
        }
    )


def _ctx() -> EvaluationContext:
    return EvaluationContext(
        strategy=_StubStrategy(),
        backtest_result=_build_fitness(),
        returns=_build_returns(),
        feature_frame=_build_feature_frame(),
        regime_frame=_build_regime_frame(),
        universe=[_TICKER],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWallFrameworkContract:
    def test_always_pass_wall_returns_passed_true(self) -> None:
        ctx = _ctx()
        report = AlwaysPassWall().evaluate(ctx)
        assert isinstance(report, WallReport)
        assert report.passed is True
        assert report.score == 1.0

    def test_always_fail_wall_returns_passed_false(self) -> None:
        ctx = _ctx()
        report = AlwaysFailWall().evaluate(ctx)
        assert isinstance(report, WallReport)
        assert report.passed is False
        assert report.score == 0.0

    def test_wall_reports_are_frozen(self) -> None:
        ctx = _ctx()
        for wall in (AlwaysPassWall(), AlwaysFailWall()):
            report = wall.evaluate(ctx)
            with pytest.raises((dataclasses.FrozenInstanceError, TypeError)):
                report.passed = not report.passed  # type: ignore[misc]

    def test_wall_name_matches_class_var(self) -> None:
        for wall in (AlwaysPassWall(), AlwaysFailWall()):
            report = wall.evaluate(_ctx())
            assert report.wall_name == wall.name

    def test_evaluation_context_is_frozen(self) -> None:
        ctx = _ctx()
        with pytest.raises((dataclasses.FrozenInstanceError, TypeError)):
            ctx.universe = ["QQQ"]  # type: ignore[misc]

    def test_wall_report_sub_results_default_empty(self) -> None:
        report = AlwaysPassWall().evaluate(_ctx())
        assert report.sub_results == {}
        assert report.metadata == {}

    def test_fitness_report_fields_accessible_from_context(self) -> None:
        ctx = _ctx()
        assert ctx.backtest_result.sharpe == pytest.approx(0.95)
        assert ctx.backtest_result.max_drawdown == pytest.approx(-0.06)
        assert ctx.backtest_result.win_rate == pytest.approx(0.58)

    def test_returns_series_has_datetime_index(self) -> None:
        ctx = _ctx()
        assert isinstance(ctx.returns.index, pd.DatetimeIndex)
        assert len(ctx.returns) == len(_BAR_DATES)
