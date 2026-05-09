# Data Foundation — Tasks

**Status:** Drafted 2026-05-09
**Spec:** [`data-foundation-spec.md`](data-foundation-spec.md)
**Plan:** [`data-foundation-plan.md`](data-foundation-plan.md)

Task IDs use prefix `P1.1.x` to match the parent [`tasks.md`](tasks.md) numbering.

## Legend

- `[code]` = implementation
- `[test]` = pytest or fixture work
- `[doc]` = README, docstring, or measurement note
- `[infra]` = .env, Makefile, CI, dependency declaration
- `→` = depends on

---

## P1.1.A — Chunk 1: connector skeleton + yfinance

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.1.A.1** | [infra] | Add `pandas`, `pyarrow`, `httpx`, `yfinance`, `tenacity` to root `pyproject.toml` (or create `services/trader/pyproject.toml` if we split). Document Python ≥3.11 requirement. | — |
| **P1.1.A.2** | [code] | Create `services/trader/__init__.py`, `services/trader/data/__init__.py`, `services/trader/data/connectors/__init__.py` | P1.1.A.1 |
| **P1.1.A.3** | [code] | Author `services/trader/data/connectors/base.py` with `Connector` ABC, `ConnectorResult`, `RateLimiter` (token bucket), `HealthStatus`, `RateLimitStatus`, `ConnectorError` | P1.1.A.2 |
| **P1.1.A.4** | [code] | Implement `services/trader/data/connectors/yfinance.py` — `YFinanceConnector(Connector)` with daily OHLCV `fetch`, throttled at ~2 req/s, exponential-backoff with jitter, max-5 attempts | P1.1.A.3 |
| **P1.1.A.5** | [test] | `services/trader/data/connectors/tests/test_base.py` — RateLimiter math + ABC contract | P1.1.A.3 |
| **P1.1.A.6** | [test] | `services/trader/data/connectors/tests/test_yfinance.py` — mocked-HTTP roundtrip; 429 backoff; 401 immediate raise | P1.1.A.4 |
| **P1.1.A.7** | [infra] | `.env.example` documents `FRED_API_KEY=` placeholder (used in chunk 3) | — |
| **P1.1.A.8** | [doc] | One-paragraph README at `services/trader/data/README.md` linking to spec/plan/tasks | P1.1.A.4 |

PR: `phase-1-data-foundation-connectors` (one PR landing all of P1.1.A.1–A.8).

## P1.1.B — Chunk 2: parquet writer + PIT view

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.1.B.1** | [code] | `services/trader/data/storage/__init__.py` + `schema.py` with `OhlcvRow`, `MacroRow` dataclasses + matching PyArrow schemas | P1.1.A done |
| **P1.1.B.2** | [code] | `services/trader/data/storage/parquet_adapter.py` — `ParquetAdapter` with `write` (append-only), `read` (PIT-correct via `pit.py`), `list_partitions`, `gaps`, `health` | P1.1.B.1 |
| **P1.1.B.3** | [code] | `services/trader/data/storage/pit.py` — `pit_view(table, asof, kind)` enforcing the §7 contract | P1.1.B.1 |
| **P1.1.B.4** | [test] | `test_roundtrip.py` — write a synthetic OHLCV df, read back, assert equal | P1.1.B.2 |
| **P1.1.B.5** | [test] | `test_pit.py` — synthetic macro rows with future `as_of_release_date`, verify `read(asof=today)` excludes them; multi-source consistency (FRED + BLS for same `reference_date` → reader returns both, joiner picks conservative) | P1.1.B.3 |
| **P1.1.B.6** | [test] | `test_append_only.py` — re-writing a row creates a new revision; reader picks the latest pre-`asof` revision | P1.1.B.2 |
| **P1.1.B.7** | [doc] | Append a "Storage adapter API" section to `services/trader/data/README.md` | P1.1.B.2 |

PR: `phase-1-data-foundation-storage`.

