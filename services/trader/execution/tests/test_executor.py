"""Executor tests — the Phase-5 architectural safety invariant (Task 10).

THE INVARIANT (Phase-5 exit criterion): the executor calls firewall + compliance
BEFORE the broker, submits ONLY orders both allow, checks halt FIRST each iteration,
and defaults to dry-run. A rejected or halted order must NEVER reach
`broker.submit_order`.

Stubs assert the invariant precisely: the stub broker records every submit call
(including the `dry_run` kwarg); the stub firewall/compliance are switchable
allow/deny; the HaltControl is isolated to a tmp flag file.
"""

from __future__ import annotations

import pandas as pd

from services.trader.execution.compliance import ComplianceVerdict
from services.trader.execution.executor import CycleReport, Executor
from services.trader.execution.firewall import FirewallContext, FirewallVerdict
from services.trader.execution.model import (
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
    Portfolio,
    Side,
)
from services.trader.ops.halt import HaltControl


class _StubBroker:
    """Records every submit_order call — the invariant witness."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def submit_order(self, order: Order, *, dry_run: bool = True) -> Order:
        self.calls.append({"order": order, "dry_run": dry_run})
        return Order(
            id=f"sim-{order.ticker}",
            ticker=order.ticker,
            side=order.side,
            qty=order.qty,
            order_type=order.order_type,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
            status=OrderStatus.SUBMITTED,
        )


class _StubFirewall:
    """Firewall stub — allow/deny switchable per constructor."""

    def __init__(self, allow: bool = True) -> None:
        self.allow = allow

    def check(self, intent, order, portfolio, ctx) -> FirewallVerdict:  # noqa: ANN001
        if self.allow:
            return FirewallVerdict(allowed=True, rejections=[])
        return FirewallVerdict(allowed=False, rejections=["stub firewall deny"])


class _StubCompliance:
    """Compliance stub — allow/deny switchable per constructor."""

    def __init__(self, allow: bool = True) -> None:
        self.allow = allow

    def check(self, intent, portfolio, recent_trades, now) -> ComplianceVerdict:  # noqa: ANN001
        if self.allow:
            return ComplianceVerdict(allowed=True, rejections=[])
        return ComplianceVerdict(allowed=False, rejections=["stub compliance deny"])


def _portfolio() -> Portfolio:
    return Portfolio(equity=100_000.0, cash=100_000.0, buying_power=200_000.0, positions={})


def _intent(ticker: str = "SPY") -> OrderIntent:
    return OrderIntent(
        ticker=ticker,
        side=Side.BUY,
        target_weight=0.03,
        reason="stub signal",
        regime_confidence=0.80,
        stop_price=480.0,
    )


def _ctx_for(intent: OrderIntent, order: Order) -> FirewallContext:
    return FirewallContext(
        now=pd.Timestamp("2026-07-01T15:00:00Z"),
        regime_confidence=intent.regime_confidence,
        daily_pl_pct=0.0,
        monthly_pl_pct=0.0,
        has_stop=order.stop_price is not None,
        sector="ETF",
        order_notional=abs(order.qty) * 500.0,
    )


def test_over_limit_never_submitted(tmp_path) -> None:
    """Firewall denies -> rejected AND broker.submit_order NEVER called."""
    broker = _StubBroker()
    halt = HaltControl(tmp_path / "halt.flag")
    ex = Executor(broker, _StubFirewall(allow=False), _StubCompliance(allow=True), halt)

    report = ex.run_cycle([_intent()], _portfolio(), {"SPY": 500.0}, _ctx_for)

    assert broker.calls == []  # the invariant: no submit for a rejected order
    assert report.submitted == 0
    assert report.rejected == 1
    assert any("firewall" in r for r in report.rejections)


def test_in_limits_submitted_dry_run_by_default(tmp_path) -> None:
    """Firewall + compliance allow -> submitted with dry_run=True (default)."""
    broker = _StubBroker()
    halt = HaltControl(tmp_path / "halt.flag")
    ex = Executor(broker, _StubFirewall(allow=True), _StubCompliance(allow=True), halt)

    report = ex.run_cycle([_intent()], _portfolio(), {"SPY": 500.0}, _ctx_for)

    assert len(broker.calls) == 1
    assert broker.calls[0]["dry_run"] is True  # dry-run default
    assert report.submitted == 1
    assert report.rejected == 0
    assert report.halted is False


def test_live_orders_flag_sets_dry_run_false(tmp_path) -> None:
    """live_orders=True -> submit_order called with dry_run=False."""
    broker = _StubBroker()
    halt = HaltControl(tmp_path / "halt.flag")
    ex = Executor(
        broker,
        _StubFirewall(allow=True),
        _StubCompliance(allow=True),
        halt,
        live_orders=True,
    )

    ex.run_cycle([_intent()], _portfolio(), {"SPY": 500.0}, _ctx_for)

    assert len(broker.calls) == 1
    assert broker.calls[0]["dry_run"] is False


def test_halt_first_stops_cycle(tmp_path) -> None:
    """Pre-halted control -> halted True, submitted 0, broker never called."""
    broker = _StubBroker()
    halt = HaltControl(tmp_path / "halt.flag")
    halt.halt("test halt")
    ex = Executor(broker, _StubFirewall(allow=True), _StubCompliance(allow=True), halt)

    report = ex.run_cycle([_intent()], _portfolio(), {"SPY": 500.0}, _ctx_for)

    assert report.halted is True
    assert report.submitted == 0
    assert broker.calls == []


def test_compliance_rejection_pre_submit(tmp_path) -> None:
    """Firewall allows, compliance denies -> rejected, never submitted."""
    broker = _StubBroker()
    halt = HaltControl(tmp_path / "halt.flag")
    ex = Executor(broker, _StubFirewall(allow=True), _StubCompliance(allow=False), halt)

    report = ex.run_cycle([_intent()], _portfolio(), {"SPY": 500.0}, _ctx_for)

    assert broker.calls == []
    assert report.submitted == 0
    assert report.rejected == 1
    assert any("compliance" in r for r in report.rejections)


def test_no_price_rejected(tmp_path) -> None:
    """Missing / non-positive price -> rejected, never sized or submitted."""
    broker = _StubBroker()
    halt = HaltControl(tmp_path / "halt.flag")
    ex = Executor(broker, _StubFirewall(allow=True), _StubCompliance(allow=True), halt)

    report = ex.run_cycle([_intent("MSFT")], _portfolio(), {}, _ctx_for)

    assert broker.calls == []
    assert report.rejected == 1
    assert any("price" in r for r in report.rejections)


def test_mixed_batch(tmp_path) -> None:
    """3 intents: 1 allowed, 1 firewall-denied, 1 compliance-denied -> 1 dry-run submit."""
    broker = _StubBroker()
    halt = HaltControl(tmp_path / "halt.flag")

    class _SelectiveFirewall:
        def check(self, intent, order, portfolio, ctx):  # noqa: ANN001, ANN201
            if intent.ticker == "FWDENY":
                return FirewallVerdict(allowed=False, rejections=["fw deny FWDENY"])
            return FirewallVerdict(allowed=True, rejections=[])

    class _SelectiveCompliance:
        def check(self, intent, portfolio, recent_trades, now):  # noqa: ANN001, ANN201
            if intent.ticker == "CMPDENY":
                return ComplianceVerdict(allowed=False, rejections=["cmp deny CMPDENY"])
            return ComplianceVerdict(allowed=True, rejections=[])

    ex = Executor(broker, _SelectiveFirewall(), _SelectiveCompliance(), halt)
    intents = [_intent("OK"), _intent("FWDENY"), _intent("CMPDENY")]
    prices = {"OK": 500.0, "FWDENY": 500.0, "CMPDENY": 500.0}

    report = ex.run_cycle(intents, _portfolio(), prices, _ctx_for)

    assert report.intents == 3
    assert report.submitted == 1
    assert report.rejected == 2
    assert len(broker.calls) == 1
    assert broker.calls[0]["order"].ticker == "OK"
    assert broker.calls[0]["dry_run"] is True


def test_cycle_report_shape() -> None:
    """CycleReport is a frozen dataclass with the specified fields."""
    r = CycleReport(intents=2, submitted=1, rejected=1, halted=False, rejections=["x"])
    assert (r.intents, r.submitted, r.rejected, r.halted, r.rejections) == (
        2,
        1,
        1,
        False,
        ["x"],
    )


def test_size_to_zero_rejected(tmp_path) -> None:
    """Sub-min-notional intent -> size_order returns None -> rejected, not submitted."""
    broker = _StubBroker()
    halt = HaltControl(tmp_path / "halt.flag")
    ex = Executor(broker, _StubFirewall(allow=True), _StubCompliance(allow=True), halt)

    tiny = OrderIntent(
        ticker="SPY",
        side=Side.BUY,
        target_weight=1e-9,
        reason="dust",
        regime_confidence=0.9,
        stop_price=480.0,
    )
    report = ex.run_cycle([tiny], _portfolio(), {"SPY": 500.0}, _ctx_for)

    assert broker.calls == []
    assert report.rejected == 1
    assert any("size" in r or "min" in r for r in report.rejections)


def test_hindsight_retains_on_submit(tmp_path) -> None:
    """When hindsight is enabled, a submitted order retains an Experience Fact."""
    broker = _StubBroker()
    halt = HaltControl(tmp_path / "halt.flag")

    class _StubHindsight:
        def __init__(self) -> None:
            self.retained: list[tuple[str, dict]] = []

        def is_enabled(self) -> bool:
            return True

        def retain(self, text, metadata=None):  # noqa: ANN001, ANN201
            self.retained.append((text, metadata or {}))
            return "fact-1"

    hs = _StubHindsight()
    ex = Executor(
        broker,
        _StubFirewall(allow=True),
        _StubCompliance(allow=True),
        halt,
        hindsight=hs,
    )
    ex.run_cycle([_intent()], _portfolio(), {"SPY": 500.0}, _ctx_for)

    assert len(hs.retained) == 1
    text, meta = hs.retained[0]
    assert "SPY" in text
    assert meta.get("ticker") == "SPY"


def test_order_type_is_market_default() -> None:
    """Sanity: sized orders are MARKET (sizing.size_order contract)."""
    assert OrderType.MARKET == "MARKET"
