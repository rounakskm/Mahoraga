<!-- SPDX-License-Identifier: Apache-2.0 -->

# `services/trader/data` — Data Foundation

Phase 1 sub-feature 1. Pulls OHLCV + macro data from free public APIs and
writes it to parquet under `data/parquet/` with point-in-time-correct read
semantics.

Design docs (read these first):

- [`docs/superpowers/specs/phase-1-foundation/data-foundation-spec.md`](../../../docs/superpowers/specs/phase-1-foundation/data-foundation-spec.md) — what we're building and why
- [`docs/superpowers/specs/phase-1-foundation/data-foundation-plan.md`](../../../docs/superpowers/specs/phase-1-foundation/data-foundation-plan.md) — five-chunk implementation plan
- [`docs/superpowers/specs/phase-1-foundation/data-foundation-tasks.md`](../../../docs/superpowers/specs/phase-1-foundation/data-foundation-tasks.md) — per-chunk task IDs + dependency graph

## Layout

```
services/trader/data/
├── connectors/
│   ├── base.py             Connector ABC + RateLimiter + ConnectorResult + errors
│   ├── yfinance.py         daily OHLCV for equities + ETFs
│   ├── fred.py             macro indicators with as_of_release_date (chunk 3, planned)
│   └── tests/              pytest fixtures
├── storage/
│   ├── schema.py           OhlcvRow / MacroRow + PyArrow schemas
│   ├── parquet_adapter.py  ParquetAdapter (write/read/list_partitions/gaps/health)
│   ├── pit.py              pit_view_ohlcv / pit_view_macro
│   └── tests/              round-trip + PIT correctness + append-only suites
├── coverage.py             per-symbol completeness (chunk 4, planned)
├── audit.py                audit-log + manifest writes (chunk 4, planned)
└── ingest.py               orchestrator (chunk 4, planned)
```

## Status

| Chunk | Branch | Status |
|---|---|---|
| 1. Connector skeleton + yfinance | `phase-1-data-foundation-connectors` | Merged |
| 2. Parquet writer + PIT view | `phase-1-data-foundation-storage` | Merged |
| 3. FRED connector + macro schema | `phase-1-data-foundation-fred` | Merged |
| 4. Coverage + audit-log integration | `phase-1-data-foundation-coverage` | Merged |
| 5. End-to-end integration test + CI | `phase-1-data-foundation-integration` | **In review (this PR)** |

## Storage adapter API (chunk 2)

The parquet adapter is the **single chokepoint** that prevents look-ahead bias.
Every read returns only data that was publicly available at the caller-supplied
`asof` timestamp:

```python
from datetime import UTC, datetime
from services.trader.data.storage import ParquetAdapter

adapter = ParquetAdapter("data/parquet")

# Append-only write — duplicates are deduped on natural key, restatements
# coexist as new rows with non-null `revision_at` (OHLCV) or later
# `as_of_release_date` (macro).
adapter.write(connector_result, kind="ohlcv")

# PIT-correct read — only rows public at `asof` are returned. For OHLCV, the
# latest revision_at <= asof wins per (ticker, bar_timestamp). For macro, the
# latest as_of_release_date <= asof wins per (indicator, reference_date, source);
# multiple sources for the same indicator+reference_date are all returned so the
# joiner downstream can apply the conservative-release-date rule.
df = adapter.read(
    kind="ohlcv",
    keys=["SPY", "QQQ"],
    start=datetime(2026, 1, 1, tzinfo=UTC),
    end=datetime(2026, 12, 31, tzinfo=UTC),
    asof=datetime(2026, 6, 30, tzinfo=UTC),
)
```

See `data-foundation-spec.md` §6 (storage layout) and §7 (PIT contract).

## Running the connector tests

```bash
cd /Users/rounakskm/AI-projects/Mahoraga
python -m pytest services/trader/data/connectors/tests/ -v
```

All current tests use injected fake downloaders — they do **not** hit the real
Yahoo or FRED endpoints, so they are CI-safe and offline.

## Required environment variables (by chunk)

- Chunk 1 (yfinance): no API key required.
- Chunk 3 (FRED): `FRED_API_KEY` is **required**. Free, instant: https://fred.stlouisfed.org/docs/api/api_key.html
- Chunk 3+ (BLS): `BLS_API_KEY` optional, used for cross-checking FRED CPI/NFP release timing.

## FRED connector usage (chunk 3)

