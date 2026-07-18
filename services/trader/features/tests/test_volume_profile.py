"""Volume-profile helper + rolling feature tests.

The pure ``volume_profile`` helper is checked against a hand-computed toy
frame (6 bars, 3 distinct price levels, 3 bins):

    closes  = [10, 10, 20, 20, 30, 30]
    volumes = [100, 100, 300, 300, 50, 50]

    lo=10 hi=30 → edges [10, 50/3, 70/3, 30]
    bin volumes: bin0 (closes at 10) = 200, bin1 (20) = 600, bin2 (30) = 100
    POC = bin1 → poc_price = center = 20.0
    total = 900, 70% target = 630; VA starts {bin1}=600 < 630, neighbors
    bin0=200 vs bin2=100 → expand down → VA={bin0,bin1}=800 ≥ 630
    → VAL = edges[0] = 10, VAH = edges[2] = 70/3

All three rolling features are PIT-safe: altering bars after index ``i``
must not change values at or before ``i`` (same tamper pattern as
``test_micro_features.py``).
"""

from __future__ import annotations

import pandas as pd
import pytest

from services.trader.features.tests.conftest import make_ctx, synthetic_ohlcv
from services.trader.features.volume_profile import (
    HvnLvnRatioFeature,
    PocDistanceFeature,
    ProfileResult,
    ValueAreaPosFeature,
    volume_profile,
)


def toy_frame() -> pd.DataFrame:
    """6 bars, 3 distinct price levels — POC/VAH/VAL hand-computable."""
    return pd.DataFrame(
        {
            "close":  [10.0, 10.0, 20.0, 20.0, 30.0, 30.0],
            "volume": [100.0, 100.0, 300.0, 300.0, 50.0, 50.0],
        }
    )


# --- volume_profile helper ----------------------------------------------


class TestVolumeProfileHelper:
    def test_toy_case_poc_vah_val_exact(self) -> None:
        result = volume_profile(toy_frame(), window=6, bins=3)
        assert isinstance(result, ProfileResult)
        assert result.poc_price == pytest.approx(20.0)
        assert result.val == pytest.approx(10.0)
        assert result.vah == pytest.approx(70.0 / 3.0)
        assert result.bin_volumes == pytest.approx([200.0, 600.0, 100.0])
        assert result.bin_edges == pytest.approx([10.0, 50.0 / 3.0, 70.0 / 3.0, 30.0])

    def test_uses_only_trailing_window_rows(self) -> None:
        # Two leading rows at an extreme price with huge volume must be
        # ignored when window=6 keeps only the trailing 6 rows.
        head = pd.DataFrame({"close": [1000.0, 1000.0], "volume": [1e9, 1e9]})
        frame = pd.concat([head, toy_frame()], ignore_index=True)
        result = volume_profile(frame, window=6, bins=3)
        assert result.poc_price == pytest.approx(20.0)
        assert result.val == pytest.approx(10.0)
        assert result.vah == pytest.approx(70.0 / 3.0)

    def test_degenerate_flat_closes(self) -> None:
        frame = pd.DataFrame({"close": [42.0] * 6, "volume": [100.0] * 6})
        result = volume_profile(frame, window=6, bins=3)
        assert result.poc_price == 42.0
        assert result.vah == 42.0
        assert result.val == 42.0
        assert len(result.bin_volumes) == 1
        assert result.bin_volumes[0] == pytest.approx(600.0)

    def test_degenerate_zero_volume(self) -> None:
        frame = pd.DataFrame({"close": [10.0, 20.0, 30.0], "volume": [0.0, 0.0, 0.0]})
        result = volume_profile(frame, window=3, bins=3)
        # No NaN, no raise: collapses to the last close.
        assert result.poc_price == 30.0
        assert result.vah == 30.0
        assert result.val == 30.0
        assert len(result.bin_volumes) == 1


# --- shared feature checks ----------------------------------------------


FEATURES = [
    (PocDistanceFeature, "poc_distance_60"),
    (ValueAreaPosFeature, "value_area_pos_60"),
    (HvnLvnRatioFeature, "hvn_lvn_ratio_60"),
]


class TestFeatureContract:
    @pytest.mark.parametrize(("cls", "name"), FEATURES)
    def test_name_category_and_history(self, cls: type, name: str) -> None:
        feat = cls()
        assert feat.name == name
        assert feat.category == "volume"
        assert feat.placeholder is False
        assert feat.required_history_bars() == 60

    @pytest.mark.parametrize(("cls", "name"), FEATURES)
    def test_warmup_is_nan_only(self, cls: type, name: str) -> None:
        df = synthetic_ohlcv(bars=80)
        series = cls().compute(make_ctx(df)).reset_index(drop=True)
        assert series.iloc[:59].isna().all(), name
        assert series.iloc[59:].notna().all(), name

    @pytest.mark.parametrize(("cls", "name"), FEATURES)
    def test_pit_safe_future_bars_do_not_change_past(self, cls: type, name: str) -> None:
        df = synthetic_ohlcv(bars=80)
        full = cls().compute(make_ctx(df)).reset_index(drop=True)

        i = 70
        tampered = df.copy()
        tampered.loc[tampered.index[i + 1 :], "close"] = 500.0
        tampered.loc[tampered.index[i + 1 :], "volume"] = 5_000_000
        after = cls().compute(make_ctx(tampered)).reset_index(drop=True)

        pd.testing.assert_series_equal(
            full.iloc[: i + 1],
            after.iloc[: i + 1],
            check_names=False,
            atol=1e-12,
        )


