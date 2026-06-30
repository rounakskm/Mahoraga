"""LLM mutator: JSON parsing, validation, and the safety fallback. No network —
the chat call is stubbed, so a flaky/hallucinating LLM is simulated deterministically.
"""

from __future__ import annotations

import numpy as np

from services.trader.training.llm import LLMMutator
from services.trader.training.strategy_template import REGIMES, RegimeConditionalStrategy

GOOD = '{"trending_low_vol":170,"trending_high_vol":150,"ranging_low_vol":70,"ranging_high_vol":40}'


class _Fake(LLMMutator):
    """LLMMutator whose chat reply is canned (or raises, to test fallback)."""

    def __init__(self, reply):
        super().__init__(api_key="x")
        self._reply = reply

    def _chat(self, user):
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


def _cur():
    return RegimeConditionalStrategy.seed()


def test_parse_extracts_json_from_prose():
    assert LLMMutator._parse("sure thing: " + GOOD + " — good luck")["ranging_low_vol"] == 70


def test_validate_accepts_and_rejects():
    assert LLMMutator._validate({k: 100 for k in REGIMES}).windows["trending_low_vol"] == 100
    assert LLMMutator._validate({"x": 100}) is None                  # wrong keys
    assert LLMMutator._validate({k: 9999 for k in REGIMES}) is None  # out of range
    assert LLMMutator._validate({k: "abc" for k in REGIMES}) is None  # non-numeric


def test_good_reply_becomes_the_candidate():
    cand = _Fake(GOOD)(_cur(), [], np.random.default_rng(0))
    assert cand.windows["trending_low_vol"] == 170 and set(cand.windows) == set(REGIMES)


def test_bad_json_falls_back_to_single_change_mechanical():
    cur = _cur()
    cand = _Fake("no json here")(cur, [], np.random.default_rng(0))
    changed = [k for k in cur.windows if cur.windows[k] != cand.windows[k]]
    assert len(changed) == 1  # mechanical fallback = exactly one regime nudged


def test_network_error_falls_back_without_raising():
    cand = _Fake(RuntimeError("boom"))(_cur(), [], np.random.default_rng(1))
    assert set(cand.windows) == set(REGIMES)  # returned a valid strategy, no exception
