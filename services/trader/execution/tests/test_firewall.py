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


# ---------------------------------------------------------------------------
# C1 — position limit must include EXISTING holdings, and equity must be > 0.
# ---------------------------------------------------------------------------


def _aapl_4pct_portfolio() -> Portfolio:
    """$100k book already holding a 4%-of-equity AAPL position."""
    return _portfolio(
        {
            "AAPL": Position(
                ticker="AAPL",
                qty=20.0,
                avg_entry=200.0,
                market_value=4_000.0,
                unrealized_pl=0.0,
                sector="TECH",
            )
        }
    )


def _aapl_intent() -> OrderIntent:
    return OrderIntent(
        ticker="AAPL",
        side=Side.BUY,
        target_weight=0.04,
        reason="test add-on entry",
        regime_confidence=0.6,
        stop_price=190.0,
    )


def test_position_limit_includes_existing_holdings() -> None:
    """Existing 4% AAPL + a 4% AAPL order = 8% resulting position -> rejected."""
    fw = HardLimitFirewall()
    verdict = fw.check(
        _aapl_intent(),
        _order(),
        _aapl_4pct_portfolio(),
        _ctx(order_notional=4_000.0, sector="TECH"),
    )
    assert verdict.allowed is False
    position_rejections = [r for r in verdict.rejections if "position" in r.lower()]
    assert position_rejections
    # The message must surface BOTH components: existing holding and the order.
    assert "4.00%" in position_rejections[0]


def test_same_order_on_unheld_ticker_allowed() -> None:
    """The same 4% order on a ticker with NO existing position is in-limits."""
    fw = HardLimitFirewall()
    msft_intent = OrderIntent(
        ticker="MSFT",
        side=Side.BUY,
        target_weight=0.04,
        reason="test fresh entry",
        regime_confidence=0.6,
        stop_price=400.0,
    )
    verdict = fw.check(
        msft_intent,
        _order(),
        _aapl_4pct_portfolio(),
        _ctx(order_notional=4_000.0, sector="OTHER"),
    )
    assert verdict.allowed is True


def test_zero_equity_rejected_outright() -> None:
    fw = HardLimitFirewall()
    portfolio = Portfolio(equity=0.0, cash=0.0, buying_power=0.0, positions={})
    verdict = fw.check(_intent(), _order(), portfolio, _ctx())
    assert verdict.allowed is False
    assert any("non-positive equity" in r for r in verdict.rejections)


def test_negative_equity_rejected_outright() -> None:
    fw = HardLimitFirewall()
    portfolio = Portfolio(equity=-5_000.0, cash=0.0, buying_power=0.0, positions={})
    verdict = fw.check(_intent(), _order(), portfolio, _ctx())
    assert verdict.allowed is False
    assert any("non-positive equity" in r for r in verdict.rejections)


# ---------------------------------------------------------------------------
# C4 — daily/monthly/blackout/stop/regime gates apply to ENTRIES only; an
# exposure-REDUCING order (e.g. a SELL closing a long) passes them.
# ---------------------------------------------------------------------------


def test_reducing_order_allowed_after_daily_loss_halt() -> None:
    """After a -2% day, a SELL closing an existing long is still ALLOWED."""
    fw = HardLimitFirewall(calendar_gate=_StubGate(blackout=True))
    verdict = fw.check(
        _intent(),
        _order(),
        _portfolio(),
        _ctx(
            reduces_exposure=True,
            daily_pl_pct=-0.02,
            monthly_pl_pct=-0.12,
            regime_confidence=0.1,
            has_stop=False,
        ),
    )
    assert verdict.allowed is True
    assert verdict.rejections == []


def test_reducing_order_skips_position_and_sector_limits() -> None:
    """A reduce cannot breach position/sector limits — they apply to increases only."""
    fw = HardLimitFirewall()
    verdict = fw.check(
        _intent(),
        _order(),
        _portfolio(),
        _ctx(reduces_exposure=True, order_notional=50_000.0, has_stop=False),
    )
    assert verdict.allowed is True


def test_increasing_order_still_rejected_after_daily_loss_halt() -> None:
    """After a -2% day, a NEW entry (exposure-increasing) is rejected."""
    fw = HardLimitFirewall()
    verdict = fw.check(
        _intent(),
        _order(),
        _portfolio(),
        _ctx(daily_pl_pct=-0.02, reduces_exposure=False),
    )
    assert verdict.allowed is False
    assert any("daily" in r.lower() for r in verdict.rejections)


# ---------------------------------------------------------------------------
# C6 — stop-distance validation: protective side + within 2xATR of entry.
# ---------------------------------------------------------------------------


def test_stop_too_far_beyond_2x_atr_rejected() -> None:
    """A stop 3xATR below entry violates the max-2xATR-stop hard limit."""
    fw = HardLimitFirewall()
    intent = OrderIntent(
        ticker="SPY",
        side=Side.BUY,
        target_weight=0.03,
        reason="test entry",
        regime_confidence=0.6,
        stop_price=94.0,  # entry 100, ATR 2 -> 3xATR away.
    )
    verdict = fw.check(
        intent, _order(), _portfolio(), _ctx(atr_value=2.0, entry_price=100.0)
    )
    assert verdict.allowed is False
    assert any("stop too far" in r for r in verdict.rejections)


def test_stop_on_wrong_side_of_entry_rejected() -> None:
    """A BUY entry with a stop ABOVE entry is not protective."""
    fw = HardLimitFirewall()
    intent = OrderIntent(
        ticker="SPY",
        side=Side.BUY,
        target_weight=0.03,
        reason="test entry",
        regime_confidence=0.6,
        stop_price=103.0,
    )
    verdict = fw.check(
        intent, _order(), _portfolio(), _ctx(atr_value=2.0, entry_price=100.0)
    )
    assert verdict.allowed is False
    assert any("wrong side" in r for r in verdict.rejections)


def test_stop_within_2x_atr_allowed() -> None:
    fw = HardLimitFirewall()
    intent = OrderIntent(
        ticker="SPY",
        side=Side.BUY,
        target_weight=0.03,
        reason="test entry",
        regime_confidence=0.6,
        stop_price=97.0,  # 1.5xATR below entry.
    )
    verdict = fw.check(
        intent, _order(), _portfolio(), _ctx(atr_value=2.0, entry_price=100.0)
    )
    assert verdict.allowed is True


def test_short_entry_stop_above_entry_is_protective() -> None:
    """A SELL (short) entry's protective stop sits ABOVE entry."""
    fw = HardLimitFirewall()
    intent = OrderIntent(
        ticker="SPY",
        side=Side.SELL,
        target_weight=-0.03,
        reason="test short entry",
        regime_confidence=0.6,
        stop_price=103.0,
    )
    verdict = fw.check(
        intent, _order(), _portfolio(), _ctx(atr_value=2.0, entry_price=100.0)
    )
    assert verdict.allowed is True


def test_no_atr_skips_distance_validation() -> None:
    """Without an ATR value the distance check cannot run (has_stop still enforced)."""
    fw = HardLimitFirewall()
    verdict = fw.check(_intent(), _order(), _portfolio(), _ctx(atr_value=None))
    assert verdict.allowed is True


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
