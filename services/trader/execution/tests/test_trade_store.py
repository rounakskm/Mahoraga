"""Tests for TradeStore (Phase 5, Task 11).

Two layers:
- The no-DSN no-op contract (always runs): `TradeStore(None)` is disabled and
  every method is a safe no-op — no raise, no psycopg import, no connection.
- The DSN-gated round-trip (skipped unless `MAHORAGA_DSN` is set): records an
  order, a fill referencing it, a position snapshot and a daily-pnl UPSERT, and
  reads each back. Test rows are cleaned up in a fixture.
"""

from __future__ import annotations

import datetime as dt
import os

import pytest

from services.trader.execution.model import (
    Order,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    Side,
)
from services.trader.execution.trade_store import TradeStore, _pl_pct

DSN = os.environ.get("MAHORAGA_DSN")
_TEST_TICKER = "ZZTEST"
# A synthetic pnl_daily date the LIVE paper window can never contain — the
# fixture deletes this date unconditionally, so it must never be a real row.
_TEST_PNL_DATE = dt.date(1999, 1, 4)


def _sample_order() -> Order:
    return Order(
        id="broker-abc-123",
        ticker=_TEST_TICKER,
        side=Side.BUY,
        qty=100.0,
        order_type=OrderType.LIMIT,
        limit_price=50.0,
        stop_price=48.0,
        status=OrderStatus.SUBMITTED,
        filled_qty=0.0,
        filled_avg_price=None,
    )


# ---------------------------------------------------------------------------
# No-DSN no-op contract — always runs, never touches psycopg or a socket.
# ---------------------------------------------------------------------------


def test_disabled_when_no_dsn() -> None:
    store = TradeStore(None)
    assert store.is_enabled() is False


def test_record_order_returns_none_when_disabled() -> None:
    store = TradeStore(None)
    assert store.record_order(_sample_order(), "test") is None


def test_all_methods_noop_when_disabled() -> None:
    """Every method returns early without raising or connecting."""
    store = TradeStore(None)
    portfolio = Portfolio(
        equity=100_000.0,
        cash=50_000.0,
        buying_power=50_000.0,
        positions={
            _TEST_TICKER: Position(
                ticker=_TEST_TICKER,
                qty=100.0,
                avg_entry=50.0,
                market_value=5_000.0,
                unrealized_pl=0.0,
            )
        },
    )
    # None of these may raise, connect, or import psycopg.
    assert store.record_order(_sample_order(), "test") is None
    assert store.record_fill(1, 100.0, 50.0) is None
    assert store.snapshot_positions(portfolio) is None
    assert store.record_daily_pnl(dt.date(2026, 7, 1), 100_000.0, 0.0, 0.0) is None
    # The connection was never established.
    assert store._conn is None


# ---------------------------------------------------------------------------
# DSN-gated round-trip.
# ---------------------------------------------------------------------------


@pytest.fixture()
def store():
    s = TradeStore(DSN)
    yield s
    # Clean up any rows this test suite created.
    conn = s._conn_for_test()
    conn.execute(
        "DELETE FROM trades.fills WHERE order_id IN "
        "(SELECT id FROM trades.orders WHERE ticker = %s)",
        (_TEST_TICKER,),
    )
    conn.execute("DELETE FROM trades.orders WHERE ticker = %s", (_TEST_TICKER,))
    conn.execute("DELETE FROM trades.positions WHERE ticker = %s", (_TEST_TICKER,))
    conn.execute("DELETE FROM trades.pnl_daily WHERE d = %s", (_TEST_PNL_DATE,))
    s.close()


