"""Paper-stats bridge tests (trades.pnl_daily -> days + Sharpe -> convergence).

Fixtures use the REAL production column names from
``infra/postgres/migrations/007_trades.sql`` (``d``, ``equity``,
``realized_pl``, ``unrealized_pl``); a cross-check test asserts every column
the module SELECTs appears in the migration DDL text (review lesson:
production-shaped inputs).

No network, no DB: the DB read is exercised via the injectable ``rows`` list;
the ``dsn=None`` path is asserted to fail closed (days=0 fails the
``paper_window`` criterion). The round-trip test imports the REAL
``scripts/convergence_report.py`` reader so the JSON contract can never drift.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import statistics
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from services.trader.ops.paper_stats import (
    PNL_DAILY_COLUMNS,
    PaperStats,
    compute_paper_stats,
    gather_paper_stats,
    to_json,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DDL_PATH = _REPO_ROOT / "infra" / "postgres" / "migrations" / "007_trades.sql"


def _pnl_row(d: str, equity: float) -> dict[str, Any]:
    """One trades.pnl_daily row (007_trades.sql column names)."""
    return {
        "d": dt.date.fromisoformat(d),
        "equity": equity,
        "realized_pl": 25.0,
        "unrealized_pl": -5.0,
    }


def _uptrend_rows(n: int = 31, start_equity: float = 100_000.0) -> list[dict[str, Any]]:
    """`n` fabricated pnl_daily rows with a gentle, non-constant uptrend
    (alternating +0.1% / +0.2% daily returns so the std is non-zero)."""
    rows: list[dict[str, Any]] = []
    equity = start_equity
    day = dt.date(2026, 6, 1)
    for i in range(n):
        rows.append(_pnl_row(day.isoformat(), equity))
        equity *= 1.001 if i % 2 == 0 else 1.002
        day += dt.timedelta(days=1)
    return rows


# ---------------------------------------------------------- compute_paper_stats


def test_uptrend_31_rows() -> None:
    stats = compute_paper_stats(_uptrend_rows(31))
    assert stats.days == 31
    assert stats.sharpe is not None and stats.sharpe > 0
    assert stats.start == "2026-06-01"
    assert stats.end == "2026-07-01"
    assert stats.total_return_pct is not None and stats.total_return_pct > 0


def test_tiny_three_row_hand_check() -> None:
    """Hand-checked exact value on 3 rows.

    equity 100 -> 101 -> 103.02 gives daily returns [0.01, 0.02]:
      mean = 0.015
      sample std (ddof=1) = sqrt(((0.01-0.015)^2 + (0.02-0.015)^2) / 1)
                          = sqrt(5e-05) = 0.0070710678...
      sharpe = 0.015 / 0.0070710678 * sqrt(252) = 2.1213203... * 15.8745078...
             = 33.6749...
    """
    rows = [
        _pnl_row("2026-06-01", 100.0),
        _pnl_row("2026-06-02", 101.0),
        _pnl_row("2026-06-03", 103.02),
    ]
    stats = compute_paper_stats(rows)
    assert stats.days == 3
    expected = (0.015 / math.sqrt(5e-05)) * math.sqrt(252)
    assert expected == pytest.approx(33.674916, abs=1e-4)  # the hand-check literal
    assert stats.sharpe == pytest.approx(expected, rel=1e-9)
    # cross-check against the stats library on the same returns
    returns = [101.0 / 100.0 - 1.0, 103.02 / 101.0 - 1.0]
    assert stats.sharpe == pytest.approx(
        statistics.mean(returns) / statistics.stdev(returns) * math.sqrt(252)
    )
    assert stats.total_return_pct == pytest.approx(3.02)
    assert stats.start == "2026-06-01"
    assert stats.end == "2026-06-03"


def test_flat_equity_sharpe_is_none() -> None:
    """Documented choice: zero-std (flat equity) -> sharpe None, NOT 0.
    None means "unmeasurable" and fails the convergence criterion closed;
    a fabricated 0.0 would look like a measured (bad) Sharpe."""
    rows = [_pnl_row(f"2026-06-{i:02d}", 100_000.0) for i in range(1, 11)]
    stats = compute_paper_stats(rows)
    assert stats.days == 10
    assert stats.sharpe is None
    assert stats.total_return_pct == pytest.approx(0.0)


def test_fewer_than_two_rows_sharpe_none() -> None:
    empty = compute_paper_stats([])
    assert empty == PaperStats(days=0, sharpe=None, start=None, end=None, total_return_pct=None)

    one = compute_paper_stats([_pnl_row("2026-06-01", 100_000.0)])
    assert one.days == 1
    assert one.sharpe is None
    assert one.start == one.end == "2026-06-01"
    assert one.total_return_pct == pytest.approx(0.0)


def test_two_rows_single_return_sharpe_none() -> None:
    """One daily return has no sample std (ddof=1) -> sharpe stays None."""
    stats = compute_paper_stats(
        [_pnl_row("2026-06-01", 100.0), _pnl_row("2026-06-02", 101.0)]
    )
    assert stats.days == 2
    assert stats.sharpe is None
    assert stats.total_return_pct == pytest.approx(1.0)


# ----------------------------------------------------------- gather_paper_stats


def test_gather_no_dsn_fails_closed() -> None:
    """dsn=None -> empty stats (days=0 fails the paper_window criterion)."""
    stats = gather_paper_stats(None)
    assert stats == PaperStats(days=0, sharpe=None, start=None, end=None, total_return_pct=None)


def test_gather_with_injected_rows() -> None:
    stats = gather_paper_stats(None, rows=_uptrend_rows(31))
    assert stats.days == 31
    assert stats.sharpe is not None and stats.sharpe > 0


def test_gather_bad_dsn_fails_closed() -> None:
    """A DB failure must degrade to empty stats, never raise."""
    stats = gather_paper_stats("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")
    assert stats.days == 0
    assert stats.sharpe is None


def test_pnl_daily_columns_match_migration_ddl() -> None:
    """Every column the module SELECTs exists in 007_trades.sql (review lesson:
    the SQL is bound to production column names, not fixture conventions)."""
    ddl = _DDL_PATH.read_text(encoding="utf-8")
    assert "trades.pnl_daily" in ddl
    for column in PNL_DAILY_COLUMNS:
        assert column in ddl, f"column {column!r} not found in 007_trades.sql"


# ------------------------------------------------------------ to_json contract


def _load_convergence_report_script() -> ModuleType:
    """Import scripts/convergence_report.py as a module (it is not a package)."""
    path = _REPO_ROOT / "scripts" / "convergence_report.py"
    spec = importlib.util.spec_from_file_location("convergence_report_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_to_json_round_trips_through_convergence_reader(tmp_path: Path) -> None:
    """to_json output, written to disk, must parse to the SAME (days, sharpe)
    through the real `scripts/convergence_report.py::_gather_paper_stats`."""
    stats = compute_paper_stats(_uptrend_rows(31))
    payload = to_json(stats)
    path = tmp_path / "paper.json"
    path.write_text(json.dumps(payload))

    script = _load_convergence_report_script()
    days, sharpe = script._gather_paper_stats(str(path))
    assert days == stats.days == 31
    assert sharpe == pytest.approx(stats.sharpe)


def test_to_json_omits_none_sharpe_for_reader_compat(tmp_path: Path) -> None:
    """The script reader does `float(stats["sharpe"]) if "sharpe" in stats`,
    so a JSON null sharpe would raise and drop BOTH values. to_json must omit
    the key instead, preserving days through the reader."""
    stats = compute_paper_stats([_pnl_row("2026-06-01", 100_000.0)])
    payload = to_json(stats)
    assert "sharpe" not in payload
    assert payload["days"] == 1

    path = tmp_path / "paper.json"
    path.write_text(json.dumps(payload))
    script = _load_convergence_report_script()
    days, sharpe = script._gather_paper_stats(str(path))
    assert days == 1
    assert sharpe is None


# ------------------------------------------------- script resolution precedence


def test_script_explicit_file_wins_over_dsn(tmp_path: Path) -> None:
    """--paper-stats wins even when a DSN is set (no DB is touched)."""
    path = tmp_path / "paper.json"
    path.write_text(json.dumps({"days": 42, "sharpe": 1.5}))
    script = _load_convergence_report_script()
    days, sharpe = script._resolve_paper_stats(str(path), "postgresql://would-not-connect/db")
    assert days == 42
    assert sharpe == pytest.approx(1.5)


def test_script_no_file_no_dsn_fails_closed() -> None:
    """Unchanged fail-closed behaviour: nothing to read -> unmeasured."""
    script = _load_convergence_report_script()
    assert script._resolve_paper_stats(None, None) == (None, None)
