"""Executor — the firewall-gated order flow (Phase 5, Task 10).

SAFETY-CRITICAL capstone. This is the single place where a sized order can reach
the broker, and by construction it cannot reach the broker without passing BOTH
the hard-limit firewall and the compliance engine first.

THE INVARIANT (Phase-5 exit criterion):
  1. `halt.is_halted()` is checked FIRST every iteration — a tripped kill-switch
     stops the cycle immediately (no further processing, no submits).
  2. The firewall and compliance run BEFORE the broker; only an order both allow
     is ever handed to `broker.submit_order`.
  3. Submission defaults to dry-run (`live_orders=False` -> `dry_run=True`), so a
     paper order is never live unless a human explicitly flips `live_orders`.

A rejected or halted order is logged, counted, and NEVER submitted.

The executor is deliberately ignorant of regime/P&L: the caller supplies a
`ctx_for(intent, order) -> FirewallContext` builder so this module stays pure
order-flow plumbing with no market-data coupling.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from services.trader.execution.compliance import ComplianceVerdict
from services.trader.execution.firewall import FirewallContext, FirewallVerdict
from services.trader.execution.model import Order, OrderIntent, Portfolio
from services.trader.execution.sizing import size_order

logger = logging.getLogger(__name__)

CtxBuilder = Callable[[OrderIntent, Order], FirewallContext]


class _BrokerLike(Protocol):
    def submit_order(self, order: Order, *, dry_run: bool = True) -> Order:
        ...


class _FirewallLike(Protocol):
    def check(
        self,
        intent: OrderIntent,
        order: Order,
        portfolio: Portfolio,
        ctx: FirewallContext,
    ) -> FirewallVerdict:
        ...


class _ComplianceLike(Protocol):
    def check(
        self,
        intent: OrderIntent,
        portfolio: Portfolio,
        recent_trades: list,
        now: object,
    ) -> ComplianceVerdict:
        ...


class _HaltLike(Protocol):
    def is_halted(self) -> bool:
        ...


class _HindsightLike(Protocol):
    def is_enabled(self) -> bool:
        ...

    def retain(self, text: str, metadata: dict | None = None) -> str | None:
        ...


@dataclass(frozen=True)
class CycleReport:
    """Outcome of one execution cycle."""

    intents: int
    submitted: int
    rejected: int
    halted: bool
    rejections: list[str] = field(default_factory=list)


class Executor:
    """Runs order intents through halt -> size -> firewall -> compliance -> broker.

    `live_orders` defaults False: every submit is a dry-run. Set it True only via
    an explicit, surfaced human decision (the CLAUDE.md real-capital gate).
    """

    def __init__(
        self,
        broker: _BrokerLike,
        firewall: _FirewallLike,
        compliance: _ComplianceLike,
        halt: _HaltLike,
        *,
        hindsight: _HindsightLike | None = None,
        live_orders: bool = False,
    ) -> None:
        self.broker = broker
        self.firewall = firewall
        self.compliance = compliance
        self.halt = halt
        self.hindsight = hindsight
        self.live_orders = live_orders

    def run_cycle(
        self,
        intents: list[OrderIntent],
        portfolio: Portfolio,
        prices: dict[str, float],
        ctx_for: CtxBuilder,
    ) -> CycleReport:
        """Process each intent in order under the safety invariant.

        For each intent, in order: halt-first -> price -> size -> firewall ->
        compliance -> submit. A halt stops the whole cycle immediately. Any
        rejection (price/size/firewall/compliance) counts as rejected and is
        NEVER submitted.
        """
        submitted = 0
        rejected = 0
        rejections: list[str] = []

        for intent in intents:
            # 1. Halt FIRST — a tripped kill-switch stops the cycle immediately.
            if self.halt.is_halted():
                logger.warning(
                    "HALT active — stopping cycle; %d intent(s) not processed",
                    len(intents) - submitted - rejected,
                )
                return CycleReport(
                    intents=len(intents),
                    submitted=submitted,
                    rejected=rejected,
                    halted=True,
                    rejections=rejections,
                )

            # 2. Price gate.
            price = prices.get(intent.ticker)
            if price is None or price <= 0:
                rejected += 1
                reason = f"{intent.ticker}: no price (skipped)"
                rejections.append(reason)
                logger.info("REJECT %s", reason)
                continue

            # 3. Sizing.
            order = size_order(intent, portfolio, price)
            if order is None:
                rejected += 1
                reason = f"{intent.ticker}: sized to zero / sub-min notional (skipped)"
                rejections.append(reason)
                logger.info("REJECT %s", reason)
                continue

            # 4. Hard-limit firewall — BEFORE the broker; never submit if denied.
            ctx = ctx_for(intent, order)
            fw = self.firewall.check(intent, order, portfolio, ctx)
            if not fw.allowed:
                rejected += 1
                rejections.extend(f"{intent.ticker}: firewall: {r}" for r in fw.rejections)
                logger.info("REJECT %s firewall: %s", intent.ticker, fw.rejections)
                continue

            # 5. Compliance — BEFORE the broker; never submit if denied.
            cv = self.compliance.check(
                intent, portfolio, recent_trades=[], now=ctx.now
            )
            if not cv.allowed:
                rejected += 1
                rejections.extend(
                    f"{intent.ticker}: compliance: {r}" for r in cv.rejections
                )
                logger.info("REJECT %s compliance: %s", intent.ticker, cv.rejections)
                continue

            # 6. Submit — dry-run unless live_orders explicitly enabled.
            dry_run = not self.live_orders
            self.broker.submit_order(order, dry_run=dry_run)
            submitted += 1
            logger.info(
                "SUBMIT %s %s qty=%s dry_run=%s",
                intent.side,
                intent.ticker,
                order.qty,
                dry_run,
            )
            self._retain(intent, order, ctx, dry_run)

        return CycleReport(
            intents=len(intents),
            submitted=submitted,
            rejected=rejected,
            halted=False,
            rejections=rejections,
        )

    def _retain(
        self,
        intent: OrderIntent,
        order: Order,
        ctx: FirewallContext,
        dry_run: bool,
    ) -> None:
        """Retain the decision context as a Hindsight Experience Fact (best-effort)."""
        if self.hindsight is None or not self.hindsight.is_enabled():
            return
        text = (
            f"Executed {intent.side} {intent.ticker} qty={order.qty} "
            f"(reason: {intent.reason}; regime_confidence={intent.regime_confidence:.2f}; "
            f"dry_run={dry_run})"
        )
        metadata = {
            "kind": "execution",
            "ticker": intent.ticker,
            "side": str(intent.side),
            "qty": order.qty,
            "reason": intent.reason,
            "regime_confidence": intent.regime_confidence,
            "dry_run": dry_run,
        }
        self.hindsight.retain(text, metadata)
