"""Tests for the Planner / Reviewer / Guardian research roles (Phase-3 Layer-3).

Deterministic + offline: no LLM, no live Hindsight. Planner falls back to the
mechanical mutator; a fake HindsightClient stubs `do-not-repeat` recall.
"""

from __future__ import annotations

from services.trader.training.hindsight_client import HindsightClient
from services.trader.training.parse_metric import FitnessReport
from services.trader.training.provenance import candidate_hash
from services.trader.training.roles import (
    Decision,
    Guardian,
    Planner,
    Reviewer,
    strategy_params,
)
from services.trader.training.strategy_template import RegimeConditionalStrategy


def _report(**kw) -> FitnessReport:
    base = dict(
        candidate_hash="abc",
        params={"trending_low_vol": 200},
        sharpe=1.0,
        fitness=1.0,
        quarterly_win_rate=0.6,
        max_drawdown=-0.05,
        promoted=True,
        reason="fortress + vault passed",
    )
    base.update(kw)
    return FitnessReport(**base)


class _FakeHindsight(HindsightClient):
    """Recall returns one forbidden candidate_hash; never touches the network."""

    def __init__(self, forbidden: str, *, nested: bool = False) -> None:
        super().__init__(base_url="http://stub")  # enabled, but _post unused
        self._forbidden = forbidden
        self._nested = nested

    def recall(self, query: str, k: int = 5) -> list[dict]:
        if self._nested:  # the real recall API shape: hash inside `metadata`
            return [{"id": "f1", "text": f"do-not-repeat {self._forbidden}: dup",
                     "metadata": {"candidate_hash": self._forbidden}}]
        return [{"candidate_hash": self._forbidden}]


# --- Planner ---------------------------------------------------------------


def test_planner_returns_n_distinct_single_change_candidates():
    current = RegimeConditionalStrategy.seed()
    queue = Planner().propose_queue(current, "trending_low_vol", n=3, seed=0)
    assert len(queue) == 3
    hashes = {candidate_hash(strategy_params(c)) for c in queue}
    assert len(hashes) == 3  # all distinct
    for c in queue:
        assert _single_change(c, current)  # each differs by exactly one field


def test_planner_drops_a_do_not_repeat_hash():
    current = RegimeConditionalStrategy.seed()
    # Discover what the first proposed candidate would be, then forbid it.
    first = Planner().propose_queue(current, "x", n=1, seed=7)[0]
    forbidden = candidate_hash(strategy_params(first))
    planner = Planner(hindsight=_FakeHindsight(forbidden))
    queue = planner.propose_queue(current, "x", n=3, seed=7)
    assert len(queue) == 3
    out = {candidate_hash(strategy_params(c)) for c in queue}
    assert forbidden not in out  # the forbidden hash never appears


def test_planner_drops_a_metadata_nested_do_not_repeat_hash():
    # The real Hindsight recall returns user metadata NESTED under `metadata`;
    # the Planner must still drop the forbidden candidate.
    current = RegimeConditionalStrategy.seed()
    first = Planner().propose_queue(current, "x", n=1, seed=7)[0]
    forbidden = candidate_hash(strategy_params(first))
    planner = Planner(hindsight=_FakeHindsight(forbidden, nested=True))
    queue = planner.propose_queue(current, "x", n=3, seed=7)
    assert len(queue) == 3
    out = {candidate_hash(strategy_params(c)) for c in queue}
    assert forbidden not in out


# --- Reviewer --------------------------------------------------------------


def test_reviewer_rejects_a_two_change_hypothesis():
    current = RegimeConditionalStrategy.seed()
    two = RegimeConditionalStrategy(
        {**current.windows, "ranging_low_vol": 80, "ranging_high_vol": 60},
    )
    d = Reviewer().check(two, current, recent_hashes=set())
    assert d.approved is False
    assert "one" in d.reason.lower()


def test_reviewer_rejects_a_duplicate():
    current = RegimeConditionalStrategy.seed()
    cand = RegimeConditionalStrategy({**current.windows, "ranging_low_vol": 70})
    dup = candidate_hash(strategy_params(cand))
    d = Reviewer().check(cand, current, recent_hashes={dup})
    assert d.approved is False
    assert "duplicate" in d.reason.lower()


def test_reviewer_approves_a_clean_single_change():
    current = RegimeConditionalStrategy.seed()
    cand = RegimeConditionalStrategy({**current.windows, "ranging_low_vol": 70})
    d = Reviewer().check(cand, current, recent_hashes=set())
    assert d.approved is True


# --- Guardian --------------------------------------------------------------


def test_guardian_vetoes_a_non_promoted_report():
    d = Guardian().review(_report(promoted=False, reason="fortress rejected"))
    assert d.approved is False
    assert d.halt is False
    assert "fortress rejected" in d.reason


def test_guardian_does_not_halt_on_deep_backtest_drawdown():
    # A promoted candidate with a deep *backtest* drawdown is approved and does NOT
    # halt the fleet: backtest DD is not the live realized-loss kill-switch. The
    # fortress already judged risk before promotion.
    d = Guardian().review(_report(promoted=True, max_drawdown=-0.30))
    assert d.approved is True
    assert d.halt is False


def test_guardian_passes_a_clean_promoted_report():
    d = Guardian().review(_report(promoted=True, max_drawdown=-0.05))
    assert d.approved is True
    assert d.halt is False


# --- helpers ---------------------------------------------------------------


def _single_change(cand: RegimeConditionalStrategy, current: RegimeConditionalStrategy) -> bool:
    diffs = sum(
        1
        for r in current.windows
        if cand.windows.get(r) != current.windows.get(r)
    )
    diffs += int(cand.adx_threshold != current.adx_threshold)
    diffs += int(cand.vol_threshold != current.vol_threshold)
    return diffs == 1


def test_decision_is_frozen():
    d = Decision(approved=True, reason="ok")
    assert d.halt is False
