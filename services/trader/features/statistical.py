"""Statistical-category features.

Ten features per `feature-pipeline-spec.md` §2:

- hurst_60, hurst_120
- autocorr_lag1_20, autocorr_lag5_20
- skew_60, kurt_60
- zscore_20, zscore_60
- min_60, max_60
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.trader.features.base import (
    Feature,
    FeatureContext,
    register_feature,
)


def _close(ctx: FeatureContext) -> pd.Series:
    return ctx.frame["close"].astype("float64").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Hurst exponent (rescaled-range)
# ---------------------------------------------------------------------------


def _hurst_rs(values: np.ndarray) -> float:
    """Compute the Hurst exponent of a 1-D series via rescaled-range analysis.

    Returns NaN if the series is too short or degenerate (zero std).
    """
    n = len(values)
    if n < 16:
        return float("nan")
    # Use return series (mean-centered log diffs of prices)
    if np.any(values <= 0):
        return float("nan")
    log_prices = np.log(values)
    returns = np.diff(log_prices)
    if returns.std() == 0:
        return float("nan")

    # Geometric lag sweep capped to ~half the window size
    max_lag = max(8, n // 2)
    lags = np.unique(np.round(np.logspace(2, np.log10(max_lag), num=6)).astype(int))
    lags = lags[lags >= 4]
    if len(lags) < 3:
        return float("nan")

    rs_values: list[float] = []
    for lag in lags:
        if lag > len(returns):
            continue
        # Split returns into non-overlapping chunks
        n_chunks = len(returns) // lag
        if n_chunks < 1:
            continue
        chunked = returns[: n_chunks * lag].reshape(n_chunks, lag)
        rs_chunks = []
        for chunk in chunked:
            mean = chunk.mean()
            centered = chunk - mean
            cumulative = centered.cumsum()
            r = cumulative.max() - cumulative.min()
            s = chunk.std(ddof=0)
            if s == 0:
                continue
            rs_chunks.append(r / s)
        if not rs_chunks:
            continue
        rs_values.append((lag, float(np.mean(rs_chunks))))

    if len(rs_values) < 3:
        return float("nan")
    lags_arr = np.log(np.array([row[0] for row in rs_values], dtype="float64"))
    rs_arr = np.log(np.array([row[1] for row in rs_values], dtype="float64"))
    if not np.isfinite(rs_arr).all():
        return float("nan")
    slope = np.polyfit(lags_arr, rs_arr, 1)[0]
    return float(slope)


class Hurst(Feature):
    """Hurst exponent of close prices over a rolling window."""

    category = "statistical"

    def __init__(self, window: int) -> None:
        self.window = int(window)
        self.name = f"hurst_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx).to_numpy()
        out = np.full(len(c), np.nan, dtype="float64")
        for i in range(self.window - 1, len(c)):
            out[i] = _hurst_rs(c[i - self.window + 1 : i + 1])
        return pd.Series(out, dtype="float64")


# ---------------------------------------------------------------------------
# Autocorrelation
# ---------------------------------------------------------------------------


class Autocorrelation(Feature):
    """Lag-N autocorrelation of close-return series over a rolling window."""

    category = "statistical"

    def __init__(self, lag: int, window: int = 20) -> None:
        self.lag = int(lag)
        self.window = int(window)
        self.name = f"autocorr_lag{self.lag}_{self.window}"

    def required_history_bars(self) -> int:
        return self.window + self.lag

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        returns = c.pct_change()

        def autocorr_kernel(values: np.ndarray) -> float:
            if len(values) <= self.lag:
                return float("nan")
            a = values[: -self.lag] if self.lag > 0 else values
            b = values[self.lag :]
            if a.std() == 0 or b.std() == 0:
                return float("nan")
            return float(np.corrcoef(a, b)[0, 1])

        return returns.rolling(window=self.window, min_periods=self.window).apply(
            autocorr_kernel, raw=True
        )


# ---------------------------------------------------------------------------
# Skew / Kurt
# ---------------------------------------------------------------------------


class Skew(Feature):
    """Skewness of close-return series over a rolling window."""

    category = "statistical"

    def __init__(self, window: int = 60) -> None:
        self.window = int(window)
        self.name = f"skew_{self.window}"

    def required_history_bars(self) -> int:
        return self.window + 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        returns = _close(ctx).pct_change()
        return returns.rolling(window=self.window, min_periods=self.window).skew()


class Kurt(Feature):
    """Excess kurtosis of close-return series over a rolling window."""

    category = "statistical"

    def __init__(self, window: int = 60) -> None:
        self.window = int(window)
        self.name = f"kurt_{self.window}"

    def required_history_bars(self) -> int:
        return self.window + 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        returns = _close(ctx).pct_change()
        return returns.rolling(window=self.window, min_periods=self.window).kurt()


# ---------------------------------------------------------------------------
# Z-score
# ---------------------------------------------------------------------------


class ZScore(Feature):
    """Z-score of close over a rolling window."""

    category = "statistical"

    def __init__(self, window: int) -> None:
        self.window = int(window)
        self.name = f"zscore_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        mean = c.rolling(window=self.window, min_periods=self.window).mean()
        std = c.rolling(window=self.window, min_periods=self.window).std(ddof=0)
        return (c - mean) / std.replace(0.0, pd.NA)


# ---------------------------------------------------------------------------
# Min / Max
# ---------------------------------------------------------------------------


class RollingMin(Feature):
    """Rolling minimum of close."""

    category = "statistical"

    def __init__(self, window: int = 60) -> None:
        self.window = int(window)
        self.name = f"min_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        return _close(ctx).rolling(window=self.window, min_periods=self.window).min()


class RollingMax(Feature):
    """Rolling maximum of close."""

    category = "statistical"

    def __init__(self, window: int = 60) -> None:
        self.window = int(window)
        self.name = f"max_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        return _close(ctx).rolling(window=self.window, min_periods=self.window).max()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_REGISTERED_STATISTICAL = [
    register_feature(Hurst(window=60)),
    register_feature(Hurst(window=120)),
    register_feature(Autocorrelation(lag=1, window=20)),
    register_feature(Autocorrelation(lag=5, window=20)),
    register_feature(Skew(window=60)),
    register_feature(Kurt(window=60)),
    register_feature(ZScore(window=20)),
    register_feature(ZScore(window=60)),
    register_feature(RollingMin(window=60)),
    register_feature(RollingMax(window=60)),
]
"""Side-effect registration; importing this module fills BUILTIN_FEATURES."""
