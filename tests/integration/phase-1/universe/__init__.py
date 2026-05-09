"""Phase 1 universe integration tests.

The index-reproduction audit (test_index_reproduction.py) is opt-in via the
`MAHORAGA_LIVE_AUDIT` env var because it requires:
  1. The full S&P 500 history written by `scripts/build_sp500_universe.py`
     (chunk U2), which in turn requires live Wikipedia access at runbook time
  2. Real yfinance OHLCV for the audited month
  3. A reference S&P 500 monthly return number to compare against

CI does not export `MAHORAGA_LIVE_AUDIT`, so the suite skips. The Phase 1
data-foundation suite already runs in CI under `tests/integration/phase-1/
data_foundation/` against synthetic + Postgres fixtures.
"""

import pytest

pytestmark = pytest.mark.integration
