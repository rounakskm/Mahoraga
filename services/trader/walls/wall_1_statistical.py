"""Wall 1 — Statistical Rigor.

Is the strategy's edge statistically real, or an artifact of luck / multiple
testing? Three RiskLabAI-backed sub-tests:

- PSR  — P(true Sharpe > 0); track-record confidence.
- DSR  — PSR deflated by E[max Sharpe] over the trials tried (multiple-testing).
- PBO  — Probability of Backtest Overfitting over the trial-returns matrix.

The trial context (how many variants were tried, their Sharpes, and the matrix
of their returns) comes from `ctx.metadata` — the autoresearch loop (Phase 3) or
the calibration harness (P2.6) populates it. A lone strategy with no trial
context still gets PSR; DSR degrades to PSR; PBO is skipped (not failed).
"""

from __future__ import annotations

from typing import ClassVar

from services.trader.walls import risklabai_wrap as rl
from services.trader.walls.base import EvaluationContext, Wall, WallReport


class StatisticalRigorWall(Wall):
    name: ClassVar[str] = "statistical_rigor"

    def __init__(self, *, pbo_threshold: float = 0.30, dsr_threshold: float = 0.95) -> None:
        self.pbo_threshold = pbo_threshold
        self.dsr_threshold = dsr_threshold

    def evaluate(self, ctx: EvaluationContext) -> WallReport:
        try:
            returns = ctx.returns
            trial_sharpes = ctx.metadata.get("trial_sharpes")
            matrix = ctx.metadata.get("trial_returns_matrix")

            psr_v = rl.psr(returns)
            dsr_v = rl.dsr(returns, trial_sharpes) if trial_sharpes is not None else psr_v
            pbo_v = rl.pbo(matrix) if matrix is not None else None

            dsr_ok = dsr_v >= self.dsr_threshold
            pbo_ok = pbo_v is None or pbo_v < self.pbo_threshold
            passed = bool(dsr_ok and pbo_ok)

            # score: confidence it's real. min(DSR, 1-PBO) when PBO is available.
            score = dsr_v if pbo_v is None else min(dsr_v, 1.0 - pbo_v)

            pbo_str = "n/a" if pbo_v is None else f"{pbo_v:.2f}"
            reason = (
                f"DSR={dsr_v:.3f} (>= {self.dsr_threshold}: {dsr_ok}), "
                f"PBO={pbo_str} (< {self.pbo_threshold}: {pbo_ok}), PSR={psr_v:.3f}"
            )
            return WallReport(
                wall_name=self.name,
                passed=passed,
                score=float(score),
                reason=reason,
                sub_results={"psr": psr_v, "dsr": dsr_v, "pbo": pbo_v},
            )
        except Exception as exc:  # walls must never raise (base.py contract)
            return WallReport(
                wall_name=self.name,
                passed=False,
                score=0.0,
                reason=f"statistical_rigor wall error: {exc!r}",
            )
