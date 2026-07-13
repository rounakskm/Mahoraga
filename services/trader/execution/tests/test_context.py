"""Tests for `build_firewall_context` — the production FirewallContext factory (C2).

The factory is the ONE way runners assemble firewall inputs. Its load-bearing
properties:

  * `order_notional` is the UN-clamped requested exposure — the firewall must
    judge true strategy intent, not the sizer's clamped output;
  * missing P&L context defaults to 0.0 but WARNS (halts silently disabled is
    a review finding, not a feature);
  * `reduces_exposure` is computed from the existing position vs. the order so
    entry-only gates (C4) can distinguish entries from exits.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from services.trader.execution.context import build_firewall_context
from services.trader.execution.model import (
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    Side,
)

NOW = pd.Timestamp("2026-07-01 15:00", tz="UTC")


def _intent(
    ticker: str = "SPY",
    side: Side = Side.BUY,
    target_weight: float = 0.03,
    stop_price: float | None = 96.0,
) -> OrderIntent:
    return OrderIntent(
        ticker=ticker,
        side=side,
        target_weight=target_weight,
        reason="test",
        regime_confidence=0.7,
        stop_price=stop_price,
    )


def _order(ticker: str = "SPY", side: Side = Side.BUY, qty: float = 30.0) -> Order:
    return Order(
        id=None,
        ticker=ticker,
        side=side,
        qty=qty,
        order_type=OrderType.MARKET,
        limit_price=None,
        stop_price=96.0,
        status=OrderStatus.NEW,
    )


def _portfolio(positions: dict[str, Position] | None = None) -> Portfolio:
    return Portfolio(
        equity=100_000.0,
        cash=50_000.0,
        buying_power=100_000.0,
        positions=positions or {},
    )


def _spy_long(qty: float = 100.0, market_value: float = 10_000.0) -> dict[str, Position]:
    return {
        "SPY": Position(
            ticker="SPY",
            qty=qty,
            avg_entry=100.0,
            market_value=market_value,
            unrealized_pl=0.0,
            sector="ETF",
        )
    }


def test_order_notional_is_unclamped_requested_exposure() -> None:
    """A 40%-weight intent yields order_notional = 40% of equity, NOT the 5% clamp."""
    ctx = build_firewall_context(
        _intent(target_weight=0.40),
        _order(qty=50.0),  # the sizer's CLAMPED order — must not leak into ctx.
        _portfolio(),
        now=NOW,
        price=100.0,
        daily_pl_pct=0.0,
        monthly_pl_pct=0.0,
    )
    assert ctx.order_notional == pytest.approx(40_000.0)


def test_sector_defaults_to_unknown_and_sector_map_applies() -> None:
    kwargs: dict[str, float] = {"daily_pl_pct": 0.0, "monthly_pl_pct": 0.0}
    ctx = build_firewall_context(
        _intent(), _order(), _portfolio(), now=NOW, price=100.0, **kwargs
    )
    assert ctx.sector == "UNKNOWN"
    ctx2 = build_firewall_context(
        _intent(),
        _order(),
        _portfolio(),
        now=NOW,
        price=100.0,
        sector_map={"SPY": "ETF"},
        **kwargs,
    )
    assert ctx2.sector == "ETF"


def test_missing_pl_defaults_zero_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        ctx = build_firewall_context(
            _intent(), _order(), _portfolio(), now=NOW, price=100.0
        )
    assert ctx.daily_pl_pct == 0.0
    assert ctx.monthly_pl_pct == 0.0
    assert any("P&L context missing" in r.message for r in caplog.records)


def test_present_pl_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        ctx = build_firewall_context(
            _intent(),
            _order(),
            _portfolio(),
            now=NOW,
            price=100.0,
            daily_pl_pct=-0.01,
            monthly_pl_pct=-0.03,
        )
    assert ctx.daily_pl_pct == -0.01
    assert ctx.monthly_pl_pct == -0.03
    assert not any("P&L context missing" in r.message for r in caplog.records)


def test_explicit_monthly_pl_reaches_context(caplog: pytest.LogCaptureFixture) -> None:
    """A store-derived monthly P&L at the catastrophic threshold flows through
    verbatim (no clamp, no default) and does NOT trigger the missing-P&L warning
    — this is the value the 10% monthly halt keys on."""
    with caplog.at_level(logging.WARNING):
        ctx = build_firewall_context(
            _intent(),
            _order(),
            _portfolio(),
            now=NOW,
            price=100.0,
            daily_pl_pct=0.0,
            monthly_pl_pct=-0.10,
        )
    assert ctx.monthly_pl_pct == -0.10
    assert not any("P&L context missing" in r.message for r in caplog.records)


def test_has_stop_and_pass_throughs() -> None:
    ctx = build_firewall_context(
        _intent(stop_price=None),
        _order(),
        _portfolio(),
        now=NOW,
        price=101.5,
        atr_value=2.5,
        daily_pl_pct=0.0,
        monthly_pl_pct=0.0,
    )
    assert ctx.has_stop is False
    assert ctx.entry_price == 101.5
    assert ctx.atr_value == 2.5
    assert ctx.now is NOW
    assert ctx.regime_confidence == 0.7


def test_reduces_exposure_sell_closing_part_of_long() -> None:
    ctx = build_firewall_context(
        _intent(side=Side.SELL, target_weight=-0.03),
        _order(side=Side.SELL, qty=50.0),
        _portfolio(_spy_long(qty=100.0)),
        now=NOW,
        price=100.0,
        daily_pl_pct=0.0,
        monthly_pl_pct=0.0,
    )
    assert ctx.reduces_exposure is True


def test_sell_bigger_than_long_is_not_a_reduce() -> None:
    """Selling MORE than the existing long flips into a short — an increase."""
    ctx = build_firewall_context(
        _intent(side=Side.SELL, target_weight=-0.20),
        _order(side=Side.SELL, qty=150.0),
        _portfolio(_spy_long(qty=100.0)),
        now=NOW,
        price=100.0,
        daily_pl_pct=0.0,
        monthly_pl_pct=0.0,
    )
    assert ctx.reduces_exposure is False


def test_buy_on_long_is_not_a_reduce() -> None:
    ctx = build_firewall_context(
        _intent(side=Side.BUY),
        _order(side=Side.BUY, qty=30.0),
        _portfolio(_spy_long(qty=100.0)),
        now=NOW,
        price=100.0,
        daily_pl_pct=0.0,
        monthly_pl_pct=0.0,
    )
    assert ctx.reduces_exposure is False


def test_buy_covering_short_is_a_reduce() -> None:
    ctx = build_firewall_context(
        _intent(side=Side.BUY),
        _order(side=Side.BUY, qty=30.0),
        _portfolio(_spy_long(qty=-100.0)),
        now=NOW,
        price=100.0,
        daily_pl_pct=0.0,
        monthly_pl_pct=0.0,
    )
    assert ctx.reduces_exposure is True


def test_no_position_is_never_a_reduce() -> None:
    ctx = build_firewall_context(
        _intent(side=Side.SELL, target_weight=-0.03),
        _order(side=Side.SELL, qty=30.0),
        _portfolio(),
        now=NOW,
        price=100.0,
        daily_pl_pct=0.0,
        monthly_pl_pct=0.0,
    )
    assert ctx.reduces_exposure is False
