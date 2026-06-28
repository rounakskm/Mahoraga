"""Regime-conditional strategy template + its mutation surface (Phase 3, Layer 1).

A candidate is a *(regime label -> SMA timing window)* mapping: in each market
regime the strategy holds SPY when price is above that regime's SMA, else flat.
This is the smallest thing that is genuinely regime-conditional — the loop learns
which timing behaviour fits which regime. The mutation surface is the per-regime
windows; the mechanical mutator (loop.py) nudges them.

ponytail: regimes are labelled inline here (a 4-state trend x vol proxy matching
the Phase-1 MESO taxonomy) so Layer 1 is self-contained and runnable now. Swapping
in the real Phase-1 RegimeDetector (features -> ADX/realized-vol -> label) is the
next slice; the strategy/eval/loop code does not change, only `label_regimes`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

REGIMES = (
    "trending_low_vol",
    "trending_high_vol",
    "ranging_low_vol",
    "ranging_high_vol",
)
WINDOW_MIN, WINDOW_MAX = 20, 250


def label_regimes(price: pd.Series) -> pd.Series:
    """Per-bar regime label: trend (vs 200-SMA) x vol (vs 1y median of 20d vol)."""
    ret = price.pct_change()
    trend = price > price.rolling(200, min_periods=50).mean()
    vol = ret.rolling(20, min_periods=10).std()
    hivol = vol > vol.rolling(252, min_periods=60).median()
    label = pd.Series("ranging_low_vol", index=price.index)
    label[trend & ~hivol] = "trending_low_vol"
    label[trend & hivol] = "trending_high_vol"
    label[~trend & hivol] = "ranging_high_vol"
    return label


@dataclass(frozen=True)
class RegimeConditionalStrategy:
    """Per-regime SMA-timing windows. The mutation surface is `windows`."""

    windows: dict[str, int]

    @classmethod
    def seed(cls) -> RegimeConditionalStrategy:
        # trend regimes ride longer trends; ranging regimes react faster.
        return cls({
            "trending_low_vol": 200,
            "trending_high_vol": 150,
            "ranging_low_vol": 50,
            "ranging_high_vol": 30,
        })

    @property
    def num_params(self) -> int:
        return len(self.windows)

    def returns(self, price: pd.Series, regimes: pd.Series) -> pd.Series:
        """One-bar-lagged daily returns (no look-ahead): hold when price > the
        current regime's SMA."""
        ret = price.pct_change()
        win_per_bar = regimes.map(self.windows)
        sma_at = pd.Series(np.nan, index=price.index)
        for w in set(self.windows.values()):
            sma_w = price.rolling(int(w), min_periods=int(w)).mean()
            sma_at = sma_at.where(win_per_bar != w, sma_w)
        signal = (price > sma_at).astype(float)
        return (signal.shift(1) * ret).dropna()

    def mutate(self, rng: np.random.Generator, step: int = 20) -> RegimeConditionalStrategy:
        """One single-change mutation: nudge one regime's window by +/- step."""
        regime = rng.choice(list(self.windows))
        delta = int(rng.choice([-step, step]))
        new_w = int(np.clip(self.windows[regime] + delta, WINDOW_MIN, WINDOW_MAX))
        return replace(self, windows={**self.windows, regime: new_w})
