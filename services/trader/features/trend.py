"""Trend-category features.

Ten features per `feature-pipeline-spec.md` §2:

- ema_20, ema_50, ema_200, sma_20, sma_50
- adx_14
- macd_12_26, macd_signal_9, macd_hist
- regression_slope_20

Implementations stay in pure pandas/numpy; no external libraries beyond
what's already declared in `pyproject.toml`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.trader.features.base import (
    Feature,
    FeatureContext,
    register_feature,
)

# ---------------------------------------------------------------------------
# Helpers
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
# Moving averages
# ---------------------------------------------------------------------------


class EMA(Feature):
    category = "trend"

    def __init__(self, span: int) -> None:
        self.span = int(span)
        self.name = f"ema_{self.span}"

    def required_history_bars(self) -> int:
        # EMA returns a non-null value from bar 1, but stabilises around span
        return self.span

    def compute(self, ctx: FeatureContext) -> pd.Series:
        return _close(ctx).ewm(span=self.span, adjust=False).mean()


class SMA(Feature):
    category = "trend"

    def __init__(self, window: int) -> None:
        self.window = int(window)
        self.name = f"sma_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        return _close(ctx).rolling(window=self.window, min_periods=self.window).mean()


# ---------------------------------------------------------------------------
# ADX
# ---------------------------------------------------------------------------


class ADX(Feature):
    category = "trend"

    def __init__(self, window: int = 14) -> None:
        self.window = int(window)
        self.name = f"adx_{self.window}"

    def required_history_bars(self) -> int:
        return 2 * self.window  # ADX needs window for DI smoothing + window for ADX smoothing

    def compute(self, ctx: FeatureContext) -> pd.Series:
        high, low, close = _high_low_close(ctx)
        plus_dm = (high.diff()).clip(lower=0.0)
        minus_dm = (-low.diff()).clip(lower=0.0)
        # Where +DM <= -DM, +DM is zeroed (and vice versa)
        plus_dm = plus_dm.where(plus_dm > minus_dm, 0.0)
        minus_dm = minus_dm.where(minus_dm > plus_dm.where(plus_dm > 0, 0.0).shift(0), minus_dm)
        # Simpler restatement matching the canonical Wilder ADX:
        plus_dm = (high.diff().where(high.diff() > -low.diff(), 0.0)).clip(lower=0.0)
        minus_dm = ((-low.diff()).where((-low.diff()) > high.diff(), 0.0)).clip(lower=0.0)

        tr = pd.concat(
            [
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr = _wilders_smoothing(tr, self.window)
        plus_di = 100.0 * _wilders_smoothing(plus_dm, self.window) / atr.replace(0.0, np.nan)
        minus_di = 100.0 * _wilders_smoothing(minus_dm, self.window) / atr.replace(0.0, np.nan)
        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
        return _wilders_smoothing(dx, self.window)


def _wilders_smoothing(series: pd.Series, window: int) -> pd.Series:
    """Wilder's smoothing — equivalent to `ewm(alpha=1/window, adjust=False)` after the
    first window's seed.
    """
    s = series.copy()
    seed = s.iloc[: window].sum()
    out = pd.Series(np.nan, index=s.index, dtype="float64")
    if len(s) <= window:
        return out
    out.iloc[window - 1] = seed
    factor = (window - 1) / window
    for i in range(window, len(s)):
        prev = out.iloc[i - 1]
        if pd.isna(prev):
            continue
        out.iloc[i] = prev * factor + (s.iloc[i] if not pd.isna(s.iloc[i]) else 0.0)
    return out


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


class MACD(Feature):
    """MACD line: EMA(close, fast) − EMA(close, slow). Default 12/26."""

    category = "trend"

    def __init__(self, fast: int = 12, slow: int = 26) -> None:
        self.fast = int(fast)
        self.slow = int(slow)
        self.name = f"macd_{self.fast}_{self.slow}"

    def required_history_bars(self) -> int:
        return self.slow

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        return c.ewm(span=self.fast, adjust=False).mean() - c.ewm(span=self.slow, adjust=False).mean()


class MACDSignal(Feature):
    """EMA of the MACD line; default span 9."""

    category = "trend"

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self.fast = int(fast)
        self.slow = int(slow)
        self.signal = int(signal)
        self.name = f"macd_signal_{self.signal}"

    def required_history_bars(self) -> int:
        return self.slow + self.signal

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        macd = c.ewm(span=self.fast, adjust=False).mean() - c.ewm(span=self.slow, adjust=False).mean()
        return macd.ewm(span=self.signal, adjust=False).mean()


class MACDHist(Feature):
    """MACD histogram: MACD line minus signal line."""

    category = "trend"
    name = "macd_hist"

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self.fast = int(fast)
        self.slow = int(slow)
        self.signal = int(signal)

    def required_history_bars(self) -> int:
        return self.slow + self.signal

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        macd = c.ewm(span=self.fast, adjust=False).mean() - c.ewm(span=self.slow, adjust=False).mean()
        signal = macd.ewm(span=self.signal, adjust=False).mean()
        return macd - signal


# ---------------------------------------------------------------------------
# Regression slope
# ---------------------------------------------------------------------------


class RegressionSlope(Feature):
    """Linear-regression slope of close vs. integer time index over a rolling window."""

    category = "trend"

    def __init__(self, window: int = 20) -> None:
        self.window = int(window)
        self.name = f"regression_slope_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        x = np.arange(self.window, dtype="float64")
        x_mean = x.mean()
        denom = ((x - x_mean) ** 2).sum()

        def slope_kernel(values: np.ndarray) -> float:
            y_mean = values.mean()
            return float(((x - x_mean) * (values - y_mean)).sum() / denom)

        return c.rolling(window=self.window, min_periods=self.window).apply(slope_kernel, raw=True)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_REGISTERED_TREND = [
    register_feature(EMA(span=20)),
    register_feature(EMA(span=50)),
    register_feature(EMA(span=200)),
    register_feature(SMA(window=20)),
    register_feature(SMA(window=50)),
    register_feature(ADX(window=14)),
    register_feature(MACD(fast=12, slow=26)),
    register_feature(MACDSignal(fast=12, slow=26, signal=9)),
    register_feature(MACDHist(fast=12, slow=26, signal=9)),
    register_feature(RegressionSlope(window=20)),
]
"""Side-effect registration; importing this module fills BUILTIN_FEATURES."""
