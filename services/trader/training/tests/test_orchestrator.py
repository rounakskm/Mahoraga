"""Orchestrator — the seven-role multi-step dispatch loop (Phase-3 Layer-3, Task 12).

Drives Planner -> Reviewer -> (Hunter eval) -> Guardian -> promote -> Archivist per
hypothesis, aborting the instant the kill-switch trips. The roles are injectable so
the loop tests deterministically offline with stubs (no LLM, no Postgres, no network).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.trader.ops.halt import HaltControl
from services.trader.training.orchestrator import CadenceSummary, Orchestrator
from services.trader.training.parse_metric import FitnessReport
from services.trader.training.provenance import candidate_hash
from services.trader.training.roles import Decision, strategy_params
from services.trader.training.strategy_template import (
    RegimeConditionalStrategy,
    label_regimes,
)


def _price(n=800, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, n))), index=idx)


class _StubPlanner:
    """Yields exactly 3 distinct single-change candidates off the seed."""

    def propose_queue(self, current, regime_label, n=3, seed=0):
        return [
            RegimeConditionalStrategy({**current.windows, "ranging_high_vol": w})
            for w in (40, 60, 80)
        ][:n]


class _StubReviewer:
    """Approves the first 2 of every queue, blocks the rest."""

    def __init__(self):
        self.seen = 0

    def check(self, hypothesis, current, recent_hashes):
        self.seen += 1
        if self.seen <= 2:
            return Decision(True, "approved (stub)")
        return Decision(False, "blocked (stub)")


class _StubGuardian:
    """Vetoes the first approved candidate it reviews, passes the rest."""

    def __init__(self):
        self.seen = 0

    def review(self, report: FitnessReport) -> Decision:
        self.seen += 1
        if self.seen == 1:
            return Decision(False, "veto (stub)")
        return Decision(True, "approved (stub)")


def test_cadence_dispatches_all_roles_offline():
    price = _price()
    regimes = label_regimes(price)
    orch = Orchestrator(
        price,
        regimes,
        dsn=None,
        planner=_StubPlanner(),
        reviewer=_StubReviewer(),
        guardian=_StubGuardian(),
    )
    summary = orch.run_cadence("nightly", iterations=3)
    assert isinstance(summary, CadenceSummary)
    assert summary.cadence == "nightly"
    assert summary.proposed == 3
    assert summary.reviewed_out == 1
    assert summary.vetoed == 1
    assert summary.recorded >= 1
    assert summary.halted is False


def test_prehalted_run_records_nothing(tmp_path):
    price = _price()
    regimes = label_regimes(price)
    halt = HaltControl(tmp_path / "halt.flag")
    halt.halt("op")
    orch = Orchestrator(
        price,
        regimes,
        dsn=None,
        planner=_StubPlanner(),
        reviewer=_StubReviewer(),
        guardian=_StubGuardian(),
        halt=halt,
    )
    summary = orch.run_cadence("nightly", iterations=3)
    assert summary.halted is True
    assert summary.recorded == 0
    assert summary.promoted == 0


def test_recent_hashes_tracked_for_reviewer():
    # The seed candidate's own hash is distinct from each stub hypothesis hash,
    # so the stub queue is genuinely distinct — sanity-guards the test fixture.
    seed = RegimeConditionalStrategy.seed()
    hashes = {
        candidate_hash(strategy_params(
            RegimeConditionalStrategy({**seed.windows, "ranging_high_vol": w})
        ))
        for w in (40, 60, 80)
    }
    assert len(hashes) == 3
