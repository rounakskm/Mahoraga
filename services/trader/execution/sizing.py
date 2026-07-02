"""Position sizing — translate an OrderIntent's target weight into a sized Order.

Pure arithmetic; no I/O, no runtime-specific glue. Applies the max-single-position
clamp (5% of equity by default) and drops sub-cost orders below `min_notional`.
"""

from __future__ import annotations

from services.trader.execution.model import (
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
    Portfolio,
)


def size_order(
    intent: OrderIntent,
    portfolio: Portfolio,
    price: float,
    *,
    max_position_pct: float = 0.05,
    allow_fractional: bool = True,
    min_notional: float = 1.0,
) -> Order | None:
    """Size an `OrderIntent` into a concrete `Order`, or `None` if it should be skipped.

    Target notional is `intent.target_weight * portfolio.equity`, clamped in
    magnitude to `max_position_pct * equity` (sign preserved). Quantity is
    notional / price, floored toward zero to whole shares when `allow_fractional`
    is False. Returns `None` when price or equity is non-positive, or when the
    resulting notional falls below `min_notional`.
    """
    if price <= 0 or portfolio.equity <= 0:
        return None

    notional = intent.target_weight * portfolio.equity
    cap = max_position_pct * portfolio.equity
    if abs(notional) > cap:
        notional = cap if notional >= 0 else -cap

    qty = notional / price
    if not allow_fractional:
        qty = float(int(qty))  # truncate toward zero

    if abs(qty * price) < min_notional:
        return None

    return Order(
        id=None,
        ticker=intent.ticker,
        side=intent.side,
        qty=abs(qty),
        order_type=OrderType.MARKET,
        limit_price=None,
        stop_price=intent.stop_price,
        status=OrderStatus.NEW,
        filled_qty=0.0,
        filled_avg_price=None,
    )
