"""Walls 2-4 — known-ground-truth fixtures. Each wall is a pure predicate over
ctx.metadata; the harness supplies perturbation / walk-forward / trial results."""

from __future__ import annotations

import pandas as pd

from services.trader.walls.base import EvaluationContext
from services.trader.walls.wall_2_complexity import ComplexityControlWall
from services.trader.walls.wall_3_generalization import GeneralizationWall
from services.trader.walls.wall_4_meta import MetaAwarenessWall


def _ctx(returns=None, **metadata):
    return EvaluationContext(
        strategy=None,
        backtest_result=None,
        returns=returns if returns is not None else pd.Series([0.001, -0.0005, 0.0008] * 50),
        feature_frame=pd.DataFrame(),
        regime_frame=pd.DataFrame(),
        universe=["SPY"],
        metadata=metadata,
    )


# ── Wall 2: Complexity Control ────────────────────────────────────────────────


def test_complexity_passes_robust_strategy():
    # base SR ~ small positive; perturbed edge stays near base; stable; few params
    r = pd.Series([0.0009, -0.0004, 0.001] * 200)
    base = r.mean() / r.std(ddof=1)
    rep = ComplexityControlWall().evaluate(
        _ctx(r, perturbed_sharpes=[base * 0.9, base * 0.95, base],
             rolling_sharpes=[0.1, 0.2, 0.15], num_params=1)
    )
    assert rep.passed, rep.reason


def test_complexity_rejects_param_fragile_strategy():
    r = pd.Series([0.0009, -0.0004, 0.001] * 200)
    base = r.mean() / r.std(ddof=1)
    rep = ComplexityControlWall().evaluate(
        _ctx(r, perturbed_sharpes=[base * 0.05, -base, 0.0], rolling_sharpes=[0.1, -0.3, -0.2], num_params=12)
    )
    assert not rep.passed, rep.reason  # edge collapses under perturbation


def test_complexity_skips_missing_inputs_and_never_raises():
    rep = ComplexityControlWall().evaluate(_ctx())  # no perturbation/rolling data
    assert rep.wall_name == "complexity_control" and isinstance(rep.passed, bool)


# ── Wall 3: Generalization ────────────────────────────────────────────────────


def test_generalization_passes_oos_and_multiregime():
    rep = GeneralizationWall().evaluate(
        _ctx(oos_sharpes=[0.3, 0.1, 0.25, 0.2], per_regime_sharpes={"bull": 0.4, "bear": 0.1, "range": 0.2})
    )
    assert rep.passed, rep.reason


def test_generalization_rejects_insample_only():
    rep = GeneralizationWall().evaluate(
        _ctx(oos_sharpes=[-0.2, -0.1, 0.05, -0.3],
             per_regime_sharpes={"bull": 0.6, "bear": -0.4, "range": -0.2})
    )
    assert not rep.passed, rep.reason  # OOS folds mostly negative


def test_generalization_skips_missing_and_never_raises():
    rep = GeneralizationWall().evaluate(_ctx())
    assert rep.wall_name == "generalization" and isinstance(rep.passed, bool)


# ── Wall 4: Meta-Awareness ────────────────────────────────────────────────────


def test_meta_passes_within_budget():
    rep = MetaAwarenessWall(trial_budget=1000).evaluate(_ctx(num_trials=50))
    assert rep.passed and rep.sub_results["num_trials"] == 50


def test_meta_rejects_budget_exhausted():
    rep = MetaAwarenessWall(trial_budget=1000).evaluate(_ctx(num_trials=5000))
    assert not rep.passed, rep.reason


def test_meta_kb_forbidden_stub_is_false():
    rep = MetaAwarenessWall().evaluate(_ctx(num_trials=1))
    assert rep.sub_results["kb_forbidden"] is False
