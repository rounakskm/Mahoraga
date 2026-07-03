"""MESO regime lens — trend × volatility cross.

Rule-based per `regime-detector-spec.md` §2. `realized_vol_pct_60` is a
percentile rank on the 0-100 scale; the 40th-percentile threshold (the
long-run median split) divides low-vol from high-vol:

- `trending_low_vol`  : `adx_14 >= 25` AND `realized_vol_pct_60 <= 40`
- `trending_high_vol` : `adx_14 >= 25` AND `realized_vol_pct_60 > 40`
- `ranging_low_vol`   : `adx_14 < 25`  AND `realized_vol_pct_60 <= 40`
- `ranging_high_vol`  : `adx_14 < 25`  AND `realized_vol_pct_60 > 40`

Confidence is the minimum of two normalized distances to the
thresholds; undefined when either input is NaN.
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

_ADX_THRESHOLD = 25.0
# realized_vol_pct_60 is on the 0-100 percentile scale (see features/volatility.py).
_VOL_THRESHOLD = 40.0


class MesoLens(Lens):
    """MESO-scale regime classifier (2-to-8-week timescale)."""

    name: ClassVar[str] = "meso"

    def required_features(self) -> list[str]:
        return ["adx_14", "realized_vol_pct_60"]

    def classify(
        self,
        *,
        feature_row: pd.Series,
        macro_row: pd.Series | None,  # unused; kept for ABC parity
    ) -> ClassificationResult:
        adx = _safe_float(feature_row.get("adx_14"))
        vol_pct = _safe_float(feature_row.get("realized_vol_pct_60"))
        if adx is None or vol_pct is None:
            return ClassificationResult(
                label=UNDEFINED_LABEL,
                confidence=0.0,
                inputs={},
            )

        trend_axis = "trending" if adx >= _ADX_THRESHOLD else "ranging"
        vol_axis = "high_vol" if vol_pct > _VOL_THRESHOLD else "low_vol"
        label = f"{trend_axis}_{vol_axis}"

        # Distance-to-threshold, normalized to [-1, 1]; magnitude is
        # the per-axis confidence. The lens confidence is the minimum
        # of the two — i.e. how cleanly the input falls inside the
        # quadrant.
        trend_conf = _clip((adx - _ADX_THRESHOLD) / _ADX_THRESHOLD, -1.0, 1.0)
        vol_conf = _clip(
            (vol_pct - _VOL_THRESHOLD) / _VOL_THRESHOLD, -1.0, 1.0
        )
        confidence = min(abs(trend_conf), abs(vol_conf))

        return ClassificationResult(
            label=label,
            confidence=confidence,
            inputs={"adx_14": adx, "realized_vol_pct_60": vol_pct},
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


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
