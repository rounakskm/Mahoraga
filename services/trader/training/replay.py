"""replay.py — compressed-history PIT-clamped clock (Phase 3, Layer 3).

Replays historical price/regime data as an expanding point-in-time (PIT) window so
the loop "experiences" many regimes at accelerated speed. Two invariants are
architectural, not advisory: every training slice is `<= asof` (no look-ahead) and
`asof <= vault_cutoff` (the last-N-months holdout is never touched). The leak
canary in the test asserts the same bound the clock guarantees.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ReplayStep:
    asof: pd.Timestamp
    train_price: pd.Series
    train_regimes: pd.Series

    def __post_init__(self) -> None:
        # The real leak canary: a slice that extends past `asof` is a look-ahead
        # bias, rejected at construction (architectural, not advisory).
        for name, series in (
            ("train_price", self.train_price),
            ("train_regimes", self.train_regimes),
        ):
            if len(series) and series.index.max() > self.asof:
                raise ValueError(
                    f"PIT violation: {name} extends to {series.index.max()} "
                    f"> asof {self.asof}"
                )


class ReplayClock:
    """Yield expanding PIT slices from ``start`` to ``vault_cutoff`` in ``step_days``
    business-day strides. Each slice is clamped to ``index <= asof <= vault_cutoff``."""

    def __init__(
        self,
        price: pd.Series,
        regimes: pd.Series,
        *,
        start: pd.Timestamp,
        vault_cutoff: pd.Timestamp,
        step_days: int = 63,
    ) -> None:
        self.price = price
        self.regimes = regimes
        self.start = pd.Timestamp(start)
        self.vault_cutoff = pd.Timestamp(vault_cutoff)
        self.step_days = step_days

    def __iter__(self) -> Iterator[ReplayStep]:
        asof = self.start
        while asof <= self.vault_cutoff:
            mask = self.price.index <= asof
            yield ReplayStep(
                asof=asof,
                train_price=self.price[mask],
                train_regimes=self.regimes[self.regimes.index <= asof],
            )
            asof = asof + pd.tseries.offsets.BDay(self.step_days)


def replay_campaign(
    price: pd.Series,
    regimes: pd.Series,
    run_fn: Callable[[ReplayStep], Any],
    **clock_kw: Any,
) -> list[Any]:
    """Run ``run_fn`` once per PIT step and collect the results."""
    return [run_fn(step) for step in ReplayClock(price, regimes, **clock_kw)]
