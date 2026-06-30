"""Vault-holdout validation (Phase 3, Layer 1).

The non-negotiable correctness gate (CLAUDE.md: "vault holdout validation must
pass before any live capital"). The search (loop) runs ONLY on training data; the
promoted best is then measured on the embargoed vault — the most recent
`vault_days` the search never touched. A strategy whose edge collapses on the
vault was a survivor of the search, not a real edge.

The regime detector is causal (rolling ADX + rolling-rank realized-vol), so labels
can be computed on the full series and sliced without look-ahead. The selected
strategy is run over the full series (so its SMAs have warmup) and only the
vault-period returns are scored — measuring a *fixed* strategy on unseen data is
not leakage.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from services.trader.training.strategy_template import RegimeConditionalStrategy
from services.trader.walls import risklabai_wrap as rl


@dataclass(frozen=True)
class VaultReport:
    train_sharpe: float
    vault_sharpe: float
    holds: bool
    reason: str


def vault_cutoff(price: pd.Series, vault_days: int = 180) -> pd.Timestamp:
    """The last timestamp that is still TRAINING data (everything after is vault)."""
    return price.index[-1] - pd.Timedelta(days=vault_days)


def split_train(
    price: pd.Series, regimes: pd.Series, vault_days: int = 180
) -> tuple[pd.Series, pd.Series, pd.Timestamp]:
    """Training slice (<= cutoff) the search is allowed to see, plus the cutoff."""
    cutoff = vault_cutoff(price, vault_days)
    mask = price.index <= cutoff
    return price[mask], regimes[mask], cutoff


def validate_on_vault(
    strategy: RegimeConditionalStrategy,
    full_price: pd.Series,
    full_regimes: pd.Series,
    cutoff: pd.Timestamp,
    train_sharpe: float,
    *,
    min_ratio: float = 0.5,
) -> VaultReport:
    """Does the promoted strategy's edge survive on the untouched vault?

    Holds iff vault Sharpe is positive AND retains at least `min_ratio` of the
    train Sharpe — the edge generalises to data the search never saw.
    """
    returns = strategy.returns(full_price, full_regimes)  # full series -> SMA warmup
    vault_returns = returns[returns.index > cutoff]
    vs = rl.sharpe(vault_returns)
    holds = bool(vs > 0 and train_sharpe > 0 and vs >= min_ratio * train_sharpe)
    reason = (
        f"train={train_sharpe:.4f} vault={vs:.4f} "
        f"(>0 and >= {min_ratio:g}×train: {holds}; {len(vault_returns)} vault bars)"
    )
    return VaultReport(train_sharpe=train_sharpe, vault_sharpe=vs, holds=holds, reason=reason)
