"""Hard-limit firewall — the architectural entry gate (Phase 5, Task 7).

SAFETY-CRITICAL. This is the architectural boundary the executor calls *before*
the broker: an order that fails any hard limit is rejected and, by construction,
never reaches Alpaca. The check is a pure predicate collection with no I/O — it
gathers EVERY violation (no short-circuit) so a rejected order surfaces its full
reason set for logging and Experience-Fact retention.

The thresholds map 1:1 to the project plan's "Hard risk limits" table and reuse
the Phase-1 `backtest/risk.py` default values as the single source of truth:

    - Max single position: 5% of portfolio equity.
    - Max sector exposure: 20%.
    - Daily loss halt: 2% (no new entries that day).
    - Catastrophic monthly drawdown: 10% -> human review.
    - No new entries if regime confidence < 40%.
    - No new entries within the FOMC/CPI/NFP blackout window (calendar gate).
    - Stop-loss on every trade (missing ATR stop -> reject).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

from services.trader.backtest.risk import (
    DEFAULT_DAILY_LOSS_HALT,
    DEFAULT_MAX_POSITION,
    DEFAULT_MAX_SECTOR,
    DEFAULT_MONTHLY_DRAWDOWN_HALT,
    DEFAULT_REGIME_CONFIDENCE_HALT,
)
from services.trader.execution.model import Order, OrderIntent, Portfolio, Side

# Float-comparison slack for the 2xATR stop-distance bound.
_STOP_DISTANCE_EPS = 1e-6


class _CalendarGateLike(Protocol):
    """The single method the firewall needs from `EconCalendarGate`."""

    def is_blackout(self, now: pd.Timestamp) -> bool:
        ...


@dataclass(frozen=True)
class FirewallContext:
    """Point-in-time inputs the firewall evaluates an order against.

    `order_notional` is the strategy's UN-clamped requested dollar exposure,
    computed by the caller (`context.build_firewall_context`) so the firewall
    stays pure — position/sector percentages are derived from it and
    `portfolio.equity`.

    `reduces_exposure` marks orders that close/shrink an existing position:
    entry-only gates (daily loss, monthly catastrophic, blackout, regime
    confidence, missing stop, position/sector limits) do NOT apply to them —
    the system must always be able to exit.

    `atr_value` / `entry_price` enable stop-distance validation: with both
    present, a stop must sit on the protective side of entry and within
    2xATR of it.
    """

    now: pd.Timestamp
    regime_confidence: float
    daily_pl_pct: float
    monthly_pl_pct: float
    has_stop: bool
    sector: str
    order_notional: float
    reduces_exposure: bool = False
    atr_value: float | None = None
    entry_price: float | None = None


@dataclass(frozen=True)
class FirewallVerdict:
    """Outcome of a firewall check: allowed plus every rejection reason."""

    allowed: bool
    rejections: list[str] = field(default_factory=list)


class HardLimitFirewall:
    """Architectural hard-limit gate. Collects ALL violations, never short-circuits.

    Defaults come from the Phase-1 `backtest/risk.py` limit logic (which the
    plan mandates reusing) so the backtest guard-rails and the live execution
    boundary enforce identical thresholds.
    """

    def __init__(
        self,
        max_position_pct: float = DEFAULT_MAX_POSITION,
        max_sector_pct: float = DEFAULT_MAX_SECTOR,
        daily_loss_halt: float = abs(DEFAULT_DAILY_LOSS_HALT),
        monthly_catastrophic: float = abs(DEFAULT_MONTHLY_DRAWDOWN_HALT),
        min_regime_conf: float = DEFAULT_REGIME_CONFIDENCE_HALT,
        calendar_gate: _CalendarGateLike | None = None,
    ) -> None:
        self.max_position_pct = max_position_pct
        self.max_sector_pct = max_sector_pct
        self.daily_loss_halt = daily_loss_halt
        self.monthly_catastrophic = monthly_catastrophic
        self.min_regime_conf = min_regime_conf
        self.calendar_gate = calendar_gate

    def check(
        self,
        intent: OrderIntent,
        order: Order,
        portfolio: Portfolio,
        ctx: FirewallContext,
    ) -> FirewallVerdict:
        """Evaluate every hard limit; return the full rejection set.

        Every gate below is ENTRY-only (exposure-increasing orders): a reducing
        order (`ctx.reduces_exposure`) can never breach a position/sector cap
        and MUST remain executable after a loss halt / blackout / regime drop —
        blocking exits would lock in risk, not remove it.
        """
        rejections: list[str] = []

        equity = portfolio.equity

        # 0. Non-positive equity: nothing can be safely sized or bounded.
        if equity <= 0:
            return FirewallVerdict(
                allowed=False,
                rejections=[
                    f"non-positive equity: {equity:,.2f} — refusing all orders"
                ],
            )

        if ctx.reduces_exposure:
            return FirewallVerdict(allowed=True, rejections=[])

        order_pct = ctx.order_notional / equity

        # 1. Max single position: 5% of equity — EXISTING holding + this order.
        existing_pct = portfolio.position_pct(intent.ticker)
        resulting_position = existing_pct + order_pct
        if resulting_position > self.max_position_pct:
            rejections.append(
                f"position limit: existing {intent.ticker} {existing_pct:.2%} + "
                f"order {order_pct:.2%} = {resulting_position:.2%} of equity "
                f"(> {self.max_position_pct:.2%} max)"
            )

        # 2. Max sector exposure: 20% (existing exposure + this order).
        resulting_sector = portfolio.sector_exposure(ctx.sector) + order_pct
        if resulting_sector > self.max_sector_pct:
            rejections.append(
                f"sector limit: {ctx.sector} exposure would be "
                f"{resulting_sector:.2%} (> {self.max_sector_pct:.2%} max)"
            )

        # 3. Daily loss halt: no new entries once the daily loss threshold trips.
        if ctx.daily_pl_pct <= -self.daily_loss_halt:
            rejections.append(
                f"daily loss halt: daily P&L {ctx.daily_pl_pct:.2%} "
                f"(<= -{self.daily_loss_halt:.2%})"
            )

        # 4. Catastrophic monthly drawdown: 10% -> human review required.
        if ctx.monthly_pl_pct <= -self.monthly_catastrophic:
            rejections.append(
                f"monthly catastrophic drawdown: monthly P&L {ctx.monthly_pl_pct:.2%} "
                f"(<= -{self.monthly_catastrophic:.2%})"
            )

        # 5. Regime confidence floor: no new entries below the threshold.
        if ctx.regime_confidence < self.min_regime_conf:
            rejections.append(
                f"regime confidence too low: {ctx.regime_confidence:.2%} "
                f"(< {self.min_regime_conf:.2%} min)"
            )

        # 6. Economic-calendar blackout: no new entries in the FOMC/CPI/NFP window.
        if self.calendar_gate is not None and self.calendar_gate.is_blackout(ctx.now):
            rejections.append(
                f"econ-calendar blackout: {ctx.now} falls in a FOMC/CPI/NFP window"
            )

        # 7. Missing stop-loss: every entry needs an ATR stop.
        if not ctx.has_stop:
            rejections.append(
                f"missing stop-loss: {intent.ticker} entry has no ATR stop attached"
            )

        # 8. Stop-distance validation: protective side of entry, within 2xATR.
        rejections.extend(self._stop_distance_violations(intent, ctx))

        return FirewallVerdict(allowed=not rejections, rejections=rejections)

    @staticmethod
    def _stop_distance_violations(
        intent: OrderIntent, ctx: FirewallContext
    ) -> list[str]:
        """Validate the stop when a stop, ATR and entry price are all present.

        A BUY entry's protective stop sits BELOW entry; a SELL (short) entry's
        sits ABOVE. The plan's hard limit caps stop distance at 2xATR from entry.
        Without `atr_value`/`entry_price` this check cannot run (the missing-stop
        gate above still enforces that a stop exists at all).
        """
        stop = intent.stop_price
        if stop is None or ctx.atr_value is None or ctx.entry_price is None:
            return []

        violations: list[str] = []
        protective = stop < ctx.entry_price if intent.side is Side.BUY else stop > ctx.entry_price
        if not protective:
            violations.append(
                f"stop on wrong side: {intent.side} entry at {ctx.entry_price:.2f} "
                f"with stop {stop:.2f} is not protective"
            )
        max_distance = 2.0 * ctx.atr_value + _STOP_DISTANCE_EPS
        distance = abs(ctx.entry_price - stop)
        if distance > max_distance:
            violations.append(
                f"stop too far (> 2xATR): |{ctx.entry_price:.2f} - {stop:.2f}| = "
                f"{distance:.2f} exceeds 2 x ATR {ctx.atr_value:.2f}"
            )
        return violations
