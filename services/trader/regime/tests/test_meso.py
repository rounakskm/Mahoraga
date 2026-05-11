"""Tests for the MESO lens (P1.5 R1).

One fixture per label bucket, plus the NaN-undefined path and the
confidence math.
"""

from __future__ import annotations

import pandas as pd

from services.trader.regime.base import UNDEFINED_LABEL
from services.trader.regime.meso import MesoLens


def _row(adx: float | None, vol_pct: float | None) -> pd.Series:
    return pd.Series({"adx_14": adx, "realized_vol_pct_60": vol_pct})


class TestMesoLensLabels:
    def test_trending_low_vol(self) -> None:
        result = MesoLens().classify(
            feature_row=_row(adx=40.0, vol_pct=0.20), macro_row=None
        )
        assert result.label == "trending_low_vol"
        assert result.confidence > 0.0

    def test_trending_high_vol(self) -> None:
        result = MesoLens().classify(
            feature_row=_row(adx=35.0, vol_pct=0.70), macro_row=None
        )
        assert result.label == "trending_high_vol"

    def test_ranging_low_vol(self) -> None:
        result = MesoLens().classify(
            feature_row=_row(adx=10.0, vol_pct=0.15), macro_row=None
        )
        assert result.label == "ranging_low_vol"

    def test_ranging_high_vol(self) -> None:
        result = MesoLens().classify(
            feature_row=_row(adx=12.0, vol_pct=0.80), macro_row=None
        )
        assert result.label == "ranging_high_vol"

    def test_threshold_boundary_picks_trending(self) -> None:
        # adx == 25 is exactly on the boundary; spec says >=25 → trending
        result = MesoLens().classify(
            feature_row=_row(adx=25.0, vol_pct=0.20), macro_row=None
        )
        assert result.label == "trending_low_vol"

    def test_vol_threshold_boundary_picks_low_vol(self) -> None:
        # vol_pct == 0.40 is exactly on the boundary; spec says <=0.40 → low_vol
        result = MesoLens().classify(
            feature_row=_row(adx=40.0, vol_pct=0.40), macro_row=None
        )
        assert result.label == "trending_low_vol"


class TestMesoLensUndefined:
    def test_nan_adx_returns_undefined(self) -> None:
        result = MesoLens().classify(
            feature_row=_row(adx=float("nan"), vol_pct=0.20), macro_row=None
        )
        assert result.label == UNDEFINED_LABEL
        assert result.confidence == 0.0

    def test_nan_vol_returns_undefined(self) -> None:
        result = MesoLens().classify(
            feature_row=_row(adx=40.0, vol_pct=float("nan")), macro_row=None
        )
        assert result.label == UNDEFINED_LABEL
        assert result.confidence == 0.0

    def test_missing_keys_return_undefined(self) -> None:
        # Empty series — both .get(...) calls return None
        result = MesoLens().classify(
            feature_row=pd.Series(dtype="float64"), macro_row=None
        )
        assert result.label == UNDEFINED_LABEL


class TestMesoConfidenceMath:
    def test_clean_quadrant_gets_high_confidence(self) -> None:
        # adx=50 → trend_conf = (50-25)/25 = 1.0
        # vol_pct=0.0 → vol_conf = (0-0.40)/0.40 = -1.0 (low-vol direction)
        # min(|1.0|, |1.0|) = 1.0
        result = MesoLens().classify(
            feature_row=_row(adx=50.0, vol_pct=0.0), macro_row=None
        )
        assert result.confidence == 1.0
        assert result.label == "trending_low_vol"

    def test_borderline_gets_low_confidence(self) -> None:
        # adx=26 → trend_conf = 1/25 = 0.04
        # vol_pct=0.41 → vol_conf = 0.01/0.40 = 0.025
        # min(0.04, 0.025) = 0.025
        result = MesoLens().classify(
            feature_row=_row(adx=26.0, vol_pct=0.41), macro_row=None
        )
        assert result.confidence < 0.05
        assert result.label == "trending_high_vol"

    def test_inputs_snapshot_preserved(self) -> None:
        result = MesoLens().classify(
            feature_row=_row(adx=30.0, vol_pct=0.30), macro_row=None
        )
        assert result.inputs == {"adx_14": 30.0, "realized_vol_pct_60": 0.30}


class TestMesoLensContract:
    def test_required_features_listed(self) -> None:
        assert MesoLens().required_features() == ["adx_14", "realized_vol_pct_60"]

    def test_name_class_var(self) -> None:
        assert MesoLens.name == "meso"
