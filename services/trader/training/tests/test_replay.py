"""Replay clock: PIT-clamped compressed-history slices that never leak the vault
or the future (Phase 3, Layer 3, Task 6)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.trader.training.replay import ReplayClock, ReplayStep, replay_campaign
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
    # a deliberately-bad step (slice extends PAST asof) must be rejected at
    # construction — the PIT invariant lives in ReplayStep itself, not the tests.
    p = _price(500)
    r = label_regimes(p)
    asof = p.index[250]
    with pytest.raises(ValueError, match="PIT"):
        ReplayStep(asof=asof, train_price=p, train_regimes=r[r.index <= asof])


def test_leak_canary_trips_on_future_regimes():
    p = _price(500)
    r = label_regimes(p)
    asof = p.index[250]
    with pytest.raises(ValueError, match="PIT"):
        ReplayStep(asof=asof, train_price=p[p.index <= asof], train_regimes=r)


def test_good_step_constructs_cleanly():
    p = _price(500)
    r = label_regimes(p)
    asof = p.index[250]
    s = ReplayStep(
        asof=asof, train_price=p[p.index <= asof], train_regimes=r[r.index <= asof]
    )
    assert s.train_price.index.max() <= s.asof


def test_replay_campaign_runs_fn_per_step():
    p = _price(2000)
    r = label_regimes(p)
    cut = p.index[-180]
    results = replay_campaign(
        p, r, lambda step: step.asof, start=p.index[250], vault_cutoff=cut, step_days=63
    )
    steps = list(ReplayClock(p, r, start=p.index[250], vault_cutoff=cut, step_days=63))
    assert results == [s.asof for s in steps]
