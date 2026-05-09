# Data Foundation — Implementation Plan

**Status:** Drafted 2026-05-09
**Spec:** [`data-foundation-spec.md`](data-foundation-spec.md)
**Parent plan:** [`plan.md`](plan.md)

---

## 1. Implementation strategy

Five PR-sized chunks, each independently reviewable in <60 minutes, each gated on tests. Chunks 1 and 2 must land sequentially (writer needs the connector contract); 3 and 4 can land in either order; 5 is the final test+audit pass.

```
[1 connector skeleton + yfinance]
        ▼
[2 parquet writer + PIT view + round-trip tests]
        ▼
   ┌────┴────┐
   ▼         ▼
[3 fred  [4 coverage + audit-log integration]
 connector
 + macro
 schema]
   │         │
   └────┬────┘
        ▼
[5 full integration tests + CI green]
```

Each chunk lands as its own PR on a `phase-1-data-foundation-<slug>` branch.

## 2. Chunk 1 — connector skeleton + first connector (`yfinance`)

**Branch:** `phase-1-data-foundation-connectors`
**Target review time:** ~45 min

### Lands

- `services/trader/data/__init__.py`, `services/trader/data/connectors/__init__.py`
- `services/trader/data/connectors/base.py` — `Connector` ABC, `ConnectorResult`, `RateLimiter`, `HealthStatus`, `RateLimitStatus`, `ConnectorError`
- `services/trader/data/connectors/yfinance.py` — daily OHLCV for equities + ETFs, token-bucket throttle, exponential backoff
- `services/trader/data/connectors/tests/test_base.py` — ABC contract + RateLimiter tests
- `services/trader/data/connectors/tests/test_yfinance.py` — mocked-HTTP roundtrip + rate-limit + 429 backoff + 401 fail-loud
- `services/trader/pyproject.toml` (or root if not split) — declare `pandas`, `pyarrow`, `httpx`, `yfinance`, `tenacity` (or hand-rolled backoff) deps
- `.env.example` updated with `FRED_API_KEY` placeholder (used by chunk 3 but documented now)

### Acceptance

- `pytest services/trader/data/connectors/tests/ -v` green
- `python -c "from services.trader.data.connectors.yfinance import YFinanceConnector; YFinanceConnector().fetch('SPY', date(2026,1,1), date(2026,2,1))"` returns a non-empty DataFrame
- Rate-limit + backoff tests pass without hitting the real Yahoo API (all mocked)

### Out of scope for this chunk

- Storage / parquet (chunk 2)
- FRED connector (chunk 3)
- Coverage / audit (chunk 4)

## 3. Chunk 2 — parquet writer + PIT view + round-trip tests

**Branch:** `phase-1-data-foundation-storage`
**Target review time:** ~50 min

### Lands

- `services/trader/data/storage/__init__.py`
- `services/trader/data/storage/schema.py` — `OhlcvRow`, `MacroRow` dataclasses + PyArrow schemas
- `services/trader/data/storage/parquet_adapter.py` — `ParquetAdapter` with `write`, `read`, `list_partitions`, `gaps`, `health`
- `services/trader/data/storage/pit.py` — `pit_view(table, asof, kind)` returning the filtered DataFrame per spec §7
- `services/trader/data/storage/tests/test_roundtrip.py` — write → read round-trip
- `services/trader/data/storage/tests/test_pit.py` — PIT correctness (synthetic rows with future `as_of_release_date`); multi-source consistency (FRED + BLS CPI for same `reference_date`)
- `services/trader/data/storage/tests/test_append_only.py` — assert that re-writing a row with the same key adds a new revision instead of overwriting

### Acceptance

- All storage tests green
- A reader call with `asof = past_date` excludes rows with `as_of_release_date > asof`
- A reader call against a key with no rows returns an empty DataFrame (not an error)

### Out of scope

