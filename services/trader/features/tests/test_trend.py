"""Trend-feature tests with hand-computed reference values."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.trader.features.tests.conftest import make_ctx, synthetic_ohlcv
from services.trader.features.trend import (
    ADX,
    EMA,
    MACD,
    SMA,
    MACDHist,
    MACDSignal,
    RegressionSlope,
)

# --- EMA / SMA ----------------------------------------------------------


class TestMovingAverages:
    def test_ema_matches_pandas_ewm(self) -> None:
        df = synthetic_ohlcv(bars=80)
        ctx = make_ctx(df)
        feature = EMA(span=20)
        out = feature.compute(ctx).reset_index(drop=True)
        expected = df["close"].astype("float64").reset_index(drop=True).ewm(span=20, adjust=False).mean()
        pd.testing.assert_series_equal(
            out, expected, check_names=False, atol=1e-9, rtol=0
        )
        assert feature.name == "ema_20"
        assert feature.category == "trend"

    def test_sma_matches_pandas_rolling(self) -> None:
        df = synthetic_ohlcv(bars=60)
        ctx = make_ctx(df)
        feature = SMA(window=20)
        out = feature.compute(ctx).reset_index(drop=True)
        close = df["close"].astype("float64").reset_index(drop=True)
        expected = close.rolling(window=20, min_periods=20).mean()
        pd.testing.assert_series_equal(
            out, expected, check_names=False, atol=1e-9, rtol=0
        )

    def test_sma_required_history_returns_window(self) -> None:
        assert SMA(window=20).required_history_bars() == 20
        assert SMA(window=50).required_history_bars() == 50

    def test_sma_first_window_minus_one_bars_are_null(self) -> None:
        df = synthetic_ohlcv(bars=30)
        ctx = make_ctx(df)
        feature = SMA(window=20)
        out = feature.compute(ctx).reset_index(drop=True)
        assert out.iloc[:19].isna().all()
        assert out.iloc[19:].notna().all()


# --- MACD ---------------------------------------------------------------


class TestMACD:
    def test_macd_line_equals_fast_ema_minus_slow_ema(self) -> None:
        df = synthetic_ohlcv(bars=100)
        ctx = make_ctx(df)
        macd = MACD(fast=12, slow=26).compute(ctx).reset_index(drop=True)
        c = df["close"].astype("float64").reset_index(drop=True)
        expected = (
            c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
        )
        pd.testing.assert_series_equal(macd, expected, check_names=False, atol=1e-9)

    def test_macd_signal_is_ema_of_macd(self) -> None:
        df = synthetic_ohlcv(bars=100)
        ctx = make_ctx(df)
        macd = MACD(fast=12, slow=26).compute(ctx).reset_index(drop=True)
        signal = MACDSignal(fast=12, slow=26, signal=9).compute(ctx).reset_index(drop=True)
        expected = macd.ewm(span=9, adjust=False).mean()
        pd.testing.assert_series_equal(signal, expected, check_names=False, atol=1e-9)

    def test_macd_hist_equals_macd_minus_signal(self) -> None:
        df = synthetic_ohlcv(bars=100)
        ctx = make_ctx(df)
        macd = MACD(fast=12, slow=26).compute(ctx).reset_index(drop=True)
        signal = MACDSignal(fast=12, slow=26, signal=9).compute(ctx).reset_index(drop=True)
        hist = MACDHist(fast=12, slow=26, signal=9).compute(ctx).reset_index(drop=True)
        pd.testing.assert_series_equal(hist, macd - signal, check_names=False, atol=1e-9)


# --- ADX ----------------------------------------------------------------


class TestADX:
    def test_adx_returns_finite_values_after_warmup(self) -> None:
        df = synthetic_ohlcv(bars=100)
        ctx = make_ctx(df)
        feature = ADX(window=14)
        out = feature.compute(ctx).reset_index(drop=True)
        # First 2*window-ish rows are NaN; tail values should be finite and ∈ [0, 100]
        tail = out.iloc[40:].dropna()
        assert len(tail) > 0
        assert (tail >= 0.0).all()
        assert (tail <= 100.0).all()

    def test_adx_required_history(self) -> None:
        assert ADX(window=14).required_history_bars() == 28


# --- Regression slope ---------------------------------------------------


class TestRegressionSlope:
    def test_constant_series_yields_zero_slope(self) -> None:
        # 25 bars of all-100 close: the regression slope of any 20-bar window is 0
        df = synthetic_ohlcv(bars=25)
        df = df.copy()
        df["close"] = 100.0
        ctx = make_ctx(df)
        out = RegressionSlope(window=20).compute(ctx).reset_index(drop=True)
        # First window-1 are NaN, rest are 0
        assert out.iloc[:19].isna().all()
        assert out.iloc[19:].abs().max() < 1e-9

    def test_linear_ramp_yields_unit_slope(self) -> None:
        df = synthetic_ohlcv(bars=25)
        df = df.copy()
        df["close"] = np.arange(25, dtype="float64")  # 0,1,2,...,24
        ctx = make_ctx(df)
        out = RegressionSlope(window=20).compute(ctx).reset_index(drop=True)
        # The slope of a perfect linear ramp is exactly 1.0 in every window
        assert out.iloc[19:].sub(1.0).abs().max() < 1e-9

    def test_required_history_equals_window(self) -> None:
        assert RegressionSlope(window=20).required_history_bars() == 20


# --- Cross-cutting -----------------------------------------------------


class TestSchemaContract:
    @pytest.mark.parametrize(
        "feature",
        [EMA(span=20), SMA(window=20), MACD(), MACDSignal(), MACDHist(),
         RegressionSlope(window=20), ADX(window=14)],
    )
    def test_compute_returns_same_length_as_input(self, feature) -> None:  # type: ignore[no-untyped-def]
        df = synthetic_ohlcv(bars=80)
        ctx = make_ctx(df)
        out = feature.compute(ctx)
        assert len(out) == len(df)
