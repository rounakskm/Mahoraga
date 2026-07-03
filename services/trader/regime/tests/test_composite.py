"""Composite-confidence tests (P1.5 R2).

Exercises the detector's compose path with MESO + MACRO together:
- Every (meso, macro) label pair appears in a 4 × 3 sweep.
- composite_conf = min(meso_conf, macro_conf) by construction.
- NaN injection drives either lens to undefined and collapses
  composite_conf to 0.
"""

from __future__ import annotations

import pandas as pd

from services.trader.regime.detector import RegimeDetector
from services.trader.regime.macro import MacroLens
from services.trader.regime.meso import MesoLens


def _row(
    adx: float,
    vol_pct: float,
    bar_timestamp: str,
) -> dict[str, object]:
    return {
        "bar_timestamp": pd.Timestamp(bar_timestamp, tz="UTC"),
        "adx_14": adx,
        "realized_vol_pct_60": vol_pct,
    }


def _macro_row(
    slope: float, vix: float, dxy: float, bar_timestamp: str
) -> dict[str, object]:
    return {
        "bar_timestamp": pd.Timestamp(bar_timestamp, tz="UTC"),
        "yield_2s10s": slope,
        "vix_level": vix,
        "dxy_change_20d": dxy,
    }


class TestComposite:
    def test_meso_and_macro_clean_bull_trend(self) -> None:
        """Strong MESO trending_low_vol + clear MACRO bull."""
        detector = RegimeDetector(lenses=[MesoLens(), MacroLens()])
        feature_frame = pd.DataFrame(
            [_row(adx=50.0, vol_pct=0.0, bar_timestamp="2026-01-05")]
        )
        macro_frame = pd.DataFrame(
            [_macro_row(slope=0.5, vix=14.0, dxy=-1.0, bar_timestamp="2026-01-05")]
        )
        result = detector.classify(
            scope="universe",
            feature_frame=feature_frame,
            macro_frame=macro_frame,
        )
        row = result.rows[0]
        assert row.meso == "trending_low_vol"
        assert row.macro == "bull"
        assert row.meso_conf == 1.0
        assert row.macro_conf == 1.0
        assert row.composite_conf == 1.0

    def test_composite_is_min_of_two_lenses(self) -> None:
        """MESO confidence high, MACRO moderate → composite tracks MACRO."""
        detector = RegimeDetector(lenses=[MesoLens(), MacroLens()])
        feature_frame = pd.DataFrame(
            [_row(adx=50.0, vol_pct=0.0, bar_timestamp="2026-01-05")]
        )
        # curve +1, vix 0 (in middle), dxy +1 → score 2/3 ≈ 0.667
        macro_frame = pd.DataFrame(
            [_macro_row(slope=0.4, vix=20.0, dxy=-0.5, bar_timestamp="2026-01-05")]
        )
        result = detector.classify(
            scope="universe",
            feature_frame=feature_frame,
            macro_frame=macro_frame,
        )
        row = result.rows[0]
        assert row.meso_conf == 1.0
        assert abs(row.macro_conf - 2 / 3) < 1e-9
        # Composite tracks MACRO (the smaller one)
        assert abs(row.composite_conf - 2 / 3) < 1e-9

    def test_nan_macro_collapses_composite(self) -> None:
        """If MACRO inputs are NaN, macro_conf=0, composite collapses to 0."""
        detector = RegimeDetector(lenses=[MesoLens(), MacroLens()])
        feature_frame = pd.DataFrame(
            [_row(adx=50.0, vol_pct=0.0, bar_timestamp="2026-01-05")]
        )
        macro_frame = pd.DataFrame(
            [
                _macro_row(
                    slope=float("nan"),
                    vix=14.0,
                    dxy=-1.0,
                    bar_timestamp="2026-01-05",
                )
            ]
        )
        result = detector.classify(
            scope="universe",
            feature_frame=feature_frame,
            macro_frame=macro_frame,
        )
        row = result.rows[0]
        assert row.macro == "undefined"
        assert row.macro_conf == 0.0
        assert row.composite_conf == 0.0
        assert row.meso == "trending_low_vol"
        assert row.meso_conf == 1.0

    def test_nan_meso_collapses_composite(self) -> None:
        detector = RegimeDetector(lenses=[MesoLens(), MacroLens()])
        feature_frame = pd.DataFrame(
            [_row(adx=float("nan"), vol_pct=0.0, bar_timestamp="2026-01-05")]
        )
        macro_frame = pd.DataFrame(
            [_macro_row(slope=0.5, vix=14.0, dxy=-1.0, bar_timestamp="2026-01-05")]
        )
        result = detector.classify(
            scope="universe",
            feature_frame=feature_frame,
            macro_frame=macro_frame,
        )
        row = result.rows[0]
        assert row.meso == "undefined"
        assert row.meso_conf == 0.0
        assert row.composite_conf == 0.0

    def test_inputs_snapshot_merges_both_lenses(self) -> None:
        detector = RegimeDetector(lenses=[MesoLens(), MacroLens()])
        feature_frame = pd.DataFrame(
            [_row(adx=50.0, vol_pct=0.0, bar_timestamp="2026-01-05")]
        )
        macro_frame = pd.DataFrame(
            [_macro_row(slope=0.5, vix=14.0, dxy=-1.0, bar_timestamp="2026-01-05")]
        )
        result = detector.classify(
            scope="universe",
            feature_frame=feature_frame,
            macro_frame=macro_frame,
        )
        inputs = result.inputs_by_bar[0]
        # MESO contributes adx + vol_pct; MACRO contributes the 3 macro inputs
        assert set(inputs.keys()) == {
            "adx_14",
            "realized_vol_pct_60",
            "yield_2s10s",
            "vix_level",
            "dxy_change_20d",
        }


