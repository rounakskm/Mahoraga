"""Tests for the MACRO lens (P1.5 R2)."""

from __future__ import annotations

import pandas as pd

from services.trader.regime.base import UNDEFINED_LABEL
from services.trader.regime.macro import MacroLens


def _macro(
    slope: float | None,
    vix: float | None,
    dxy: float | None,
) -> pd.Series:
    return pd.Series(
        {
            "yield_2s10s": slope,
            "vix_level": vix,
            "dxy_change_20d": dxy,
        }
    )


class TestMacroLensLabels:
    def test_clear_bull(self) -> None:
        # curve +1, vix +1 (low), dxy +1 (weak USD) → score 1.0
        result = MacroLens().classify(
            feature_row=pd.Series(dtype="float64"),
            macro_row=_macro(slope=0.5, vix=14.0, dxy=-1.2),
        )
        assert result.label == "bull"
        assert result.confidence == 1.0

    def test_clear_bear(self) -> None:
        # curve -1, vix -1 (high), dxy -1 (strong USD) → score -1.0
        result = MacroLens().classify(
            feature_row=pd.Series(dtype="float64"),
            macro_row=_macro(slope=-0.10, vix=35.0, dxy=2.0),
        )
        assert result.label == "bear"
        assert result.confidence == 1.0

    def test_transitioning_when_signals_mixed(self) -> None:
        # curve +1, vix -1, dxy +1 → score 1/3 ≈ 0.333 → transitioning
        result = MacroLens().classify(
            feature_row=pd.Series(dtype="float64"),
            macro_row=_macro(slope=0.3, vix=30.0, dxy=-0.5),
        )
        assert result.label == "transitioning"
        assert 0.30 < result.confidence < 0.40

    def test_vix_in_middle_band(self) -> None:
        # vix between 18 and 25 → vix_signal = 0
        # curve +1, vix 0, dxy +1 → score 2/3 ≈ 0.667 → bull
        result = MacroLens().classify(
            feature_row=pd.Series(dtype="float64"),
            macro_row=_macro(slope=0.4, vix=20.0, dxy=-0.5),
        )
        assert result.label == "bull"
        assert result.confidence == pd_approx(2 / 3)


class TestMacroLensUndefined:
    def test_no_macro_row(self) -> None:
        result = MacroLens().classify(
            feature_row=pd.Series(dtype="float64"), macro_row=None
        )
        assert result.label == UNDEFINED_LABEL
        assert result.confidence == 0.0

    def test_nan_slope(self) -> None:
        result = MacroLens().classify(
            feature_row=pd.Series(dtype="float64"),
            macro_row=_macro(slope=float("nan"), vix=20.0, dxy=0.0),
        )
        assert result.label == UNDEFINED_LABEL

    def test_missing_columns(self) -> None:
        result = MacroLens().classify(
            feature_row=pd.Series(dtype="float64"),
            macro_row=pd.Series({"vix_level": 18.0}),  # no slope, no dxy
        )
        assert result.label == UNDEFINED_LABEL


class TestMacroLensBoundary:
    def test_macro_score_exactly_at_bull_threshold(self) -> None:
        # score = 0.5 exactly → bull (>=)
        # curve +1, vix 0, dxy +0.5? No — signals are ±1 or 0. Need
        # +1, +1, -1 → score 1/3. Use +1, 0, +1 = 2/3. Tricky to hit
        # 0.50 exactly with integer signals. So construct: curve +1,
        # vix +1, dxy -1 → score 1/3 (transitioning). +1, +1, +1 → 1.
        # The boundary itself isn't reachable from these signals;
        # confirm we behave at the closest above-0.5 case.
        result = MacroLens().classify(
            feature_row=pd.Series(dtype="float64"),
            macro_row=_macro(slope=0.10, vix=22.0, dxy=-0.10),
        )
        # curve +1, vix 0 (middle), dxy +1 → score 2/3 → bull
        assert result.label == "bull"

    def test_curve_zero_treated_as_inverted(self) -> None:
        # slope == 0 → curve_signal = -1 (>0 required for +1)
        result = MacroLens().classify(
            feature_row=pd.Series(dtype="float64"),
            macro_row=_macro(slope=0.0, vix=15.0, dxy=-0.5),
        )
        # curve -1, vix +1, dxy +1 → score 1/3 → transitioning
        assert result.label == "transitioning"

    def test_inputs_snapshot(self) -> None:
        result = MacroLens().classify(
            feature_row=pd.Series(dtype="float64"),
            macro_row=_macro(slope=0.3, vix=15.0, dxy=-1.0),
        )
        assert result.inputs == {
            "yield_2s10s": 0.3,
            "vix_level": 15.0,
            "dxy_change_20d": -1.0,
        }


class TestMacroLensContract:
    def test_required_features(self) -> None:
        assert MacroLens().required_features() == [
            "yield_2s10s",
            "vix_level",
            "dxy_change_20d",
        ]

    def test_name(self) -> None:
        assert MacroLens.name == "macro"


def pd_approx(expected: float, rel: float = 1e-9, abs_: float = 1e-9):
    """Local tolerance helper — pytest.approx works but we avoid the
    indirect import to keep the test file self-contained."""
    import pytest

    return pytest.approx(expected, rel=rel, abs=abs_)
