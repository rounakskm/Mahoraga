"""Orchestrator — the seven-role multi-step dispatch loop (Phase-3 Layer-3, Task 12).

Drives Planner -> Reviewer -> (Hunter eval) -> Guardian -> promote -> Archivist per
hypothesis, aborting the instant the kill-switch trips. The roles are injectable so
the loop tests deterministically offline with stubs (no LLM, no Postgres, no network).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.trader.ops.halt import HaltControl
from services.trader.training import orchestrator as orch_mod
from services.trader.training.orchestrator import (
    CadenceSummary,
    Orchestrator,
    _strategy_from_params,
)
from services.trader.training.parse_metric import FitnessReport
from services.trader.training.promote import PromoteResult
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
    """Yields exactly 3 distinct single-change candidates off the seed; records
    the `current` strategy it was asked to mutate (for the refresh_master tests)."""

    def __init__(self):
        self.currents: list[RegimeConditionalStrategy] = []

    def propose_queue(self, current, regime_label, n=3, seed=0):
        self.currents.append(current)
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


class _RecordingNotebook:
    """In-memory Notebook: records `record` and `mark_do_not_repeat` calls."""

    def __init__(self):
        self.recorded: list[tuple[FitnessReport, str, int]] = []
        self.do_not_repeat: list[tuple[str, str]] = []

    def record(self, report, run_id, iteration):
        self.recorded.append((report, run_id, iteration))

    def mark_do_not_repeat(self, candidate_hash, reason):
        self.do_not_repeat.append((candidate_hash, reason))


class _RecordingHindsight:
    """In-memory Hindsight: enabled, records retain calls, no network."""

    def __init__(self):
        self.retained: list[tuple[str, dict]] = []

    def is_enabled(self):
        return True

    def retain(self, text, metadata=None):
        self.retained.append((text, metadata or {}))
        return "ok"

    def recall(self, query, k=5):
        return []


def _orch(tmp_path, **kw):
    price = _price()
    regimes = label_regimes(price)
    defaults = dict(
        dsn=None,
        planner=_StubPlanner(),
        reviewer=_StubReviewer(),
        guardian=_StubGuardian(),
        halt=HaltControl(tmp_path / "halt.flag"),
    )
    defaults.update(kw)
    return Orchestrator(price, regimes, **defaults)


def test_cadence_dispatches_all_roles_offline(tmp_path):
    orch = _orch(tmp_path)
    summary = orch.run_cadence("nightly", iterations=3)
    assert isinstance(summary, CadenceSummary)
    assert summary.cadence == "nightly"
    assert summary.proposed == 3
    assert summary.reviewed_out == 1
    assert summary.vetoed == 1
    assert summary.recorded >= 1
    assert summary.halted is False


def test_prehalted_run_records_nothing(tmp_path):
    halt = HaltControl(tmp_path / "halt.flag")
    halt.halt("op")
    orch = _orch(tmp_path, halt=halt)
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


# --- A1: a Guardian-vetoed candidate is still recorded, with its reason -------


def test_vetoed_candidate_is_recorded_with_reason(tmp_path, monkeypatch):
    promote_calls: list[tuple[str, int, FitnessReport]] = []

    def fake_promote(dsn, run_id, iteration, report, parent_hash=None):
        promote_calls.append((run_id, iteration, report))
        return PromoteResult(True, False, "recorded (fortress rejected)")

    monkeypatch.setattr(orch_mod, "promote_pipeline", fake_promote)
    monkeypatch.setattr(orch_mod, "refresh_master", lambda dsn: None)

    notebook = _RecordingNotebook()
    hindsight = _RecordingHindsight()
    orch = _orch(
        tmp_path, dsn="postgresql://stub", notebook=notebook, hindsight=hindsight
    )
    summary = orch.run_cadence("nightly", iterations=3)
    assert summary.vetoed == 1

    # The vetoed candidate is the FIRST approved hypothesis (ranging_high_vol=40).
    seed = RegimeConditionalStrategy.seed()
    vetoed_hash = candidate_hash(strategy_params(
        RegimeConditionalStrategy({**seed.windows, "ranging_high_vol": 40})
    ))

    # Recorded to Postgres (promote_pipeline) — vetoed AND surviving candidates.
    assert len(promote_calls) == 2
    assert promote_calls[0][2].candidate_hash == vetoed_hash
    # Distinct iteration indices — the vetoed row never collides with a later one.
    assert promote_calls[0][1] != promote_calls[1][1]

    # Recorded to the notebook, and marked do-not-repeat with the veto reason.
    assert vetoed_hash in [r.candidate_hash for r, _, _ in notebook.recorded]
    assert (vetoed_hash, "veto (stub)") in notebook.do_not_repeat

    # A4: the do-not-repeat fact is retained with the hash at metadata top level.
    dnr = [(t, m) for t, m in hindsight.retained if t.startswith("do-not-repeat")]
    assert any(m.get("candidate_hash") == vetoed_hash for _, m in dnr)


def test_reviewer_rejection_closes_do_not_repeat_loop(tmp_path):
    notebook = _RecordingNotebook()
    hindsight = _RecordingHindsight()
    orch = _orch(tmp_path, notebook=notebook, hindsight=hindsight)
    summary = orch.run_cadence("nightly", iterations=3)
    assert summary.reviewed_out == 1
    # Pre-eval rejection: no FitnessReport, but do-not-repeat is marked + retained.
    rejected = [h for h, reason in notebook.do_not_repeat if "blocked" in reason]
    assert len(rejected) == 1
    dnr = [(t, m) for t, m in hindsight.retained if t.startswith("do-not-repeat")]
    assert any(m.get("candidate_hash") == rejected[0] for _, m in dnr)


# --- A2: a provenance-write failure degrades gracefully -----------------------


def test_promote_failure_never_crashes_the_cadence(tmp_path, monkeypatch, caplog):
    def broken_promote(dsn, run_id, iteration, report, parent_hash=None):
        raise RuntimeError("postgres is down")

    monkeypatch.setattr(orch_mod, "promote_pipeline", broken_promote)
    monkeypatch.setattr(orch_mod, "refresh_master", lambda dsn: None)

    orch = _orch(tmp_path, dsn="postgresql://stub")
    with caplog.at_level("WARNING", logger="services.trader.training.orchestrator"):
        summary = orch.run_cadence("nightly", iterations=3)
    # The cadence completed; the iteration is still counted in-memory.
    assert summary.recorded == 1
    assert summary.halted is False
    assert any("provenance write failed" in r.message for r in caplog.records)


# --- A7: refresh_master seeds the starting strategy ---------------------------


def test_refresh_master_params_become_starting_strategy(tmp_path, monkeypatch):
    flat = {
        "trending_low_vol": 120,
        "trending_high_vol": 90,
        "ranging_low_vol": 45,
        "ranging_high_vol": 25,
        "adx_threshold": 21.0,
        "vol_threshold": 0.55,
    }
    monkeypatch.setattr(orch_mod, "refresh_master", lambda dsn: dict(flat))
    monkeypatch.setattr(
        orch_mod,
        "promote_pipeline",
        lambda *a, **k: PromoteResult(True, False, "recorded"),
    )
    planner = _StubPlanner()
    orch = _orch(tmp_path, dsn="postgresql://stub", planner=planner)
    orch.run_cadence("nightly", iterations=3)
    (current,) = planner.currents
    assert current.windows == {
        "trending_low_vol": 120, "trending_high_vol": 90,
        "ranging_low_vol": 45, "ranging_high_vol": 25,
    }
    assert current.adx_threshold == 21.0
    assert current.vol_threshold == 0.55


def test_refresh_master_failure_falls_back_to_seed(tmp_path, monkeypatch):
    def broken(dsn):
        raise RuntimeError("postgres is down")

    monkeypatch.setattr(orch_mod, "refresh_master", broken)
    monkeypatch.setattr(
        orch_mod,
        "promote_pipeline",
        lambda *a, **k: PromoteResult(True, False, "recorded"),
    )
    planner = _StubPlanner()
    orch = _orch(tmp_path, dsn="postgresql://stub", planner=planner)
    summary = orch.run_cadence("nightly", iterations=3)
    assert summary.halted is False
    (current,) = planner.currents
    assert current == RegimeConditionalStrategy.seed()


def test_no_dsn_never_touches_refresh_master(tmp_path, monkeypatch):
    def must_not_be_called(dsn):  # pragma: no cover - failure path
        raise AssertionError("refresh_master must not run without a DSN")

    monkeypatch.setattr(orch_mod, "refresh_master", must_not_be_called)
    planner = _StubPlanner()
    orch = _orch(tmp_path, planner=planner)
    orch.run_cadence("nightly", iterations=3)
    assert planner.currents[0] == RegimeConditionalStrategy.seed()


def test_strategy_from_params_accepts_nested_registry_shape():
    # run_autoresearch registers {"windows": {...}, "adx_threshold", "vol_threshold"}
    nested = {
        "windows": {
            "trending_low_vol": 200, "trending_high_vol": 150,
            "ranging_low_vol": 50, "ranging_high_vol": 30,
        },
        "adx_threshold": 27.0,
        "vol_threshold": 0.35,
    }
    s = _strategy_from_params(nested)
    assert s.windows == nested["windows"]
    assert s.adx_threshold == 27.0
    assert s.vol_threshold == 0.35


def test_strategy_from_params_rejects_windowless_params():
    with pytest.raises(ValueError, match="windows"):
        _strategy_from_params({"adx_threshold": 20.0})
