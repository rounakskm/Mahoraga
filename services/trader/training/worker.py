"""worker.py — Hunter isolated git-worktree mechanic (Phase 3, Layer 3).

A Hunter experiment runs inside its own `git worktree`, giving each parallel
candidate filesystem isolation for its per-experiment artifacts/logs (the
seven-role amendment's parallel-Hunter isolation requirement). Two concurrent
experiments never share a path; the worktree is always removed, even on failure.

ponytail: the eval is pure-Python in-process; the worktree isolates artifacts, not
compute — `# ponytail: worktree isolates artifacts, not compute; upgrade to
subprocess eval if a mutation ever shells out`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd

from services.trader.training.eval import evaluate
from services.trader.training.parse_metric import FitnessReport, report_from_eval
from services.trader.training.strategy_template import RegimeConditionalStrategy


def run_in_worktree(
    candidate: RegimeConditionalStrategy,
    price: pd.Series,
    regimes: pd.Series,
    *,
    base_dir: str = ".runtime/worktrees",
    experiment_id: str,
) -> FitnessReport:
    """Evaluate ``candidate`` inside an isolated ``git worktree`` at
    ``<base_dir>/<experiment_id>`` and return its FitnessReport. The worktree is
    removed afterwards, even if evaluation raises."""
    path = Path(base_dir) / experiment_id
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(path)],
        check=True,
        capture_output=True,
    )
    try:
        ev = evaluate(candidate, price, regimes)
        return report_from_eval(ev, candidate.windows)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(path)],
            check=False,
            capture_output=True,
        )
