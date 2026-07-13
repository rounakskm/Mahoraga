"""Trades persistence (Phase 5, Task 11) — write orders/fills/positions to `trades.*`.

Mirrors the Phase-3 `ProvenanceWriter` graceful-no-DSN idiom: lazy `psycopg`,
`dsn=None` makes every method a safe no-op (no import, no connection, no raise).
Transactional trade state lives in Postgres (not Hindsight) because
reconciliation / tax / regulatory reporting need exact tabular queries.

Schema: `infra/postgres/migrations/007_trades.sql`
(`trades.orders`, `trades.fills`, `trades.positions`, `trades.pnl_daily`).
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from services.trader.execution.compliance import TradeRecord
from services.trader.execution.model import Order, Portfolio, Position, Side


def _pl_pct(baseline: float, end: float) -> float | None:
    """Fractional return `(end - baseline) / baseline`; None when baseline <= 0."""
    if baseline <= 0:
        return None
    return (end - baseline) / baseline


class TradeStore:
    """Persist orders/fills/positions/pnl to `trades.*`; no-op without a DSN."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn
        self._conn = None

    def is_enabled(self) -> bool:
        return self.dsn is not None

    def _conn_for_test(self):  # noqa: ANN202 (test helper returning a psycopg conn)
        """Return the live connection (opening it if needed). Used by tests."""
        return self._get_conn()

    def _get_conn(self):  # noqa: ANN202
        if self._conn is None:
            import psycopg  # noqa: PLC0415 (lazy: only when a DSN is set)

            self._conn = psycopg.connect(self.dsn, autocommit=True)
        return self._conn

    def record_order(self, order: Order, reason: str) -> int | None:
        """INSERT an order into `trades.orders`; return the new id (None if disabled)."""
        if self.dsn is None:
            return None
        row = self._get_conn().execute(
            "INSERT INTO trades.orders "
            "(ticker, side, qty, order_type, limit_price, stop_price, status, "
            " broker_order_id, reason, filled_qty, filled_avg_price) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (
                order.ticker,
                str(order.side),
                order.qty,
                str(order.order_type),
                order.limit_price,
                order.stop_price,
                str(order.status),
                order.id,
                reason,
                order.filled_qty,
                order.filled_avg_price,
            ),
        ).fetchone()
        return int(row[0])

    def record_fill(self, order_id: int, qty: float, price: float) -> None:
        """INSERT an execution against an order into `trades.fills`."""
        if self.dsn is None:
            return
        self._get_conn().execute(
            "INSERT INTO trades.fills (order_id, qty, price) VALUES (%s,%s,%s)",
            (order_id, qty, price),
        )

    def snapshot_positions(self, portfolio: Portfolio) -> None:
        """INSERT one `trades.positions` row per open position."""
        if self.dsn is None:
            return
        conn = self._get_conn()
        for pos in portfolio.positions.values():
            conn.execute(
                "INSERT INTO trades.positions "
                "(ticker, qty, avg_entry, market_value, unrealized_pl) "
                "VALUES (%s,%s,%s,%s,%s)",
                (
                    pos.ticker,
                    pos.qty,
                    pos.avg_entry,
                    pos.market_value,
                    pos.unrealized_pl,
                ),
            )

    def recent_trades(self, days: int = 35) -> list[TradeRecord]:
        """Best-effort trade history for the compliance engine (PDT / wash-sale).

        Derivation — deliberately simple and documented (C3):
          * Rows: FILLED/PARTIAL `trades.orders` with a positive `filled_qty`
            inside the trailing `days` window, oldest first.
          * `realized_pl`: running average-cost basis per ticker WITHIN the
            window — a SELL realizes `(fill_price - avg_cost) * matched_qty`
            against BUY fills seen earlier in the window; with no in-window
            basis (position opened before the window) it is 0.0. Good enough
            for wash-sale loss detection on recent round-trips; exact tax lots
            live with the ops/pnl wiring.
          * `is_day_trade`: the ticker has BOTH a BUY and a SELL fill on that
            calendar date.

        Returns [] when the store is disabled (no DSN).
        """
        if self.dsn is None:
            return []
        rows = self._get_conn().execute(
            "SELECT ticker, side, ts, filled_qty, filled_avg_price "
            "FROM trades.orders "
            "WHERE status IN ('FILLED','PARTIAL') AND filled_qty > 0 "
            "AND ts >= NOW() - make_interval(days => %s) "
            "ORDER BY ts",
            (days,),
        ).fetchall()

        # Pass 1: which (ticker, date) pairs saw both sides -> day trades.
        sides_by_day: dict[tuple[str, dt.date], set[str]] = {}
        for ticker, side, ts, _qty, _price in rows:
            sides_by_day.setdefault((ticker, ts.date()), set()).add(side)

        # Pass 2: running average-cost basis per ticker for realized P&L.
        basis: dict[str, tuple[float, float]] = {}  # ticker -> (qty, cost)
        records: list[TradeRecord] = []
        for ticker, side, ts, qty, price in rows:
            fill_price = float(price or 0.0)
            realized = 0.0
            held_qty, held_cost = basis.get(ticker, (0.0, 0.0))
            if side == str(Side.BUY):
                basis[ticker] = (held_qty + qty, held_cost + qty * fill_price)
            elif held_qty > 0:
                avg_cost = held_cost / held_qty
                matched = min(qty, held_qty)
                realized = (fill_price - avg_cost) * matched
                basis[ticker] = (held_qty - matched, held_cost - avg_cost * matched)
            records.append(
                TradeRecord(
                    ticker=ticker,
                    side=Side(side),
                    ts=pd.Timestamp(ts),
                    realized_pl=realized,
                    is_day_trade=sides_by_day[(ticker, ts.date())]
                    >= {str(Side.BUY), str(Side.SELL)},
                )
            )
        return records

    def tickers_ordered_since_snapshot(self) -> frozenset[str]:
        """Tickers with orders recorded AFTER the latest position snapshot.

        These explain a broker-vs-snapshot divergence (an entry submitted after
        yesterday's snapshot filled at today's open), so the reconciler treats
        them as explained rather than halting. Disabled/no orders -> empty set.
        """
        if not self.is_enabled():
            return frozenset()
        rows = self._get_conn().execute(
            "SELECT DISTINCT ticker FROM trades.orders "
            "WHERE ts > COALESCE((SELECT MAX(ts) FROM trades.positions), 'epoch')"
        ).fetchall()
        return frozenset(r[0] for r in rows)

    def latest_positions(self, max_age_hours: float = 24.0) -> dict[str, Position] | None:
        """Positions from the most recent `trades.positions` snapshot batch.

        `snapshot_positions` inserts one row per position with per-statement
        timestamps, so a "batch" is every row within 60s of the max ts (newest
        row per ticker wins). Returns None when the store is disabled, no
        snapshot exists, or the newest snapshot is older than `max_age_hours` —
        a stale local book must not be reconciled as if it were current.
        """
        if self.dsn is None:
            return None
        conn = self._get_conn()
        row = conn.execute("SELECT MAX(ts) FROM trades.positions").fetchone()
        if row is None or row[0] is None:
            return None
        newest: dt.datetime = row[0]
        if dt.datetime.now(dt.UTC) - newest > dt.timedelta(hours=max_age_hours):
            return None
        rows = conn.execute(
            "SELECT DISTINCT ON (ticker) ticker, qty, avg_entry, market_value, unrealized_pl "
            "FROM trades.positions "
            "WHERE ts >= %s::timestamptz - interval '60 seconds' "
            "ORDER BY ticker, ts DESC",
            (newest,),
        ).fetchall()
        return {
            ticker: Position(
                ticker=ticker,
                qty=float(qty),
                avg_entry=float(avg_entry),
                market_value=float(market_value),
                unrealized_pl=float(unrealized_pl),
            )
            for ticker, qty, avg_entry, market_value, unrealized_pl in rows
        }

    def record_daily_pnl(
        self,
        d: dt.date,
        equity: float,
        realized: float,
        unrealized: float,
    ) -> None:
        """UPSERT the date-keyed daily equity / P&L row in `trades.pnl_daily`."""
        if self.dsn is None:
            return
        self._get_conn().execute(
            "INSERT INTO trades.pnl_daily (d, equity, realized_pl, unrealized_pl) "
            "VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (d) DO UPDATE SET "
            "equity = EXCLUDED.equity, "
            "realized_pl = EXCLUDED.realized_pl, "
            "unrealized_pl = EXCLUDED.unrealized_pl",
            (d, equity, realized, unrealized),
        )

    def monthly_pl_pct(
        self, window_days: int = 30, *, current_equity: float | None = None
    ) -> float | None:
        """Trailing-`window_days` P&L fraction from `trades.pnl_daily`.

        This is the monthly P&L feeding the CLAUDE.md 10% monthly-catastrophic
        halt in the hard-limit firewall. Baseline = the OLDEST equity row
        within the trailing window; endpoint = `current_equity` when given
        (the live account equity mid-cycle), else the NEWEST in-window row.

        Returns None when the store is disabled, the window holds no rows, or
        the baseline equity is <= 0. Fail-safe direction: None -> 0.0 plus a
        WARNING inside `build_firewall_context` (unchanged), so a missing
        store degrades loudly, not silently.

        `d` is a DATE column and `CURRENT_DATE - %s` (date - integer) is
        evaluated server-side in the Postgres session's date — the filter has
        no client/server timezone pitfalls.
        """
        if self.dsn is None:
            return None
        conn = self._get_conn()
        oldest = conn.execute(
            "SELECT equity FROM trades.pnl_daily "
            "WHERE d >= CURRENT_DATE - %s ORDER BY d ASC LIMIT 1",
            (window_days,),
        ).fetchone()
        if oldest is None:
            return None
        baseline = float(oldest[0])
        if current_equity is not None:
            end = float(current_equity)
        else:
            newest = conn.execute(
                "SELECT equity FROM trades.pnl_daily "
                "WHERE d >= CURRENT_DATE - %s ORDER BY d DESC LIMIT 1",
                (window_days,),
            ).fetchone()
            if newest is None:  # pragma: no cover — oldest exists, so newest must
                return None
            end = float(newest[0])
        return _pl_pct(baseline, end)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> TradeStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
