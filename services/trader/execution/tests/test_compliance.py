"""Tests for the compliance engine (Phase 5, Task 8)."""

from __future__ import annotations

import pandas as pd

from services.trader.execution.compliance import (
    ComplianceEngine,
    ComplianceVerdict,
    TradeRecord,
)
from services.trader.execution.model import OrderIntent, Portfolio, Side


def _buy(ticker: str) -> OrderIntent:
    return OrderIntent(
        ticker=ticker,
        side=Side.BUY,
        target_weight=0.05,
        reason="test",
        regime_confidence=0.9,
    )


def _portfolio(equity: float) -> Portfolio:
    return Portfolio(equity=equity, cash=equity, buying_power=equity)


def _day_trades(now: pd.Timestamp, n: int) -> list[TradeRecord]:
    return [
        TradeRecord(
            ticker="SPY",
            side=Side.SELL,
            ts=now - pd.Timedelta(days=i),
            realized_pl=10.0,
            is_day_trade=True,
        )
        for i in range(1, n + 1)
    ]


def test_pdt_fourth_day_trade_under_floor_rejects() -> None:
    now = pd.Timestamp("2026-07-01")
    engine = ComplianceEngine()
    trades = _day_trades(now, 3)  # 3 prior day-trades in window
    verdict = engine.check(_buy("AAPL"), _portfolio(10_000.0), trades, now)
    assert isinstance(verdict, ComplianceVerdict)
    assert verdict.allowed is False
    assert any("PDT" in r for r in verdict.rejections)


def test_pdt_fourth_day_trade_at_or_above_floor_allowed() -> None:
    now = pd.Timestamp("2026-07-01")
    engine = ComplianceEngine()
    trades = _day_trades(now, 3)
    verdict = engine.check(_buy("AAPL"), _portfolio(25_000.0), trades, now)
    assert verdict.allowed is True
    assert verdict.rejections == []


def test_wash_sale_btc_etf_sibling_loss_within_window_rejects() -> None:
    now = pd.Timestamp("2026-07-01")
    engine = ComplianceEngine()
    trades = [
        TradeRecord(
            ticker="FBTC",
            side=Side.SELL,
            ts=now - pd.Timedelta(days=10),
            realized_pl=-500.0,
            is_day_trade=False,
        )
    ]
    verdict = engine.check(_buy("IBIT"), _portfolio(50_000.0), trades, now)
    assert verdict.allowed is False
    assert any("wash" in r.lower() for r in verdict.rejections)


def test_wash_sale_outside_window_allowed() -> None:
    now = pd.Timestamp("2026-07-01")
    engine = ComplianceEngine()
    trades = [
        TradeRecord(
            ticker="FBTC",
            side=Side.SELL,
            ts=now - pd.Timedelta(days=45),
            realized_pl=-500.0,
            is_day_trade=False,
        )
    ]
    verdict = engine.check(_buy("IBIT"), _portfolio(50_000.0), trades, now)
    assert verdict.allowed is True


def test_wash_sale_profitable_sale_allowed() -> None:
    now = pd.Timestamp("2026-07-01")
    engine = ComplianceEngine()
    trades = [
        TradeRecord(
            ticker="FBTC",
            side=Side.SELL,
            ts=now - pd.Timedelta(days=10),
            realized_pl=500.0,  # profitable — not a wash sale
            is_day_trade=False,
        )
    ]
    verdict = engine.check(_buy("IBIT"), _portfolio(50_000.0), trades, now)
    assert verdict.allowed is True


def test_ssr_stub_always_ok() -> None:
    engine = ComplianceEngine()
    assert engine._ssr_ok(_buy("AAPL")) is True


# ---------------------------------------------------------------------------
# C10 — timezone normalization: naive timestamps are treated as UTC, and mixed
# naive/aware inputs never raise.
# ---------------------------------------------------------------------------


def test_naive_trade_ts_vs_aware_now_wash_sale_detected() -> None:
    """A naive loss-sale ts against an aware `now` must still trip the wash-sale."""
    now = pd.Timestamp("2026-07-01 15:00", tz="UTC")
    engine = ComplianceEngine()
    trades = [
        TradeRecord(
            ticker="AAPL",
            side=Side.SELL,
            ts=pd.Timestamp("2026-06-20 15:00"),  # naive -> treated as UTC
            realized_pl=-50.0,
            is_day_trade=False,
        )
    ]
    verdict = engine.check(_buy("AAPL"), _portfolio(100_000.0), trades, now)
    assert verdict.allowed is False
    assert any("wash-sale" in r for r in verdict.rejections)


def test_aware_trade_ts_vs_naive_now_no_raise() -> None:
    """Aware trade ts + naive `now` (treated as UTC) compares without raising."""
    now = pd.Timestamp("2026-07-01 15:00")  # naive -> treated as UTC
    engine = ComplianceEngine()
    trades = [
        TradeRecord(
            ticker="AAPL",
            side=Side.SELL,
            ts=pd.Timestamp("2026-06-20 15:00", tz="UTC"),
            realized_pl=-50.0,
            is_day_trade=True,
        )
    ]
    verdict = engine.check(_buy("AAPL"), _portfolio(100_000.0), trades, now)
    assert verdict.allowed is False
    assert any("wash-sale" in r for r in verdict.rejections)
