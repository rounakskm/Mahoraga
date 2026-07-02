"""DSN-gated round-trip test for the Phase-5 `trades.*` schema (007_trades.sql).

Skips locally (no MAHORAGA_DSN). CI integration-smoke applies the migration on a
fresh DB and runs this against it.
"""

import datetime as dt
import os
from collections.abc import Iterator

import psycopg
import pytest

DSN: str | None = os.environ.get("MAHORAGA_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="no MAHORAGA_DSN")


@pytest.fixture()
def conn() -> Iterator[psycopg.Connection]:
    """A connection that cleans up any rows this test inserts."""
    assert DSN is not None
    with psycopg.connect(DSN) as c:
        try:
            yield c
        finally:
            with c.cursor() as cur:
                cur.execute("DELETE FROM trades.fills WHERE order_id IN "
                            "(SELECT id FROM trades.orders WHERE ticker = %s)",
                            ("ZZTEST",))
                cur.execute("DELETE FROM trades.orders WHERE ticker = %s", ("ZZTEST",))
                cur.execute("DELETE FROM trades.positions WHERE ticker = %s", ("ZZTEST",))
                cur.execute("DELETE FROM trades.pnl_daily WHERE d = %s",
                            (dt.date(1970, 1, 1),))
            c.commit()


def test_trades_schema_round_trip(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO trades.orders "
            "(ticker, side, qty, order_type, status, reason) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            ("ZZTEST", "BUY", 10.0, "MARKET", "SUBMITTED", "unit-test"),
        )
        row = cur.fetchone()
        assert row is not None
        order_id: int = row[0]

        cur.execute(
            "INSERT INTO trades.fills (order_id, qty, price) VALUES (%s, %s, %s)",
            (order_id, 10.0, 123.45),
        )
        cur.execute(
            "INSERT INTO trades.positions "
            "(ticker, qty, avg_entry, market_value, unrealized_pl) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("ZZTEST", 10.0, 123.45, 1240.0, 5.5),
        )
        cur.execute(
            "INSERT INTO trades.pnl_daily (d, equity, realized_pl, unrealized_pl) "
            "VALUES (%s, %s, %s, %s)",
            (dt.date(1970, 1, 1), 100_000.0, 0.0, 5.5),
        )

        cur.execute(
            "SELECT o.side, o.filled_qty, f.price "
            "FROM trades.orders o JOIN trades.fills f ON f.order_id = o.id "
            "WHERE o.id = %s",
            (order_id,),
        )
        got = cur.fetchone()
        assert got is not None
        assert got[0] == "BUY"
        assert got[1] == 0.0  # filled_qty default
        assert got[2] == pytest.approx(123.45)

        cur.execute(
            "SELECT market_value FROM trades.positions WHERE ticker = %s",
            ("ZZTEST",),
        )
        pos = cur.fetchone()
        assert pos is not None
        assert pos[0] == pytest.approx(1240.0)

        cur.execute(
            "SELECT equity FROM trades.pnl_daily WHERE d = %s",
            (dt.date(1970, 1, 1),),
        )
        pnl = cur.fetchone()
        assert pnl is not None
        assert pnl[0] == pytest.approx(100_000.0)

    conn.commit()