## P1.1.C — Chunk 3: fred connector + macro schema wiring

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.1.C.1** | [code] | `services/trader/data/connectors/release_calendar.py` — fetch FRED's release schedule, cache locally, expose `as_of_release_date(series_id, reference_date)` | P1.1.B done |
| **P1.1.C.2** | [code] | `services/trader/data/connectors/fred.py` — `FredConnector(Connector)`; fetches series + joins release-calendar so every row's `as_of_release_date` is populated | P1.1.C.1 |
| **P1.1.C.3** | [test] | `test_release_calendar.py` — mocked-HTTP cache hit/miss; release-calendar refresh | P1.1.C.1 |
| **P1.1.C.4** | [test] | `test_fred.py` — mocked-HTTP roundtrip; `as_of_release_date` populated correctly; 120-req/min throttle honored | P1.1.C.2 |
| **P1.1.C.5** | [infra] | `.env.example` `FRED_API_KEY` documented with link to https://fred.stlouisfed.org/docs/api/api_key.html | P1.1.C.2 |
| **P1.1.C.6** | [test] | One opt-in live test (skip without key) pulling CPIAUCSL for last 12 months | P1.1.C.2 |
| **P1.1.C.7** | [doc] | README section for FRED with the env-var requirement and a list of supported series | P1.1.C.2 |

PR: `phase-1-data-foundation-fred`.

## P1.1.D — Chunk 4: coverage monitor + audit-log integration

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.1.D.1** | [infra] | Add `pandas_market_calendars` (or hand-rolled NYSE calendar) to deps | P1.1.B done |
| **P1.1.D.2** | [code] | `services/trader/data/coverage.py` — per-symbol bar coverage (uses trading calendar) + per-indicator release coverage; emits a `CoverageReport` | P1.1.D.1 |
| **P1.1.D.3** | [code] | `services/trader/data/audit.py` — `AuditLogger` writes to Postgres `audit.events` and to `data/parquet/manifests/ingest-runs.parquet`; integrates with the Phase 0 hash-chain | P1.1.B done |
| **P1.1.D.4** | [code] | `services/trader/data/ingest.py` — orchestrator that wires `Connector` + `ParquetAdapter` + `Coverage` + `AuditLogger`; raises `CoverageError` on fresh-run <99% coverage | P1.1.D.2 + P1.1.D.3 |
| **P1.1.D.5** | [test] | `test_coverage.py` — deliberate-gap fixture, assert flagged; trading-calendar awareness (don't flag weekends/holidays) | P1.1.D.2 |
| **P1.1.D.6** | [test] | `test_audit.py` — exactly one `manifests/ingest-runs.parquet` row + one `audit.events` row per ingest run; hash-chain verifies | P1.1.D.3 |
| **P1.1.D.7** | [test] | `test_ingest.py` — orchestrator end-to-end with a single-symbol mocked yfinance + temp parquet root; coverage gate fires | P1.1.D.4 |

PR: `phase-1-data-foundation-coverage`.

## P1.1.E — Chunk 5: integration test + CI

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.1.E.1** | [test] | `tests/integration/phase-1/__init__.py` and `tests/integration/phase-1/data-foundation/__init__.py` (with `pytestmark = pytest.mark.integration`) | P1.1.D done |
| **P1.1.E.2** | [test] | `tests/integration/phase-1/data-foundation/test_end_to_end.py` — uses cassette-style HTTP fixtures; spins up orchestrator; round-trips a synthetic universe through the full data path; verifies shape + PIT correctness end-to-end | P1.1.E.1 |
| **P1.1.E.3** | [infra] | Extend `.github/workflows/ci.yml` integration-smoke job to run the new test (still without live API keys) | P1.1.E.2 |
| **P1.1.E.4** | [doc] | Update `docs/superpowers/specs/phase-1-foundation/data-foundation-spec.md` §10 with the actual measurements (rows ingested, coverage achieved, PIT test results) | P1.1.E.2 |
| **P1.1.E.5** | [doc] | Tick the parent [`tasks.md`](tasks.md) P1.1 items as complete | P1.1.E.4 |

PR: `phase-1-data-foundation-integration`.

## Cross-chunk parallelism

After **chunk 1** lands, **chunk 3** (FRED connector) can be developed against the chunk-1 base in parallel with **chunk 2** (storage). They both depend only on the connector-base contract, not on each other. **Chunk 4** depends on chunk 2 (storage) but is otherwise independent of chunk 3. **Chunk 5** waits for all of 1–4.

```
1 → 2 → 4 → 5
1 → 3 ──┘
```

## Task ownership note

All five chunks are foreground work — no subagent dispatch in Phase 1's data foundation. Subagent-driven development becomes appropriate when a sub-feature has many parallel-safe leaf tasks; here the chunks are sequential by review surface, not by intrinsic dependency.
