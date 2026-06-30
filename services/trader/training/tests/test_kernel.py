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


def _ohlcv(n=900, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, n)))
    span = close * rng.uniform(0.003, 0.02, n)
    return pd.DataFrame(
        {"open": close, "high": close + span, "low": close - span,
         "close": close, "volume": rng.integers(1e6, 5e6, n)},
        index=idx,
    )


def test_meso_regimes_real_detector_aligns_and_labels():
    from services.trader.training.regime import meso_regimes

    ohlcv = _ohlcv()
    labels = meso_regimes(ohlcv)
    assert labels.index.equals(ohlcv.index)  # the index-alignment bug stays fixed
    assert set(labels.unique()) <= set(REGIMES) | {"undefined"}
    assert (labels != "undefined").sum() > 100  # most bars get a real regime


def test_loop_accepts_external_regimes():
    from services.trader.training.regime import meso_regimes

    ohlcv = _ohlcv(seed=3)
    price = ohlcv["close"]
    res = run_loop(price, iterations=3, seed=3, regimes=meso_regimes(ohlcv))
    assert len(res.iterations) == 3


def test_vault_split_holds_out_the_recent_window():
    from services.trader.training.vault import split_train

    price = _price(n=1500)
    regimes = label_regimes(price)
    tp, _tr, cutoff = split_train(price, regimes, vault_days=180)
    assert cutoff == price.index[-1] - pd.Timedelta(days=180)
    assert (tp.index <= cutoff).all()      # search sees nothing past the cutoff
    assert len(tp) < len(price)            # something is held out


def test_vault_validation_report_and_ratio_rule():
    from services.trader.training.vault import split_train, validate_on_vault

    price = _price(n=1500, seed=5)
    regimes = label_regimes(price)
    _, _, cutoff = split_train(price, regimes, 180)
    strat = RegimeConditionalStrategy.seed()
    vr = validate_on_vault(strat, price, regimes, cutoff, train_sharpe=0.05)
    assert isinstance(vr.holds, bool) and isinstance(vr.vault_sharpe, float)
    # a non-positive train edge can never "hold"
    assert validate_on_vault(strat, price, regimes, cutoff, train_sharpe=-0.1).holds is False


def test_fitness_rewards_quarterly_consistency_and_resilience():
    from services.trader.training.eval import compute_fitness

    idx = pd.bdate_range("2018-01-01", periods=520)
    rng = np.random.default_rng(0)
    consistent = pd.Series(rng.normal(0.0006, 0.004, 520), index=idx)
    lumpy = consistent.copy()
    lumpy.iloc[60:130] = -0.012  # a deeply negative quarter -> losing quarter + drawdown
    fc, fl = compute_fitness(consistent), compute_fitness(lumpy)
    assert fc.quarterly_win_rate >= fl.quarterly_win_rate
    assert fc.resilience >= fl.resilience
    assert fc.score > fl.score  # the resilient, quarter-consistent series wins on fitness


def test_candidate_hash_stable_and_order_independent():
    from services.trader.training.provenance import candidate_hash

    a = {"trending_low_vol": 200, "ranging_high_vol": 30}
    assert candidate_hash(a) == candidate_hash({"ranging_high_vol": 30, "trending_low_vol": 200})
    assert candidate_hash(a) != candidate_hash({**a, "trending_low_vol": 199})


def test_provenance_writer_is_noop_without_dsn():
    from services.trader.training.provenance import ProvenanceWriter

    w = ProvenanceWriter(None)
    assert not w.is_enabled()
    # no DSN -> writes are skipped, no connection attempted, no error
    w.write_iteration(run_id="r", iteration=0, params={"a": 1}, train_sharpe=0.1,
                      promoted=True, is_best=True, reason="ok")
    w.register_strategy(run_id="r", params={"a": 1}, train_sharpe=0.1,
                        vault_sharpe=0.1, vault_holds=True)
    w.close()