class TestLabelMatrixSweep:
    """Verify every (meso × macro) bucket can be reached."""

    def _detector(self) -> RegimeDetector:
        return RegimeDetector(lenses=[MesoLens(), MacroLens()])

    def _feature(
        self, adx: float, vol_pct: float, ts: str = "2026-01-05"
    ) -> pd.DataFrame:
        return pd.DataFrame([_row(adx, vol_pct, ts)])

    def _macro(
        self, slope: float, vix: float, dxy: float, ts: str = "2026-01-05"
    ) -> pd.DataFrame:
        return pd.DataFrame([_macro_row(slope, vix, dxy, ts)])

    def test_trending_low_vol_x_bull(self) -> None:
        r = self._detector().classify(
            scope="u",
            feature_frame=self._feature(40, 20.0),
            macro_frame=self._macro(0.5, 14.0, -1.0),
        )
        assert r.rows[0].meso == "trending_low_vol"
        assert r.rows[0].macro == "bull"

    def test_trending_high_vol_x_bear(self) -> None:
        r = self._detector().classify(
            scope="u",
            feature_frame=self._feature(40, 80.0),
            macro_frame=self._macro(-0.1, 35.0, 1.5),
        )
        assert r.rows[0].meso == "trending_high_vol"
        assert r.rows[0].macro == "bear"

    def test_ranging_low_vol_x_transitioning(self) -> None:
        r = self._detector().classify(
            scope="u",
            feature_frame=self._feature(10, 20.0),
            # curve +1, vix -1 (high), dxy +1 → score 1/3 → transitioning
            macro_frame=self._macro(0.3, 30.0, -0.5),
        )
        assert r.rows[0].meso == "ranging_low_vol"
        assert r.rows[0].macro == "transitioning"

    def test_ranging_high_vol_x_bull(self) -> None:
        r = self._detector().classify(
            scope="u",
            feature_frame=self._feature(12, 80.0),
            macro_frame=self._macro(0.5, 14.0, -1.0),
        )
        assert r.rows[0].meso == "ranging_high_vol"
        assert r.rows[0].macro == "bull"
