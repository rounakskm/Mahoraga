"""Phase-5 exit-criterion integration smoke — the architectural firewall invariant.

End-to-end and fully OFFLINE: no network, no Alpaca key, no DSN. A stub broker
records every `submit_order` call (order + `dry_run` kwarg) so the test can assert
the single safety property Phase-5 stands on:

  * an order that violates a hard limit (position > 5% of equity) is REJECTED by the
    real `HardLimitFirewall` and NEVER handed to the broker;
  * an in-limits order (small weight, high regime confidence, ATR stop attached) is
    submitted, and — because `live_orders` defaults False — always with `dry_run=True`;
  * a pre-tripped `HaltControl` stops the cycle immediately: `halted=True`, zero submits.

This is the Phase-5 firewall exit criterion, exercised through the production
`Executor` + `HardLimitFirewall` + `ComplianceEngine` (only the broker is stubbed).
"""

from __future__ import annotations

import pandas as pd

from services.trader.execution.compliance import ComplianceEngine
from services.trader.execution.executor import Executor
from services.trader.execution.firewall import FirewallContext, HardLimitFirewall
from services.trader.execution.model import Order, OrderIntent, Portfolio, Side
from services.trader.ops.halt import HaltControl

# Illustrative constants for the offline scenario.
_EQUITY = 100_000.0
_PRICE = 100.0
_IN_LIMITS_WEIGHT = 0.03      # ~3% of equity -> under the 5% position cap.
_OVER_LIMIT_WEIGHT = 0.06     # ~6% of equity -> over the 5% position cap.
_STOP = 96.0                  # a 2xATR-style stop below entry.


class _StubBroker:
    """Records every submit_order call — the spy the firewall invariant checks."""

    def __init__(self) -> None:
        self.calls: list[tuple[Order, bool]] = []

    def submit_order(self, order: Order, *, dry_run: bool = True) -> Order:
        self.calls.append((order, dry_run))
        return order


def _portfolio() -> Portfolio:
    return Portfolio(equity=_EQUITY, cash=_EQUITY, buying_power=_EQUITY, positions={})


def _ctx_for_factory(now: pd.Timestamp):
    """Build a ctx_for that sets order_notional from the intent's desired weight.

    Uses the intent's (un-clamped) target notional so the firewall sees the true
    requested size — in-limits ~3% of equity, over-limit ~6% — and enforces the
    5% position cap architecturally (rather than silently clamping at sizing).
    The firewall derives position/sector pct from `order_notional / equity`.
    """

    def ctx_for(intent: OrderIntent, order: Order) -> FirewallContext:
        return FirewallContext(
            now=now,
            regime_confidence=intent.regime_confidence,
            daily_pl_pct=0.0,
            monthly_pl_pct=0.0,
            has_stop=intent.stop_price is not None,
            sector="ETF",
            order_notional=abs(intent.target_weight) * _EQUITY,
        )

    return ctx_for


def _intents() -> list[OrderIntent]:
    in_limits = OrderIntent(
        ticker="SPY",
        side=Side.BUY,
        target_weight=_IN_LIMITS_WEIGHT,
        reason="in-limits illustrative entry",
        regime_confidence=0.80,
        stop_price=_STOP,
    )
    over_limit = OrderIntent(
        ticker="QQQ",
        side=Side.BUY,
        target_weight=_OVER_LIMIT_WEIGHT,
        reason="over-5%-position illustrative entry",
        regime_confidence=0.80,
        stop_price=_STOP,
    )
    return [in_limits, over_limit]


def test_firewall_invariant_over_limit_rejected_in_limits_dry_run() -> None:
    """Over-limit intent never reaches the broker; in-limits is dry-run submitted."""
    now = pd.Timestamp("2026-07-01", tz="UTC")
    broker = _StubBroker()
    executor = Executor(
        broker=broker,
        firewall=HardLimitFirewall(),
        compliance=ComplianceEngine(),
        halt=HaltControl(flag_path="/tmp/mahoraga-p5-never-halted.flag"),
        live_orders=False,
    )

    report = executor.run_cycle(
        _intents(),
        _portfolio(),
        prices={"SPY": _PRICE, "QQQ": _PRICE},
        ctx_for=_ctx_for_factory(now),
    )

    # Exactly the in-limits intent submitted; the over-limit one rejected.
    assert report.intents == 2
    assert report.submitted == 1
    assert report.rejected == 1
    assert report.halted is False

    # The broker saw exactly one order — the in-limits SPY buy — and it was dry-run.
    assert len(broker.calls) == 1
    submitted_order, dry_run = broker.calls[0]
    assert submitted_order.ticker == "SPY"
    assert dry_run is True

    # The over-limit QQQ order was NEVER handed to the broker.
    assert all(order.ticker != "QQQ" for order, _ in broker.calls)
    assert any("QQQ" in r and "firewall" in r for r in report.rejections)


def test_pre_halted_control_stops_cycle_zero_submits(tmp_path) -> None:
    """A tripped kill-switch halts the cycle before any submit."""
    now = pd.Timestamp("2026-07-01", tz="UTC")
    broker = _StubBroker()
    halt = HaltControl(flag_path=tmp_path / "halt.flag")
    halt.halt("test: pre-halted")

    executor = Executor(
        broker=broker,
        firewall=HardLimitFirewall(),
        compliance=ComplianceEngine(),
        halt=halt,
        live_orders=False,
    )

    report = executor.run_cycle(
        _intents(),
        _portfolio(),
        prices={"SPY": _PRICE, "QQQ": _PRICE},
        ctx_for=_ctx_for_factory(now),
    )

    assert report.halted is True
    assert report.submitted == 0
    assert broker.calls == []
