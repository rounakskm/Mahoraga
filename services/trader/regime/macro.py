"""MACRO regime lens — bull / bear / transitioning.

Rule-based per `regime-detector-spec.md` §3:

- curve_signal: +1 if `yield_2s10s > 0`; -1 if inverted (<= 0)
- vix_signal:   +1 if `vix_level < 18`; -1 if `vix_level > 25`; 0 otherwise
- dxy_signal:   +1 if `dxy_change_20d < 0` (USD weakening); -1 otherwise

`macro_score = (curve_signal + vix_signal + dxy_signal) / 3` in [-1, 1].

- `bull` when `macro_score >= 0.50`
- `bear` when `macro_score <= -0.50`
- `transitioning` otherwise

`macro_conf = abs(macro_score)`.
"""

from __future__ import annotations

import math
from typing import ClassVar

import pandas as pd

from services.trader.regime.base import (
    UNDEFINED_LABEL,
    ClassificationResult,
    Lens,
)

_VIX_LOW = 18.0
_VIX_HIGH = 25.0
_BULL_THRESHOLD = 0.50
_BEAR_THRESHOLD = -0.50


class MacroLens(Lens):
    """MACRO-scale regime classifier (3-to-18-month timescale)."""

    name: ClassVar[str] = "macro"

    def required_features(self) -> list[str]:
        # Macro features land in the macro-side parquet read by the
        # detector's macro_lookup; the lens reads them off the
        # `macro_row` Series passed in.
        return ["yield_2s10s", "vix_level", "dxy_change_20d"]

    def classify(
        self,
        *,
        feature_row: pd.Series,  # unused — kept for ABC parity
        macro_row: pd.Series | None,
    ) -> ClassificationResult:
        if macro_row is None:
            return ClassificationResult(
                label=UNDEFINED_LABEL, confidence=0.0, inputs={}
            )
        slope = _safe_float(macro_row.get("yield_2s10s"))
        vix = _safe_float(macro_row.get("vix_level"))
        dxy = _safe_float(macro_row.get("dxy_change_20d"))
        if slope is None or vix is None or dxy is None:
            return ClassificationResult(
                label=UNDEFINED_LABEL, confidence=0.0, inputs={}
            )

        curve_signal = 1.0 if slope > 0 else -1.0
        if vix < _VIX_LOW:
            vix_signal = 1.0
        elif vix > _VIX_HIGH:
            vix_signal = -1.0
        else:
            vix_signal = 0.0
        dxy_signal = 1.0 if dxy < 0 else -1.0

        macro_score = (curve_signal + vix_signal + dxy_signal) / 3.0
        if macro_score >= _BULL_THRESHOLD:
            label = "bull"
        elif macro_score <= _BEAR_THRESHOLD:
            label = "bear"
        else:
            label = "transitioning"

        return ClassificationResult(
            label=label,
            confidence=abs(macro_score),
            inputs={
                "yield_2s10s": slope,
                "vix_level": vix,
                "dxy_change_20d": dxy,
            },
        )


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f
