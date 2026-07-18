"""Rolling volume-profile feature family (POC distance, value-area position, HVN/LVN ratio).

A volume profile is a price-level volume distribution over a trailing window:
prices between the window's low/high close are split into equal bins and each
bar's volume is assigned to the bin containing its close
(# ponytail: close-bin approximation — intrabar H-L smearing is the upgrade path).
From the histogram we derive:

- **POC** (point of control) — the center price of the highest-volume bin.
- **Value area** — the smallest contiguous set of bins around the POC (greedy:
  expand to the higher-volume neighbor) covering ≥ 70% of total volume;
  **VAH**/**VAL** are its top/bottom edges.

The pure :func:`volume_profile` helper is exported for reuse (dashboard chart
overlay, future strategy templates). The three registered features roll it
over the trailing 60-bar window; each bar ``i`` uses ONLY rows ≤ ``i``, so the
family is point-in-time safe (tamper-tested).

# ponytail: plain Python loop over bars — ~3000 bars × 24 bins is fine;
# vectorize only if the pipeline ever measures slow.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd

from services.trader.features.base import (
    BUILTIN_FEATURES,
    Feature,
    FeatureContext,
    register_feature,
)

VALUE_AREA_FRACTION = 0.70


@dataclass(frozen=True)
class ProfileResult:
    """One trailing-window volume profile."""

    poc_price: float
    vah: float
    val: float
    bin_edges: list[float]
    bin_volumes: list[float]


def _close_bin(close: float, lo: float, hi: float, bins: int) -> int:
    """Bin index of ``close`` given ``bins`` equal bins spanning [lo, hi]."""
    return min(int((close - lo) / (hi - lo) * bins), bins - 1)


def volume_profile(frame: pd.DataFrame, window: int = 60, bins: int = 24) -> ProfileResult:
    """Volume profile over the TRAILING ``window`` rows of ``frame``.

    ``frame`` needs ``close`` and ``volume`` columns. Degenerate windows
    (all-equal closes, or zero total volume) collapse to a single-bin profile
    with poc = vah = val = last close — never NaN, never raises.
    """
    tail = frame.tail(window)
    closes = tail["close"].astype("float64").to_numpy()
    volumes = tail["volume"].astype("float64").to_numpy()
    lo = float(closes.min())
    hi = float(closes.max())
    total = float(volumes.sum())
    last_close = float(closes[-1])

    if hi <= lo or total <= 0.0:
        return ProfileResult(
            poc_price=last_close,
            vah=last_close,
            val=last_close,
            bin_edges=[lo, hi],
            bin_volumes=[total],
        )

    edges = np.linspace(lo, hi, bins + 1)
    idx = np.minimum(((closes - lo) / (hi - lo) * bins).astype(np.int64), bins - 1)
    bin_volumes = np.zeros(bins, dtype="float64")
    np.add.at(bin_volumes, idx, volumes)

    poc = int(bin_volumes.argmax())
    poc_price = float((edges[poc] + edges[poc + 1]) / 2.0)

    # Greedy value area: grow the contiguous [lo_i, hi_i] span around the POC
    # toward the higher-volume neighbor until ≥ 70% of total volume is covered.
    lo_i = hi_i = poc
    covered = float(bin_volumes[poc])
    target = VALUE_AREA_FRACTION * total
    while covered < target and (lo_i > 0 or hi_i < bins - 1):
        vol_down = float(bin_volumes[lo_i - 1]) if lo_i > 0 else -1.0
        vol_up = float(bin_volumes[hi_i + 1]) if hi_i < bins - 1 else -1.0
        if vol_up >= vol_down:
            hi_i += 1
            covered += vol_up
        else:
            lo_i -= 1
            covered += vol_down

    return ProfileResult(
        poc_price=poc_price,
        vah=float(edges[hi_i + 1]),
        val=float(edges[lo_i]),
        bin_edges=[float(e) for e in edges],
        bin_volumes=[float(v) for v in bin_volumes],
    )


# ---------------------------------------------------------------------------
# Rolling features
# ---------------------------------------------------------------------------


class _RollingProfileFeature(Feature):
    """Shared rolling-apply of :func:`volume_profile`; PIT by construction —
    the value at bar ``i`` is computed from ``frame.iloc[i-window+1 : i+1]``."""

    def __init__(self, window: int = 60, bins: int = 24) -> None:
        self.window = int(window)
        self.bins = int(bins)

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        frame = ctx.frame
        closes = frame["close"].astype("float64").to_numpy()
        out = np.full(len(frame), np.nan)
        for i in range(self.window - 1, len(frame)):
            win = frame.iloc[i - self.window + 1 : i + 1]
            profile = volume_profile(win, window=self.window, bins=self.bins)
            out[i] = self._value(closes[i], profile)
        return pd.Series(out, index=frame.index, dtype="float64")

    @abstractmethod
    def _value(self, close: float, profile: ProfileResult) -> float:
        """Scalar feature value for bar ``i`` given its trailing profile."""


class PocDistanceFeature(_RollingProfileFeature):
    """Signed distance from the point of control: (close − poc_price) / close."""

    category = "volume"
    name = "poc_distance_60"
    placeholder = False

    def _value(self, close: float, profile: ProfileResult) -> float:
        return (close - profile.poc_price) / close


class ValueAreaPosFeature(_RollingProfileFeature):
    """Where close sits in the 70% value area: 0 at VAL, 1 at VAH,
    clipped to [−0.5, 1.5] (below/above the VA); vah == val → 0.5."""

    category = "volume"
    name = "value_area_pos_60"
    placeholder = False

    def _value(self, close: float, profile: ProfileResult) -> float:
        span = profile.vah - profile.val
        if span <= 0.0:
            return 0.5
        return float(np.clip((close - profile.val) / span, -0.5, 1.5))


class HvnLvnRatioFeature(_RollingProfileFeature):
    """Volume of the close's bin over the mean nonzero-bin volume (≥ 0):
    >1 means the close sits at a high-volume node, <1 at a low-volume node."""

    category = "volume"
    name = "hvn_lvn_ratio_60"
    placeholder = False

    def _value(self, close: float, profile: ProfileResult) -> float:
        nonzero = [v for v in profile.bin_volumes if v > 0.0]
        if not nonzero:  # zero-volume window — no nodes at all
            return 0.0
        if len(profile.bin_volumes) == 1:  # degenerate single-bin profile
            return 1.0
        lo, hi = profile.bin_edges[0], profile.bin_edges[-1]
        idx = _close_bin(close, lo, hi, len(profile.bin_volumes))
        return profile.bin_volumes[idx] / (sum(nonzero) / len(nonzero))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _register_if_absent(feature: Feature) -> Feature:
    """Register ``feature`` unless its name is already taken (idempotent
    across imports — same guard as ``micro.py``)."""
    if any(f.name == feature.name for f in BUILTIN_FEATURES):
        return feature
    return register_feature(feature)


_REGISTERED_VOLUME_PROFILE = [
    _register_if_absent(PocDistanceFeature()),
    _register_if_absent(ValueAreaPosFeature()),
    _register_if_absent(HvnLvnRatioFeature()),
]
"""Side-effect registration; importing this module fills BUILTIN_FEATURES."""
