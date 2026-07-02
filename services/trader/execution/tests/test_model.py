"""Tests for the execution domain model (Task 1)."""

from __future__ import annotations

from services.trader.execution.model import (
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    Side,
)


def _sample_portfolio() -> Portfolio:
    positions = {
        "AAPL": Position(
            ticker="AAPL",
            qty=40.0,
            avg_entry=150.0,
            market_value=6_000.0,
            unrealized_pl=0.0,
            sector="TECH",
        ),
        "XOM": Position(
            ticker="XOM",
            qty=40.0,
            avg_entry=100.0,
            market_value=4_000.0,
            unrealized_pl=0.0,
            sector="ENERGY",
        ),
    }
    return Portfolio(
        equity=100_000.0,
        cash=90_000.0,
        buying_power=180_000.0,
        positions=positions,
    )


def test_position_pct() -> None:
    pf = _sample_portfolio()
    assert pf.position_pct("AAPL") == 0.06
    assert pf.position_pct("XOM") == 0.04


def test_position_pct_absent_ticker_is_zero() -> None:
    pf = _sample_portfolio()
    assert pf.position_pct("MSFT") == 0.0


def test_position_pct_zero_equity_is_zero() -> None:
    pf = Portfolio(equity=0.0, cash=0.0, buying_power=0.0)
    assert pf.position_pct("AAPL") == 0.0


def test_sector_exposure() -> None:
    pf = _sample_portfolio()
    assert pf.sector_exposure("TECH") == 0.06
    assert pf.sector_exposure("ENERGY") == 0.04
    assert pf.sector_exposure("HEALTHCARE") == 0.0


def test_sector_exposure_zero_equity_is_zero() -> None:
    pf = Portfolio(equity=0.0, cash=0.0, buying_power=0.0)
    assert pf.sector_exposure("TECH") == 0.0


def test_notional() -> None:
    pf = _sample_portfolio()
    assert pf.notional() == 10_000.0


def test_notional_uses_absolute_value() -> None:
    positions = {
        "SHORT": Position(
            ticker="SHORT",
            qty=-10.0,
            avg_entry=100.0,
            market_value=-1_000.0,
            unrealized_pl=0.0,
        ),
    }
    pf = Portfolio(
        equity=100_000.0,
        cash=100_000.0,
        buying_power=100_000.0,
        positions=positions,
    )
    assert pf.notional() == 1_000.0
    assert pf.position_pct("SHORT") == 0.01


def test_portfolio_defaults() -> None:
    pf = Portfolio(equity=1.0, cash=1.0, buying_power=1.0)
    assert pf.positions == {}
    assert pf.day_trade_count == 0


def test_position_defaults() -> None:
    pos = Position(
        ticker="AAPL",
        qty=1.0,
        avg_entry=100.0,
        market_value=100.0,
        unrealized_pl=0.0,
    )
    assert pos.sector == "UNKNOWN"


def test_order_intent_defaults() -> None:
    intent = OrderIntent(
        ticker="AAPL",
        side=Side.BUY,
        target_weight=0.05,
        reason="momentum",
        regime_confidence=0.8,
    )
    assert intent.stop_price is None
    assert intent.side is Side.BUY


def test_order_defaults() -> None:
    order = Order(
        id=None,
        ticker="AAPL",
        side=Side.BUY,
        qty=10.0,
        order_type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
        status=OrderStatus.NEW,
    )
    assert order.filled_qty == 0.0
    assert order.filled_avg_price is None


def test_enums_roundtrip_value_strings() -> None:
    assert Side.BUY.value == "BUY"
    assert Side.SELL.value == "SELL"
    assert Side("BUY") is Side.BUY

    assert OrderType.MARKET.value == "MARKET"
    assert OrderType.LIMIT.value == "LIMIT"
    assert OrderType("LIMIT") is OrderType.LIMIT

    for status in ("NEW", "SUBMITTED", "FILLED", "PARTIAL", "CANCELED", "REJECTED"):
        assert OrderStatus(status).value == status


def test_dataclasses_are_frozen() -> None:
    import dataclasses

    pf = _sample_portfolio()
    with pytest_raises_frozen():
        pf.equity = 1.0  # type: ignore[misc]

    assert dataclasses.is_dataclass(Order)
    assert dataclasses.is_dataclass(Position)
    assert dataclasses.is_dataclass(OrderIntent)


def pytest_raises_frozen():
    import dataclasses

    import pytest

    return pytest.raises(dataclasses.FrozenInstanceError)
