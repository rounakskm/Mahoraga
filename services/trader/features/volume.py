"""Volume-category features.

Ten features per `feature-pipeline-spec.md` §2:

- obv
- vwap_dev_5, vwap_dev_20
- mfi_14
- volume_sma_20, volume_sma_50
- volume_z_20
- dollar_volume_20
- cmf_20
- force_index_13
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


def _close(ctx: FeatureContext) -> pd.Series:
    return ctx.frame["close"].astype("float64").reset_index(drop=True)


def _volume(ctx: FeatureContext) -> pd.Series:
    return ctx.frame["volume"].astype("float64").reset_index(drop=True)


def _ohlcv(
    ctx: FeatureContext,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    f = ctx.frame
    return (
        f["high"].astype("float64").reset_index(drop=True),
        f["low"].astype("float64").reset_index(drop=True),
        f["close"].astype("float64").reset_index(drop=True),
        f["volume"].astype("float64").reset_index(drop=True),
    )


# ---------------------------------------------------------------------------
# OBV — On-Balance Volume
# ---------------------------------------------------------------------------


class OBV(Feature):
    """On-Balance Volume: cumulative volume signed by close-to-close direction."""

    category = "volume"
    name = "obv"

    def required_history_bars(self) -> int:
        return 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        v = _volume(ctx)
        direction = np.sign(c.diff()).fillna(0.0)
        return (direction * v).cumsum()


# ---------------------------------------------------------------------------
# VWAP deviation
# ---------------------------------------------------------------------------


class VWAPDeviation(Feature):
    """(close - rolling VWAP) / close. VWAP = sum(close*volume) / sum(volume)."""

    category = "volume"

    def __init__(self, window: int) -> None:
        self.window = int(window)
        self.name = f"vwap_dev_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        v = _volume(ctx)
        pv = (c * v).rolling(window=self.window, min_periods=self.window).sum()
        tv = v.rolling(window=self.window, min_periods=self.window).sum()
        vwap = pv / tv.replace(0.0, pd.NA)
        return (c - vwap) / c.replace(0.0, pd.NA)


# ---------------------------------------------------------------------------
# MFI — Money Flow Index
# ---------------------------------------------------------------------------


class MFI(Feature):
    """Money Flow Index (Wilder smoothing replaced by simple rolling sums, per the
    canonical "raw money flow" definition).
    """

    category = "volume"

    def __init__(self, window: int = 14) -> None:
        self.window = int(window)
        self.name = f"mfi_{self.window}"

    def required_history_bars(self) -> int:
        return self.window + 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        high, low, close, volume = _ohlcv(ctx)
        typical = (high + low + close) / 3.0
        raw_flow = typical * volume
        direction = np.sign(typical.diff()).fillna(0.0)
        positive_flow = raw_flow.where(direction > 0, 0.0)
        negative_flow = raw_flow.where(direction < 0, 0.0)
        pos_sum = positive_flow.rolling(window=self.window, min_periods=self.window).sum()
        neg_sum = negative_flow.rolling(window=self.window, min_periods=self.window).sum()
        ratio = pos_sum / neg_sum.replace(0.0, pd.NA)
        mfi = 100.0 - 100.0 / (1.0 + ratio)
        # When neg_sum == 0 and pos_sum > 0, MFI = 100; both zero -> 50 (neutral).
        mfi = mfi.where(neg_sum != 0.0, 100.0)
        mfi = mfi.where((pos_sum != 0.0) | (neg_sum != 0.0), 50.0)
        return mfi.astype("float64")


# ---------------------------------------------------------------------------
# Volume SMA + Z-score
# ---------------------------------------------------------------------------


class VolumeSMA(Feature):
    """Simple moving average of volume."""

    category = "volume"

    def __init__(self, window: int) -> None:
        self.window = int(window)
        self.name = f"volume_sma_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        return _volume(ctx).rolling(window=self.window, min_periods=self.window).mean()


class VolumeZScore(Feature):
    """(volume - rolling_mean) / rolling_std over the same window."""

    category = "volume"

    def __init__(self, window: int = 20) -> None:
        self.window = int(window)
        self.name = f"volume_z_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        v = _volume(ctx)
        mean = v.rolling(window=self.window, min_periods=self.window).mean()
        std = v.rolling(window=self.window, min_periods=self.window).std(ddof=0)
        return (v - mean) / std.replace(0.0, pd.NA)


# ---------------------------------------------------------------------------
# Dollar volume
# ---------------------------------------------------------------------------


class DollarVolume(Feature):
    """Rolling mean of close × volume."""

    category = "volume"

    def __init__(self, window: int = 20) -> None:
        self.window = int(window)
        self.name = f"dollar_volume_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        v = _volume(ctx)
        return (c * v).rolling(window=self.window, min_periods=self.window).mean()


# ---------------------------------------------------------------------------
# Chaikin Money Flow
# ---------------------------------------------------------------------------


class CMF(Feature):
    """Chaikin Money Flow: sum(MF Volume) / sum(volume) over the window."""

    category = "volume"

    def __init__(self, window: int = 20) -> None:
        self.window = int(window)
        self.name = f"cmf_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        high, low, close, volume = _ohlcv(ctx)
        denom = (high - low).replace(0.0, pd.NA)
        mf_mult = ((close - low) - (high - close)) / denom
        mf_volume = mf_mult * volume
        mf_volume = mf_volume.fillna(0.0)
        return (
            mf_volume.rolling(window=self.window, min_periods=self.window).sum()
            / volume.rolling(window=self.window, min_periods=self.window).sum().replace(0.0, pd.NA)
        )


# ---------------------------------------------------------------------------
# Force Index (EMA-smoothed)
# ---------------------------------------------------------------------------


class ForceIndex(Feature):
    """Force Index: ema(span) of (close - close.shift(1)) * volume."""

    category = "volume"

    def __init__(self, window: int = 13) -> None:
        self.window = int(window)
        self.name = f"force_index_{self.window}"

    def required_history_bars(self) -> int:
        return self.window + 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        c = _close(ctx)
        v = _volume(ctx)
        raw = c.diff() * v
        return raw.ewm(span=self.window, adjust=False).mean()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_REGISTERED_VOLUME = [
    register_feature(OBV()),
    register_feature(VWAPDeviation(window=5)),
    register_feature(VWAPDeviation(window=20)),
    register_feature(MFI(window=14)),
    register_feature(VolumeSMA(window=20)),
    register_feature(VolumeSMA(window=50)),
    register_feature(VolumeZScore(window=20)),
    register_feature(DollarVolume(window=20)),
    register_feature(CMF(window=20)),
    register_feature(ForceIndex(window=13)),
]
"""Side-effect registration; importing this module fills BUILTIN_FEATURES."""
