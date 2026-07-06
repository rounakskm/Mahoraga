"""DashboardData — pure panel data layer tests (Phase-6 Task 5).

Fixtures use the REAL production column names from
``infra/postgres/migrations/007_trades.sql`` / ``005_experiments.sql`` (+
``006_master_pointer.sql``, which ALTERs ``experiments.iterations`` to add
``fitness``); a cross-check test asserts every column each SQL selects appears
in the migration DDL text (review lesson: production-shaped inputs).

No network, no DB: DB reads are exercised via the injectable ``rows`` lists,
the broker via a stub, Hindsight via an overridden ``_post`` transport.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from services.trader.execution.alpaca_broker import AlpacaBrokerClient
from services.trader.execution.model import Position
from services.trader.ops.attribution import AttributionReport
from services.trader.ops.dashboard_data import (
    FLEET_COLUMNS,
    ORDERS_COLUMNS,
    PNL_COLUMNS,
    POSITIONS_COLUMNS,
    DashboardData,
)
from services.trader.ops.halt import HaltControl
from services.trader.training.hindsight_client import HindsightClient

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATIONS = _REPO_ROOT / "infra" / "postgres" / "migrations"


# ------------------------------------------------------- production-shaped rows


def _position_row(ticker: str = "SPY") -> dict[str, Any]:
    """One trades.positions row (007_trades.sql column names)."""
    return {
        "ticker": ticker,
        "qty": 10.0,
        "avg_entry": 500.0,
        "market_value": 5100.0,
        "unrealized_pl": 100.0,
    }


def _order_row(ts: str, ticker: str, side: str, qty: float, price: float) -> dict[str, Any]:
    """One trades.orders row (007_trades.sql column names)."""
    return {
        "ts": pd.Timestamp(ts),
        "ticker": ticker,
        "side": side,
        "qty": float(qty),
        "filled_qty": float(qty),
        "status": "FILLED",
        "filled_avg_price": float(price),
        "reason": "firewall: all limits passed",
    }


def _iteration_row(ts: str, iteration: int) -> dict[str, Any]:
    """One experiments.iterations row (005_experiments.sql + 006 fitness)."""
    return {
        "ts": pd.Timestamp(ts),
        "run_id": "fleet-nightly-seed7-1751000000",
        "iteration": iteration,
        "train_sharpe": 1.2,
        "fitness": 1.1,
        "promoted": True,
        "is_best": iteration == 2,
        "reason": "fortress: passed all gates",
    }


def _pnl_row(d: str, equity: float) -> dict[str, Any]:
    """One trades.pnl_daily row (007_trades.sql column names)."""
    return {
        "d": pd.Timestamp(d).date(),
        "equity": equity,
        "realized_pl": 25.0,
        "unrealized_pl": -5.0,
    }


# ----------------------------------------------------------------- positions


def test_positions_from_injected_rows() -> None:
    frame = DashboardData().positions(rows=[_position_row("SPY"), _position_row("QQQ")])
    assert list(frame.columns) == list(POSITIONS_COLUMNS)
    assert len(frame) == 2
    assert set(frame["ticker"]) == {"SPY", "QQQ"}
    assert frame.loc[frame["ticker"] == "SPY", "unrealized_pl"].iloc[0] == 100.0


def test_positions_prefers_enabled_broker() -> None:
    class _StubBroker:
        def is_enabled(self) -> bool:
            return True

        def positions(self) -> dict[str, Position]:
            return {
                "AAPL": Position(
                    ticker="AAPL",
                    qty=3.0,
                    avg_entry=200.0,
                    market_value=630.0,
                    unrealized_pl=30.0,
                )
            }

    frame = DashboardData(broker=_StubBroker()).positions(rows=[_position_row("SPY")])
    assert list(frame.columns) == list(POSITIONS_COLUMNS)
    assert list(frame["ticker"]) == ["AAPL"]  # broker wins over the DB snapshot
    assert frame["market_value"].iloc[0] == 630.0


def test_positions_disabled_broker_falls_back_to_rows() -> None:
    broker = AlpacaBrokerClient()  # no key -> disabled
    assert not broker.is_enabled()
    frame = DashboardData(broker=broker).positions(rows=[_position_row("SPY")])
    assert list(frame["ticker"]) == ["SPY"]


# -------------------------------------------------------------- recent_orders


def test_recent_orders_newest_first_with_limit() -> None:
    rows = [
        _order_row("2026-06-01", "SPY", "BUY", 10, 500.0),
        _order_row("2026-06-03", "SPY", "SELL", 10, 505.0),
        _order_row("2026-06-02", "QQQ", "BUY", 5, 400.0),
    ]
    frame = DashboardData().recent_orders(limit=2, rows=rows)
    assert list(frame.columns) == list(ORDERS_COLUMNS)
    assert len(frame) == 2
    assert list(frame["ts"]) == [pd.Timestamp("2026-06-03"), pd.Timestamp("2026-06-02")]


# ------------------------------------------------------------- fleet_activity


def test_fleet_activity_newest_first_with_limit() -> None:
    rows = [_iteration_row("2026-06-01", 1), _iteration_row("2026-06-02", 2)]
    frame = DashboardData().fleet_activity(limit=1, rows=rows)
    assert list(frame.columns) == list(FLEET_COLUMNS)
    assert len(frame) == 1
    assert frame["iteration"].iloc[0] == 2
    assert bool(frame["is_best"].iloc[0]) is True


# ----------------------------------------------------------------- pnl_series


def test_pnl_series_ordered_by_date() -> None:
    rows = [_pnl_row("2026-06-02", 100500.0), _pnl_row("2026-06-01", 100000.0)]
    frame = DashboardData().pnl_series(rows=rows)
    assert list(frame.columns) == list(PNL_COLUMNS)
    assert list(frame["equity"]) == [100000.0, 100500.0]  # ascending by d


# ----------------------------------------------------------------- regime_now


def test_regime_now_labels_from_synthetic_parquet(tmp_path: Path) -> None:
    """With SPY OHLCV parquet present, the real MESO detector labels the last bar."""
    rng = np.random.default_rng(7)
    n = 420
    ts = pd.bdate_range("2024-01-02", periods=n, tz="UTC")
    close = 500.0 + np.cumsum(rng.normal(0.2, 2.0, n))
    frame = pd.DataFrame(
        {
            "bar_timestamp": ts,
            "open": close - 0.5,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "adj_close": close,
            "volume": 1_000_000.0,
        }
    )
    frame.to_parquet(tmp_path / "spy_2024.parquet")

    dd = DashboardData()
    dd._spy_parquet_dir = tmp_path
    result = dd.regime_now()
    assert set(result) == {"label", "asof"}
    assert isinstance(result["label"], str) and result["label"]
    assert result["asof"].startswith("2025")  # last synthetic business day


def test_regime_now_no_parquet_returns_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    dd = DashboardData()
    dd._spy_parquet_dir = tmp_path / "missing"
    with caplog.at_level(logging.WARNING):
        assert dd.regime_now() == {}
    assert any("regime_now" in r.message for r in caplog.records)


# ------------------------------------------------------------------ kb_recent


def test_kb_recent_uses_hindsight_recall() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class _StubHindsight(HindsightClient):
        def _post(self, path: str, payload: dict) -> dict:
            calls.append((path, payload))
            return {"results": [{"content": "fact-1"}, {"content": "fact-2"}, {"content": "f3"}]}

    out = DashboardData(hindsight=_StubHindsight("http://hindsight:8888")).kb_recent(k=2)
    assert out == [{"content": "fact-1"}, {"content": "fact-2"}]
    assert calls[0][0].endswith("/memories/recall")
    assert calls[0][1] == {"query": "recent activity"}


def test_kb_recent_offline_returns_empty() -> None:
    assert DashboardData().kb_recent() == []
    assert DashboardData(hindsight=HindsightClient(None)).kb_recent() == []


# ---------------------------------------------------------------- attribution


def test_attribution_over_injected_orders() -> None:
    rows = [
        _order_row("2026-06-01", "SPY", "BUY", 10, 500.0),
        _order_row("2026-06-03", "SPY", "SELL", 10, 505.0),
    ]
    report = DashboardData().attribution(rows=rows)
    assert isinstance(report, AttributionReport)
    assert report.n_round_trips == 1
    assert report.total_pl == 50.0
    assert report.by_ticker == {"SPY": 50.0}


# ---------------------------------------------------------------- halt_status


def test_halt_status_flips_with_halt_control(tmp_path: Path) -> None:
    halt = HaltControl(tmp_path / "halt.flag")
    dd = DashboardData(halt=halt)
    assert dd.halt_status() == {"halted": False, "reason": None}
    halt.halt("dashboard operator halt")
    assert dd.halt_status() == {"halted": True, "reason": "dashboard operator halt"}
    halt.resume()
    assert dd.halt_status() == {"halted": False, "reason": None}


# ------------------------------------------------------- graceful-offline (all-None)


def test_all_none_constructor_is_empty_but_typed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """dsn/broker/hindsight all None: every panel returns its empty typed shape,
    nothing raises, and the no-DSN degradation warns exactly ONCE."""
    dd = DashboardData(halt=HaltControl(tmp_path / "halt.flag"))
    dd._spy_parquet_dir = tmp_path / "no-parquet"
    with caplog.at_level(logging.WARNING):
        positions = dd.positions()
        orders = dd.recent_orders()
        fleet = dd.fleet_activity()
        pnl = dd.pnl_series()
        regime = dd.regime_now()
        kb = dd.kb_recent()
        report = dd.attribution()
        status = dd.halt_status()

    assert positions.empty and list(positions.columns) == list(POSITIONS_COLUMNS)
    assert orders.empty and list(orders.columns) == list(ORDERS_COLUMNS)
    assert fleet.empty and list(fleet.columns) == list(FLEET_COLUMNS)
    assert pnl.empty and list(pnl.columns) == list(PNL_COLUMNS)
    assert regime == {}
    assert kb == []
    assert report == AttributionReport()
    assert status == {"halted": False, "reason": None}

    no_dsn = [r for r in caplog.records if "no DSN" in r.message]
    assert len(no_dsn) == 1  # one-time warning across all DB-backed panels


# ------------------------------------------------------------- DDL cross-check


def test_sql_columns_appear_in_migration_ddl() -> None:
    """Every column each panel SQL selects must exist in the real migration DDL
    (trades.* in 007; experiments.iterations in 005 + the 006 fitness ALTER)."""
    trades_ddl = (_MIGRATIONS / "007_trades.sql").read_text(encoding="utf-8")
    for column in (*POSITIONS_COLUMNS, *ORDERS_COLUMNS, *PNL_COLUMNS):
        assert column in trades_ddl, f"column {column!r} not found in 007_trades.sql"

    experiments_ddl = (_MIGRATIONS / "005_experiments.sql").read_text(encoding="utf-8") + (
        _MIGRATIONS / "006_master_pointer.sql"
    ).read_text(encoding="utf-8")
    for column in FLEET_COLUMNS:
        assert column in experiments_ddl, f"column {column!r} not found in 005/006 DDL"


def test_sql_targets_production_tables() -> None:
    from services.trader.ops import dashboard_data as mod

    assert "trades.positions" in mod._POSITIONS_SQL
    assert "trades.orders" in mod._ORDERS_SQL
    assert "experiments.iterations" in mod._FLEET_SQL
    assert "trades.pnl_daily" in mod._PNL_SQL
    # The SQL select lists are BUILT from the exported column tuples, so the
    # DDL cross-check above covers exactly what runs in production.
    for column in ORDERS_COLUMNS:
        assert column in mod._ORDERS_SQL
    for column in FLEET_COLUMNS:
        assert column in mod._FLEET_SQL
