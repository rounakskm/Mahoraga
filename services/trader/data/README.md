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
│   ├── base.py        Connector ABC + RateLimiter + ConnectorResult + errors
│   ├── yfinance.py    daily OHLCV for equities + ETFs (chunk 1, this PR)
│   ├── fred.py        macro indicators with as_of_release_date (chunk 3, planned)
│   └── tests/         pytest fixtures
├── storage/           parquet adapter + PIT view (chunk 2, planned)
├── coverage.py        per-symbol completeness (chunk 4, planned)
├── audit.py           audit-log + manifest writes (chunk 4, planned)
└── ingest.py          orchestrator (chunk 4, planned)
```

## Status

| Chunk | Branch | Status |
|---|---|---|
| 1. Connector skeleton + yfinance | `phase-1-data-foundation-connectors` | **In review (this PR)** |
| 2. Parquet writer + PIT view | `phase-1-data-foundation-storage` | Planned |
| 3. FRED connector + macro schema | `phase-1-data-foundation-fred` | Planned |
| 4. Coverage + audit-log integration | `phase-1-data-foundation-coverage` | Planned |
| 5. End-to-end integration test + CI | `phase-1-data-foundation-integration` | Planned |

## Running the connector tests

```bash
cd /Users/rounakskm/AI-projects/Mahoraga
python -m pytest services/trader/data/connectors/tests/ -v
```

All current tests use injected fake downloaders — they do **not** hit the real
Yahoo or FRED endpoints, so they are CI-safe and offline.

## Required environment variables (by chunk)

- Chunk 1 (yfinance): no API key required.
- Chunk 3+ (FRED, BLS): `FRED_API_KEY`, optionally `BLS_API_KEY`. See `.env.example`.

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
