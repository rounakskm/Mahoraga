"""Tests for the hard-limit firewall — the architectural entry gate (Phase 5, Task 7).

The firewall is the Phase-5 exit criterion: an order failing any hard limit or
compliance check must be rejected (and thus never reach the broker). These tests
pin each of the seven independent limits, plus the "collect ALL violations"
(non-short-circuiting) contract.
"""

from __future__ import annotations

import pandas as pd

from services.trader.execution.firewall import (
    FirewallContext,
    FirewallVerdict,
    HardLimitFirewall,
)
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


class _StubGate:
    """Minimal calendar-gate stand-in with a fixed blackout verdict."""

    def __init__(self, blackout: bool) -> None:
        self._blackout = blackout

    def is_blackout(self, now: pd.Timestamp, series: tuple[str, ...] = ()) -> bool:
        return self._blackout


def _intent() -> OrderIntent:
    return OrderIntent(
        ticker="SPY",
        side=Side.BUY,
        target_weight=0.03,
        reason="test entry",
        regime_confidence=0.6,
        stop_price=490.0,
    )


def _order(qty: float = 6.0) -> Order:
    return Order(
        id=None,
        ticker="SPY",
        side=Side.BUY,
        qty=qty,
        order_type=OrderType.MARKET,
        limit_price=None,
        stop_price=490.0,
        status=OrderStatus.NEW,
    )


def _portfolio(sector_positions: dict[str, Position] | None = None) -> Portfolio:
    return Portfolio(
        equity=100_000.0,
        cash=50_000.0,
        buying_power=100_000.0,
        positions=sector_positions or {},
    )


def _ctx(**overrides: object) -> FirewallContext:
    base: dict[str, object] = {
        "now": NOW,
        "regime_confidence": 0.6,
        "daily_pl_pct": -0.005,
        "monthly_pl_pct": -0.02,
        "has_stop": True,
        "sector": "TECH",
        "order_notional": 3_000.0,  # 3% of 100k
    }
    base.update(overrides)
    return FirewallContext(**base)  # type: ignore[arg-type]


def test_in_limits_entry_is_allowed() -> None:
    fw = HardLimitFirewall()
    verdict = fw.check(_intent(), _order(), _portfolio(), _ctx())
    assert isinstance(verdict, FirewallVerdict)
    assert verdict.allowed is True
    assert verdict.rejections == []


def test_position_over_5pct_rejected() -> None:
    fw = HardLimitFirewall()
    verdict = fw.check(_intent(), _order(), _portfolio(), _ctx(order_notional=6_000.0))
    assert verdict.allowed is False
    assert any("position" in r.lower() for r in verdict.rejections)


def test_sector_over_20pct_rejected() -> None:
    # Existing 18% in TECH + a 5% order -> 23% sector exposure.
    existing = {
        "AAPL": Position(
            ticker="AAPL",
            qty=100.0,
            avg_entry=180.0,
            market_value=18_000.0,
            unrealized_pl=0.0,
            sector="TECH",
        )
    }
    fw = HardLimitFirewall()
    verdict = fw.check(
        _intent(), _order(), _portfolio(existing), _ctx(order_notional=5_000.0)
    )
    assert verdict.allowed is False
    assert any("sector" in r.lower() for r in verdict.rejections)


def test_daily_loss_halt_rejected() -> None:
    fw = HardLimitFirewall()
    verdict = fw.check(_intent(), _order(), _portfolio(), _ctx(daily_pl_pct=-0.02))
    assert verdict.allowed is False
    assert any("daily" in r.lower() for r in verdict.rejections)


def test_monthly_catastrophic_rejected() -> None:
    fw = HardLimitFirewall()
    verdict = fw.check(_intent(), _order(), _portfolio(), _ctx(monthly_pl_pct=-0.10))
    assert verdict.allowed is False
    assert any("monthly" in r.lower() for r in verdict.rejections)


def test_low_regime_confidence_rejected() -> None:
    fw = HardLimitFirewall()
    verdict = fw.check(_intent(), _order(), _portfolio(), _ctx(regime_confidence=0.3))
    assert verdict.allowed is False
    assert any(
        "regime" in r.lower() or "confidence" in r.lower() for r in verdict.rejections
    )


def test_econ_blackout_rejected() -> None:
    fw = HardLimitFirewall(calendar_gate=_StubGate(blackout=True))
    verdict = fw.check(_intent(), _order(), _portfolio(), _ctx())
    assert verdict.allowed is False
    assert any(
        "blackout" in r.lower() or "calendar" in r.lower() for r in verdict.rejections
    )


def test_missing_stop_rejected() -> None:
    fw = HardLimitFirewall()
    verdict = fw.check(_intent(), _order(), _portfolio(), _ctx(has_stop=False))
    assert verdict.allowed is False
    assert any("stop" in r.lower() for r in verdict.rejections)


def test_multiple_violations_all_listed() -> None:
    # Force position + daily loss + low confidence + missing stop simultaneously.
    fw = HardLimitFirewall(calendar_gate=_StubGate(blackout=True))
    verdict = fw.check(
        _intent(),
        _order(),
        _portfolio(),
        _ctx(
            order_notional=6_000.0,
            daily_pl_pct=-0.05,
            regime_confidence=0.2,
            has_stop=False,
        ),
    )
    assert verdict.allowed is False
    assert len(verdict.rejections) >= 2