- Connector wiring through to the writer (the writer accepts a `ConnectorResult`-shaped DataFrame; chunk 1 produces one; chunk 5's integration test wires them end-to-end)

## 4. Chunk 3 — `fred` connector + macro schema wiring

**Branch:** `phase-1-data-foundation-fred`
**Target review time:** ~45 min

### Lands

- `services/trader/data/connectors/fred.py` — pulls macro series with `as_of_release_date` populated from FRED's release-calendar API
- `services/trader/data/connectors/release_calendar.py` — small helper that joins FRED's release schedule onto fetched series so every row carries the correct `as_of_release_date`
- Tests: `test_fred.py` — mocked release-calendar + series fetch; per-row `as_of_release_date` populated; rate-limit (120 req/min) honored
- `.env.example` — `FRED_API_KEY` documented (was placeholder in chunk 1)

### Acceptance

- `pytest services/trader/data/connectors/tests/test_fred.py -v` green
- A live test (skipped in CI without key) pulls e.g. CPIAUCSL for the last 12 months and the row dates differ between `reference_date` (15th-of-month-ish) and `as_of_release_date` (~middle of next month)

### Out of scope

- BLS / TreasuryDirect / CBOE connectors — Phase 4-ish or only if FRED can't cover something we need
- yfinance integration (chunk 1) is independent

## 5. Chunk 4 — coverage monitor + audit-log integration

**Branch:** `phase-1-data-foundation-coverage`
**Target review time:** ~40 min

### Lands

- `services/trader/data/coverage.py` — per-symbol bar-coverage + per-indicator release-coverage; trading-calendar aware (use `pandas_market_calendars` or hand-rolled NYSE calendar)
- `services/trader/data/audit.py` — `AuditLogger` writes to Postgres `audit.events` and to `data/parquet/manifests/ingest-runs.parquet`
- `services/trader/data/ingest.py` — orchestrator: takes a `Connector` + `ParquetAdapter` + `AuditLogger`, runs an ingest, raises `CoverageError` if fresh-run coverage <99%
- Tests: deliberate-gap test (drop a known bar, assert coverage monitor flags it); manifest-row-per-run test; audit-events-row-per-run test (uses a Postgres testcontainer or a Phase-0 test DSN)

### Acceptance

- Coverage monitor catches a deliberate gap and surfaces it
- `manifests/ingest-runs.parquet` and `audit.events` both gain exactly one row per ingest run
- Hash-chain in `audit.events` verifies after the ingest writes (the chain mechanism is from Phase 0; this chunk validates that data-ingest writes integrate cleanly)

### Out of scope

- Live integration test (chunk 5)

## 6. Chunk 5 — integration test + CI

**Branch:** `phase-1-data-foundation-integration`
**Target review time:** ~30 min

### Lands

- `tests/integration/phase-1/data-foundation/test_end_to_end.py` — spins up the orchestrator with a recorded-cassette-style HTTP fixture (e.g. `vcrpy` or hand-rolled), writes parquet to a tmp dir, reads back via PIT view, asserts shape + correctness
- `.github/workflows/ci.yml` — extend the integration-smoke job to run the new test (still without a FRED key — uses cassettes)
- `docs/measurements/phase-1-llm-throughput.md` left untouched (this sub-feature has no LLM throughput element)

### Acceptance

- End-to-end test green in CI
- All Phase 1 data-foundation tests collected by `pytest -m integration tests/integration/phase-1/data-foundation/`
- Documentation cross-links: `data-foundation-spec.md` §10 acceptance criteria all checked off

## 7. Per-chunk PR template body

Each chunk's PR body should follow the same shape (already established by Phase 0 PRs):

```
## Summary
1-3 bullets — what this chunk lands.

## Scope
- In-scope:
- Out-of-scope (deferred to chunk N):

## Test plan
- [ ] pytest <path>
- [ ] CI green on lint + unit-tests + integration-smoke
- [ ] Cross-check against data-foundation-spec.md §<section> acceptance criterion
```

## 8. Risks during implementation

| Risk | Mitigation |
|---|---|
| yfinance API silently breaks mid-implementation | Cassette fixtures pin the response shape; a daily smoke job can detect drift before a real ingest fails |
| FRED key not available for the operator | Chunk 3 tests are mocked; live verification deferred until the operator provisions the key |
| Postgres `audit.events` schema drift since Phase 0 | Re-run the Phase 0 migration tests as part of chunk 4 acceptance |
| Append-only file growth | Per-year partition keeps file size manageable; chunk 4's manifests track total row count and surface anomalies |
| Substrate-portability slip | Keep imports limited to stdlib + pandas + pyarrow + httpx + the connector libraries; no NemoClaw imports anywhere in `services/trader/data/` |

## 9. Definition of done for the whole sub-feature

All 5 chunks merged → `data-foundation-spec.md` §10 acceptance criteria 1-8 all checked off → P1.1 task complete in [`tasks.md`](tasks.md).

This unblocks `universe-spec.md`, `vault-embargo-spec.md`, `feature-pipeline-spec.md`, and `regime-detector-spec.md`.
