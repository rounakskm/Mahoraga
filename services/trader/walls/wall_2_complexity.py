"""Wall 2 — Complexity Control.

Is the edge robust to its own parameters, or curve-fit? Three checks over results
the harness/loop supplies in `ctx.metadata` (the wall stays a pure predicate; the
expensive re-backtesting is the harness's job):

- sensitivity: `perturbed_sharpes` (Sharpes under ±10/20% parameter perturbation)
  must not collapse vs the base Sharpe;
- stability: `rolling_sharpes` (per rolling-window Sharpe) must stay mostly positive;
- MDL: more parameters (`num_params`) = a description-length penalty on the score.

A missing input skips that check (not a failure), as in Wall 1.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from services.trader.walls import risklabai_wrap as rl
from services.trader.walls.base import EvaluationContext, Wall, WallReport


class ComplexityControlWall(Wall):
    name: ClassVar[str] = "complexity_control"

    def __init__(
        self, *, sensitivity_ratio: float = 0.5, stability_frac: float = 0.5
    ) -> None:
        self.sensitivity_ratio = sensitivity_ratio  # perturbed edge must keep >= this share
        self.stability_frac = stability_frac  # this share of windows must be positive

    def evaluate(self, ctx: EvaluationContext) -> WallReport:
        try:
            base = rl.sharpe(ctx.returns)
            perturbed = ctx.metadata.get("perturbed_sharpes")
            rolling = ctx.metadata.get("rolling_sharpes")
            num_params = int(ctx.metadata.get("num_params", 1))

            checks: dict[str, bool] = {}

            # sensitivity: edge survives small parameter perturbation
            if perturbed is not None and base > 1e-9:
                ratio = float(np.nanmean(perturbed)) / base
                checks["sensitivity"] = ratio >= self.sensitivity_ratio
            else:
                ratio = None

            # stability: edge holds across rolling windows
            if rolling is not None and len(rolling) > 0:
                frac_pos = float(np.mean(np.asarray(rolling, float) > 0))
                checks["stability"] = frac_pos >= self.stability_frac
            else:
                frac_pos = None

            # MDL: penalise parameter count (cheap proxy: 1/(1+log2 params))
            mdl_score = 1.0 / (1.0 + np.log2(max(num_params, 1)))

            passed = all(checks.values()) if checks else True
            score = mdl_score if not checks else min([mdl_score, *map(float, checks.values())])
            reason = (
                f"sensitivity_ratio={_fmt(ratio)} (ok={checks.get('sensitivity', 'n/a')}), "
                f"stability_frac={_fmt(frac_pos)} (ok={checks.get('stability', 'n/a')}), "
                f"num_params={num_params} mdl={mdl_score:.2f}"
            )
            return WallReport(
                wall_name=self.name,
                passed=bool(passed),
                score=float(score),
                reason=reason,
                sub_results={
                    "sensitivity_ratio": ratio,
                    "stability_frac": frac_pos,
                    "num_params": num_params,
                    "mdl_score": mdl_score,
                },
            )
        except Exception as exc:
            return WallReport(self.name, False, 0.0, f"complexity_control wall error: {exc!r}")


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"
