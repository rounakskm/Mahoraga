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

from services.trader.training.eval import compute_fitness
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


@dataclass(frozen=True)
class VaultValidation:
    """The Layer-3 in-sample-vs-vault verdict: did the promoted candidate's edge
    survive AND match its in-sample fitness within tolerance?"""

    passes: bool
    vault_fitness: float
    ratio: float
    reason: str


class VaultValidator:
    """Layer-3 exit check (amendment §7): a promoted candidate is deployment-eligible
    only when its *fitness* on the embargoed vault holds within `tolerance` of its
    in-sample fitness. Wraps the Layer-1 `validate_on_vault` holds-gate (vault edge
    is real, positive, and retains a fraction of the train Sharpe) and adds the
    fitness-tolerance band on the loop's true objective (`compute_fitness`).
    """

    def __init__(self, tolerance: float = 0.5) -> None:
        self.tolerance = tolerance

    def validate(
        self,
        strategy: RegimeConditionalStrategy,
        price: pd.Series,
        regimes: pd.Series,
        cutoff: pd.Timestamp,
        train_fitness: float,
    ) -> VaultValidation:
        # Score the FIXED strategy over the full series (SMA warmup) and isolate the
        # vault period — measuring a frozen strategy on unseen data is not leakage.
        returns = strategy.returns(price, regimes)
        vault_returns = returns[returns.index > cutoff]
        vault_fitness = compute_fitness(vault_returns).score
        ratio = vault_fitness / train_fitness if train_fitness > 0 else 0.0

        # The Layer-1 holds-gate (vault edge real, positive, generalises on Sharpe).
        train_returns = returns[returns.index <= cutoff]
        holds_report = validate_on_vault(
            strategy, price, regimes, cutoff, rl.sharpe(train_returns)
        )

        within_tolerance = vault_fitness >= self.tolerance * train_fitness
        passes = bool(holds_report.holds and within_tolerance)
        if not holds_report.holds:
            reason = f"vault edge did not hold ({holds_report.reason})"
        elif not within_tolerance:
            reason = (
                f"vault fitness {vault_fitness:.4f} below tolerance "
                f"({self.tolerance:g}×train {train_fitness:.4f} = "
                f"{self.tolerance * train_fitness:.4f}); ratio={ratio:.3f}"
            )
        else:
            reason = (
                f"vault holds and fitness {vault_fitness:.4f} within tolerance "
                f"(ratio={ratio:.3f} >= {self.tolerance:g})"
            )
        return VaultValidation(
            passes=passes, vault_fitness=vault_fitness, ratio=ratio, reason=reason
        )
