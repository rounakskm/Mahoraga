"""VaultValidator — Layer-3 in-sample-vs-vault tolerance check (Task 9)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.trader.training.eval import compute_fitness
from services.trader.training.strategy_template import RegimeConditionalStrategy, label_regimes
from services.trader.training.vault import VaultValidation, VaultValidator, vault_cutoff


def _trending_price(n: int = 1200, seed: int = 0) -> pd.Series:
    """A persistently up-trending series so a long-SMA strategy has a real edge
    that survives into the vault (the SMA-timing edge generalises)."""
    idx = pd.bdate_range("2016-01-01", periods=n)
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(7e-4, 8e-3, n))), index=idx)


def _train_fitness(strategy: RegimeConditionalStrategy, price: pd.Series,
                   regimes: pd.Series, cutoff: pd.Timestamp) -> float:
    returns = strategy.returns(price, regimes)
    train_returns = returns[returns.index <= cutoff]
    return compute_fitness(train_returns).score


def test_validate_passes_when_vault_edge_holds_within_tolerance() -> None:
    price = _trending_price()
    regimes = label_regimes(price)
    cutoff = vault_cutoff(price)
    strategy = RegimeConditionalStrategy.seed()
    train_fitness = _train_fitness(strategy, price, regimes, cutoff)

    result = VaultValidator(tolerance=0.5).validate(
        strategy, price, regimes, cutoff, train_fitness
    )
    assert isinstance(result, VaultValidation)
    assert result.passes is True
    assert result.vault_fitness == result.vault_fitness  # not NaN
    assert result.ratio >= 0.5
    assert "vault" in result.reason.lower()


def test_validate_fails_when_vault_fitness_collapses() -> None:
    price = _trending_price()
    regimes = label_regimes(price)
    cutoff = vault_cutoff(price)
    strategy = RegimeConditionalStrategy.seed()

    # Claim an in-sample fitness far above anything the vault period can reach: the
    # vault fitness then sits well below tolerance×train and the candidate is failed.
    inflated_train_fitness = 100.0
    result = VaultValidator(tolerance=0.5).validate(
        strategy, price, regimes, cutoff, inflated_train_fitness
    )
    assert result.passes is False
    assert result.ratio < 0.5  # vault fitness is a tiny fraction of the claimed train
    assert "tolerance" in result.reason.lower() or "below" in result.reason.lower()
