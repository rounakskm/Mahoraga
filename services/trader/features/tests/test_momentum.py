"""Momentum-feature tests with hand-computed reference values."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.trader.features.momentum import (
    ROC,
    RSI,
    Momentum,
    StochD,
    StochK,
    WilliamsR,
)
from services.trader.features.tests.conftest import make_ctx, synthetic_ohlcv

# --- RSI ----------------------------------------------------------------


class TestRSI:
    def test_strict_uptrend_rsi_at_100(self) -> None:
        # Monotonically increasing close: every bar is a gain, no losses
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["close"] = np.arange(100.0, 130.0, dtype="float64")
        ctx = make_ctx(df)
        rsi = RSI(window=14).compute(ctx).reset_index(drop=True)
        # RSI saturates at 100 because avg_loss == 0
        tail = rsi.iloc[15:].dropna()
        assert (tail == 100.0).all()

    def test_strict_downtrend_rsi_at_zero(self) -> None:
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["close"] = np.arange(130.0, 100.0, -1.0, dtype="float64")
        ctx = make_ctx(df)
        rsi = RSI(window=14).compute(ctx).reset_index(drop=True)
        # RSI lands at 0 because avg_gain == 0 (rs = 0 -> RSI = 100 - 100/(1+0) = 0)
        tail = rsi.iloc[15:].dropna()
        assert (tail == 0.0).all()

    def test_constant_close_rsi_neutral(self) -> None:
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["close"] = 100.0
        ctx = make_ctx(df)
        rsi = RSI(window=14).compute(ctx).reset_index(drop=True)
        # No gain, no loss → defined as 50
        tail = rsi.iloc[15:].dropna()
        assert (tail == 50.0).all()

    def test_rsi_bounded(self) -> None:
        df = synthetic_ohlcv(bars=80)
        ctx = make_ctx(df)
        rsi = RSI(window=14).compute(ctx).reset_index(drop=True)
        non_null = rsi.dropna()
        assert (non_null >= 0.0).all()
        assert (non_null <= 100.0).all()


# --- ROC ----------------------------------------------------------------


class TestROC:
    def test_roc_against_hand_computation(self) -> None:
        df = synthetic_ohlcv(bars=30)
        ctx = make_ctx(df)
        roc = ROC(window=10).compute(ctx).reset_index(drop=True)
        c = df["close"].astype("float64").reset_index(drop=True)
        expected = 100.0 * (c - c.shift(10)) / c.shift(10)
        pd.testing.assert_series_equal(roc, expected, check_names=False, atol=1e-9)

    def test_roc_first_window_is_null(self) -> None:
        df = synthetic_ohlcv(bars=20)
        ctx = make_ctx(df)
        roc = ROC(window=5).compute(ctx).reset_index(drop=True)
        assert roc.iloc[:5].isna().all()
        assert roc.iloc[5:].notna().all()

    def test_roc_constant_series_zero(self) -> None:
        df = synthetic_ohlcv(bars=15)
        df = df.copy()
        df["close"] = 100.0
        ctx = make_ctx(df)
        roc = ROC(window=5).compute(ctx).reset_index(drop=True)
        assert (roc.iloc[5:].abs() < 1e-12).all()


# --- Stochastic --------------------------------------------------------


class TestStochastic:
    def test_close_at_window_high_yields_100(self) -> None:
        # 14 bars: highs and closes are 100..113, lows are constant; close == highest_high
        df = synthetic_ohlcv(bars=14)
        df = df.copy()
        closes = np.arange(100.0, 114.0, dtype="float64")
        df["close"] = closes
        df["high"] = closes
        df["low"] = closes - 5.0
        ctx = make_ctx(df)
        k = StochK(window=14).compute(ctx).reset_index(drop=True)
        # Last bar: close 113 == highest_high 113; lowest_low = 95.
        # %K = 100 * (113 - 95) / (113 - 95) = 100.0
        assert k.iloc[13] == pytest.approx(100.0)

    def test_close_at_window_low_yields_zero(self) -> None:
        df = synthetic_ohlcv(bars=14)
        df = df.copy()
        closes = np.arange(100.0, 86.0, -1.0, dtype="float64")
        df["close"] = closes
        df["high"] = closes + 5.0
        df["low"] = closes
        ctx = make_ctx(df)
        k = StochK(window=14).compute(ctx).reset_index(drop=True)
        # %K = 100 * (87 - 87) / (105 - 87) = 0.0
        assert k.iloc[13] == pytest.approx(0.0)

    def test_d_is_3bar_sma_of_k(self) -> None:
        df = synthetic_ohlcv(bars=40)
        ctx = make_ctx(df)
        k = StochK(window=14).compute(ctx).reset_index(drop=True)
        d = StochD(window=14, d_window=3).compute(ctx).reset_index(drop=True)
        expected = k.rolling(window=3, min_periods=3).mean()
        pd.testing.assert_series_equal(d, expected, check_names=False, atol=1e-9)


# --- Williams %R --------------------------------------------------------


class TestWilliamsR:
    def test_close_at_high_yields_zero(self) -> None:
        df = synthetic_ohlcv(bars=14)
        df = df.copy()
        closes = np.arange(100.0, 114.0, dtype="float64")
        df["close"] = closes
        df["high"] = closes
        df["low"] = closes - 5.0
        ctx = make_ctx(df)
        wr = WilliamsR(window=14).compute(ctx).reset_index(drop=True)
        # close == highest -> %R = 0
        assert wr.iloc[13] == pytest.approx(0.0)

    def test_close_at_low_yields_minus_100(self) -> None:
        df = synthetic_ohlcv(bars=14)
        df = df.copy()
        closes = np.arange(100.0, 86.0, -1.0, dtype="float64")
        df["close"] = closes
        df["high"] = closes + 5.0
        df["low"] = closes
        ctx = make_ctx(df)
        wr = WilliamsR(window=14).compute(ctx).reset_index(drop=True)
        # close == lowest -> %R = -100
        assert wr.iloc[13] == pytest.approx(-100.0)

    def test_williams_r_bounded(self) -> None:
        df = synthetic_ohlcv(bars=60)
        ctx = make_ctx(df)
        wr = WilliamsR(window=14).compute(ctx).dropna()
        assert (wr >= -100.0).all()
        assert (wr <= 0.0).all()


# --- Momentum (absolute close diff) -------------------------------------


class TestMomentum:
    def test_against_hand_computation(self) -> None:
        df = synthetic_ohlcv(bars=30)
        ctx = make_ctx(df)
        m = Momentum(window=10).compute(ctx).reset_index(drop=True)
        c = df["close"].astype("float64").reset_index(drop=True)
        expected = c - c.shift(10)
        pd.testing.assert_series_equal(m, expected, check_names=False, atol=1e-9)

    def test_constant_series_zero(self) -> None:
        df = synthetic_ohlcv(bars=15)
        df = df.copy()
        df["close"] = 100.0
        ctx = make_ctx(df)
        m = Momentum(window=5).compute(ctx).reset_index(drop=True)
        assert (m.iloc[5:].abs() < 1e-12).all()
