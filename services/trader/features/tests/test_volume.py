"""Volume-feature tests with hand-computed reference values."""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.trader.features.tests.conftest import make_ctx, synthetic_ohlcv
from services.trader.features.volume import (
    CMF,
    MFI,
    OBV,
    DollarVolume,
    ForceIndex,
    VolumeSMA,
    VolumeZScore,
    VWAPDeviation,
)

# --- OBV ----------------------------------------------------------------


class TestOBV:
    def test_monotonic_uptrend_obv_equals_cum_volume(self) -> None:
        # Closes strictly increasing → every diff is +1 → direction +1 → OBV is cum volume
        df = synthetic_ohlcv(bars=10)
        df = df.copy()
        df["close"] = np.arange(100.0, 110.0, dtype="float64")
        df["volume"] = 1000
        ctx = make_ctx(df)
        obv = OBV().compute(ctx).reset_index(drop=True)
        # Bar 0: direction NaN → 0; bars 1..9 each add 1000
        expected = pd.Series(
            [0.0] + [1000.0 * i for i in range(1, 10)], dtype="float64"
        )
        pd.testing.assert_series_equal(obv, expected, check_names=False, atol=1e-9)

    def test_monotonic_downtrend_obv_decreases(self) -> None:
        df = synthetic_ohlcv(bars=10)
        df = df.copy()
        df["close"] = np.arange(110.0, 100.0, -1.0, dtype="float64")
        df["volume"] = 500
        ctx = make_ctx(df)
        obv = OBV().compute(ctx).reset_index(drop=True)
        expected = pd.Series(
            [0.0] + [-500.0 * i for i in range(1, 10)], dtype="float64"
        )
        pd.testing.assert_series_equal(obv, expected, check_names=False, atol=1e-9)

    def test_constant_close_obv_stays_zero(self) -> None:
        df = synthetic_ohlcv(bars=10)
        df = df.copy()
        df["close"] = 100.0
        df["volume"] = 1000
        ctx = make_ctx(df)
        obv = OBV().compute(ctx).reset_index(drop=True)
        assert (obv == 0.0).all()


# --- VWAP deviation ----------------------------------------------------


class TestVWAPDeviation:
    def test_constant_close_zero_deviation(self) -> None:
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["close"] = 100.0
        ctx = make_ctx(df)
        dev = VWAPDeviation(window=20).compute(ctx).reset_index(drop=True)
        assert (dev.iloc[19:].abs() < 1e-12).all()

    def test_against_hand_math(self) -> None:
        df = synthetic_ohlcv(bars=60)
        ctx = make_ctx(df)
        out = VWAPDeviation(window=20).compute(ctx).reset_index(drop=True)
        c = df["close"].astype("float64").reset_index(drop=True)
        v = df["volume"].astype("float64").reset_index(drop=True)
        pv = (c * v).rolling(window=20, min_periods=20).sum()
        tv = v.rolling(window=20, min_periods=20).sum()
        vwap = pv / tv
        expected = (c - vwap) / c
        pd.testing.assert_series_equal(out, expected, check_names=False, atol=1e-9)


# --- MFI ---------------------------------------------------------------


class TestMFI:
    def test_constant_typical_price_neutral(self) -> None:
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["high"] = 100.0
        df["low"] = 100.0
        df["close"] = 100.0
        df["volume"] = 1000
        ctx = make_ctx(df)
        mfi = MFI(window=14).compute(ctx).reset_index(drop=True)
        # No direction → both pos_sum and neg_sum are 0 → MFI = 50
        tail = mfi.iloc[15:].dropna()
        assert (tail == 50.0).all()

    def test_uptrend_typical_price_mfi_at_100(self) -> None:
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        # Strictly increasing typical price → only positive flows
        df["high"] = np.arange(100.0, 130.0, dtype="float64") + 1.0
        df["low"] = np.arange(100.0, 130.0, dtype="float64") - 1.0
        df["close"] = np.arange(100.0, 130.0, dtype="float64")
        df["volume"] = 1000
        ctx = make_ctx(df)
        mfi = MFI(window=14).compute(ctx).reset_index(drop=True)
        # No negative flow → MFI saturates at 100
        tail = mfi.iloc[15:].dropna()
        assert (tail == 100.0).all()

    def test_mfi_bounded(self) -> None:
        df = synthetic_ohlcv(bars=60)
        ctx = make_ctx(df)
        mfi = MFI(window=14).compute(ctx).dropna()
        assert (mfi >= 0.0).all()
        assert (mfi <= 100.0).all()


