"""Performance attribution over production-shaped trades.orders rows (Phase-6 Task 2).

Fixtures use the REAL ``trades.orders`` column names from
``infra/postgres/migrations/007_trades.sql`` (review lesson: production-shaped
inputs), and a cross-check test asserts every consumed column appears in the DDL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from services.trader.ops.attribution import (
    CONSUMED_COLUMNS,
    AttributionReport,
    attribute,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DDL_PATH = _REPO_ROOT / "infra" / "postgres" / "migrations" / "007_trades.sql"


def _row(
    ts: str,
    ticker: str,
    side: str,
    qty: float,
    price: float,
    status: str = "FILLED",
) -> dict[str, Any]:
    return {
        "ts": pd.Timestamp(ts),
        "ticker": ticker,
        "side": side,
        "filled_qty": float(qty),
        "filled_avg_price": float(price),
        "status": status,
    }


def _orders(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(CONSUMED_COLUMNS))


# ---------------------------------------------------------------- (1) long trip


def test_single_long_round_trip_spy() -> None:
    orders = _orders(
        [
            _row("2024-01-02", "SPY", "BUY", 100, 500.0),
            _row("2024-01-05", "SPY", "SELL", 100, 505.0),
        ]
    )
    report = attribute(orders)
    assert isinstance(report, AttributionReport)
    assert report.total_pl == 500.0
    assert report.by_ticker == {"SPY": 500.0}
    assert report.by_side == {"long": 500.0}
    assert report.by_holding_period == {"1-5d": 500.0}
    assert report.n_round_trips == 1
    # No regimes series supplied -> everything is "unknown".
    assert report.by_regime == {"unknown": 500.0}


def test_by_regime_uses_entry_date_label_asof() -> None:
    orders = _orders(
        [
            _row("2024-01-02", "SPY", "BUY", 100, 500.0),
            _row("2024-01-05", "SPY", "SELL", 100, 505.0),
        ]
    )
    regimes = pd.Series(
        ["trending_low_vol"], index=pd.DatetimeIndex([pd.Timestamp("2024-01-02")])
    )
    report = attribute(orders, regimes=regimes)
    assert report.by_regime == {"trending_low_vol": 500.0}


def test_by_regime_nearest_prior_lookup_and_missing() -> None:
    orders = _orders(
        [
            # Entry 2024-01-02: nearest prior label is 2024-01-01.
            _row("2024-01-02", "SPY", "BUY", 100, 500.0),
            _row("2024-01-05", "SPY", "SELL", 100, 505.0),
            # Entry 2023-06-01 predates every label -> "unknown".
            _row("2023-06-01", "IWM", "BUY", 10, 200.0),
            _row("2023-06-02", "IWM", "SELL", 10, 210.0),
        ]
    )
    regimes = pd.Series(
        ["choppy_high_vol"], index=pd.DatetimeIndex([pd.Timestamp("2024-01-01")])
    )
    report = attribute(orders, regimes=regimes)
    assert report.by_regime == {"choppy_high_vol": 500.0, "unknown": 100.0}


# ------------------------------------------------------- (2) intraday aggregation


def test_intraday_loser_aggregates_with_multiday_winner() -> None:
    orders = _orders(
        [
            _row("2024-01-02", "SPY", "BUY", 100, 500.0),
            _row("2024-01-05", "SPY", "SELL", 100, 505.0),
            _row("2024-01-03 10:00", "QQQ", "BUY", 100, 400.0),
            _row("2024-01-03 15:30", "QQQ", "SELL", 100, 398.0),
        ]
    )
    report = attribute(orders)
    assert report.total_pl == 300.0
    assert report.by_ticker == {"SPY": 500.0, "QQQ": -200.0}
    assert report.by_side == {"long": 300.0}
    assert report.by_holding_period == {"1-5d": 500.0, "intraday": -200.0}
    assert report.n_round_trips == 2


# ----------------------------------------------------------- (3) partial match


def test_partial_fill_leaves_open_lot_excluded() -> None:
    orders = _orders(
        [
            _row("2024-01-02", "SPY", "BUY", 100, 500.0),
            _row("2024-01-04", "SPY", "SELL", 60, 510.0),
        ]
    )
    report = attribute(orders)
    # One 60-qty round trip; the remaining 40 shares stay open (unrealized,
    # out of scope) and contribute nothing.
    assert report.n_round_trips == 1
    assert report.total_pl == 600.0
    assert report.by_ticker == {"SPY": 600.0}


def test_status_filter_partial_counts_others_ignored() -> None:
    orders = _orders(
        [
            _row("2024-01-02", "SPY", "BUY", 100, 500.0, status="PARTIAL"),
            _row("2024-01-03", "SPY", "SELL", 100, 505.0),
            # Non-filled statuses never count, even with a price attached.
            _row("2024-01-03", "SPY", "SELL", 50, 999.0, status="SUBMITTED"),
            _row("2024-01-03", "SPY", "BUY", 0, 500.0, status="PARTIAL"),
        ]
    )
    report = attribute(orders)
    assert report.n_round_trips == 1
    assert report.total_pl == 500.0


# ------------------------------------------------------------- (4) short trip


def test_short_round_trip_sell_then_buy() -> None:
    orders = _orders(
        [
            _row("2024-01-02", "IWM", "SELL", 50, 400.0),
            _row("2024-01-10", "IWM", "BUY", 50, 390.0),
        ]
    )
    report = attribute(orders)
    assert report.total_pl == 500.0
    assert report.by_side == {"short": 500.0}
    assert report.by_ticker == {"IWM": 500.0}
    # 8 calendar days -> "5-20d".
    assert report.by_holding_period == {"5-20d": 500.0}
    assert report.n_round_trips == 1


def test_holding_period_20d_plus() -> None:
    orders = _orders(
        [
            _row("2024-01-02", "SPY", "BUY", 10, 500.0),
            _row("2024-02-15", "SPY", "SELL", 10, 501.0),
        ]
    )
    report = attribute(orders)
    assert report.by_holding_period == {"20d+": 10.0}


# ------------------------------------------------------------ (5) empty frame


def test_empty_frame_returns_zeroed_report() -> None:
    report = attribute(_orders([]))
    assert report.total_pl == 0.0
    assert report.by_regime == {}
    assert report.by_ticker == {}
    assert report.by_side == {}
    assert report.by_holding_period == {}
    assert report.n_round_trips == 0


def test_only_open_lots_returns_zeroed_report() -> None:
    report = attribute(_orders([_row("2024-01-02", "SPY", "BUY", 100, 500.0)]))
    assert report.total_pl == 0.0
    assert report.n_round_trips == 0
    assert report.by_ticker == {}


# -------------------------------------------------------- (6) DDL cross-check


def test_consumed_columns_exist_in_trades_orders_ddl() -> None:
    """Every column `attribute` consumes must appear in the real migration DDL."""
    ddl = _DDL_PATH.read_text()
    for column in CONSUMED_COLUMNS:
        assert column in ddl, f"column {column!r} not found in 007_trades.sql"
