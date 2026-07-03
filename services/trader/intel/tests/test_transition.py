"""TransitionPredictor (Phase-4) — deterministic rules layer + Hindsight overlay.

The rules layer is always on and pure: recent regime_history + a feature_row drive
an elevated transition probability toward a high-vol/shock label (rising realized
vol + a sentiment flip to negative), or a low probability of staying in a stable
trending regime. The Hunter-learned overlay only engages when `hindsight` is enabled;
it recalls a learned prior and blends it, setting `source="rules+learned"`. Offline
(`hindsight=None`/disabled/empty recall) the predictor is `source="rules"` and never
raises. All fakes are in-memory — no network.
"""

from __future__ import annotations

import pandas as pd

from services.trader.intel.transition import Transition, TransitionPredictor
from services.trader.training.hindsight_client import HindsightClient


class _FakeHindsight(HindsightClient):
    """Enabled Hindsight returning a canned learned prior. No network."""

    def __init__(self, recall_return: list[dict]) -> None:
        super().__init__(base_url="http://hindsight:8888")
        self.recall_calls: list[tuple[str, int]] = []
        self.recall_return = recall_return

    def recall(self, query: str, k: int = 5) -> list[dict]:
        self.recall_calls.append((query, k))
        return list(self.recall_return)


def _rising_vol_negative_flip() -> pd.Series:
    return pd.Series(
        {
            "realized_vol_pct_60": 92.0,  # high realized-vol percentile (0-100 scale)
            "sentiment_score": -0.6,  # flipped negative
        }
    )


def _stable_trending() -> pd.Series:
    return pd.Series(
        {
            "realized_vol_pct_60": 20.0,  # calm (0-100 scale)
            "sentiment_score": 0.35,  # steady positive
        }
    )


# --- rules layer, offline (hindsight=None) ---------------------------------


def test_rising_vol_negative_flip_elevates_prob_toward_shock() -> None:
    history = ["trending_up", "trending_up", "choppy"]
    t = TransitionPredictor(hindsight=None).predict(history, _rising_vol_negative_flip())

    assert isinstance(t, Transition)
    assert t.source == "rules"
    assert t.from_label == "choppy"
    assert t.prob > 0.5
    assert t.to_label in {"high_vol", "shock"}
    assert 0.0 <= t.prob <= 1.0


def test_stable_trending_history_low_prob_same_label() -> None:
    history = ["trending_up", "trending_up", "trending_up"]
    t = TransitionPredictor(hindsight=None).predict(history, _stable_trending())

    assert t.source == "rules"
    assert t.from_label == "trending_up"
    assert t.prob < 0.3
    assert t.to_label == "trending_up"


def test_empty_history_never_raises() -> None:
    t = TransitionPredictor(hindsight=None).predict([], _stable_trending())
    assert isinstance(t, Transition)
    assert t.source == "rules"
    assert 0.0 <= t.prob <= 1.0


# --- Hunter-learned overlay -------------------------------------------------


def test_learned_prior_shifts_prob_and_marks_source() -> None:
    hs = _FakeHindsight([{"prob": 0.9, "text": "shock followed high-vol"}])
    # Rules alone here are low (stable trending); a 0.9 learned prior must pull up.
    rules_only = TransitionPredictor(hindsight=None).predict(
        ["trending_up", "trending_up", "trending_up"], _stable_trending()
    )
    blended = TransitionPredictor(hindsight=hs).predict(
        ["trending_up", "trending_up", "trending_up"], _stable_trending()
    )

    assert blended.source == "rules+learned"
    assert hs.recall_calls, "overlay must recall"
    query, _k = hs.recall_calls[0]
    assert "trending_up" in query  # from_label in the query
    assert blended.prob > rules_only.prob  # shifted toward 0.9
    assert 0.0 <= blended.prob <= 1.0


def test_learned_prior_accepts_probability_key() -> None:
    hs = _FakeHindsight([{"probability": 0.8}])
    t = TransitionPredictor(hindsight=hs).predict(["choppy"], _stable_trending())
    assert t.source == "rules+learned"
    assert (
        t.prob
        > TransitionPredictor(hindsight=None)
        .predict(["choppy"], _stable_trending())
        .prob
    )


def test_malformed_recall_falls_back_to_rules() -> None:
    hs = _FakeHindsight([{"text": "no numeric prob here"}, {"prob": "NaN-ish"}])
    t = TransitionPredictor(hindsight=hs).predict(["choppy"], _stable_trending())
    assert t.source == "rules"  # nothing usable recalled


def test_empty_recall_is_rules_only() -> None:
    hs = _FakeHindsight([])
    t = TransitionPredictor(hindsight=hs).predict(["choppy"], _stable_trending())
    assert t.source == "rules"


def test_disabled_client_is_rules_only() -> None:
    t = TransitionPredictor(hindsight=HindsightClient(None)).predict(
        ["choppy"], _stable_trending()
    )
    assert t.source == "rules"
