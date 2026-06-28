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
from services.trader.training.strategy_template import RegimeConditionalStrategy
from services.trader.walls import EvaluationContext
from services.trader.walls import risklabai_wrap as rl


@dataclass(frozen=True)
class EvalResult:
    report: GateSystemReport
    returns: pd.Series
    sharpe: float


def _walk_forward(returns: pd.Series, folds: int = 5) -> list[float]:
    return [rl.sharpe(c) for c in np.array_split(returns.values, folds) if len(c) > 20]


def _per_regime(returns: pd.Series, regimes: pd.Series) -> dict[str, float]:
    aligned = regimes.reindex(returns.index)
    return {
        str(label): rl.sharpe(returns[aligned == label])
        for label in aligned.dropna().unique()
        if (aligned == label).sum() > 20
    }


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
    if trial_returns_matrix is not None:
        metadata["trial_returns_matrix"] = trial_returns_matrix
    if trial_sharpes is not None:
        metadata["trial_sharpes"] = trial_sharpes

    ctx = EvaluationContext(
        strategy=strategy, backtest_result=None, returns=returns,
        universe=["SPY"], metadata=metadata,
    )
    report = (gates or GateSystem()).evaluate(ctx)
    return EvalResult(report=report, returns=returns, sharpe=rl.sharpe(returns))
