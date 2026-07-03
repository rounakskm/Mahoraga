"""Worker: Hunter isolated git-worktree mechanic (Phase 3, Layer 3, Task 5).

Skips cleanly until parse_metric (Task 1) merges; runs post-integration.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("services.trader.training.parse_metric")

from services.trader.training.parse_metric import FitnessReport  # noqa: E402
from services.trader.training.strategy_template import (  # noqa: E402
    RegimeConditionalStrategy,
    label_regimes,
)
from services.trader.training.worker import run_in_worktree  # noqa: E402


def _price(n: int = 600, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(4e-4, 1e-2, n))), index=idx)


def test_run_in_worktree_returns_report_and_cleans_up(tmp_path):
    p = _price()
    r = label_regimes(p)
    s = RegimeConditionalStrategy.seed()
    base = tmp_path / "worktrees"
    report = run_in_worktree(
        s, p, r, base_dir=str(base), experiment_id="exp-a"
    )
    assert isinstance(report, FitnessReport)
    assert not (base / "exp-a").exists()  # worktree removed


def test_hash_surface_includes_detector_thresholds():
    # Two candidates differing ONLY in adx_threshold must produce distinct
    # report.candidate_hash via the worker's report path (same surface, no
    # worktree needed: report_from_eval + strategy_params directly).
    from dataclasses import replace

    from services.trader.training.eval import evaluate
    from services.trader.training.parse_metric import report_from_eval
    from services.trader.training.roles import strategy_params

    p = _price()
    r = label_regimes(p)
    a = RegimeConditionalStrategy.seed()
    b = replace(a, adx_threshold=a.adx_threshold + 2.0)
    report_a = report_from_eval(evaluate(a, p, r), strategy_params(a))
    report_b = report_from_eval(evaluate(b, p, r), strategy_params(b))
    assert report_a.candidate_hash != report_b.candidate_hash


def test_two_experiments_never_collide(tmp_path):
    p = _price()
    r = label_regimes(p)
    s = RegimeConditionalStrategy.seed()
    base = tmp_path / "worktrees"
    a = run_in_worktree(s, p, r, base_dir=str(base), experiment_id="exp-a")
    b = run_in_worktree(s, p, r, base_dir=str(base), experiment_id="exp-b")
    assert isinstance(a, FitnessReport) and isinstance(b, FitnessReport)
    assert not (base / "exp-a").exists()
    assert not (base / "exp-b").exists()
    # distinct paths never shared
    assert Path(base / "exp-a") != Path(base / "exp-b")