# --- per-feature values on the toy window -------------------------------


class TestToyWindowValues:
    """window=6/bins=3 features over the 6-bar toy frame: one value at i=5,
    close_5=30, poc=20, val=10, vah=70/3."""

    def test_poc_distance(self) -> None:
        series = PocDistanceFeature(window=6, bins=3).compute(make_ctx(toy_frame()))
        assert series.iloc[:5].isna().all()
        assert series.iloc[5] == pytest.approx((30.0 - 20.0) / 30.0)

    def test_value_area_pos_at_upper_clip_boundary(self) -> None:
        # raw = (30 − 10) / (70/3 − 10) = 1.5 → exactly the upper clip edge.
        series = ValueAreaPosFeature(window=6, bins=3).compute(make_ctx(toy_frame()))
        assert series.iloc[5] == pytest.approx(1.5)

    def test_hvn_lvn_ratio(self) -> None:
        # close 30 sits in bin2 (vol 100); mean nonzero bin volume = 300.
        series = HvnLvnRatioFeature(window=6, bins=3).compute(make_ctx(toy_frame()))
        assert series.iloc[5] == pytest.approx(100.0 / 300.0)


class TestValueAreaPosBehaviour:
    def test_clipped_above(self) -> None:
        # POC bin alone covers 70%; VA = [10, 70/3]; close 50 → raw 3.0 → clip 1.5.
        frame = pd.DataFrame(
            {
                "close":  [10.0, 10.0, 20.0, 20.0, 20.0, 50.0],
                "volume": [300.0, 300.0, 500.0, 100.0, 100.0, 10.0],
            }
        )
        series = ValueAreaPosFeature(window=6, bins=3).compute(make_ctx(frame))
        assert series.iloc[5] == pytest.approx(1.5)

    def test_clipped_below(self) -> None:
        # Mirror image: close 10 far below the value area → clip at −0.5.
        frame = pd.DataFrame(
            {
                "close":  [50.0, 50.0, 40.0, 40.0, 40.0, 10.0],
                "volume": [300.0, 300.0, 500.0, 100.0, 100.0, 10.0],
            }
        )
        series = ValueAreaPosFeature(window=6, bins=3).compute(make_ctx(frame))
        assert series.iloc[5] == pytest.approx(-0.5)

    def test_flat_prices_give_half(self) -> None:
        # vah == val (degenerate) → defined as 0.5.
        frame = pd.DataFrame({"close": [42.0] * 6, "volume": [100.0] * 6})
        series = ValueAreaPosFeature(window=6, bins=3).compute(make_ctx(frame))
        assert series.iloc[5] == 0.5

    def test_all_values_within_clip_range(self) -> None:
        df = synthetic_ohlcv(bars=120)
        series = ValueAreaPosFeature().compute(make_ctx(df)).dropna()
        assert (series >= -0.5).all()
        assert (series <= 1.5).all()


class TestHvnLvnRatioBehaviour:
    def test_non_negative_where_defined(self) -> None:
        df = synthetic_ohlcv(bars=120)
        series = HvnLvnRatioFeature().compute(make_ctx(df)).dropna()
        assert (series >= 0.0).all()

    def test_flat_prices_give_one(self) -> None:
        # Single-bin degenerate profile: the close's bin IS the mean bin.
        frame = pd.DataFrame({"close": [42.0] * 6, "volume": [100.0] * 6})
        series = HvnLvnRatioFeature(window=6, bins=3).compute(make_ctx(frame))
        assert series.iloc[5] == 1.0


class TestPocDistanceBehaviour:
    def test_flat_prices_give_zero(self) -> None:
        frame = pd.DataFrame({"close": [42.0] * 6, "volume": [100.0] * 6})
        series = PocDistanceFeature(window=6, bins=3).compute(make_ctx(frame))
        assert series.iloc[5] == 0.0


# --- registration side effect -------------------------------------------


class TestRegistration:
    def test_volume_profile_features_registered(self) -> None:
        import services.trader.features.volume_profile  # noqa: F401
        from services.trader.features.base import feature_names

        names = feature_names()
        assert "poc_distance_60" in names
        assert "value_area_pos_60" in names
        assert "hvn_lvn_ratio_60" in names
