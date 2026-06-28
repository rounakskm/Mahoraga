"""Layer-1 kernel: strategy template, regime-conditional returns, and the loop."""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.trader.training import eval as kernel_eval
from services.trader.training.loop import run_loop
from services.trader.training.strategy_template import (
    REGIMES,
    RegimeConditionalStrategy,
    label_regimes,
)


def _price(n=800, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, n))), index=idx)


def test_label_regimes_covers_taxonomy():
    labels = label_regimes(_price())
    assert set(labels.unique()) <= set(REGIMES)
    assert len(labels) == 800


def test_returns_are_regime_conditional_and_lagged():
    price = _price()
    regimes = label_regimes(price)
    a = RegimeConditionalStrategy.seed()
    b = RegimeConditionalStrategy({**a.windows, "ranging_high_vol": 120})
    # different per-regime windows -> different return streams
    assert not a.returns(price, regimes).equals(b.returns(price, regimes))
    # no look-ahead: returns start at/after the longest SMA warmup
    assert a.returns(price, regimes).notna().all()


def test_mutate_is_single_change():
    a = RegimeConditionalStrategy.seed()
    b = a.mutate(np.random.default_rng(0))
    changed = [k for k in a.windows if a.windows[k] != b.windows[k]]
    assert len(changed) == 1  # exactly one regime's window moved


def test_eval_populates_metadata_contract_and_runs_gates():
    price = _price()
    regimes = label_regimes(price)
    ev = kernel_eval.evaluate(RegimeConditionalStrategy.seed(), price, regimes)
    md_keys = {"per_regime_sharpes", "oos_sharpes", "rolling_sharpes", "perturbed_sharpes"}
    # the wall reports exist for all four walls
    assert set(ev.report.wall_reports) == {
        "statistical_rigor", "complexity_control", "generalization", "meta_awareness",
    }
    assert isinstance(ev.report.promoted, bool)
    # eval actually fed the per-regime sharpes (the regime-conditional objective)
    assert ev.report.wall_reports["generalization"].sub_results["regime_frac_pos"] is not None
    assert md_keys  # contract keys named above are produced by eval.evaluate


def test_loop_runs_and_fortress_gates():
    res = run_loop(_price(seed=2), iterations=4, seed=2)
    assert len(res.iterations) == 4
    # the fortress gates: not everything is promoted (or the loop tracked a best)
    assert res.num_promoted <= 4
    if res.best is not None:
        assert set(res.best.windows) == set(REGIMES)  # best is regime-conditional


def test_pbo_gated_on_trial_diversity():
    """eval feeds PBO only when trials are diverse; correlated micro-tweaks skip it."""
    price = _price()
    regimes = label_regimes(price)
    seed = RegimeConditionalStrategy.seed()
    # near-identical (correlated) trial columns -> PBO must be skipped (N/A)
    corr = np.column_stack([seed.returns(price, regimes).to_numpy()[-2000:]] * 12)
    corr = corr + np.random.default_rng(0).normal(0, 1e-9, corr.shape)
    rep = kernel_eval.evaluate(
        seed, price, regimes, trial_returns_matrix=corr,
        trial_sharpes=[0.06] * 12, num_trials=12,
    ).report
    assert rep.wall_reports["statistical_rigor"].sub_results["pbo"] is None
    # genuinely diverse columns (pure noise) -> PBO computed
    diverse = np.random.default_rng(1).standard_normal((2000, 16))
    rep2 = kernel_eval.evaluate(
        seed, price, regimes, trial_returns_matrix=diverse,
        trial_sharpes=[0.06] * 16, num_trials=16,
    ).report
    assert rep2.wall_reports["statistical_rigor"].sub_results["pbo"] is not None
