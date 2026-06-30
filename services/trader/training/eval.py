"""eval.py — run a candidate through the Phase-2 fortress (Phase 3, Layer 1).

This is the kernel's core interface (spec §2): the Phase-2 walls are pure
predicates over `EvaluationContext.metadata`; here we *populate* that metadata
(per-regime / walk-forward / rolling / perturbed Sharpes + the campaign trial
matrix) and run the `GateSystem`. The Phase-2 calibration already proved the gate
side on real SPY; this feeds it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from services.trader.gates import GateSystem, GateSystemReport
from services.trader.gates.gates import max_drawdown
from services.trader.training.strategy_template import RegimeConditionalStrategy
from services.trader.walls import EvaluationContext
from services.trader.walls import risklabai_wrap as rl


@dataclass(frozen=True)
class Fitness:
    """What the loop maximises — Mahoraga's actual objective, not raw Sharpe.

    Encodes the thesis: end every quarter profitable (quarterly_win_rate) and stay
    resilient when hit (bounded drawdown), on top of risk-adjusted return.
    """

    score: float
    sharpe: float
    quarterly_win_rate: float
    max_drawdown: float
    resilience: float


def compute_fitness(returns: pd.Series) -> Fitness:
    sharpe = rl.sharpe(returns)
    r = returns.dropna()
    if len(r) >= 60 and isinstance(r.index, pd.DatetimeIndex):
        q = (1.0 + r).resample("QE").prod() - 1.0  # per-calendar-quarter return
        q_win = float((q > 0).mean()) if len(q) else 0.0
    else:  # short / non-dated series: 4 equal chunks
        chunks = np.array_split(r.to_numpy(), 4)
        q_win = float(np.mean([c.sum() > 0 for c in chunks if len(c)]))
    dd = max_drawdown(r)  # negative
    # resilience: full credit to -10% drawdown, linearly to 0 at -40%.
    resilience = float(np.clip(1.0 - max(0.0, abs(dd) - 0.10) / 0.30, 0.0, 1.0))
    # reward risk-adjusted return, weighted by quarterly consistency (up to 2x) and
    # scaled by resilience. A strategy with losing quarters or deep drawdowns is
    # ranked below an equally-sharp one that ends quarters green and stays shallow.
    score = sharpe * (0.5 + 0.5 * q_win) * resilience
    return Fitness(score, sharpe, q_win, dd, resilience)


@dataclass(frozen=True)
class EvalResult:
    report: GateSystemReport
    returns: pd.Series
    sharpe: float
    fitness: Fitness


def _walk_forward(returns: pd.Series, folds: int = 5) -> list[float]:
    return [rl.sharpe(c) for c in np.array_split(returns.values, folds) if len(c) > 20]


def _per_regime(returns: pd.Series, regimes: pd.Series) -> dict[str, float]:
    aligned = regimes.reindex(returns.index)
    return {
        str(label): rl.sharpe(returns[aligned == label])
        for label in aligned.dropna().unique()
        if (aligned == label).sum() > 20
    }


def _diverse_enough(matrix, min_cols: int = 10, max_abs_corr: float = 0.90) -> bool:
    """Is the trial set diverse enough for PBO (CSCV) to mean anything?

    PBO's power comes from a sizeable set of GENUINELY DIFFERENT strategies. A
    mechanical hill-climb of near-identical micro-mutations (200-vs-220 SMA) is
    ~0.97 correlated, where CSCV becomes high-variance noise (the validated PBO
    caveat — it bounced 0.01..0.55 on the same Sharpe). Gate PBO on real
    diversity; the correlated loop relies on DSR + the complexity/generalization/
    risk gates instead. PBO re-enters at Layer 2+ when the LLM proposes distinct
    hypotheses (the calibration's diverse crossover grid sits at ~0.82 and still
    fires PBO=0.84).
    """
    m = np.asarray(matrix, float)
    m = m[:, ~np.isnan(m).any(axis=0)]
    if m.shape[1] < min_cols:
        return False
    c = np.corrcoef(m.T)
    n = c.shape[0]
    return ((np.abs(c).sum() - n) / (n * (n - 1))) < max_abs_corr


def _perturbed(strategy, price, regimes) -> list[float]:
    """Sharpe under +/-10/20% perturbation of each per-regime window (Wall 2)."""
    out = []
    for regime in strategy.windows:
        for f in (0.8, 0.9, 1.1, 1.2):
            w = max(2, int(round(strategy.windows[regime] * f)))
            perturbed = type(strategy)({**strategy.windows, regime: w})
            out.append(rl.sharpe(perturbed.returns(price, regimes)))
    return out


def evaluate(
    strategy: RegimeConditionalStrategy,
    price: pd.Series,
    regimes: pd.Series,
    *,
    trial_returns_matrix: np.ndarray | None = None,
    trial_sharpes: list[float] | None = None,
    num_trials: int = 1,
    gates: GateSystem | None = None,
) -> EvalResult:
    returns = strategy.returns(price, regimes)
    metadata: dict = {
        "num_trials": num_trials,
        "num_params": strategy.num_params,
        "per_regime_sharpes": _per_regime(returns, regimes),
        "oos_sharpes": _walk_forward(returns, folds=5),
        "rolling_sharpes": _walk_forward(returns, folds=8),
        "perturbed_sharpes": _perturbed(strategy, price, regimes),
    }
    # PBO only when the trial set is diverse enough to be reliable (see helper).
    if trial_returns_matrix is not None and _diverse_enough(trial_returns_matrix):
        metadata["trial_returns_matrix"] = trial_returns_matrix
    if trial_sharpes is not None:
        metadata["trial_sharpes"] = trial_sharpes

    ctx = EvaluationContext(
        strategy=strategy, backtest_result=None, returns=returns,
        universe=["SPY"], metadata=metadata,
    )
    report = (gates or GateSystem()).evaluate(ctx)
    return EvalResult(
        report=report, returns=returns, sharpe=rl.sharpe(returns),
        fitness=compute_fitness(returns),
    )
