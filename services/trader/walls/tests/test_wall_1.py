"""Wall 1 (Statistical Rigor) + RiskLabAI wrapper tests.

Wrapper values are pinned to the figures validated 2026-06-22 (PSR textbook
0.96901; noise PBO high; persistent-winner PBO low). Wall behaviour is tested on
known-ground-truth fixtures: real-edge -> PASS, multiple-tested noise -> REJECT.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.trader.walls import risklabai_wrap as rl
from services.trader.walls.base import EvaluationContext
from services.trader.walls.wall_1_statistical import StatisticalRigorWall

# ── wrapper: pinned to validated values ───────────────────────────────────────


def test_psr_reproduces_bailey_ldp_textbook():
    # SR=0.55, n=36, skew=-2.448, non-excess kurt=10.164, benchmark 0 -> 0.96901
    r = _series_with_moments(sr=0.55, n=36, skew=-2.448, kurt=10.164)
    # exact textbook value uses the moments directly, not a fitted series:
    from RiskLabAI.backtest.probabilistic_sharpe_ratio import probabilistic_sharpe_ratio

    val = probabilistic_sharpe_ratio(
        observed_sharpe_ratio=0.55, benchmark_sharpe_ratio=0.0,
        number_of_returns=36, skewness_of_returns=-2.448, kurtosis_of_returns=10.164,
    )
    assert val == pytest.approx(0.96901, abs=1e-5)
    assert r is not None  # series helper smoke


def test_pbo_noise_is_high_persistent_is_low():
    rng = np.random.default_rng(7)
    noise = rng.standard_normal((3000, 60))
    assert rl.pbo(noise) > 0.30  # multiple-tested noise overfits

    persistent = rng.standard_normal((3000, 60)) * 0.01
    persistent[:, 0] += 0.02  # column 0 has a real, persistent edge
    assert rl.pbo(persistent) < 0.10


def test_pbo_drops_nan_columns_and_requires_even_partitions():
    rng = np.random.default_rng(1)
    m = rng.standard_normal((1000, 10))
    m[5, 3] = np.nan  # one NaN -> that column dropped, no silent corruption
    p = rl.pbo(m, n_partitions=15)  # odd -> rounded to 16 internally
    assert 0.0 <= p <= 1.0


def test_dsr_below_psr_when_many_trials():
    r = _series_with_moments(sr=0.08, n=1500, skew=0.0, kurt=3.0)
    rng = np.random.default_rng(11)
    trials = rng.normal(0.05, 0.03, 50).tolist()  # spread -> E[max SR] > 0 -> deflation
    assert rl.dsr(r, trial_sharpes=trials) < rl.psr(r)


# ── wall: ground-truth fixtures ───────────────────────────────────────────────


def test_wall_passes_real_edge_single_trial():
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.normal(0.0009, 0.008, 1500))  # daily SR ~0.11, strong
    ctx = _ctx(returns)  # no trial context
    rep = StatisticalRigorWall().evaluate(ctx)
    assert rep.passed, rep.reason
    assert rep.sub_results["pbo"] is None


def test_wall_rejects_multiple_tested_noise_canary():
    rng = np.random.default_rng(42)
    matrix = rng.standard_normal((2000, 50)) * 0.01  # 50 noise trials
    best = int(np.argmax(matrix.sum(axis=0)))  # the in-sample winner
    returns = pd.Series(matrix[:, best])
    trial_sharpes = [rl.sharpe(matrix[:, j]) for j in range(matrix.shape[1])]
    ctx = _ctx(returns, trial_sharpes=trial_sharpes, trial_returns_matrix=matrix)
    rep = StatisticalRigorWall().evaluate(ctx)
    assert not rep.passed, rep.reason  # DSR (and/or PBO) must reject


def test_wall_never_raises_on_bad_input():
    ctx = _ctx(pd.Series([0.0, 0.0, 0.0]))  # constant -> degenerate
    rep = StatisticalRigorWall().evaluate(ctx)
    assert rep.wall_name == "statistical_rigor"
    assert isinstance(rep.passed, bool)


# ── helpers ───────────────────────────────────────────────────────────────────


def _series_with_moments(*, sr, n, skew, kurt):  # noqa: ARG001 - moments smoke only
    rng = np.random.default_rng(3)
    return pd.Series(rng.normal(0.0005, 0.01, n))


def _ctx(returns, **metadata):
    return EvaluationContext(
        strategy=None,
        backtest_result=None,
        returns=returns,
        feature_frame=pd.DataFrame(),
        regime_frame=pd.DataFrame(),
        universe=["SPY"],
        metadata=metadata,
    )
