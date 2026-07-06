"""DashboardData — the pure panel data layer for the ops dashboard (Phase-6 Task 5).

One method per dashboard panel, all graceful-offline (the load-bearing repo
contract): every degraded path logs ONE warning and returns its empty typed
shape — an all-`None` constructor never raises. Every DB read takes an
injectable ``rows`` list for tests AND carries real SQL bound to the
production column names (``infra/postgres/migrations/007_trades.sql`` for
``trades.*``, ``005_experiments.sql`` + the ``006_master_pointer.sql``
``fitness`` ALTER for ``experiments.iterations``); the test suite cross-checks
the exported column tuples against the migration DDL text (review lesson).

Sources per panel:
    positions       broker (`AlpacaBrokerClient.positions()`) when enabled,
                    else the latest `trades.positions` snapshot batch
                    (mirrors `TradeStore.latest_positions`'s 60s-batch rule)
    recent_orders   `trades.orders` newest-first (includes `filled_qty` so
                    `attribution()` can pair fills FIFO)
    fleet_activity  `experiments.iterations` newest-first
    pnl_series      `trades.pnl_daily` ordered by `d`
    regime_now      latest MESO label from the Phase-1 SPY parquet store
    kb_recent       Hindsight `recall` (bank `mahoraga-trader`)
    attribution     `ops.attribution.attribute` over `recent_orders(limit=500)`
    halt_status     `HaltControl` state + reason

No streamlit here — the UI shell (Task 6) stays thin; this module is plain
data. Lazy imports (psycopg, the regime detector + parquet engine) keep the
module importable in environments without those extras.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from services.trader.ops.attribution import AttributionReport, attribute
from services.trader.ops.halt import HaltControl

logger = logging.getLogger(__name__)

# dashboard_data.py lives at <repo>/services/trader/ops/, so parents[3] is the
# repo root (same anchoring as halt.py — never the cwd).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SPY_PARQUET_DIR = _REPO_ROOT / "data" / "parquet" / "ohlcv" / "SPY"

# ~400 bars: comfortably past the MESO warmup (adx_14 + realized_vol_pct_60's
# 60-bar window) so the LAST bar always carries a real quadrant label.
_REGIME_BARS = 400

# Column tuples each panel SELECTs — exported so the DDL cross-check test can
# assert them against the migration files, and interpolated into the SQL below
# so the check covers exactly what runs in production.
POSITIONS_COLUMNS: tuple[str, ...] = ("ticker", "qty", "avg_entry", "market_value", "unrealized_pl")
ORDERS_COLUMNS: tuple[str, ...] = (
    "ts",
    "ticker",
    "side",
    "qty",
    "filled_qty",
    "status",
    "filled_avg_price",
    "reason",
)
FLEET_COLUMNS: tuple[str, ...] = (
    "ts",
    "run_id",
    "iteration",
    "train_sharpe",
    "fitness",
    "promoted",
    "is_best",
    "reason",
)
PNL_COLUMNS: tuple[str, ...] = ("d", "equity", "realized_pl", "unrealized_pl")

# Latest snapshot batch = every row within 60s of MAX(ts), newest per ticker —
# the same batch rule as TradeStore.latest_positions (snapshot_positions inserts
# one row per position with per-statement timestamps).
_POSITIONS_SQL = (
    f"SELECT DISTINCT ON (ticker) {', '.join(POSITIONS_COLUMNS)} "
    "FROM trades.positions "
    "WHERE ts >= (SELECT MAX(ts) FROM trades.positions) - interval '60 seconds' "
    "ORDER BY ticker, ts DESC"
)
_ORDERS_SQL = f"SELECT {', '.join(ORDERS_COLUMNS)} FROM trades.orders ORDER BY ts DESC LIMIT %s"
_FLEET_SQL = (
    f"SELECT {', '.join(FLEET_COLUMNS)} FROM experiments.iterations ORDER BY ts DESC LIMIT %s"
)
_PNL_SQL = f"SELECT {', '.join(PNL_COLUMNS)} FROM trades.pnl_daily ORDER BY d"


class DashboardData:
    """Pure data source for the ops dashboard; every panel degrades gracefully."""

    def __init__(
        self,
        dsn: str | None = None,
        broker: Any | None = None,
        hindsight: Any | None = None,
        halt: HaltControl | None = None,
    ) -> None:
        self.dsn = dsn
        self.broker = broker
        self.hindsight = hindsight
        self.halt = halt if halt is not None else HaltControl()
        self._spy_parquet_dir = _SPY_PARQUET_DIR
        self._warned: set[str] = set()

    # ------------------------------------------------------------------ panels

    def positions(self, rows: list[dict[str, Any]] | None = None) -> pd.DataFrame:
        """Open positions: the broker's live view when enabled, else the latest
        `trades.positions` snapshot batch. Empty typed frame offline."""
        if self.broker is not None and self.broker.is_enabled():
            held = self.broker.positions()
            return _frame(
                [
                    {
                        "ticker": p.ticker,
                        "qty": p.qty,
                        "avg_entry": p.avg_entry,
                        "market_value": p.market_value,
                        "unrealized_pl": p.unrealized_pl,
                    }
                    for p in held.values()
                ],
                POSITIONS_COLUMNS,
            )
        if rows is None:
            rows = self._fetch(_POSITIONS_SQL)
        return _frame(rows, POSITIONS_COLUMNS)

    def recent_orders(
        self, limit: int = 50, rows: list[dict[str, Any]] | None = None
    ) -> pd.DataFrame:
        """`trades.orders` newest-first (up to `limit` rows)."""
        if rows is None:
            rows = self._fetch(_ORDERS_SQL, (limit,))
        return _newest_first(_frame(rows, ORDERS_COLUMNS), "ts", limit)

    def fleet_activity(
        self, limit: int = 100, rows: list[dict[str, Any]] | None = None
    ) -> pd.DataFrame:
        """`experiments.iterations` newest-first (up to `limit` rows)."""
        if rows is None:
            rows = self._fetch(_FLEET_SQL, (limit,))
        return _newest_first(_frame(rows, FLEET_COLUMNS), "ts", limit)

    def pnl_series(self, rows: list[dict[str, Any]] | None = None) -> pd.DataFrame:
        """`trades.pnl_daily` ordered by `d` ascending (chart-ready)."""
        if rows is None:
            rows = self._fetch(_PNL_SQL)
        frame = _frame(rows, PNL_COLUMNS)
        if frame.empty:
            return frame
        return frame.sort_values("d", kind="stable").reset_index(drop=True)

    def regime_now(self) -> dict[str, str]:
        """Latest MESO regime label from the Phase-1 SPY parquet store.

        Loads the parquet exactly like `scripts/run_autoresearch.py::load_spy`
        (concat files, sort + index on `bar_timestamp`), labels the last
        `_REGIME_BARS` bars via the real detector, and returns
        `{"label": ..., "asof": ...}`. No parquet (or a failed compute) ->
        `{}` with a one-time warning. Heavy imports stay lazy."""
        files = sorted(self._spy_parquet_dir.glob("*.parquet"))
        if not files:
            self._warn_once(
                "regime",
                f"regime_now: no SPY parquet under {self._spy_parquet_dir} — returning {{}}",
            )
            return {}
        try:
            # Lazy: the detector pulls in the Phase-1 feature stack, and
            # read_parquet needs the pyarrow engine.
            from services.trader.training.regime import meso_regimes  # noqa: PLC0415

            ohlcv = pd.concat(pd.read_parquet(f) for f in files).sort_values("bar_timestamp")
            ohlcv.index = pd.to_datetime(ohlcv["bar_timestamp"])
            labels = meso_regimes(ohlcv.tail(_REGIME_BARS))
        except Exception as exc:  # degraded data must never blank the dashboard
            self._warn_once("regime", f"regime_now: detector failed — returning {{}}: {exc}")
            return {}
        return {
            "label": str(labels.iloc[-1]),
            "asof": pd.Timestamp(labels.index[-1]).isoformat(),
        }

    def kb_recent(self, k: int = 10) -> list[dict]:
        """Up to `k` Hindsight recall hits for "recent activity"; [] offline."""
        if self.hindsight is None or not self.hindsight.is_enabled():
            self._warn_once("hindsight", "kb_recent: no Hindsight client — returning []")
            return []
        return self.hindsight.recall("recent activity", k)

    def attribution(self, rows: list[dict[str, Any]] | None = None) -> AttributionReport:
        """Realized-P&L attribution over the recent order flow (Task 2 engine)."""
        return attribute(self.recent_orders(limit=500, rows=rows))

    def halt_status(self) -> dict[str, Any]:
        """Kill-switch state: `{"halted": bool, "reason": str | None}`."""
        return {"halted": self.halt.is_halted(), "reason": self.halt.reason()}

    # -------------------------------------------------------------------- SQL

    def _fetch(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Run `sql` and return dict rows; `dsn=None` -> [] with a ONE-TIME
        warning (mirrors trade_store.py's graceful-no-DSN idiom)."""
        if self.dsn is None:
            self._warn_once(
                "dsn", "no DSN configured — DB-backed panels return empty (set MAHORAGA_DSN)"
            )
            return []
        import psycopg  # noqa: PLC0415 (lazy: only when a DSN is set)
        from psycopg.rows import dict_row  # noqa: PLC0415

        with (
            psycopg.connect(self.dsn) as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            cur.execute(sql, params)
            return list(cur.fetchall())

    def _warn_once(self, key: str, message: str) -> None:
        """One warning per degraded path per instance; repeats stay quiet."""
        if key not in self._warned:
            self._warned.add(key)
            logger.warning(message)


# --------------------------------------------------------------------- helpers


def _frame(rows: list[dict[str, Any]] | None, columns: tuple[str, ...]) -> pd.DataFrame:
    """Rows -> DataFrame with exactly `columns` (empty-but-typed when no rows)."""
    return pd.DataFrame(rows or [], columns=list(columns))


def _newest_first(frame: pd.DataFrame, ts_column: str, limit: int) -> pd.DataFrame:
    """Sort `frame` newest-first on `ts_column` and cap at `limit` rows —
    applied to injected rows too, so both paths return the same shape."""
    if frame.empty:
        return frame
    return (
        frame.sort_values(ts_column, ascending=False, kind="stable")
        .head(limit)
        .reset_index(drop=True)
    )
