"""Paper-stats bridge: trades.pnl_daily -> (days, Sharpe) -> convergence report.

Computes the two paper-trading gate inputs (`paper_days`, `paper_sharpe` on
`services.trader.ops.convergence.ConvergenceInputs`) from the Phase-5 daily
P&L journal instead of a hand-written ``--paper-stats`` JSON file.

Sharpe convention (documented, hand-checked in the tests):

    daily returns r_i = equity_i / equity_{i-1} - 1     (equity pct-change)
    sharpe        = mean(r) / stdev(r) * sqrt(252)

* ``stdev`` is the SAMPLE standard deviation (ddof=1) — the standard Sharpe
  estimator; it needs >=2 daily returns, i.e. >=3 pnl_daily rows.
* ``sqrt(252)`` annualizes a daily-return Sharpe: variance of iid daily
  returns scales linearly with time, so the ratio scales with the square root
  of the ~252 US-equity trading days per year. Risk-free rate assumed 0
  (paper account, ~1-month window — the rf term is noise at this horizon).
* ``sharpe`` is ``None`` (NOT 0) when it is unmeasurable — fewer than 2
  returns, or zero std (flat equity). ``None`` fails the convergence
  criterion closed; a fabricated 0.0 would masquerade as a measured value.

Follows the ``dashboard_data.py`` idiom: the DB read takes an injectable
``rows`` list for tests AND carries real SQL bound to the production column
names in ``infra/postgres/migrations/007_trades.sql`` (cross-checked by the
test suite); psycopg is imported lazily; every degraded path (no DSN, DB
down) returns the empty stats shape — days=0 fails the ``paper_window``
criterion, so convergence stays fail-closed.
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ~252 US-equity trading days per year: the standard daily->annual Sharpe scale.
_TRADING_DAYS_PER_YEAR = 252

# Columns SELECTed from trades.pnl_daily — exported so the DDL cross-check test
# can assert them against 007_trades.sql, and interpolated into the SQL below
# so the check covers exactly what runs in production.
PNL_DAILY_COLUMNS: tuple[str, ...] = ("d", "equity", "realized_pl", "unrealized_pl")

_PNL_DAILY_SQL = f"SELECT {', '.join(PNL_DAILY_COLUMNS)} FROM trades.pnl_daily ORDER BY d"


@dataclass(frozen=True)
class PaperStats:
    """The paper-trading window measured from trades.pnl_daily."""

    days: int
    sharpe: float | None
    start: str | None
    end: str | None
    total_return_pct: float | None


_EMPTY = PaperStats(days=0, sharpe=None, start=None, end=None, total_return_pct=None)


def compute_paper_stats(rows: list[dict[str, Any]]) -> PaperStats:
    """Pure computation over pnl_daily-shaped dict rows (``d``, ``equity``,
    ``realized_pl``, ``unrealized_pl``) already in date order.

    ``days`` is the row count (one row per trading day journalled);
    ``sharpe`` follows the module-docstring convention (None when
    unmeasurable); ``total_return_pct`` is first->last equity in percent.
    """
    if not rows:
        return _EMPTY

    equities = [float(row["equity"]) for row in rows]
    returns = [
        curr / prev - 1.0 for prev, curr in zip(equities, equities[1:], strict=False) if prev != 0.0
    ]

    sharpe: float | None = None
    if len(returns) >= 2:  # sample std (ddof=1) needs >=2 returns, i.e. >=3 rows
        std = statistics.stdev(returns)
        if std > 0.0:  # flat equity -> unmeasurable, stays None (see module doc)
            sharpe = statistics.mean(returns) / std * math.sqrt(_TRADING_DAYS_PER_YEAR)

    total_return_pct: float | None = None
    if equities[0] != 0.0:
        total_return_pct = (equities[-1] / equities[0] - 1.0) * 100.0

    return PaperStats(
        days=len(rows),
        sharpe=sharpe,
        start=str(rows[0]["d"]),
        end=str(rows[-1]["d"]),
        total_return_pct=total_return_pct,
    )


def gather_paper_stats(dsn: str | None, rows: list[dict[str, Any]] | None = None) -> PaperStats:
    """Fetch ``trades.pnl_daily`` ordered by ``d`` and delegate to
    :func:`compute_paper_stats`.

    ``rows`` is injectable for tests (skips the DB entirely). ``dsn=None`` or
    any DB failure returns the empty stats shape — days=0 fails the
    convergence ``paper_window`` criterion, never raises (fail-closed)."""
    if rows is not None:
        return compute_paper_stats(rows)
    if not dsn:
        logger.warning("paper stats: no DSN — returning empty stats (criteria fail closed)")
        return _EMPTY
    try:
        import psycopg  # noqa: PLC0415 (lazy: only when a DSN is set)
        from psycopg.rows import dict_row  # noqa: PLC0415

        with (
            psycopg.connect(dsn, connect_timeout=5) as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            cur.execute(_PNL_DAILY_SQL)
            fetched = list(cur.fetchall())
    except Exception as exc:  # any DB failure -> unmeasured, never a crash
        logger.warning("paper stats: pnl_daily unavailable (%s); criteria fail closed", exc)
        return _EMPTY
    return compute_paper_stats(fetched)


def to_json(stats: PaperStats) -> dict[str, Any]:
    """The exact shape ``scripts/convergence_report.py::_gather_paper_stats``
    reads from a ``--paper-stats`` file: ``{"days": int, "sharpe": float}``
    plus informational extras the reader ignores.

    A ``None`` sharpe is OMITTED rather than serialized as JSON null: the
    reader does ``float(stats["sharpe"]) if "sharpe" in stats``, and
    ``float(None)`` would raise and drop BOTH values (days included)."""
    payload: dict[str, Any] = {
        "days": stats.days,
        "start": stats.start,
        "end": stats.end,
        "total_return_pct": stats.total_return_pct,
    }
    if stats.sharpe is not None:
        payload["sharpe"] = stats.sharpe
    return payload
