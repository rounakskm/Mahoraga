"""MICRO momentum + volume-surge feature tests.

Covers `RocFeature` (fractional rate-of-change via `close.pct_change`) and
`VolumeSurgeFeature` (volume over its rolling mean), including PIT safety:
altering bars after index `i` must not change the value at `i`.
"""

from __future__ import annotations

import pandas as pd

from services.trader.features.micro import (
    RocFeature,
    VolumeSurgeFeature,
)
from services.trader.features.tests.conftest import make_ctx, synthetic_ohlcv

# --- RocFeature ---------------------------------------------------------


class TestRocFeature:
    def test_name_and_metadata(self) -> None:
        feat = RocFeature(5)
        assert feat.name == "roc_5"
        assert feat.category == "momentum"
        assert feat.placeholder is False
        assert feat.required_history_bars() == 5

    def test_equals_close_pct_change(self) -> None:
        df = synthetic_ohlcv(bars=40)
        ctx = make_ctx(df)
        roc = RocFeature(5).compute(ctx).reset_index(drop=True)
        expected = df["close"].astype("float64").reset_index(drop=True).pct_change(5)
        pd.testing.assert_series_equal(roc, expected, check_names=False, atol=1e-12)

    def test_warmup_is_nan_only(self) -> None:
        df = synthetic_ohlcv(bars=20)
        ctx = make_ctx(df)
        roc = RocFeature(5).compute(ctx).reset_index(drop=True)
        assert roc.iloc[:5].isna().all()
        assert roc.iloc[5:].notna().all()

    def test_aligned_to_frame_index(self) -> None:
        df = synthetic_ohlcv(bars=30)
        ctx = make_ctx(df)
        roc = RocFeature(3).compute(ctx)
        assert list(roc.index) == list(ctx.frame.index)

    def test_pit_safe_future_bars_do_not_change_past(self) -> None:
        df = synthetic_ohlcv(bars=40)
        ctx = make_ctx(df)
        roc_full = RocFeature(5).compute(ctx).reset_index(drop=True)

        # Corrupt every bar strictly after index i; the value at i must be stable.
        i = 25
        tampered = df.copy()
        tampered.loc[tampered.index[i + 1 :], "close"] = 999.0
        roc_tampered = RocFeature(5).compute(make_ctx(tampered)).reset_index(drop=True)

        pd.testing.assert_series_equal(
            roc_full.iloc[: i + 1],
            roc_tampered.iloc[: i + 1],
            check_names=False,
            atol=1e-12,
        )


# --- VolumeSurgeFeature -------------------------------------------------


class TestVolumeSurgeFeature:
    def test_name_and_metadata(self) -> None:
        feat = VolumeSurgeFeature(20)
        assert feat.name == "volume_surge"
        assert feat.category == "volume"
        assert feat.placeholder is False
        assert feat.required_history_bars() == 20

    def test_default_window_is_20(self) -> None:
        assert VolumeSurgeFeature().window == 20

    def test_equals_volume_over_rolling_mean(self) -> None:
        df = synthetic_ohlcv(bars=60)
        ctx = make_ctx(df)
        surge = VolumeSurgeFeature(20).compute(ctx).reset_index(drop=True)
        v = df["volume"].astype("float64").reset_index(drop=True)
        expected = v / v.rolling(20).mean()
        pd.testing.assert_series_equal(surge, expected, check_names=False, atol=1e-12)

    def test_non_negative_where_defined(self) -> None:
        df = synthetic_ohlcv(bars=60)
        ctx = make_ctx(df)
        surge = VolumeSurgeFeature(20).compute(ctx).dropna()
        assert (surge >= 0.0).all()

    def test_warmup_is_nan_only(self) -> None:
        df = synthetic_ohlcv(bars=40)
        ctx = make_ctx(df)
        surge = VolumeSurgeFeature(20).compute(ctx).reset_index(drop=True)
        assert surge.iloc[:19].isna().all()
        assert surge.iloc[19:].notna().all()

    def test_pit_safe_future_bars_do_not_change_past(self) -> None:
        df = synthetic_ohlcv(bars=60)
        ctx = make_ctx(df)
        surge_full = VolumeSurgeFeature(20).compute(ctx).reset_index(drop=True)

        i = 40
        tampered = df.copy()
        tampered.loc[tampered.index[i + 1 :], "volume"] = 5_000_000
        surge_tampered = (
            VolumeSurgeFeature(20).compute(make_ctx(tampered)).reset_index(drop=True)
        )

        pd.testing.assert_series_equal(
            surge_full.iloc[: i + 1],
            surge_tampered.iloc[: i + 1],
            check_names=False,
            atol=1e-12,
        )


# --- Registration side effect -------------------------------------------


class TestRegistration:
    def test_micro_features_registered(self) -> None:
        import services.trader.features.micro  # noqa: F401
        from services.trader.features.base import feature_names

        names = feature_names()
        assert "roc_3" in names
        assert "volume_surge" in names
