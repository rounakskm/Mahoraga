"""MICRO-lens momentum + volume features.

Two fast, short-horizon inputs to the MICRO regime lens (see Phase-4 plan
Task 4 / Task 6):

- ``roc_3`` / ``roc_5`` — fractional rate-of-change of close over N bars,
  i.e. ``close.pct_change(N)`` (a return, not a percentage). This is the
  MICRO lens's short-momentum signal; it is intentionally the plain
  ``pct_change`` form rather than the ``100 * ...`` percentage that
  ``momentum.ROC`` emits.
- ``volume_surge`` — current volume divided by its trailing rolling mean;
  a value near 1.0 is normal flow, >1 is a surge.

All values at bar ``i`` use only data at or before ``i`` (``pct_change`` and
``rolling`` look strictly backward), so the features are point-in-time safe.
"""

from __future__ import annotations

import pandas as pd

from services.trader.features.base import (
    BUILTIN_FEATURES,
    Feature,
    FeatureContext,
    register_feature,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _close(ctx: FeatureContext) -> pd.Series:
    return ctx.frame["close"].astype("float64")


def _volume(ctx: FeatureContext) -> pd.Series:
    return ctx.frame["volume"].astype("float64")


# ---------------------------------------------------------------------------
# Rate of Change (fractional)
# ---------------------------------------------------------------------------


class RocFeature(Feature):
    """Fractional rate-of-change of close: ``close.pct_change(window)``.

    Unlike ``momentum.ROC`` (which multiplies by 100), this returns the raw
    fractional return over ``window`` bars, matching the MICRO-lens contract.
    """

    category = "momentum"
    placeholder = False

    def __init__(self, window: int) -> None:
        self.window = int(window)
        self.name = f"roc_{self.window}"

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        return _close(ctx).pct_change(self.window).astype("float64")


# ---------------------------------------------------------------------------
# Volume surge
# ---------------------------------------------------------------------------


class VolumeSurgeFeature(Feature):
    """Ratio of current volume to its trailing rolling mean.

    ``volume / volume.rolling(window).mean()`` — 1.0 is average flow, values
    above 1 indicate a surge. Non-negative wherever defined (volume >= 0);
    NaN only during the ``window - 1`` warmup bars.
    """

    category = "volume"
    name = "volume_surge"
    placeholder = False

    def __init__(self, window: int = 20) -> None:
        self.window = int(window)

    def required_history_bars(self) -> int:
        return self.window

    def compute(self, ctx: FeatureContext) -> pd.Series:
        v = _volume(ctx)
        mean = v.rolling(self.window).mean()
        return (v / mean).astype("float64")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _register_if_absent(feature: Feature) -> Feature:
    """Register ``feature`` unless its name is already taken.

    ``momentum.py`` already registers a ``roc_5`` (the percentage variant), so a
    plain ``register_feature`` here would raise on the duplicate name whenever
    both modules are imported. The MICRO features are additive; skip any name
    that is already present rather than crash the registry at import time.
    """
    if any(f.name == feature.name for f in BUILTIN_FEATURES):
        return feature
    return register_feature(feature)


_REGISTERED_MICRO = [
    _register_if_absent(RocFeature(window=3)),
    _register_if_absent(RocFeature(window=5)),
    _register_if_absent(VolumeSurgeFeature(window=20)),
]
"""Side-effect registration; importing this module fills BUILTIN_FEATURES."""
