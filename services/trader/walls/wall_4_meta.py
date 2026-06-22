"""Wall 4 — Meta-Awareness.

Are we fooling ourselves across the whole search, not just this strategy?

- trial budget: `num_trials` (how many variants the search has tried) vs a budget.
  Past the budget, the best result is probably multiple-testing luck — reject.
  This same count feeds Wall 1's DSR/PBO deflation.
- KB forbidden-pattern: a stub that returns False (no pattern forbidden) until the
  Hindsight knowledge base is wired in Phase 3.

ponytail: no `walls.trial_budget` Postgres table yet. The wall is a pure predicate
over the count the caller passes; persisting/incrementing a cumulative counter is
the Phase-3 autoresearch loop's job. Add the table when the loop exists.
"""

from __future__ import annotations

from typing import ClassVar

from services.trader.walls.base import EvaluationContext, Wall, WallReport


def kb_forbidden(ctx: EvaluationContext) -> bool:
    """Phase-2 stub: nothing is forbidden yet. Hindsight wiring lands in Phase 3."""
    return False


class MetaAwarenessWall(Wall):
    name: ClassVar[str] = "meta_awareness"

    def __init__(self, *, trial_budget: int = 1000) -> None:
        self.trial_budget = trial_budget

    def evaluate(self, ctx: EvaluationContext) -> WallReport:
        try:
            num_trials = int(ctx.metadata.get("num_trials", 1))
            within_budget = num_trials <= self.trial_budget
            forbidden = kb_forbidden(ctx)
            passed = bool(within_budget and not forbidden)
            score = max(0.0, 1.0 - num_trials / self.trial_budget) if within_budget else 0.0
            reason = (
                f"num_trials={num_trials}/{self.trial_budget} (within={within_budget}), "
                f"kb_forbidden={forbidden}"
            )
            return WallReport(
                wall_name=self.name,
                passed=passed,
                score=float(score),
                reason=reason,
                sub_results={"num_trials": num_trials, "kb_forbidden": forbidden},
            )
        except Exception as exc:
            return WallReport(self.name, False, 0.0, f"meta_awareness wall error: {exc!r}")
