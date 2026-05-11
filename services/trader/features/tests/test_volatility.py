"""Volatility-feature tests with hand-computed reference values."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.trader.features.tests.conftest import make_ctx, synthetic_ohlcv
from services.trader.features.volatility import (
    ATR,
    BBLower,
    BBMiddle,
    BBUpper,
    BBWidth,
    GarmanKlass,
    Parkinson,
    RealizedVol,
    RealizedVolPercentile,
)

# --- ATR ---------------------------------------------------------------


class TestATR:
    def test_constant_high_low_close_atr_constant(self) -> None:
        # If high=low=close every bar, true range = 0 → ATR = 0
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["high"] = 100.0
        df["low"] = 100.0
        df["close"] = 100.0
        ctx = make_ctx(df)
        atr = ATR(window=14).compute(ctx).reset_index(drop=True)
        assert (atr.iloc[15:].abs() < 1e-9).all()

    def test_atr_against_pandas_ewm(self) -> None:
        df = synthetic_ohlcv(bars=80)
        ctx = make_ctx(df)
        atr = ATR(window=14).compute(ctx).reset_index(drop=True)
        # Reconstruct via the same formula
        high = df["high"].astype("float64").reset_index(drop=True)
        low = df["low"].astype("float64").reset_index(drop=True)
        close = df["close"].astype("float64").reset_index(drop=True)
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        expected = tr.ewm(alpha=1.0 / 14.0, adjust=False).mean()
        pd.testing.assert_series_equal(atr, expected, check_names=False, atol=1e-9)


# --- Bollinger Bands ---------------------------------------------------


class TestBollinger:
    def test_middle_equals_sma(self) -> None:
        df = synthetic_ohlcv(bars=40)
        ctx = make_ctx(df)
        middle = BBMiddle(window=20).compute(ctx).reset_index(drop=True)
        expected = (
            df["close"].astype("float64").reset_index(drop=True)
            .rolling(window=20, min_periods=20).mean()
        )
        pd.testing.assert_series_equal(middle, expected, check_names=False, atol=1e-9)

    def test_upper_lower_symmetric_around_middle(self) -> None:
        df = synthetic_ohlcv(bars=60)
        ctx = make_ctx(df)
        upper = BBUpper(window=20).compute(ctx).reset_index(drop=True)
        middle = BBMiddle(window=20).compute(ctx).reset_index(drop=True)
        lower = BBLower(window=20).compute(ctx).reset_index(drop=True)
        # upper - middle == middle - lower (within float)
        pd.testing.assert_series_equal(
            upper - middle, middle - lower, check_names=False, atol=1e-9
        )

    def test_bb_width_relative(self) -> None:
        df = synthetic_ohlcv(bars=60)
        ctx = make_ctx(df)
        upper = BBUpper(window=20).compute(ctx).reset_index(drop=True)
        middle = BBMiddle(window=20).compute(ctx).reset_index(drop=True)
        lower = BBLower(window=20).compute(ctx).reset_index(drop=True)
        width = BBWidth(window=20).compute(ctx).reset_index(drop=True)
        expected = (upper - lower) / middle
        pd.testing.assert_series_equal(width, expected, check_names=False, atol=1e-9)

    def test_constant_close_bands_collapse(self) -> None:
        df = synthetic_ohlcv(bars=40)
        df = df.copy()
        df["close"] = 100.0
        ctx = make_ctx(df)
        upper = BBUpper(window=20).compute(ctx).reset_index(drop=True)
        lower = BBLower(window=20).compute(ctx).reset_index(drop=True)
        # std=0 → upper=middle=lower, so upper-lower≈0
        diff = upper - lower
        assert diff.iloc[19:].abs().max() < 1e-9


# --- Realized vol ------------------------------------------------------


class TestRealizedVol:
    def test_constant_close_zero_vol(self) -> None:
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["close"] = 100.0
        ctx = make_ctx(df)
        rv = RealizedVol(window=20).compute(ctx).reset_index(drop=True)
        assert (rv.iloc[20:].abs() < 1e-9).all()

    def test_log_return_stdev_annualized(self) -> None:
        df = synthetic_ohlcv(bars=80)
        ctx = make_ctx(df)
        rv = RealizedVol(window=20).compute(ctx).reset_index(drop=True)
        c = df["close"].astype("float64").reset_index(drop=True)
        log_ret = np.log(c / c.shift(1))
        expected = log_ret.rolling(window=20, min_periods=20).std(ddof=0) * np.sqrt(252)
        pd.testing.assert_series_equal(rv, expected, check_names=False, atol=1e-9)

    def test_percentile_bounded_in_0_100(self) -> None:
        # Need a long series for the lookback
        df = synthetic_ohlcv(bars=400)
        ctx = make_ctx(df)
        pct = RealizedVolPercentile(window=60, lookback=252).compute(ctx).dropna()
        assert (pct >= 0.0).all()
        assert (pct <= 100.0).all()


# --- Parkinson ---------------------------------------------------------


class TestParkinson:
    def test_constant_high_low_zero_vol(self) -> None:
        df = synthetic_ohlcv(bars=40)
        df = df.copy()
        df["high"] = 100.0
        df["low"] = 100.0
        ctx = make_ctx(df)
        pk = Parkinson(window=20).compute(ctx).reset_index(drop=True)
        # ln(H/L) = ln(1) = 0 → squared = 0 → vol = 0
        assert (pk.iloc[19:].abs() < 1e-9).all()

    def test_parkinson_factor(self) -> None:
        df = synthetic_ohlcv(bars=40)
        df = df.copy()
        # Make every bar have H/L = e^0.1 → ln(H/L) = 0.1, squared = 0.01
        df["high"] = 110.5170918  # 100 * e^0.1
        df["low"] = 100.0
        ctx = make_ctx(df)
        pk = Parkinson(window=20).compute(ctx).reset_index(drop=True)
        # rolling mean = 0.01; factor = 1/(4 ln 2); annualized × sqrt(252)
        expected = np.sqrt(0.01 / (4.0 * np.log(2.0)) * 252.0)
        # Tolerate the rounding in 110.5170918
        assert pk.iloc[19] == pytest.approx(expected, abs=5e-3)


# --- Garman-Klass -----------------------------------------------------


class TestGarmanKlass:
    def test_constant_ohlc_zero_vol(self) -> None:
        df = synthetic_ohlcv(bars=40)
        df = df.copy()
        df["open"] = 100.0
        df["high"] = 100.0
        df["low"] = 100.0
        df["close"] = 100.0
        ctx = make_ctx(df)
        gk = GarmanKlass(window=20).compute(ctx).reset_index(drop=True)
        assert (gk.iloc[19:].abs() < 1e-9).all()
