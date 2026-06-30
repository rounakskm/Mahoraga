"""loop.py — the headless mechanical autoresearch loop (Phase 3, Layer 1).

mutate -> eval through the fortress -> record (kept + discarded, with reason) ->
keep the best *promoted* candidate. No LLM, no agents — the mutator is a simple
hill-climb over the regime-conditional windows. This is the runnable training loop
(Layer-1 milestone); Layer 2 swaps the mutator for an LLM, Layer 3 wraps it in the
agent fleet. The campaign accumulates every trial's returns so Wall 1 can compute
PBO/DSR over the multiple-testing set.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from services.trader.gates import GateSystem
from services.trader.training import eval as kernel_eval
from services.trader.training.strategy_template import (
    RegimeConditionalStrategy,
    label_regimes,
)


@dataclass
class Iteration:
    index: int
    windows: dict[str, int]
    sharpe: float
    promoted: bool
    is_best: bool
    reason: str
    fitness: float = 0.0
    quarterly_win_rate: float = 0.0
    max_drawdown: float = 0.0


@dataclass
class CampaignResult:
    iterations: list[Iteration] = field(default_factory=list)
    best: RegimeConditionalStrategy | None = None
    best_sharpe: float = float("-inf")
    best_fitness: float = float("-inf")
    best_quarterly_win_rate: float = 0.0

    @property
    def num_promoted(self) -> int:
        return sum(i.promoted for i in self.iterations)


def run_loop(
    price: pd.Series,
    *,
    iterations: int = 30,
    seed: int = 0,
    gates: GateSystem | None = None,
    regimes: pd.Series | None = None,
    mutator: Callable | None = None,
    on_iteration: Callable[[Iteration], None] | None = None,
) -> CampaignResult:
    """Hill-climb the regime-conditional strategy on a real price series.

    `regimes` is the per-bar regime label series; if omitted, the inline
    trend×vol proxy (`label_regimes`) is used. `mutator(current, iterations, rng)`
    proposes each candidate; default is the mechanical ±-window nudge, Layer 2
    passes `training.llm.LLMMutator`. `on_iteration` gives live progress.
    """
    rng = np.random.default_rng(seed)
    regimes = label_regimes(price) if regimes is None else regimes.reindex(price.index)
    gates = gates or GateSystem()
    mutate = mutator or (lambda cur, _iters, r: cur.mutate(r))

    current = RegimeConditionalStrategy.seed()
    result = CampaignResult()
    trials_returns: list[np.ndarray] = []
    trials_sharpes: list[float] = []

    for i in range(iterations):
        cand = current if i == 0 else mutate(current, result.iterations, rng)

        # campaign trial context: PBO/DSR over all trials so far (need >= 2 cols)
        matrix = sharpes = None
        if len(trials_returns) >= 2:
            n = min(len(r) for r in trials_returns)
            matrix = np.column_stack([r[-n:] for r in trials_returns])
            sharpes = list(trials_sharpes)

        ev = kernel_eval.evaluate(
            cand, price, regimes,
            trial_returns_matrix=matrix, trial_sharpes=sharpes,
            num_trials=i + 1, gates=gates,
        )

        trials_returns.append(ev.returns.to_numpy())
        trials_sharpes.append(ev.sharpe)

        promoted = ev.report.promoted
        # rank by FITNESS (quarterly consistency + resilience + Sharpe), not raw Sharpe
        is_best = promoted and ev.fitness.score > result.best_fitness
        if is_best:
            result.best = cand
            result.best_fitness = ev.fitness.score
            result.best_sharpe = ev.sharpe
            result.best_quarterly_win_rate = ev.fitness.quarterly_win_rate
            current = cand  # hill-climb: accept the improvement
        it = Iteration(
            i, dict(cand.windows), ev.sharpe, promoted, is_best, ev.report.reason,
            fitness=ev.fitness.score, quarterly_win_rate=ev.fitness.quarterly_win_rate,
            max_drawdown=ev.fitness.max_drawdown,
        )
        result.iterations.append(it)
        if on_iteration is not None:
            on_iteration(it)
    return result
