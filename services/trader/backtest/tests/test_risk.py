"""Tests for the hard-limit firewall stub (P1.6 B2)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from services.trader.backtest.risk import (
    catastrophic_drawdown_halt,
    clip_positions,
    clip_sectors,
    halt_daily_loss,
    halt_low_confidence,
)


def _wide_weights(rows: list[dict[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        index=pd.to_datetime(
            [f"2026-01-{i + 5:02d}" for i in range(len(rows))], utc=True
        ),
    )


class TestClipPositions:
    def test_clip_to_5pct(self) -> None:
        weights = _wide_weights(
            [
                {"SPY": 0.10, "QQQ": -0.20, "IWM": 0.03},
                {"SPY": 0.04, "QQQ": 0.30, "IWM": -0.07},
            ]
        )
        clipped = clip_positions(weights)
        expected = _wide_weights(
            [
                {"SPY": 0.05, "QQQ": -0.05, "IWM": 0.03},
                {"SPY": 0.04, "QQQ": 0.05, "IWM": -0.05},
            ]
        )
        pd.testing.assert_frame_equal(clipped, expected, check_names=False)

    def test_clip_empty_returns_empty(self) -> None:
        assert clip_positions(pd.DataFrame()).empty

    def test_custom_threshold(self) -> None:
        weights = _wide_weights([{"SPY": 0.5}])
        clipped = clip_positions(weights, max_per_position=0.10)
        assert clipped.iloc[0]["SPY"] == 0.10


class TestClipSectors:
    def test_overweight_sector_scaled_down(self) -> None:
        # Two tickers in same sector, aggregate 0.30 > 0.20 cap
        weights = _wide_weights(
            [{"AAPL": 0.20, "MSFT": 0.10}]
        )
        sector_map = {"AAPL": "tech", "MSFT": "tech"}
        out = clip_sectors(weights, sector_map=sector_map)
        # Sum should be exactly 0.20 (sign preserved, proportional scale)
        assert abs(out.iloc[0].sum() - 0.20) < 1e-12
        # Ratios preserved
        assert abs(out.iloc[0]["AAPL"] / out.iloc[0]["MSFT"] - 2.0) < 1e-12

    def test_under_cap_unchanged(self) -> None:
        weights = _wide_weights([{"AAPL": 0.05, "MSFT": 0.05}])
        out = clip_sectors(weights, sector_map={"AAPL": "tech", "MSFT": "tech"})
        pd.testing.assert_frame_equal(out, weights, check_names=False)

    def test_default_sector_unknown(self) -> None:
        # No sector_map → everything maps to "unknown"; cap applies to total
        weights = _wide_weights([{"SPY": 0.15, "QQQ": 0.20}])  # sum 0.35
        out = clip_sectors(weights)
        assert abs(out.iloc[0].sum() - 0.20) < 1e-12

    def test_negative_aggregate_scaled(self) -> None:
        weights = _wide_weights([{"SPY": -0.30, "QQQ": -0.10}])  # sum -0.40
        out = clip_sectors(weights, sector_map={"SPY": "x", "QQQ": "x"})
        # Magnitude clipped to 0.20, sign preserved
        assert abs(out.iloc[0].sum() + 0.20) < 1e-12


class TestHaltLowConfidence:
    def test_high_confidence_no_halt(self) -> None:
        regime = pd.DataFrame(
            {
                "asof": pd.to_datetime(["2026-01-05", "2026-01-06"], utc=True),
                "composite_conf": [0.8, 0.6],
            }
        )
        halts = halt_low_confidence(regime)
        assert not halts.any()

    def test_low_confidence_halts(self) -> None:
        regime = pd.DataFrame(
            {
                "asof": pd.to_datetime(
                    ["2026-01-05", "2026-01-06", "2026-01-07"], utc=True
                ),
                "composite_conf": [0.30, 0.50, 0.20],
            }
        )
        halts = halt_low_confidence(regime)
        assert list(halts.values) == [True, False, True]


class TestHaltDailyLoss:
    def test_breach_triggers_next_day_halt(self) -> None:
        # Day-0 return -3% (breach), day-1 should be halted
        returns = pd.Series(
            [-0.03, 0.01, 0.005],
            index=pd.to_datetime(
                ["2026-01-05", "2026-01-06", "2026-01-07"], utc=True
            ),
        )
        halts = halt_daily_loss(returns)
        assert list(halts.values) == [False, True, False]

    def test_no_breach_no_halt(self) -> None:
        returns = pd.Series(
            [0.01, 0.01, -0.005],
            index=pd.to_datetime(
                ["2026-01-05", "2026-01-06", "2026-01-07"], utc=True
            ),
        )
        halts = halt_daily_loss(returns)
        assert not halts.any()

    def test_first_day_never_halted(self) -> None:
        returns = pd.Series(
            [-0.05],
            index=pd.to_datetime(["2026-01-05"], utc=True),
        )
        halts = halt_daily_loss(returns)
        assert halts.iloc[0] is False or halts.iloc[0] == False  # noqa: E712


class TestCatastrophicDrawdown:
    def test_no_drawdown_returns_none(self) -> None:
        equity = pd.Series(
            [1.0, 1.05, 1.10, 1.15],
            index=pd.to_datetime(
                ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"],
                utc=True,
            ),
        )
        assert catastrophic_drawdown_halt(equity) is None

    def test_drawdown_breach_returns_first_breach(self) -> None:
        # Peak at 1.10, drops to 0.95 (-13.6% drawdown)
        equity = pd.Series(
            [1.00, 1.10, 1.05, 0.95],
            index=pd.to_datetime(
                ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"],
                utc=True,
            ),
        )
        result = catastrophic_drawdown_halt(equity)
        assert result == datetime.fromisoformat("2026-01-08T00:00:00+00:00")

    def test_empty_returns_none(self) -> None:
        assert catastrophic_drawdown_halt(pd.Series(dtype="float64")) is None

    def test_threshold_inclusive(self) -> None:
        equity = pd.Series(
            [1.0, 1.0, 0.90],  # exactly -10%
            index=pd.to_datetime(
                ["2026-01-05", "2026-01-06", "2026-01-07"], utc=True
            ),
        )
        # exactly -0.10 ≤ -0.10 → breach
        assert catastrophic_drawdown_halt(equity) is not None


class TestRiskHelpersEmpty:
    def test_halt_low_conf_empty(self) -> None:
        assert halt_low_confidence(pd.DataFrame()).empty

    def test_halt_daily_loss_empty(self) -> None:
        assert halt_daily_loss(pd.Series(dtype="float64")).empty


class TestClipSectorsValidation:
    def test_empty_input(self) -> None:
        assert clip_sectors(pd.DataFrame()).empty

    def test_zero_aggregate_unchanged(self) -> None:
        # Long + short cancel; aggregate 0 < cap, no scaling
        weights = _wide_weights([{"AAPL": 0.10, "MSFT": -0.10}])
        out = clip_sectors(weights, sector_map={"AAPL": "tech", "MSFT": "tech"})
        pd.testing.assert_frame_equal(out, weights, check_names=False)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
