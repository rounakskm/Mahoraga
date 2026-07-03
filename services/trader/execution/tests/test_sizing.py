"""Tests for position sizing (Phase 5, Task 6)."""

from __future__ import annotations

import pytest

from services.trader.execution.model import (
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
    Portfolio,
    Side,
)
from services.trader.execution.sizing import size_order


def _portfolio(equity: float = 100_000.0) -> Portfolio:
    return Portfolio(equity=equity, cash=equity, buying_power=equity)


def _intent(**kw: object) -> OrderIntent:
    base: dict[str, object] = {
        "ticker": "SPY",
        "side": Side.BUY,
        "target_weight": 0.10,
        "reason": "test",
        "regime_confidence": 0.9,
        "stop_price": 48.0,
    }
    base.update(kw)
    return OrderIntent(**base)  # type: ignore[arg-type]


def test_weight_clamped_to_max_position_pct() -> None:
    # 0.10 target on $100k = $10k notional, clamped to 5% ($5k) at $50 -> 100 shares.
    order = size_order(_intent(), _portfolio(), price=50.0)
    assert order is not None
    assert isinstance(order, Order)
    assert order.qty == 100.0
    assert order.ticker == "SPY"
    assert order.side is Side.BUY
    assert order.order_type is OrderType.MARKET
    assert order.limit_price is None
    assert order.status is OrderStatus.NEW
    assert order.id is None
    assert order.filled_qty == 0.0
    assert order.filled_avg_price is None


def test_stop_price_carried_from_intent() -> None:
    order = size_order(_intent(stop_price=47.5), _portfolio(), price=50.0)
    assert order is not None
    assert order.stop_price == 47.5


def test_below_min_notional_returns_none() -> None:
    order = size_order(_intent(target_weight=0.0000001), _portfolio(), price=50.0)
    assert order is None


def test_fractional_off_yields_integer_qty() -> None:
    # 5% of $100k = $5k / $30 = 166.66... -> floored to 166.
    order = size_order(
        _intent(target_weight=0.05), _portfolio(), price=30.0, allow_fractional=False
    )
    assert order is not None
    assert order.qty == 166.0


def test_fractional_on_keeps_fraction() -> None:
    order = size_order(
        _intent(target_weight=0.05), _portfolio(), price=30.0, allow_fractional=True
    )
    assert order is not None
    assert order.qty != int(order.qty)


def test_non_positive_price_returns_none() -> None:
    assert size_order(_intent(), _portfolio(), price=0.0) is None
    assert size_order(_intent(), _portfolio(), price=-5.0) is None


def test_non_positive_equity_returns_none() -> None:
    assert size_order(_intent(), _portfolio(equity=0.0), price=50.0) is None


def test_side_matches_intent_sell() -> None:
    order = size_order(
        _intent(side=Side.SELL, target_weight=-0.10), _portfolio(), price=50.0
    )
    assert order is not None
    assert order.side is Side.SELL
    assert order.qty == 100.0  # magnitude, sign-independent


# ---------------------------------------------------------------------------
# C10 — side/weight sign mismatch is a caller bug and must raise, not size.
# ---------------------------------------------------------------------------


def test_buy_with_negative_weight_raises() -> None:
    with pytest.raises(ValueError, match="mismatch"):
        size_order(_intent(side=Side.BUY, target_weight=-0.03), _portfolio(), price=50.0)


def test_sell_with_positive_weight_raises() -> None:
    with pytest.raises(ValueError, match="mismatch"):
        size_order(_intent(side=Side.SELL, target_weight=0.03), _portfolio(), price=50.0)
