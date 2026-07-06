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

from services.trader.execution.compliance import ComplianceVerdict, TradeRecord
from services.trader.execution.firewall import FirewallContext, FirewallVerdict
from services.trader.execution.model import Order, OrderIntent, OrderStatus, Portfolio
from services.trader.execution.sizing import size_order

logger = logging.getLogger(__name__)

CtxBuilder = Callable[[OrderIntent, Order], FirewallContext]
RecentTradesProvider = Callable[[], list[TradeRecord]]
OnSubmitHook = Callable[[OrderIntent, Order], None]


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
    """Outcome of one execution cycle.

    `errors` counts intents whose broker submit RAISED (an HTTP/broker error):
    those are neither submitted nor rejected — the order's true state at the
    broker is unknown and reconciliation is the recovery path.
    """

    intents: int
    submitted: int
    rejected: int
    halted: bool
    errors: int = 0
    rejections: list[str] = field(default_factory=list)


class Executor:
    """Runs order intents through halt -> size -> firewall -> compliance -> broker.

    `live_orders` defaults False: every submit is a dry-run. Set it True only via
    an explicit, surfaced human decision (the CLAUDE.md real-capital gate). It is
    read-only after construction — no code path may flip a dry-run executor live.

    `recent_trades` supplies the compliance engine's trade history (PDT /
    wash-sale), fetched ONCE per cycle. `on_submit` is a best-effort persistence
    hook (trade store) called with the broker's RETURNED order; its failures are
    contained and never affect order accounting.
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
        recent_trades: RecentTradesProvider | None = None,
        on_submit: OnSubmitHook | None = None,
        allow_fractional: bool = True,
    ) -> None:
        self.broker = broker
        self.firewall = firewall
        self.compliance = compliance
        self.halt = halt
        self.hindsight = hindsight
        self._live_orders = live_orders
        self._recent_trades = recent_trades
        self._on_submit = on_submit
        # Alpaca rejects fractional qty on advanced order classes (OTO/bracket),
        # so live runners size whole shares; tests/backtests keep fractional.
        self._allow_fractional = allow_fractional

    @property
    def live_orders(self) -> bool:
        """Whether submits are live (True) or dry-run (False). Read-only."""
        return self._live_orders

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
        errors = 0
        rejections: list[str] = []

        # Trade history for compliance — fetched ONCE per cycle (C3): every
        # intent is judged against the same PDT / wash-sale history snapshot.
        recent_trades: list[TradeRecord] = (
            self._recent_trades() if self._recent_trades is not None else []
        )

        for intent in intents:
            # 1. Halt FIRST — a tripped kill-switch stops the cycle immediately.
            if self.halt.is_halted():
                logger.warning(
                    "HALT active — stopping cycle; %d intent(s) not processed",
                    len(intents) - submitted - rejected - errors,
                )
                return CycleReport(
                    intents=len(intents),
                    submitted=submitted,
                    rejected=rejected,
                    halted=True,
                    errors=errors,
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
            order = size_order(
                intent, portfolio, price, allow_fractional=self._allow_fractional
            )
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
                intent, portfolio, recent_trades=recent_trades, now=ctx.now
            )
            if not cv.allowed:
                rejected += 1
                rejections.extend(
                    f"{intent.ticker}: compliance: {r}" for r in cv.rejections
                )
                logger.info("REJECT %s compliance: %s", intent.ticker, cv.rejections)
                continue

            # 6. Submit — dry-run unless live_orders explicitly enabled. A broker
            # exception is contained per-intent (C9): counted under `errors`,
            # the cycle continues, and the report is never lost.
            dry_run = not self._live_orders
            try:
                returned = self.broker.submit_order(order, dry_run=dry_run)
            except Exception:
                errors += 1
                logger.exception(
                    "broker error submitting %s %s qty=%s — intent counted as "
                    "error (neither submitted nor rejected); continuing cycle",
                    intent.side,
                    intent.ticker,
                    order.qty,
                )
                continue

            # The broker may ACCEPT the call but REJECT the order.
            if returned is not None and returned.status is OrderStatus.REJECTED:
                rejected += 1
                reason = f"{intent.ticker}: broker returned status REJECTED (id={returned.id})"
                rejections.append(reason)
                logger.info("REJECT %s", reason)
                continue

            submitted += 1
            logger.info(
                "SUBMIT %s %s qty=%s dry_run=%s",
                intent.side,
                intent.ticker,
                order.qty,
                dry_run,
            )
            self._record_submit(intent, returned if returned is not None else order)
            self._retain(intent, order, ctx, dry_run)

        return CycleReport(
            intents=len(intents),
            submitted=submitted,
            rejected=rejected,
            halted=False,
            errors=errors,
            rejections=rejections,
        )

    def _record_submit(self, intent: OrderIntent, returned: Order) -> None:
        """Invoke the on_submit persistence hook; failures logged, never re-raised."""
        if self._on_submit is None:
            return
        try:
            self._on_submit(intent, returned)
        except Exception:
            logger.exception(
                "on_submit hook failed for %s (ignored — accounting unaffected)",
                intent.ticker,
            )

    def _retain(
        self,
        intent: OrderIntent,
        order: Order,
        ctx: FirewallContext,
        dry_run: bool,
    ) -> None:
        """Retain the decision context as a Hindsight Experience Fact (best-effort).

        Contained (C9): a Hindsight failure is logged and ignored — memory
        writes must never affect order accounting.
        """
        try:
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
        except Exception:
            logger.exception(
                "hindsight retain failed for %s (ignored — accounting unaffected)",
                intent.ticker,
            )
