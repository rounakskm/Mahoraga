"""Compliance engine — PDT, wash-sale, and SSR-ready checks (Phase 5, Task 8).

Pure data + arithmetic; no I/O, no runtime-specific glue. Sits between sizing
and the hard-limit firewall: given an `OrderIntent`, the current `Portfolio`,
and recent trade history, it collects *all* regulatory violations rather than
short-circuiting on the first, so the caller sees the full picture.

Checks:
  * PDT (pattern day trader) — under the $25k equity floor, a 4th day-trade in
    a rolling 5-business-day window is prohibited.
  * Wash-sale — re-buying a security (or a BTC-ETF-group sibling) within 30 days
    of closing it at a loss disallows the loss for tax purposes.
  * SSR (short-sale restriction) — stubbed here; activates in Phase 8b.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from pandas.tseries.offsets import BDay

from services.trader.execution.model import OrderIntent, Portfolio, Side


@dataclass(frozen=True)
class ComplianceVerdict:
    """Outcome of a compliance check — allowed plus the list of violations."""

    allowed: bool
    rejections: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TradeRecord:
    """A minimal historical trade fact the compliance checks reason over."""

    ticker: str
    side: Side
    ts: pd.Timestamp
    realized_pl: float
    is_day_trade: bool


class ComplianceEngine:
    """Collects all regulatory violations for a prospective order intent."""

    def __init__(
        self,
        pdt_equity_floor: float = 25_000.0,
        wash_window_days: int = 30,
        btc_etf_group: frozenset[str] = frozenset(
            {"IBIT", "FBTC", "GBTC", "BITB", "ARKB"}
        ),
    ) -> None:
        self.pdt_equity_floor = pdt_equity_floor
        self.wash_window_days = wash_window_days
        self.btc_etf_group = btc_etf_group

    def check(
        self,
        intent: OrderIntent,
        portfolio: Portfolio,
        recent_trades: list[TradeRecord],
        now: pd.Timestamp,
    ) -> ComplianceVerdict:
        """Return a verdict collecting every compliance violation found."""
        rejections: list[str] = []

        pdt = self._pdt_violation(intent, portfolio, recent_trades, now)
        if pdt is not None:
            rejections.append(pdt)

        wash = self._wash_sale_violation(intent, recent_trades, now)
        if wash is not None:
            rejections.append(wash)

        if not self._ssr_ok(intent):
            rejections.append("SSR: short-sale restriction active for ticker")

        return ComplianceVerdict(allowed=not rejections, rejections=rejections)

    def _pdt_violation(
        self,
        intent: OrderIntent,
        portfolio: Portfolio,
        recent_trades: list[TradeRecord],
        now: pd.Timestamp,
    ) -> str | None:
        """Pattern-day-trader check.

        Only applies below the equity floor. Counts day-trades within a rolling
        5-business-day window ending `now`; the intent itself is treated as a
        potential day-trade, so 3 prior day-trades + this one is the 4th.
        """
        if portfolio.equity >= self.pdt_equity_floor:
            return None

        window_start = now - BDay(5)
        recent_day_trades = sum(
            1
            for t in recent_trades
            if t.is_day_trade and window_start <= t.ts <= now
        )
        if recent_day_trades >= 3:
            return (
                "PDT: 4th+ day-trade in a rolling 5-business-day window while "
                f"equity ${portfolio.equity:,.0f} is below the "
                f"${self.pdt_equity_floor:,.0f} floor"
            )
        return None

    def _wash_sale_violation(
        self,
        intent: OrderIntent,
        recent_trades: list[TradeRecord],
        now: pd.Timestamp,
    ) -> str | None:
        """Wash-sale check on re-buys within the wash window.

        A BUY of `intent.ticker` is a wash sale if the same ticker — or, when the
        ticker is a BTC-ETF-group member, any group sibling — was sold at a loss
        within `wash_window_days` days before `now`.
        """
        if intent.side != Side.BUY:
            return None

        watched = (
            self.btc_etf_group
            if intent.ticker in self.btc_etf_group
            else frozenset({intent.ticker})
        )

        window_start = now - pd.Timedelta(days=self.wash_window_days)
        for t in recent_trades:
            if (
                t.side == Side.SELL
                and t.realized_pl < 0
                and t.ticker in watched
                and window_start <= t.ts <= now
            ):
                return (
                    f"wash-sale: re-buy of {intent.ticker} within "
                    f"{self.wash_window_days}d of a loss-closing sale of "
                    f"{t.ticker}"
                )
        return None

    def _ssr_ok(self, intent: OrderIntent) -> bool:
        """Short-sale-restriction predicate — stub; activates in Phase 8b."""
        return True
