"""Phase-1 backtest-harness integration tests (P1.6 B3 — closes Phase 1).

All tests in this package are marked `pytest.mark.integration`. They
run in CI's integration-smoke job (which has Postgres available) and
locally when the operator has `MAHORAGA_TEST_DSN` set + the postgres
compose service up.
"""

import pytest

pytestmark = pytest.mark.integration
