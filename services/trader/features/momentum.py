"""Momentum-category features.

Ten features per `feature-pipeline-spec.md` §2:

- rsi_14, rsi_5
- roc_5, roc_10, roc_20
- stoch_k_14, stoch_d_14
- williams_r_14
- momentum_10, momentum_20
"""

from __future__ import annotations

import pandas as pd

from services.trader.features.base import (
    Feature,
    FeatureContext,
    register_feature,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _close(ctx: FeatureContext) -> pd.Series:
    return ctx.frame["close"].astype("float64").reset_index(drop=True)


def _high_low_close(ctx: FeatureContext) -> tuple[pd.Series, pd.Series, pd.Series]:
    f = ctx.frame
    return (
        f["high"].astype("float64").reset_index(drop=True),
        f["low"].astype("float64").reset_index(drop=True),
        f["close"].astype("float64").reset_index(drop=True),
    )


# ---------------------------------------------------------------------------
# RSI (Wilder)
# ---------------------------------------------------------------------------


class RSI(Feature):
    """Relative Strength Index (Wilder smoothing via ewm alpha=1/window)."""

    category = "momentum"

    def __init__(self, window: int = 14) -> None:
        self.window = int(window)
        self.name = f"rsi_{self.window}"

    def required_history_bars(self) -> int:
        return self.window + 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        delta = c.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        alpha = 1.0 / self.window
        avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
        avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
        # Avoid divide-by-zero. When avg_loss=0, RSI = 100.
        rs = avg_gain / avg_loss.replace(0.0, pd.NA)
        rsi = 100.0 - 100.0 / (1.0 + rs)
        # Where avg_loss was zero and avg_gain > 0, RSI is 100; both zero -> 50 (neutral).
        rsi = rsi.where(avg_loss != 0.0, 100.0)
        rsi = rsi.where((avg_gain != 0.0) | (avg_loss != 0.0), 50.0)
        return rsi.astype("float64")


# ---------------------------------------------------------------------------
# Rate of Change
# ---------------------------------------------------------------------------


class ROC(Feature):
    """Rate of Change: 100 * (close[t] - close[t-N]) / close[t-N]."""

    category = "momentum"

    def __init__(self, window: int) -> None:
        self.window = int(window)
        self.name = f"roc_{self.window}"

    def required_history_bars(self) -> int:
        return self.window + 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        prev = c.shift(self.window)
        return 100.0 * (c - prev) / prev.replace(0.0, pd.NA)


# ---------------------------------------------------------------------------
# Stochastic
# ---------------------------------------------------------------------------


class StochK(Feature):
    """Stochastic %K: 100 * (close - lowest_low) / (highest_high - lowest_low)."""

    category = "momentum"

    def __init__(self, window: int = 14) -> None:
        self.window = int(window)
        self.name = f"stoch_k_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        high, low, close = _high_low_close(ctx)
        lowest = low.rolling(window=self.window, min_periods=self.window).min()
        highest = high.rolling(window=self.window, min_periods=self.window).max()
        denom = (highest - lowest).replace(0.0, pd.NA)
        return 100.0 * (close - lowest) / denom


class StochD(Feature):
    """Stochastic %D: 3-period SMA of %K (default smoothing)."""

    category = "momentum"

    def __init__(self, window: int = 14, d_window: int = 3) -> None:
        self.window = int(window)
        self.d_window = int(d_window)
        self.name = f"stoch_d_{self.window}"

    def required_history_bars(self) -> int:
        return self.window + self.d_window - 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        # Compute %K then take its rolling mean
        k = StochK(window=self.window).compute(ctx)
        return k.rolling(window=self.d_window, min_periods=self.d_window).mean()


# ---------------------------------------------------------------------------
# Williams %R
# ---------------------------------------------------------------------------


class WilliamsR(Feature):
    """Williams %R: -100 * (highest_high - close) / (highest_high - lowest_low). ∈ [-100, 0]."""

    category = "momentum"

    def __init__(self, window: int = 14) -> None:
        self.window = int(window)
        self.name = f"williams_r_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        high, low, close = _high_low_close(ctx)
        highest = high.rolling(window=self.window, min_periods=self.window).max()
        lowest = low.rolling(window=self.window, min_periods=self.window).min()
        denom = (highest - lowest).replace(0.0, pd.NA)
        return -100.0 * (highest - close) / denom


# ---------------------------------------------------------------------------
# Momentum (absolute close diff)
# ---------------------------------------------------------------------------


class Momentum(Feature):
    """Absolute close difference: close[t] - close[t-N]."""

    category = "momentum"

    def __init__(self, window: int) -> None:
        self.window = int(window)
        self.name = f"momentum_{self.window}"

    def required_history_bars(self) -> int:
        return self.window + 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        return c - c.shift(self.window)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_REGISTERED_MOMENTUM = [
    register_feature(RSI(window=14)),
    register_feature(RSI(window=5)),
    register_feature(ROC(window=5)),
    register_feature(ROC(window=10)),
    register_feature(ROC(window=20)),
    register_feature(StochK(window=14)),
    register_feature(StochD(window=14, d_window=3)),
    register_feature(WilliamsR(window=14)),
    register_feature(Momentum(window=10)),
    register_feature(Momentum(window=20)),
]
"""Side-effect registration; importing this module fills BUILTIN_FEATURES."""
