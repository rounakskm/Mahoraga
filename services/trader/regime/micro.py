"""MICRO regime lens — short-horizon momentum / reversal / shock.

Rule-based, filling `CompositeRegime.micro`. Reads Phase-4 features:

- `shock`    : extreme-negative sentiment AND a high volume surge — a
  panic/news-shock bar. Confidence from how far past both thresholds.
- `momentum` : `roc_3` and `roc_5` agree in sign AND sentiment agrees
  in sign with them, with meaningful magnitude. Confidence from
  agreement + magnitude.
- `reversal` : short-term price momentum (`roc_3`) opposes the
  sentiment sign — a mean-reversion setup. Confidence from divergence
  magnitude.
- else       : low-confidence `undefined`.

Undefined (confidence 0) when any required input is NaN.

`roc_3` / `roc_5` are both percentage-convention (`100 * pct_change`),
same scale — safe to compare magnitudes. `sentiment_score` ∈ [-1, 1];
`volume_surge` is a ratio (~1.0 normal, >1 surge); `realized_vol_pct_60`
is a percentile. Thresholds are first-pass and tunable.
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

# Shock: sentiment at/below this AND volume_surge at/above this.
_SHOCK_SENTIMENT = -0.5
_SHOCK_VOLUME_SURGE = 1.8

# Momentum: |roc_5| must clear this (percentage points) to be meaningful.
_ROC_MIN_MAGNITUDE = 0.5
# Sentiment must clear this magnitude to count as directional.
_SENTIMENT_MIN_MAGNITUDE = 0.1

# Confidence normalizers — divide magnitudes by these to map into [0, 1].
_ROC_CONF_SCALE = 5.0  # ~5% ROC over the window reads as full-strength.
_VOLUME_CONF_SCALE = 2.0  # surge of 2x over the shock floor reads as full.


class MicroLens(Lens):
    """MICRO-scale regime classifier (intraday-to-few-day timescale)."""

    name: ClassVar[str] = "micro"

    def required_features(self) -> list[str]:
        return [
            "sentiment_score",
            "roc_3",
            "roc_5",
            "volume_surge",
            "realized_vol_pct_60",
        ]

    def classify(
        self,
        *,
        feature_row: pd.Series,
        macro_row: pd.Series | None = None,  # unused; kept for ABC parity
    ) -> ClassificationResult:
        sentiment = _safe_float(feature_row.get("sentiment_score"))
        roc_3 = _safe_float(feature_row.get("roc_3"))
        roc_5 = _safe_float(feature_row.get("roc_5"))
        volume_surge = _safe_float(feature_row.get("volume_surge"))
        vol_pct = _safe_float(feature_row.get("realized_vol_pct_60"))
        if (
            sentiment is None
            or roc_3 is None
            or roc_5 is None
            or volume_surge is None
            or vol_pct is None
        ):
            return ClassificationResult(
                label=UNDEFINED_LABEL,
                confidence=0.0,
                inputs={},
            )

        inputs = {
            "sentiment_score": sentiment,
            "roc_3": roc_3,
            "roc_5": roc_5,
            "volume_surge": volume_surge,
            "realized_vol_pct_60": vol_pct,
        }

        # --- shock: extreme-negative sentiment AND high volume surge ---
        if (
            sentiment <= _SHOCK_SENTIMENT
            and volume_surge >= _SHOCK_VOLUME_SURGE
        ):
            sentiment_conf = _clip(
                abs(sentiment) - abs(_SHOCK_SENTIMENT), 0.0, 1.0
            )
            volume_conf = _clip(
                (volume_surge - _SHOCK_VOLUME_SURGE) / _VOLUME_CONF_SCALE,
                0.0,
                1.0,
            )
            confidence = _clip(
                max(sentiment_conf, volume_conf), 0.0, 1.0
            )
            return ClassificationResult(
                label="shock", confidence=confidence, inputs=inputs
            )

        sentiment_sign = _sign(sentiment, _SENTIMENT_MIN_MAGNITUDE)
        roc_3_sign = _sign(roc_3, 0.0)
        roc_5_sign = _sign(roc_5, 0.0)

        # --- momentum: roc_3, roc_5 and sentiment all agree in sign ---
        if (
            roc_3_sign != 0
            and roc_3_sign == roc_5_sign == sentiment_sign
            and abs(roc_5) >= _ROC_MIN_MAGNITUDE
        ):
            roc_conf = _clip(abs(roc_5) / _ROC_CONF_SCALE, 0.0, 1.0)
            sentiment_conf = _clip(abs(sentiment), 0.0, 1.0)
            # Reward alignment: average the two directional strengths.
            confidence = _clip(0.5 * (roc_conf + sentiment_conf), 0.0, 1.0)
            return ClassificationResult(
                label="momentum", confidence=confidence, inputs=inputs
            )

        # --- reversal: short-term momentum opposes sentiment sign ---
        if (
            sentiment_sign != 0
            and roc_3_sign != 0
            and roc_3_sign != sentiment_sign
        ):
            roc_conf = _clip(abs(roc_3) / _ROC_CONF_SCALE, 0.0, 1.0)
            sentiment_conf = _clip(abs(sentiment), 0.0, 1.0)
            confidence = _clip(0.5 * (roc_conf + sentiment_conf), 0.0, 1.0)
            return ClassificationResult(
                label="reversal", confidence=confidence, inputs=inputs
            )

        # --- else: no clean signal ---
        return ClassificationResult(
            label=UNDEFINED_LABEL, confidence=0.0, inputs=inputs
        )


def _sign(value: float, deadband: float) -> int:
    """+1 / -1 for values outside the deadband, 0 inside it."""
    if value > deadband:
        return 1
    if value < -deadband:
        return -1
    return 0


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
