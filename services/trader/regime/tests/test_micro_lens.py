"""Unit tests for the MICRO regime lens (`MicroLens`)."""

from __future__ import annotations

import pandas as pd

from services.trader.regime.base import UNDEFINED_LABEL
from services.trader.regime.micro import MicroLens


def test_required_features() -> None:
    assert MicroLens().required_features() == [
        "sentiment_score",
        "roc_3",
        "roc_5",
        "volume_surge",
        "realized_vol_pct_60",
    ]


def test_strong_positive_momentum() -> None:
    row = pd.Series(
        {
            "sentiment_score": 0.6,
            "roc_3": 3.0,
            "roc_5": 4.0,
            "volume_surge": 1.1,
            "realized_vol_pct_60": 30.0,
        }
    )
    result = MicroLens().classify(feature_row=row, macro_row=None)
    assert result.label == "momentum"
    assert result.confidence > 0.5


def test_shock_extreme_negative_sentiment_volume_spike() -> None:
    row = pd.Series(
        {
            "sentiment_score": -0.8,
            "roc_3": -1.0,
            "roc_5": -0.5,
            "volume_surge": 2.5,
            "realized_vol_pct_60": 90.0,
        }
    )
    result = MicroLens().classify(feature_row=row, macro_row=None)
    assert result.label == "shock"


def test_shock_confidence_rises_with_realized_vol() -> None:
    # High realized-vol percentile strengthens a shock read (review B6).
    def _shock_row(vol_pct: float) -> pd.Series:
        return pd.Series(
            {
                "sentiment_score": -0.8,
                "roc_3": -1.0,
                "roc_5": -0.5,
                "volume_surge": 2.5,
                "realized_vol_pct_60": vol_pct,
            }
        )

    hi = MicroLens().classify(feature_row=_shock_row(95.0), macro_row=None)
    lo = MicroLens().classify(feature_row=_shock_row(50.0), macro_row=None)
    assert hi.label == lo.label == "shock"
    assert hi.confidence > lo.confidence


def test_reversal_momentum_opposes_sentiment() -> None:
    row = pd.Series(
        {
            "sentiment_score": 0.6,
            "roc_3": -3.0,
            "roc_5": -0.5,
            "volume_surge": 1.1,
            "realized_vol_pct_60": 30.0,
        }
    )
    result = MicroLens().classify(feature_row=row, macro_row=None)
    assert result.label == "reversal"


def test_reversal_deadband_suppresses_tiny_roc3() -> None:
    # |roc_3| inside the 0.1pp deadband must not read as a reversal (review B7).
    row = pd.Series(
        {
            "sentiment_score": 0.6,
            "roc_3": -0.05,
            "roc_5": 0.0,
            "volume_surge": 1.1,
            "realized_vol_pct_60": 30.0,
        }
    )
    result = MicroLens().classify(feature_row=row, macro_row=None)
    assert result.label != "reversal"


def test_nan_input_is_undefined() -> None:
    row = pd.Series(
        {
            "sentiment_score": float("nan"),
            "roc_3": 3.0,
            "roc_5": 4.0,
            "volume_surge": 1.1,
            "realized_vol_pct_60": 30.0,
        }
    )
    result = MicroLens().classify(feature_row=row, macro_row=None)
    assert result.label == UNDEFINED_LABEL
    assert result.confidence == 0.0


def test_nan_vol_is_neutral_not_undefined() -> None:
    # A NaN realized_vol_pct_60 alone must not gate classification (review B6):
    # strong momentum still classifies as momentum with vol treated as neutral.
    row = pd.Series(
        {
            "sentiment_score": 0.6,
            "roc_3": 3.0,
            "roc_5": 4.0,
            "volume_surge": 1.1,
            "realized_vol_pct_60": float("nan"),
        }
    )
    result = MicroLens().classify(feature_row=row, macro_row=None)
    assert result.label == "momentum"
    assert result.confidence > 0.0
