"""Production `FirewallContext` factory — the ONE way runners build a context.

Every runner (run_paper, future live loops) must assemble firewall inputs through
`build_firewall_context` rather than hand-rolling a `FirewallContext`, so the
safety-critical derivations live in exactly one reviewed place:

* **`order_notional` is the UN-clamped requested exposure** —
  `abs(intent.target_weight) * portfolio.equity`. The sizer clamps orders to the
  5% cap before submission, but the firewall must judge the strategy's TRUE
  intent: if the clamped notional were passed, a runaway 40%-of-equity signal
  would sail through the position check at exactly 5% and the hard limit would
  never observe the violation it exists to catch.

* **Missing P&L context is loud.** `daily_pl_pct` / `monthly_pl_pct` default to
  0.0 when the caller cannot supply them, but that silently disarms the daily
  loss halt and monthly catastrophic-drawdown gates — so the factory emits a
  `logging.warning` every time it happens.

* **`reduces_exposure`** is computed from the existing position: the order side
  opposes the sign of the held quantity AND the order quantity does not exceed
  the held quantity (a larger opposing order flips through zero into a new
  position — an entry, not an exit).
"""

from __future__ import annotations

import logging

import pandas as pd

from services.trader.execution.firewall import FirewallContext
from services.trader.execution.model import Order, OrderIntent, Portfolio, Side

logger = logging.getLogger(__name__)


def _reduces_exposure(intent: OrderIntent, order: Order, portfolio: Portfolio) -> bool:
    """True when the order closes/shrinks the existing position in `intent.ticker`."""
    existing = portfolio.positions.get(intent.ticker)
    if existing is None or existing.qty == 0:
        return False
    opposes = (existing.qty > 0 and intent.side is Side.SELL) or (
        existing.qty < 0 and intent.side is Side.BUY
    )
    return opposes and abs(order.qty) <= abs(existing.qty)


def build_firewall_context(
    intent: OrderIntent,
    order: Order,
    portfolio: Portfolio,
    *,
    now: pd.Timestamp,
    price: float,
    atr_value: float | None = None,
    daily_pl_pct: float | None = None,
    monthly_pl_pct: float | None = None,
    sector_map: dict[str, str] | None = None,
) -> FirewallContext:
    """Build the point-in-time `FirewallContext` for one intent/order pair.

    Args:
        intent: The strategy's desired position change (pre-sizing).
        order: The sized (clamped) order — used only for the reduce/entry
            classification; NEVER for `order_notional` (see module docstring).
        portfolio: The current account snapshot.
        now: Decision timestamp (tz-aware UTC expected).
        price: The REAL market price used as the entry-price reference for
            stop-distance validation.
        atr_value: Current ATR for the ticker, when available; enables the
            2xATR stop-distance check.
        daily_pl_pct / monthly_pl_pct: Realized P&L context. `None` defaults to
            0.0 with a WARNING — the daily/monthly halts cannot trip without it.
        sector_map: ticker -> sector; unmapped tickers get "UNKNOWN" (which the
            20% sector cap still bounds, rather than exempting them).
    """
    if daily_pl_pct is None or monthly_pl_pct is None:
        missing = [
            name
            for name, value in (
                ("daily_pl_pct", daily_pl_pct),
                ("monthly_pl_pct", monthly_pl_pct),
            )
            if value is None
        ]
        logger.warning(
            "P&L context missing (%s) — daily/monthly halts cannot trip",
            ", ".join(missing),
        )

    return FirewallContext(
        now=now,
        regime_confidence=intent.regime_confidence,
        daily_pl_pct=0.0 if daily_pl_pct is None else daily_pl_pct,
        monthly_pl_pct=0.0 if monthly_pl_pct is None else monthly_pl_pct,
        has_stop=intent.stop_price is not None,
        sector=(sector_map or {}).get(intent.ticker, "UNKNOWN"),
        order_notional=abs(intent.target_weight) * portfolio.equity,
        reduces_exposure=_reduces_exposure(intent, order, portfolio),
        atr_value=atr_value,
        entry_price=price,
    )