# --- Volume SMA / Z ----------------------------------------------------


class TestVolumeSMA:
    def test_constant_volume_equals_input(self) -> None:
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["volume"] = 1234
        ctx = make_ctx(df)
        sma = VolumeSMA(window=20).compute(ctx).reset_index(drop=True)
        assert (sma.iloc[19:] == 1234.0).all()


class TestVolumeZScore:
    def test_constant_volume_zero_after_warmup(self) -> None:
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["volume"] = 1000
        ctx = make_ctx(df)
        z = VolumeZScore(window=20).compute(ctx).reset_index(drop=True)
        # std=0 → division by NA → null
        assert z.iloc[19:].isna().all()

    def test_zscore_bounded_reasonably(self) -> None:
        df = synthetic_ohlcv(bars=60)
        ctx = make_ctx(df)
        z = VolumeZScore(window=20).compute(ctx).dropna()
        # Sanity: stdev z-score for synthetic noise should fit ±5σ
        assert (z.abs() < 5.0).all()


# --- Dollar volume -----------------------------------------------------


class TestDollarVolume:
    def test_against_hand_math(self) -> None:
        df = synthetic_ohlcv(bars=30)
        ctx = make_ctx(df)
        out = DollarVolume(window=20).compute(ctx).reset_index(drop=True)
        c = df["close"].astype("float64").reset_index(drop=True)
        v = df["volume"].astype("float64").reset_index(drop=True)
        expected = (c * v).rolling(window=20, min_periods=20).mean()
        pd.testing.assert_series_equal(out, expected, check_names=False, atol=1e-6)


# --- CMF ---------------------------------------------------------------


class TestCMF:
    def test_close_at_high_yields_positive_cmf(self) -> None:
        # close == high every bar → MF multiplier = +1 → CMF = +1
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["close"] = df["high"]
        ctx = make_ctx(df)
        cmf = CMF(window=20).compute(ctx).reset_index(drop=True)
        tail = cmf.iloc[19:]
        assert (tail >= 0.99).all()

    def test_close_at_low_yields_negative_cmf(self) -> None:
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["close"] = df["low"]
        ctx = make_ctx(df)
        cmf = CMF(window=20).compute(ctx).reset_index(drop=True)
        tail = cmf.iloc[19:]
        assert (tail <= -0.99).all()


# --- Force Index --------------------------------------------------------


class TestForceIndex:
    def test_constant_close_zero_force(self) -> None:
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["close"] = 100.0
        ctx = make_ctx(df)
        out = ForceIndex(window=13).compute(ctx).reset_index(drop=True)
        # close.diff() is 0 every bar → raw force = 0 → EMA = 0
        assert (out.fillna(0.0).abs() < 1e-9).all()

    def test_constant_uptrend_force_positive(self) -> None:
        df = synthetic_ohlcv(bars=30)
        df = df.copy()
        df["close"] = np.arange(100.0, 130.0, dtype="float64")
        df["volume"] = 1000
        ctx = make_ctx(df)
        out = ForceIndex(window=13).compute(ctx).reset_index(drop=True)
        # Every diff is +1, every volume is 1000 → raw is +1000 every bar
        # EMA converges to 1000
        assert out.iloc[15:].between(900.0, 1100.0).all()
