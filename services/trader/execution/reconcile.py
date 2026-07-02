"""Reconciler — local Portfolio vs broker positions, halt on material drift (Phase 5, Task 9).

The reconciliation invariant: the system's belief about its open positions must
match the broker's truth. Any *material* discrepancy is a state-integrity failure —
we cannot safely trade against a portfolio we don't understand — so it trips the
kill-switch and requires human review rather than being silently reconciled.

Two failure classes are material:
  * phantom position — a ticker held on one side but not the other, and
  * notional drift — a shared ticker whose market values differ by more than
    `notional_tolerance` of local equity (default 1%).
Sub-tolerance notional diffs are benign (fills, quote skew) and do not halt.

Pure domain code: consumes the broker only through `.positions() -> dict[str, Position]`
and the halt only through `HaltControl`; no runtime-specific glue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from services.trader.execution.model import Portfolio, Position
from services.trader.ops.halt import HaltControl


class _BrokerPositions(Protocol):
    """Structural type: anything exposing broker positions by ticker."""

    def positions(self) -> dict[str, Position]: ...


@dataclass(frozen=True)
class ReconResult:
    """Outcome of one reconciliation pass."""

    matched: bool
    mismatches: list[str]
    halted: bool


class Reconciler:
    """Compares a local Portfolio against live broker positions; halts on material drift."""

    def __init__(
        self,
        broker: _BrokerPositions,
        halt: HaltControl,
        notional_tolerance: float = 0.01,
    ) -> None:
        self.broker = broker
        self.halt = halt
        self.notional_tolerance = notional_tolerance

    def reconcile(self, local: Portfolio) -> ReconResult:
        """Fetch broker positions, diff against `local.positions`, halt on any mismatch."""
        broker_positions = self.broker.positions()

        # Graceful-offline guard: a disabled/empty broker with an empty local
        # book is not a discrepancy — there is simply nothing to reconcile.
        if not broker_positions and not local.positions:
            return ReconResult(matched=True, mismatches=[], halted=False)

        mismatches: list[str] = []
        tolerance = self.notional_tolerance * max(local.equity, 1.0)

        # Phantom positions: present on exactly one side.
        for ticker in sorted(set(broker_positions) - set(local.positions)):
            mv = broker_positions[ticker].market_value
            mismatches.append(
                f"phantom broker position {ticker} (market_value={mv:.2f}, not in local)"
            )
        for ticker in sorted(set(local.positions) - set(broker_positions)):
            mv = local.positions[ticker].market_value
            mismatches.append(
                f"phantom local position {ticker} (market_value={mv:.2f}, not in broker)"
            )

        # Notional drift on shared tickers.
        for ticker in sorted(set(broker_positions) & set(local.positions)):
            drift = abs(
                broker_positions[ticker].market_value
                - local.positions[ticker].market_value
            )
            if drift > tolerance:
                mismatches.append(
                    f"notional drift {ticker} (drift={drift:.2f} > tol={tolerance:.2f})"
                )

        halted = False
        if mismatches:
            self.halt.halt(f"reconciliation: {'; '.join(mismatches)}")
            halted = True

        return ReconResult(matched=not mismatches, mismatches=mismatches, halted=halted)
