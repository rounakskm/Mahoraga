"""Sentiment placeholder feature.

The `sentiment_score` column always returns 0.0 with `placeholder=True`
until Phase 4 ships real news classification. Per Phase 1 plan §3, the
backtest harness (P1.6) rejects strategies that read placeholder columns
unless `allow_placeholder_features=True` is set in their config — forcing
Phase 4 to deliver real sentiment before any sentiment-dependent strategy
can train.
"""

from __future__ import annotations

from typing import ClassVar

import pandas as pd

from services.trader.features.base import (
    Feature,
    FeatureContext,
    register_feature,
)


class PlaceholderFeature(Feature):
    """Feature that always returns 0.0 with `placeholder=True` metadata flag.

    The Phase 1 sentiment column is the only placeholder. Later phases may
    add others; the `placeholder` flag is the discriminator the backtest
    harness checks.
    """

    category: ClassVar[str] = "sentiment"
    placeholder: ClassVar[bool] = True

    def __init__(self, name: str) -> None:
        self.name = name

    def required_history_bars(self) -> int:
        return 0

    def compute(self, ctx: FeatureContext) -> pd.Series:
        return pd.Series([0.0] * len(ctx.frame), dtype="float64")


# ---------------------------------------------------------------------------
# Registry — single sentiment_score placeholder
# ---------------------------------------------------------------------------


_REGISTERED_SENTIMENT = [
    register_feature(PlaceholderFeature("sentiment_score")),
]
"""Side-effect registration; importing this module fills BUILTIN_FEATURES."""
