"""Execution domain model — enums + frozen dataclasses (Phase 5, Task 1).

Bridges strategy signals and broker fills. Pure data + arithmetic helpers;
no I/O, no runtime-specific glue. Consumed unchanged by the broker client,
sizing, firewall, compliance, reconciliation, executor and trade-store tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Side(StrEnum):
    """Direction of an order."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """Order execution type."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    """Lifecycle status of an order."""

    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class OrderIntent:
    """A strategy's desired position change before sizing/firewall.

    `target_weight` is the desired portfolio weight in [-1, 1].
    """

    ticker: str
    side: Side
    target_weight: float
    reason: str
    regime_confidence: float
    stop_price: float | None = None


@dataclass(frozen=True)
class Order:
    """A concrete, sized order (pre- or post-submission)."""

    id: str | None
    ticker: str
    side: Side
    qty: float
    order_type: OrderType
    limit_price: float | None
    stop_price: float | None
    status: OrderStatus
    filled_qty: float = 0.0
    filled_avg_price: float | None = None


@dataclass(frozen=True)
class Position:
    """An open position snapshot."""

    ticker: str
    qty: float
    avg_entry: float
    market_value: float
    unrealized_pl: float
    sector: str = "UNKNOWN"


@dataclass(frozen=True)
class Portfolio:
    """Account-level snapshot: equity, cash, buying power, open positions."""

    equity: float
    cash: float
    buying_power: float
    positions: dict[str, Position] = field(default_factory=dict)
    day_trade_count: int = 0

    def position_pct(self, ticker: str) -> float:
        """Absolute market value of `ticker` as a fraction of equity.

        Returns 0.0 if equity is zero or the ticker is not held.
        """
        if self.equity == 0:
            return 0.0
        pos = self.positions.get(ticker)
        if pos is None:
            return 0.0
        return abs(pos.market_value) / self.equity

    def sector_exposure(self, sector: str) -> float:
        """Summed absolute market value of positions in `sector` / equity.

        Returns 0.0 if equity is zero.
        """
        if self.equity == 0:
            return 0.0
        total = sum(
            abs(pos.market_value)
            for pos in self.positions.values()
            if pos.sector == sector
        )
        return total / self.equity

    def notional(self) -> float:
        """Total gross notional — sum of absolute market values."""
        return sum(abs(pos.market_value) for pos in self.positions.values())
