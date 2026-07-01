"""MICRO-lens momentum + volume features.

Fast, short-horizon inputs to the MICRO regime lens (see Phase-4 plan Task 4 /
Task 6):

- ``roc_3`` — 3-bar rate-of-change of close, registered via the *existing*
  ``momentum.ROC`` class so it shares that module's convention
  (``100 * pct_change``). ``momentum.py`` already ships ``roc_5``/``roc_10``/
  ``roc_20``; the MICRO lens's short-momentum signal only needs the extra
  ``roc_3``. Reusing ``ROC`` keeps ``roc_3`` and ``roc_5`` on the SAME scale so
  the lens can compare their magnitudes (a fractional variant here would be
  100x off from ``roc_5`` and silently break momentum-strength comparisons).
- ``volume_surge`` — current volume divided by its trailing rolling mean; a
  value near 1.0 is normal flow, >1 is a surge.

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
from services.trader.features.momentum import ROC

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
        v = ctx.frame["volume"].astype("float64")
        mean = v.rolling(self.window).mean()
        return (v / mean).astype("float64")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _register_if_absent(feature: Feature) -> Feature:
    """Register ``feature`` unless its name is already taken (idempotent across
    imports; ``momentum.py`` owns ``roc_5``+, this module only adds ``roc_3``)."""
    if any(f.name == feature.name for f in BUILTIN_FEATURES):
        return feature
    return register_feature(feature)


_REGISTERED_MICRO = [
    _register_if_absent(ROC(3)),  # roc_3 — same 100*pct_change scale as roc_5
    _register_if_absent(VolumeSurgeFeature(window=20)),
]
"""Side-effect registration; importing this module fills BUILTIN_FEATURES."""
