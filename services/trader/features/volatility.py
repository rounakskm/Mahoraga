"""Volatility-category features.

Ten features per `feature-pipeline-spec.md` §2:

- atr_14
- bb_upper_20, bb_middle_20, bb_lower_20, bb_width_20
- realized_vol_20, realized_vol_60
- realized_vol_pct_60
- parkinson_vol_20
- garman_klass_20
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
# helpers
# ---------------------------------------------------------------------------


_TRADING_DAYS_PER_YEAR = 252


def _close(ctx: FeatureContext) -> pd.Series:
    return ctx.frame["close"].astype("float64").reset_index(drop=True)


def _high_low(ctx: FeatureContext) -> tuple[pd.Series, pd.Series]:
    f = ctx.frame
    return (
        f["high"].astype("float64").reset_index(drop=True),
        f["low"].astype("float64").reset_index(drop=True),
    )


def _ohlc(
    ctx: FeatureContext,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    f = ctx.frame
    return (
        f["open"].astype("float64").reset_index(drop=True),
        f["high"].astype("float64").reset_index(drop=True),
        f["low"].astype("float64").reset_index(drop=True),
        f["close"].astype("float64").reset_index(drop=True),
    )


# ---------------------------------------------------------------------------
# ATR (Wilder)
# ---------------------------------------------------------------------------


class ATR(Feature):
    """Average True Range, Wilder smoothing via `ewm(alpha=1/window)`."""

    category = "volatility"

    def __init__(self, window: int = 14) -> None:
        self.window = int(window)
        self.name = f"atr_{self.window}"

    def required_history_bars(self) -> int:
        return self.window + 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        high, low = _high_low(ctx)
        close = _close(ctx)
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        return tr.ewm(alpha=1.0 / self.window, adjust=False).mean()


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------


def _bollinger(close: pd.Series, window: int, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = close.rolling(window=window, min_periods=window).mean()
    std = close.rolling(window=window, min_periods=window).std(ddof=0)
    upper = middle + k * std
    lower = middle - k * std
    return upper, middle, lower


class BBMiddle(Feature):
    category = "volatility"

    def __init__(self, window: int = 20) -> None:
        self.window = int(window)
        self.name = f"bb_middle_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        return c.rolling(window=self.window, min_periods=self.window).mean()


class BBUpper(Feature):
    category = "volatility"

    def __init__(self, window: int = 20, k: float = 2.0) -> None:
        self.window = int(window)
        self.k = float(k)
        self.name = f"bb_upper_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        upper, _m, _l = _bollinger(_close(ctx), self.window, self.k)
        return upper


class BBLower(Feature):
    category = "volatility"

    def __init__(self, window: int = 20, k: float = 2.0) -> None:
        self.window = int(window)
        self.k = float(k)
        self.name = f"bb_lower_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        _u, _m, lower = _bollinger(_close(ctx), self.window, self.k)
        return lower


class BBWidth(Feature):
    """(upper - lower) / middle — relative bandwidth."""

    category = "volatility"

    def __init__(self, window: int = 20, k: float = 2.0) -> None:
        self.window = int(window)
        self.k = float(k)
        self.name = f"bb_width_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        upper, middle, lower = _bollinger(_close(ctx), self.window, self.k)
        return (upper - lower) / middle.replace(0.0, pd.NA)


# ---------------------------------------------------------------------------
# Realized volatility (close-to-close)
# ---------------------------------------------------------------------------


class RealizedVol(Feature):
    """Annualized close-to-close stdev of log returns over a rolling window."""

    category = "volatility"

    def __init__(self, window: int) -> None:
        self.window = int(window)
        self.name = f"realized_vol_{self.window}"

    def required_history_bars(self) -> int:
        return self.window + 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        log_returns = np.log(c / c.shift(1))
        return log_returns.rolling(
            window=self.window, min_periods=self.window
        ).std(ddof=0) * np.sqrt(_TRADING_DAYS_PER_YEAR)


class RealizedVolPercentile(Feature):
    """Percentile rank of `realized_vol_<window>` within its trailing 252-bar history."""

    category = "volatility"

    def __init__(self, window: int = 60, lookback: int = 252) -> None:
        self.window = int(window)
        self.lookback = int(lookback)
        self.name = f"realized_vol_pct_{self.window}"

    def required_history_bars(self) -> int:
        return self.window + self.lookback

    def compute(self, ctx: FeatureContext) -> pd.Series:
        rv = RealizedVol(window=self.window).compute(ctx)
        return rv.rolling(
            window=self.lookback, min_periods=self.lookback
        ).rank(pct=True) * 100.0


# ---------------------------------------------------------------------------
# Parkinson
# ---------------------------------------------------------------------------


class Parkinson(Feature):
    """Parkinson high-low volatility estimator, annualized."""

    category = "volatility"

    def __init__(self, window: int = 20) -> None:
        self.window = int(window)
        self.name = f"parkinson_vol_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        high, low = _high_low(ctx)
        log_ratio = np.log((high / low.replace(0.0, pd.NA)).astype("float64"))
        squared = log_ratio**2
        # Parkinson factor: 1 / (4 ln 2)
        factor = 1.0 / (4.0 * np.log(2.0))
        rolling_mean = squared.rolling(
            window=self.window, min_periods=self.window
        ).mean()
        return np.sqrt(factor * rolling_mean * _TRADING_DAYS_PER_YEAR)


# ---------------------------------------------------------------------------
# Garman-Klass
# ---------------------------------------------------------------------------


class GarmanKlass(Feature):
    """Garman-Klass volatility estimator, annualized."""

    category = "volatility"

    def __init__(self, window: int = 20) -> None:
        self.window = int(window)
        self.name = f"garman_klass_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        op, high, low, close = _ohlc(ctx)
        log_hl = np.log((high / low.replace(0.0, pd.NA)).astype("float64"))
        log_co = np.log((close / op.replace(0.0, pd.NA)).astype("float64"))
        per_bar = 0.5 * (log_hl**2) - (2.0 * np.log(2.0) - 1.0) * (log_co**2)
        rolling_mean = per_bar.rolling(
            window=self.window, min_periods=self.window
        ).mean()
        return np.sqrt(rolling_mean * _TRADING_DAYS_PER_YEAR)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_REGISTERED_VOLATILITY = [
    register_feature(ATR(window=14)),
    register_feature(BBUpper(window=20)),
    register_feature(BBMiddle(window=20)),
    register_feature(BBLower(window=20)),
    register_feature(BBWidth(window=20)),
    register_feature(RealizedVol(window=20)),
    register_feature(RealizedVol(window=60)),
    register_feature(RealizedVolPercentile(window=60, lookback=252)),
    register_feature(Parkinson(window=20)),
    register_feature(GarmanKlass(window=20)),
]
"""Side-effect registration; importing this module fills BUILTIN_FEATURES."""
