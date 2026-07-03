"""Regime TransitionPredictor (Phase-4) — deterministic rules + learned overlay.

Predicts the probability that the current regime is about to transition, and toward
which label. Two layers:

- **Rules layer (always on, deterministic):** reads the recent `regime_history` and a
  `feature_row`. Rising realized volatility (`realized_vol_pct_60` high) combined with a
  sentiment flip to negative (`sentiment_score < 0`) reads as regime instability → an
  elevated probability toward a high-vol / shock label. A calm, persistent, same-label
  trending history with steady sentiment reads as stable → a low probability of leaving
  the current regime. Thresholds below are first-pass and tunable.

- **Hunter-learned overlay:** when a `HindsightClient` is enabled, `recall` a learned
  transition prior keyed on `from_label` and blend it with the rules probability (simple
  average, which shifts the estimate toward the learned value). `source="rules+learned"`.
  A recalled dict carries the prior under a numeric `prob`/`probability` key; malformed
  or empty results are ignored and the predictor stays `source="rules"`.

Graceful-offline is the contract (mirrors `HindsightClient`): `hindsight=None`/disabled
/empty recall → pure rules layer, and the predictor never raises.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from services.trader.training.hindsight_client import HindsightClient

# --- rules thresholds (first-pass, tunable) --------------------------------

# realized_vol_pct_60 is a percentile in [0, 100]; at/above this reads as "high vol".
_VOL_HIGH_PCT = 75.0
# sentiment_score ∈ [-1, 1]; strictly below this counts as a negative flip.
_SENTIMENT_NEGATIVE = 0.0
# Elevated probability assigned when instability is detected (high vol + neg flip).
_PROB_ELEVATED = 0.7
# Low baseline probability of transitioning out of a stable, persistent regime.
_PROB_STABLE = 0.15
# Middling default when signals are mixed / inputs missing.
_PROB_DEFAULT = 0.4
# The label the rules layer routes toward under detected instability.
_SHOCK_LABEL = "high_vol"
# Fallback from_label when history is empty.
_UNKNOWN_LABEL = "undefined"


@dataclass(frozen=True)
class Transition:
    """A predicted regime transition.

    `prob` ∈ [0, 1] is the probability of transitioning; `from_label` is the current
    regime (last element of history), `to_label` the predicted target; `source` is
    `"rules"` (deterministic layer only) or `"rules+learned"` (Hindsight-blended).
    """

    prob: float
    from_label: str
    to_label: str
    source: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.prob <= 1.0:
            raise ValueError(f"prob out of [0, 1]: {self.prob}")


class TransitionPredictor:
    """Rules-first regime transition predictor with an optional learned overlay."""

    def __init__(self, hindsight: HindsightClient | None = None) -> None:
        self._hindsight = hindsight

    def predict(
        self,
        regime_history: list[str],
        feature_row: pd.Series,
    ) -> Transition:
        """Predict the next regime transition; never raises offline."""
        from_label = regime_history[-1] if regime_history else _UNKNOWN_LABEL
        rules_prob, to_label = self._rules_layer(regime_history, feature_row, from_label)

        learned = self._learned_prior(from_label)
        if learned is None:
            return Transition(
                prob=_clip(rules_prob, 0.0, 1.0),
                from_label=from_label,
                to_label=to_label,
                source="rules",
            )

        # Blend: average shifts the estimate toward the learned prior.
        blended = _clip(0.5 * (rules_prob + learned), 0.0, 1.0)
        # A high learned prior of instability points toward the shock label.
        blended_to = _SHOCK_LABEL if learned > rules_prob else to_label
        return Transition(
            prob=blended,
            from_label=from_label,
            to_label=blended_to,
            source="rules+learned",
        )

    # --- rules layer --------------------------------------------------------

    def _rules_layer(
        self,
        regime_history: list[str],
        feature_row: pd.Series,
        from_label: str,
    ) -> tuple[float, str]:
        vol_pct = _safe_float(feature_row.get("realized_vol_pct_60"))
        sentiment = _safe_float(feature_row.get("sentiment_score"))

        if vol_pct is None or sentiment is None:
            return _PROB_DEFAULT, from_label

        # Instability: elevated realized vol AND a flip to negative sentiment.
        if vol_pct >= _VOL_HIGH_PCT and sentiment < _SENTIMENT_NEGATIVE:
            return _PROB_ELEVATED, _SHOCK_LABEL

        # Stable: calm vol, non-negative sentiment, and a persistent same-label
        # trend → low probability of leaving the current regime.
        persistent = len(regime_history) >= 2 and len(set(regime_history[-3:])) == 1
        if (
            vol_pct < _VOL_HIGH_PCT
            and sentiment >= _SENTIMENT_NEGATIVE
            and persistent
        ):
            return _PROB_STABLE, from_label

        # Mixed signals: middling probability, stay in the current label.
        return _PROB_DEFAULT, from_label

    # --- learned overlay ----------------------------------------------------

    def _learned_prior(self, from_label: str) -> float | None:
        """Recall a learned transition prior for `from_label`; None if unavailable."""
        if self._hindsight is None or not self._hindsight.is_enabled():
            return None
        results = self._hindsight.recall(f"regime transition {from_label}", k=5)
        if not results:
            return None
        for result in results:
            if not isinstance(result, dict):
                continue
            for key in ("prob", "probability"):
                prior = _safe_float(result.get(key))
                if prior is not None and 0.0 <= prior <= 1.0:
                    return prior
        return None


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
