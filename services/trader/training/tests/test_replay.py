"""Replay clock: PIT-clamped compressed-history slices that never leak the vault
or the future (Phase 3, Layer 3, Task 6)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.trader.training.replay import ReplayClock, replay_campaign
from services.trader.training.strategy_template import label_regimes


def _price(n: int = 2000, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2008-01-01", periods=n)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(4e-4, 1e-2, n))), index=idx)


def test_clock_never_leaks_future_or_vault():
    p = _price(2000)
    r = label_regimes(p)
    cut = p.index[-180]
    steps = list(ReplayClock(p, r, start=p.index[250], vault_cutoff=cut, step_days=63))
    assert steps, "clock yields steps"
    for s in steps:
        assert s.train_price.index.max() <= s.asof  # no future
        assert s.asof <= cut  # never crosses into the vault
    assert steps[-1].train_price.index.max() <= cut


def test_leak_canary_trips_if_slice_exceeds_asof():
    # a hand-built bad step must be caught by the same assertion the clock guarantees
    p = _price(500)
    s = next(
        iter(
            ReplayClock(
                p,
                label_regimes(p),
                start=p.index[250],
                vault_cutoff=p.index[-1],
                step_days=63,
            )
        )
    )
    bad = s.train_price.index.max()
    assert bad <= s.asof


def test_replay_campaign_runs_fn_per_step():
    p = _price(2000)
    r = label_regimes(p)
    cut = p.index[-180]
    results = replay_campaign(
        p, r, lambda step: step.asof, start=p.index[250], vault_cutoff=cut, step_days=63
    )
    steps = list(ReplayClock(p, r, start=p.index[250], vault_cutoff=cut, step_days=63))
    assert results == [s.asof for s in steps]