@pytest.mark.skipif(not DSN, reason="MAHORAGA_DSN not set")
def test_record_order_returns_id_and_persists(store: TradeStore) -> None:
    order = _sample_order()
    order_id = store.record_order(order, "unit-test entry")
    assert isinstance(order_id, int)

    conn = store._conn_for_test()
    row = conn.execute(
        "SELECT ticker, side, qty, order_type, limit_price, stop_price, status, "
        "broker_order_id, reason, filled_qty FROM trades.orders WHERE id = %s",
        (order_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == _TEST_TICKER
    assert row[1] == "BUY"
    assert row[2] == 100.0
    assert row[3] == "LIMIT"
    assert row[4] == 50.0
    assert row[5] == 48.0
    assert row[6] == "SUBMITTED"
    assert row[7] == "broker-abc-123"
    assert row[8] == "unit-test entry"
    assert row[9] == 0.0


@pytest.mark.skipif(not DSN, reason="MAHORAGA_DSN not set")
def test_record_fill_references_order(store: TradeStore) -> None:
    order_id = store.record_order(_sample_order(), "fill-test")
    assert order_id is not None
    store.record_fill(order_id, 100.0, 50.25)

    conn = store._conn_for_test()
    row = conn.execute(
        "SELECT order_id, qty, price FROM trades.fills WHERE order_id = %s",
        (order_id,),
    ).fetchone()
    assert row == (order_id, 100.0, 50.25)


@pytest.mark.skipif(not DSN, reason="MAHORAGA_DSN not set")
def test_snapshot_positions_round_trip(store: TradeStore) -> None:
    portfolio = Portfolio(
        equity=100_000.0,
        cash=50_000.0,
        buying_power=50_000.0,
        positions={
            _TEST_TICKER: Position(
                ticker=_TEST_TICKER,
                qty=100.0,
                avg_entry=50.0,
                market_value=5_100.0,
                unrealized_pl=100.0,
            )
        },
    )
    store.snapshot_positions(portfolio)

    conn = store._conn_for_test()
    row = conn.execute(
        "SELECT ticker, qty, avg_entry, market_value, unrealized_pl "
        "FROM trades.positions WHERE ticker = %s",
        (_TEST_TICKER,),
    ).fetchone()
    assert row == (_TEST_TICKER, 100.0, 50.0, 5_100.0, 100.0)


@pytest.mark.skipif(not DSN, reason="MAHORAGA_DSN not set")
def test_record_daily_pnl_upserts(store: TradeStore) -> None:
    d = _TEST_PNL_DATE
    store.record_daily_pnl(d, 100_000.0, 500.0, 200.0)
    store.record_daily_pnl(d, 101_000.0, 600.0, 250.0)  # UPSERT — same date

    conn = store._conn_for_test()
    rows = conn.execute(
        "SELECT equity, realized_pl, unrealized_pl FROM trades.pnl_daily WHERE d = %s",
        (d,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0] == (101_000.0, 600.0, 250.0)


# ---------------------------------------------------------------------------
# C3/C7 — recent_trades + latest_positions: disabled no-op contract.
# ---------------------------------------------------------------------------


def test_recent_trades_empty_when_disabled() -> None:
    store = TradeStore(None)
    assert store.recent_trades() == []
    assert store._conn is None


def test_latest_positions_none_when_disabled() -> None:
    store = TradeStore(None)
    assert store.latest_positions() is None
    assert store._conn is None


@pytest.mark.skipif(not DSN, reason="MAHORAGA_DSN not set")
def test_recent_trades_round_trip(store: TradeStore) -> None:
    """A filled BUY + loss-closing SELL on the same day come back as TradeRecords
    with a negative realized_pl on the sell and is_day_trade=True on both."""
    from services.trader.execution.compliance import TradeRecord

    buy = Order(
        id="b-1",
        ticker=_TEST_TICKER,
        side=Side.BUY,
        qty=10.0,
        order_type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
        status=OrderStatus.FILLED,
        filled_qty=10.0,
        filled_avg_price=50.0,
    )
    sell = Order(
        id="s-1",
        ticker=_TEST_TICKER,
        side=Side.SELL,
        qty=10.0,
        order_type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
        status=OrderStatus.FILLED,
        filled_qty=10.0,
        filled_avg_price=48.0,  # sold below the 50.0 buy -> realized loss
    )
    store.record_order(buy, "test buy")
    store.record_order(sell, "test sell")

    records = [t for t in store.recent_trades(days=35) if t.ticker == _TEST_TICKER]
    assert len(records) == 2
    assert all(isinstance(t, TradeRecord) for t in records)
    sells = [t for t in records if t.side is Side.SELL]
    assert sells and sells[0].realized_pl < 0
    assert all(t.is_day_trade for t in records)  # same-ticker buy+sell same date


# ---------------------------------------------------------------------------
# Monthly P&L — feeds the 10% monthly-catastrophic halt.
# ---------------------------------------------------------------------------


def test_pl_pct_pure_math() -> None:
    """The extracted return math: (end - baseline) / baseline, None on bad base."""
    assert _pl_pct(100_000.0, 95_000.0) == pytest.approx(-0.05)
    assert _pl_pct(100_000.0, 90_000.0) == pytest.approx(-0.10)
    assert _pl_pct(100_000.0, 110_000.0) == pytest.approx(0.10)
    assert _pl_pct(0.0, 95_000.0) is None
    assert _pl_pct(-1.0, 95_000.0) is None


def test_monthly_pl_pct_none_when_disabled() -> None:
    """No DSN -> None (the ctx factory turns that into 0.0 + a loud WARNING)."""
    store = TradeStore(None)
    assert store.monthly_pl_pct() is None
    assert store.monthly_pl_pct(current_equity=100_000.0) is None
    assert store._conn is None


@pytest.fixture()
def pnl_window_rows(store: TradeStore):
    """Insert a 30d-ago baseline (100k) + today's row (95k); restore on teardown.

    The paper window is LIVE — real pnl_daily rows may already exist on these
    dates (the UPSERT would clobber them), so pre-existing rows are snapshotted
    and restored rather than blindly deleted.
    """
    conn = store._conn_for_test()
    today = conn.execute("SELECT CURRENT_DATE").fetchone()[0]
    baseline_d = today - dt.timedelta(days=30)  # oldest date inside the window
    saved = conn.execute(
        "SELECT d, equity, realized_pl, unrealized_pl FROM trades.pnl_daily "
        "WHERE d IN (%s, %s)",
        (baseline_d, today),
    ).fetchall()
    store.record_daily_pnl(baseline_d, 100_000.0, 0.0, 0.0)
    store.record_daily_pnl(today, 95_000.0, -5_000.0, 0.0)
    yield
    conn.execute(
        "DELETE FROM trades.pnl_daily WHERE d IN (%s, %s)", (baseline_d, today)
    )
    for d, equity, realized, unrealized in saved:
        store.record_daily_pnl(d, equity, realized, unrealized)


@pytest.mark.skipif(not DSN, reason="MAHORAGA_DSN not set")
def test_monthly_pl_pct_round_trip(store: TradeStore, pnl_window_rows: None) -> None:
    """Baseline = oldest in-window equity; endpoint = newest row (or override)."""
    assert store.monthly_pl_pct() == pytest.approx(-0.05)
    # Live-equity endpoint: baseline 100k vs current 90k -> the 10% halt trips.
    assert store.monthly_pl_pct(current_equity=90_000.0) == pytest.approx(-0.10)


@pytest.mark.skipif(not DSN, reason="MAHORAGA_DSN not set")
def test_latest_positions_round_trip(store: TradeStore) -> None:
    portfolio = Portfolio(
        equity=100_000.0,
        cash=50_000.0,
        buying_power=50_000.0,
        positions={
            _TEST_TICKER: Position(
                ticker=_TEST_TICKER,
                qty=100.0,
                avg_entry=50.0,
                market_value=5_000.0,
                unrealized_pl=0.0,
            )
        },
    )
    store.snapshot_positions(portfolio)
    latest = store.latest_positions()
    assert latest is not None
    assert _TEST_TICKER in latest
    assert latest[_TEST_TICKER].qty == 100.0
