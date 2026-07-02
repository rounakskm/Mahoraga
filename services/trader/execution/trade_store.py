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

from services.trader.execution.model import Order, Portfolio


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

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> TradeStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
