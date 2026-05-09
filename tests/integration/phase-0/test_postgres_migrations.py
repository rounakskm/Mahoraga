import os

import psycopg
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def conn():
    dsn = os.environ.get("MAHORAGA_TEST_DSN", "postgresql://postgres:change_me_locally@localhost:5432/postgres")
    with psycopg.connect(dsn) as c:
        yield c

def test_pgvector_installed(conn):
    cur = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    assert cur.fetchone() is not None

def test_schemas_exist(conn):
    # `knowledge` was dropped by migration 004 — Hindsight (vendor/hindsight/) now owns
    # all knowledge-layer storage. Only system-of-record schemas remain in this Postgres.
    # See docs/superpowers/specs/2026-05-03-hindsight-memory-layer-revision.md.
    cur = conn.execute(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name IN ('knowledge','trades','experiments','strategies','audit')"
    )
    found = {r[0] for r in cur.fetchall()}
    assert found == {"trades", "experiments", "strategies", "audit"}, (
        f"expected 4 system-of-record schemas; got {found}"
    )

def test_audit_table(conn):
    cur = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='audit' AND table_name='events'"
    )
    cols = {r[0] for r in cur.fetchall()}
    assert {"id","ts","actor","action","payload","prev_hash","hash"} <= cols
