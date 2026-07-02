"""Tests for AlpacaBrokerClient — mappers, graceful no-key, dry-run safety.

The load-bearing test is `test_submit_order_default_dry_run_makes_no_post`: with a
`_post` injected to raise, the default `submit_order(order)` must still return a
SUBMITTED order with a simulated id and NEVER touch the network. That is the
Phase-5 dry-run safety invariant for the broker boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.trader.execution.alpaca_broker import AlpacaBrokerClient
from services.trader.execution.model import (
    Order,
    OrderStatus,
    OrderType,
    Portfolio,
    Side,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict | list:
    return json.loads((_FIXTURES / name).read_text())


def _sample_order() -> Order:
    return Order(
        id=None,
        ticker="SPY",
        side=Side.BUY,
        qty=10,
        order_type=OrderType.LIMIT,
        limit_price=541.00,
        stop_price=530.00,
        status=OrderStatus.NEW,
    )


def test_map_account_and_positions_to_portfolio() -> None:
    account = _load("account.json")
    positions = _load("positions.json")
    client = AlpacaBrokerClient(key="k", secret="s")

    portfolio = client._map_account(account, positions)

    assert isinstance(portfolio, Portfolio)
    assert portfolio.equity == pytest.approx(102340.50)
    assert portfolio.cash == pytest.approx(48250.75)
    assert portfolio.buying_power == pytest.approx(192000.00)
    assert portfolio.day_trade_count == 2
    # positions keyed by ticker
    assert set(portfolio.positions) == {"SPY", "IBIT"}
    spy = portfolio.positions["SPY"]
    assert spy.qty == pytest.approx(100)
    assert spy.avg_entry == pytest.approx(530.10)
    assert spy.market_value == pytest.approx(54120.00)
    assert spy.unrealized_pl == pytest.approx(1110.00)


def test_map_position_keys_by_ticker() -> None:
    positions = _load("positions.json")
    client = AlpacaBrokerClient(key="k", secret="s")
    mapped = {p["symbol"]: client._map_position(p) for p in positions}
    assert mapped["IBIT"].unrealized_pl == pytest.approx(-500.00)


def test_no_key_disabled_and_empty_account() -> None:
    client = AlpacaBrokerClient(None, None)
    assert client.is_enabled() is False
    portfolio = client.account()
    assert portfolio.equity == 0
    assert portfolio.cash == 0
    assert portfolio.buying_power == 0
    assert portfolio.positions == {}
    assert client.positions() == {}


def test_no_key_submit_is_dry_no_op() -> None:
    client = AlpacaBrokerClient(None, None)
    order = _sample_order()
    result = client.submit_order(order)
    assert result.status == OrderStatus.SUBMITTED
    assert result.id is not None


def test_submit_order_default_dry_run_makes_no_post() -> None:
    """SAFETY INVARIANT: default submit_order must not POST."""
    client = AlpacaBrokerClient(key="k", secret="s")

    def _boom(path: str, body: dict) -> dict:
        raise AssertionError(f"_post must NOT be called on dry-run (path={path})")

    client._post = _boom  # type: ignore[method-assign]

    order = _sample_order()
    result = client.submit_order(order)  # default dry_run=True

    assert result.status == OrderStatus.SUBMITTED
    assert result.id is not None
    assert result.id.startswith("dry-")
    assert "SPY" in result.id
    # unchanged trade attributes carried through
    assert result.ticker == "SPY"
    assert result.qty == pytest.approx(10)


def test_submit_order_live_posts_and_maps_response() -> None:
    client = AlpacaBrokerClient(key="k", secret="s")
    order_payload = _load("order.json")

    calls: list[tuple[str, dict]] = []

    def _stub_post(path: str, body: dict) -> dict:
        calls.append((path, body))
        return order_payload

    client._post = _stub_post  # type: ignore[method-assign]

    order = _sample_order()
    result = client.submit_order(order, dry_run=False)

    assert calls and calls[0][0] == "/orders"
    assert result.id == "61e69015-8549-4bfd-b9c3-01e75843f47d"
    assert result.status == OrderStatus.FILLED
    assert result.side == Side.BUY
    assert result.order_type == OrderType.LIMIT
    assert result.filled_qty == pytest.approx(10)
    assert result.filled_avg_price == pytest.approx(540.85)


def test_get_order_maps_response() -> None:
    client = AlpacaBrokerClient(key="k", secret="s")
    order_payload = _load("order.json")
    client._get = lambda path: order_payload  # type: ignore[method-assign]
    result = client.get_order("61e69015-8549-4bfd-b9c3-01e75843f47d")
    assert result is not None
    assert result.status == OrderStatus.FILLED
    assert result.ticker == "SPY"


def test_get_order_disabled_returns_none() -> None:
    client = AlpacaBrokerClient(None, None)
    assert client.get_order("whatever") is None


def test_cancel_order_calls_delete() -> None:
    client = AlpacaBrokerClient(key="k", secret="s")
    deleted: list[str] = []
    client._delete = lambda path: deleted.append(path) or True  # type: ignore[method-assign]
    ok = client.cancel_order("abc-123")
    assert ok is True
    assert deleted == ["/orders/abc-123"]


def test_cancel_order_disabled_returns_false() -> None:
    client = AlpacaBrokerClient(None, None)
    assert client.cancel_order("abc-123") is False