```python
from datetime import date
from services.trader.data.connectors.fred import FredConnector

connector = FredConnector(api_key=os.environ["FRED_API_KEY"])
result = connector.fetch("CPIAUCSL", date(2026, 1, 1), date(2026, 12, 31))
# result.frame columns:
#   indicator, reference_date, as_of_release_date, value, unit, source, fetched_at
# Every row's `as_of_release_date` is computed via FRED's release-calendar API
# so downstream PIT-correct reads can filter on it.
```

The `as_of_release_date` field is the load-bearing piece: it's the date FRED
first published this value, which is what the storage layer's `pit_view_macro`
gates against when serving reads at a simulated `asof` timestamp.

## Orchestrated ingest (chunk 4)

Wire a connector + the storage adapter + the audit logger together:

```python
from services.trader.data.audit import make_audit_logger_from_env
from services.trader.data.ingest import Ingest, IngestMode
from services.trader.data.storage import ParquetAdapter
from services.trader.data.connectors.yfinance import YFinanceConnector

adapter = ParquetAdapter("data/parquet")
audit = make_audit_logger_from_env(parquet_root="data/parquet")
ingest = Ingest(adapter=adapter, audit=audit)

result = ingest.run_ohlcv(
    YFinanceConnector(),
    tickers=["SPY", "QQQ", "IWM"],
    start=date(2026, 1, 1),
    end=date(2026, 12, 31),
    mode=IngestMode.FRESH,  # raise on per-key coverage <99%
)
```

The orchestrator:
- runs the connector + writes parquet via the adapter,
- computes per-key coverage against the NYSE trading calendar,
- writes one row to `data/parquet/manifests/ingest-runs.parquet` per run,
- writes one hash-chained row to Postgres `audit.events` per run (when
  `MAHORAGA_AUDIT_DSN` or `MAHORAGA_TEST_DSN` is set).

## Vault embargo (P1.3)

`ParquetAdapter` enforces a rolling 180-day embargo by default. The most
recent 6 months are held back from training so that the live deployment
in Phase 7+ has a genuinely out-of-sample window to validate against.

```python
from services.trader.data.audit import PostgresAuditWriter
from services.trader.data.storage import ParquetAdapter, VaultEmbargoError

# Default: 180-day vault enforced. Wire an audit_writer if you want
# every override forensically reconstructible (recommended in production).
adapter = ParquetAdapter(
    "data/parquet",
    audit_writer=PostgresAuditWriter(dsn=os.environ["MAHORAGA_AUDIT_DSN"]),
    audit_actor="trader-backtest",
)

# Reads inside the last 180 days raise by default — the policy is impossible
# to bypass silently:
try:
    adapter.read(kind="ohlcv", keys=["SPY"],
                 start=datetime(2026, 5, 1, tzinfo=UTC),
                 end=datetime.now(UTC))
except VaultEmbargoError as exc:
    print(f"vault hit: cutoff={exc.vault_cutoff}")

# To bypass deliberately, pass vault_override=True AND vault_override_reason.
# The override path writes a hash-chained `audit.events` row with action=
# 'vault_override' so the bypass is forensically reconstructible.
adapter.read(
    kind="ohlcv", keys=["SPY"],
    start=datetime(2026, 5, 1, tzinfo=UTC),
    end=datetime.now(UTC),
    vault_override=True,
    vault_override_reason="live-PnL reconciliation against the broker tape",
)
```

**Opt-out**: pass `vault_cutoff_days=None` for use cases that legitimately
need vault-window reads (backfill jobs, synthetic-data fixtures, tests
exercising storage mechanics rather than vault policy). Production
strategy code should never pass `None`.

```python
# Backfill job — explicit opt-out, documented in the call site
adapter = ParquetAdapter("data/parquet", vault_cutoff_days=None)
```

## Substrate-portability discipline

Per `CLAUDE.md` item 7, this package contains **only** plain Python with clean
interfaces — no NemoClaw / OpenClaw / OpenShell imports. The package can be
imported from any runtime; the substrate (NemoClaw sandbox) is wired in at a
higher layer in later phases.

## Related cherry-picks already on `main`

The vendored `tradingagents` upstream has a `yfinance_utils` module that
inspired (but does not back) `connectors/yfinance.py`. We chose a minimal
fresh implementation rather than cherry-picking from `vendor/tradingagents/`
because (a) we want explicit retry + rate-limit semantics, (b) we want the
ConnectorResult envelope to be uniform across sources, and (c) tradingagents'
helper would have required carrying its API surface forward as a port-log
entry without much benefit.

If a future need surfaces, lifts from `vendor/tradingagents/` follow the
attribution discipline in `vendor/tradingagents/MAHORAGA_NOTES.md`.
