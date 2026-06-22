"""Wall 3 — Generalization.

Does the edge hold out-of-sample and across regimes, or only in-sample on one
market state? Two checks over harness-supplied results:

- walk-forward: `oos_sharpes` (Sharpe on each out-of-sample fold) must stay
  positive on a majority of folds and average > 0;
- multi-regime: `per_regime_sharpes` (regime -> Sharpe; falls back to
  `backtest_result.per_regime`) must be positive in a majority of regimes — an
  edge that lives in one regime only doesn't generalize.

Cross-asset rotation is deferred (single instrument: SPY). Missing input skips
that check.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from services.trader.walls.base import EvaluationContext, Wall, WallReport


class GeneralizationWall(Wall):
    name: ClassVar[str] = "generalization"

    def __init__(self, *, oos_frac: float = 0.5, regime_frac: float = 0.5) -> None:
        self.oos_frac = oos_frac
        self.regime_frac = regime_frac

    def evaluate(self, ctx: EvaluationContext) -> WallReport:
        try:
            oos = ctx.metadata.get("oos_sharpes")
            per_regime = ctx.metadata.get("per_regime_sharpes")
            if per_regime is None and ctx.backtest_result is not None:
                pr = getattr(ctx.backtest_result, "per_regime", None)
                if pr:
                    per_regime = {k: v.get("sharpe") for k, v in pr.items() if "sharpe" in v}

            checks: dict[str, bool] = {}

            if oos is not None and len(oos) > 0:
                a = np.asarray(oos, float)
                frac_pos = float(np.mean(a > 0))
                checks["walk_forward"] = bool(frac_pos >= self.oos_frac and np.nanmean(a) > 0)
            else:
                frac_pos = None

            if per_regime:
                vals = np.asarray([v for v in per_regime.values() if v is not None], float)
                regime_pos = float(np.mean(vals > 0)) if len(vals) else 0.0
                checks["multi_regime"] = regime_pos >= self.regime_frac
            else:
                regime_pos = None

            passed = all(checks.values()) if checks else True
            score = min(map(float, checks.values())) if checks else 0.5
            reason = (
                f"oos_frac_pos={_fmt(frac_pos)} (ok={checks.get('walk_forward', 'n/a')}), "
                f"regime_frac_pos={_fmt(regime_pos)} (ok={checks.get('multi_regime', 'n/a')})"
            )
            return WallReport(
                wall_name=self.name,
                passed=bool(passed),
                score=float(score),
                reason=reason,
                sub_results={"oos_frac_pos": frac_pos, "regime_frac_pos": regime_pos},
            )
        except Exception as exc:
            return WallReport(self.name, False, 0.0, f"generalization wall error: {exc!r}")


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"
