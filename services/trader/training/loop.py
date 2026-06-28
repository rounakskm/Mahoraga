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


@dataclass
class CampaignResult:
    iterations: list[Iteration] = field(default_factory=list)
    best: RegimeConditionalStrategy | None = None
    best_sharpe: float = float("-inf")

    @property
    def num_promoted(self) -> int:
        return sum(i.promoted for i in self.iterations)


def run_loop(
    price: pd.Series,
    *,
    iterations: int = 30,
    seed: int = 0,
    gates: GateSystem | None = None,
    on_iteration: Callable[[Iteration], None] | None = None,
) -> CampaignResult:
    """Hill-climb the regime-conditional strategy on a real price series.

    `on_iteration` is called as each iteration completes — used for live progress
    during training (the loop is otherwise silent until it returns).
    """
    rng = np.random.default_rng(seed)
    regimes = label_regimes(price)
    gates = gates or GateSystem()

    current = RegimeConditionalStrategy.seed()
    result = CampaignResult()
    trials_returns: list[np.ndarray] = []
    trials_sharpes: list[float] = []

    for i in range(iterations):
        cand = current if i == 0 else current.mutate(rng)

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
        is_best = promoted and ev.sharpe > result.best_sharpe
        if is_best:
            result.best, result.best_sharpe = cand, ev.sharpe
            current = cand  # hill-climb: accept the improvement
        it = Iteration(i, dict(cand.windows), ev.sharpe, promoted, is_best, ev.report.reason)
        result.iterations.append(it)
        if on_iteration is not None:
            on_iteration(it)
    return result
