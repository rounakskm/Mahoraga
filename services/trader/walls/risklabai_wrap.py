"""Thin wrapper over RiskLabAI's backtest-overfitting stats.

RiskLabAI's PSR/DSR/PBO math is correct (validated 2026-06-22: bit-identical to
the rubenbriones reference, reproduces the Bailey & López de Prado PSR textbook
value 0.96901). The caveats it has are ergonomic, and this module handles them so
the walls don't have to:

- no packaged `deflated_sharpe_ratio()` — `dsr()` assembles it (E[max SR] -> PSR);
- kurtosis must be FULL/non-excess (normal = 3.0) — we feed `kurtosis(fisher=False)`;
- a NaN in the PBO matrix propagates silently — `pbo()` drops NaN columns;
- PBO `n_partitions` must be even — `pbo()` rounds up.

Frequency note: PSR takes a per-period Sharpe with the per-period sample count;
keep both in the same frequency (don't mix an annualized SR with a daily n).
"""

from __future__ import annotations

import numpy as np
from RiskLabAI.backtest.probabilistic_sharpe_ratio import (
    benchmark_sharpe_ratio,
    probabilistic_sharpe_ratio,
)
from RiskLabAI.backtest.probability_of_backtest_overfitting import (
    probability_of_backtest_overfitting,
)
from scipy.stats import kurtosis, skew


def _clean(returns) -> np.ndarray:
    r = np.asarray(returns, dtype=float).ravel()
    return r[~np.isnan(r)]


def sharpe(returns) -> float:
    """Per-period Sharpe (ddof=1). 0.0 for a constant series."""
    r = _clean(returns)
    sd = r.std(ddof=1)
    return float(r.mean() / sd) if sd > 1e-12 else 0.0


def psr(returns, benchmark_sr: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio: P(true SR > benchmark_sr). In [0, 1]."""
    r = _clean(returns)
    if len(r) < 3:
        return 0.0
    return float(
        probabilistic_sharpe_ratio(
            observed_sharpe_ratio=sharpe(r),
            benchmark_sharpe_ratio=benchmark_sr,
            number_of_returns=len(r),
            skewness_of_returns=float(skew(r)),
            kurtosis_of_returns=float(kurtosis(r, fisher=False)),  # non-excess
        )
    )


def dsr(returns, trial_sharpes) -> float:
    """Deflated Sharpe Ratio = PSR against E[max SR] over the trials.

    `trial_sharpes` = the per-period Sharpe of every strategy variant tried
    (the multiple-testing set). One trial -> E[max]=0 -> DSR == PSR.

    ponytail: uses RiskLabAI's raw-N E[max] (conservative for correlated trials
    -> DSR slightly understated). Add a correlation-deflated effective-N here if
    calibration shows it over-rejects.
    """
    sr_list = [float(s) for s in trial_sharpes if not np.isnan(s)]
    if len(sr_list) <= 1:
        return psr(returns, 0.0)
    emax = float(benchmark_sharpe_ratio(sr_list))
    return psr(returns, benchmark_sr=emax)


def pbo(returns_matrix, n_partitions: int = 16) -> float:
    """Probability of Backtest Overfitting via CSCV. Matrix is (T_obs, N_strats).

    ~0.5 for pure noise, ->0 for a genuinely persistent strategy. Deterministic
    for a fixed matrix (the high-variance caveat is across random draws, not for
    one input). Drops any column containing a NaN (silent-NaN guard).
    """
    m = np.asarray(returns_matrix, dtype=float)
    if m.ndim != 2:
        raise ValueError("returns_matrix must be 2-D (T_obs, N_strategies)")
    m = m[:, ~np.isnan(m).any(axis=0)]
    if m.shape[1] < 2:
        raise ValueError("PBO needs >= 2 non-NaN strategy columns")
    n_partitions += n_partitions % 2  # must be even
    prob, _ = probability_of_backtest_overfitting(m, n_partitions=n_partitions, n_jobs=1)
    return float(prob)
