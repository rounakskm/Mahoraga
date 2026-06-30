import os

import psycopg
import pytest

DSN = os.environ.get("MAHORAGA_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="no MAHORAGA_DSN")

def test_master_is_singleton_and_seeded():
    with psycopg.connect(DSN) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM strategies.master")
        assert cur.fetchone()[0] == 1  # singleton row exists
        cur.execute("INSERT INTO strategies.master (id, candidate_hash, fitness) "
                    "VALUES (1,'x',0) ON CONFLICT (id) DO NOTHING")  # second insert is a no-op
        cur.execute("SELECT count(*) FROM strategies.master")
        assert cur.fetchone()[0] == 1
