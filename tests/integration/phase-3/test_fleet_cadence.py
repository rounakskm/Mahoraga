"""Phase-3 Layer-3 fleet integration smoke (Task 17).

Drives the seven-role Orchestrator cadence end-to-end on a synthetic SPY-like
series, fully offline: no Postgres (`dsn=None`), no LLM (mechanical Planner
fallback), no Hindsight, no network. Asserts a cadence produces a non-empty
CadenceSummary and that a compressed-replay campaign yields per-step summaries.

The halt kill-switch is a shared file flag (`data/control/halt.flag`); each test
injects an isolated `HaltControl` under `tmp_path` so a prior run that tripped the
catastrophic-drawdown halt cannot poison this hermetic smoke.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from services.trader.ops.halt import HaltControl
from services.trader.training.orchestrator import CadenceSummary, Orchestrator
from services.trader.training.replay import replay_campaign
from services.trader.training.strategy_template import label_regimes


def _price(n: int = 700, seed: int = 0, drift: float = 0.0006, vol: float = 0.003) -> pd.Series:
    """A low-volatility uptrend so a real strategy stays above the catastrophic
    drawdown gate, exercising the full record path (not just the halt branch)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(drift, vol, n))), index=idx)


def _halt(tmp_path: Path) -> HaltControl:
    return HaltControl(tmp_path / "halt.flag")


def test_nightly_cadence_runs_offline(tmp_path: Path) -> None:
    price = _price()
    regimes = label_regimes(price)
    summary = Orchestrator(price, regimes, halt=_halt(tmp_path)).run_cadence(
        "nightly", iterations=3
    )
    assert isinstance(summary, CadenceSummary)
    assert summary.cadence == "nightly"
    assert summary.proposed > 0
    assert summary.recorded > 0
    assert summary.halted is False


def test_replay_cadence_yields_step_summaries(tmp_path: Path) -> None:
    price = _price(n=1400, seed=1)
    regimes = label_regimes(price)
    cut = price.index[-180]

    def run_fn(step) -> CadenceSummary:
        return Orchestrator(
            step.train_price, step.train_regimes, halt=_halt(tmp_path)
        ).run_cadence("replay", iterations=2)

    summaries = replay_campaign(
        price,
        regimes,
        run_fn,
        start=price.index[252],
        vault_cutoff=cut,
        step_days=126,
    )
    assert len(summaries) >= 1
    assert all(isinstance(s, CadenceSummary) for s in summaries)
    assert all(s.cadence == "replay" for s in summaries)
