"""Statistical-feature tests with hand-computed reference values."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.trader.features.statistical import (
    Autocorrelation,
    Hurst,
    Kurt,
    RollingMax,
    RollingMin,
    Skew,
    ZScore,
)
from services.trader.features.tests.conftest import make_ctx, synthetic_ohlcv

# --- Hurst -------------------------------------------------------------


class TestHurst:
    def test_random_walk_hurst_near_half(self) -> None:
        # A random-walk price series has Hurst ≈ 0.5
        rng = np.random.default_rng(7)
        n = 250
        log_returns = rng.normal(0.0, 0.01, size=n)
        log_prices = np.log(100.0) + log_returns.cumsum()
        prices = np.exp(log_prices)
        df = synthetic_ohlcv(bars=n)
        df = df.copy()
        df["close"] = prices
        ctx = make_ctx(df)
        # Use a 120-bar window; tolerate ±0.2 around 0.5 (Hurst R/S is noisy at this length)
        out = Hurst(window=120).compute(ctx).dropna()
        assert len(out) > 0
        median = float(out.median())
        assert 0.3 <= median <= 0.7, f"random-walk Hurst median {median:.3f} far from 0.5"

    def test_short_series_returns_nan(self) -> None:
        df = synthetic_ohlcv(bars=20)
        ctx = make_ctx(df)
        # 60-bar window on 20 bars → all NaN
        out = Hurst(window=60).compute(ctx).reset_index(drop=True)
        assert out.isna().all()


# --- Autocorrelation ---------------------------------------------------


class TestAutocorrelation:
    def test_constant_return_series_returns_nan(self) -> None:
        # Constant close → zero-stdev returns → undefined autocorr → NaN
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["close"] = 100.0
        ctx = make_ctx(df)
        out = Autocorrelation(lag=1, window=20).compute(ctx).reset_index(drop=True)
        assert out.iloc[20:].isna().all()

    def test_autocorr_bounded(self) -> None:
        df = synthetic_ohlcv(bars=80)
        ctx = make_ctx(df)
        out = Autocorrelation(lag=1, window=20).compute(ctx).dropna()
        assert (out >= -1.0).all()
        assert (out <= 1.0).all()


# --- Skew / Kurt --------------------------------------------------------


class TestSkewKurt:
    def test_skew_kurt_on_constant_close(self) -> None:
        df = synthetic_ohlcv(bars=80)
        df = df.copy()
        df["close"] = 100.0
        ctx = make_ctx(df)
        skew = Skew(window=60).compute(ctx).reset_index(drop=True)
        kurt = Kurt(window=60).compute(ctx).reset_index(drop=True)
        # Constant close -> returns are 0 -> sample skewness is 0 by definition.
        assert skew.iloc[61:].isna().all() or (skew.iloc[61:].abs() < 1e-9).all()
        # Fisher excess kurtosis of a zero-variance series is -3 per pandas'
        # documented convention (rolling().kurt() formula). We accept that
        # AND the historically-expected NaN, so we don't tie to a pandas
        # version's exact corner-case handling.
        non_null = kurt.iloc[61:].dropna()
        if len(non_null) > 0:
            assert ((non_null.abs() < 1e-9) | (non_null == pytest.approx(-3.0, abs=1e-9))).all()

    def test_skew_matches_pandas(self) -> None:
        df = synthetic_ohlcv(bars=120)
        ctx = make_ctx(df)
        out = Skew(window=60).compute(ctx).reset_index(drop=True)
        returns = df["close"].astype("float64").reset_index(drop=True).pct_change()
        expected = returns.rolling(window=60, min_periods=60).skew()
        pd.testing.assert_series_equal(out, expected, check_names=False, atol=1e-9)


# --- Z-score ----------------------------------------------------------


class TestZScore:
    def test_constant_series_undefined(self) -> None:
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["close"] = 100.0
        ctx = make_ctx(df)
        z = ZScore(window=20).compute(ctx).reset_index(drop=True)
        # std=0 → divide by NA → null
        assert z.iloc[19:].isna().all()

    def test_against_hand_math(self) -> None:
        df = synthetic_ohlcv(bars=60)
        ctx = make_ctx(df)
        out = ZScore(window=20).compute(ctx).reset_index(drop=True)
        c = df["close"].astype("float64").reset_index(drop=True)
        mean = c.rolling(window=20, min_periods=20).mean()
        std = c.rolling(window=20, min_periods=20).std(ddof=0)
        expected = (c - mean) / std
        pd.testing.assert_series_equal(out, expected, check_names=False, atol=1e-9)


# --- Rolling min / max ------------------------------------------------


class TestMinMax:
    def test_monotonic_uptrend_min_equals_first_max_equals_last(self) -> None:
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["close"] = np.arange(100.0, 130.0, dtype="float64")
        ctx = make_ctx(df)
        rmin = RollingMin(window=10).compute(ctx).reset_index(drop=True)
        rmax = RollingMax(window=10).compute(ctx).reset_index(drop=True)
        # At bar 9 the window covers 100..109; bar 29 covers 120..129
        assert rmin.iloc[9] == pytest.approx(100.0)
        assert rmax.iloc[9] == pytest.approx(109.0)
        assert rmin.iloc[29] == pytest.approx(120.0)
        assert rmax.iloc[29] == pytest.approx(129.0)
