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
            "realized_vol_pct_60": 0.3,
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
            "realized_vol_pct_60": 0.9,
        }
    )
    result = MicroLens().classify(feature_row=row, macro_row=None)
    assert result.label == "shock"


def test_reversal_momentum_opposes_sentiment() -> None:
    row = pd.Series(
        {
            "sentiment_score": 0.6,
            "roc_3": -3.0,
            "roc_5": -0.5,
            "volume_surge": 1.1,
            "realized_vol_pct_60": 0.3,
        }
    )
    result = MicroLens().classify(feature_row=row, macro_row=None)
    assert result.label == "reversal"


def test_nan_input_is_undefined() -> None:
    row = pd.Series(
        {
            "sentiment_score": float("nan"),
            "roc_3": 3.0,
            "roc_5": 4.0,
            "volume_surge": 1.1,
            "realized_vol_pct_60": 0.3,
        }
    )
    result = MicroLens().classify(feature_row=row, macro_row=None)
    assert result.label == UNDEFINED_LABEL
    assert result.confidence == 0.0
