# Phase 1 — Tasks

**Status:** Approved 2026-05-09
**Plan:** [`plan.md`](plan.md)

This file enumerates Phase 1 work items as a dependency graph so independent items can be picked up in parallel. Items below the spec/plan/tasks line for each sub-feature are *placeholders* — they're owned by that sub-feature's own `<feature>-tasks.md` and re-listed here only to make the cross-sub-feature dependency edges visible.

## Legend

- `[plan]` = design artifact (spec / plan / tasks markdown)
- `[code]` = implementation work
- `[test]` = test or measurement
- `[doc]` = non-design documentation (README, measurements log, etc.)
- `→` = depends on
- `‖` = parallel-safe (no dependency edge between siblings)

## Top-level dependency graph

```
                              [P1.0 plan PR (this PR)]
                                       │
                                       ▼
                             [P1.1 data-foundation-spec]
                                       │
                ┌──────────────────────┼──────────────────────┐
                ▼                      ▼                      ▼
    [P1.1.code data-ingest        [P1.2 universe-spec]    [P1.3 vault-embargo-spec]
     skeleton + free-API
     connectors + parquet
     writers + PIT scaffold]
                │                      │                      │
                └──────────────┬───────┴──────────────────────┘
                               ▼
                  [P1.2.code + P1.3.code merged]
                               │
                ┌──────────────┴──────────────┐
                ▼                             ▼
    [P1.4 feature-pipeline-spec]   [P1.5 regime-detector-spec]
                │                             │
    [P1.4.code 70+ features]         [P1.5.code MACRO/MESO/MICRO v1]
                │                             │
                └──────────────┬──────────────┘
                               ▼
                  [P1.6 backtest-harness-spec]
                               │
                  [P1.6.code vectorbt skeleton]
                               │
                               ▼
              [P1.exit Phase 1 verification + tag]

                  [P1.7 btc-data-spec]    ← deferred; can land in parallel with P1.4–P1.6
                                            once a free 15Y BTCUSD API is sourced;
                                            NOT a phase-exit gate.
```

## Phase-level tasks

### P1.0 — Phase 1 plan landing (this PR)

- [x] **P1.0.1 [plan]** Resolve spec §8 open questions; record in spec.md (BTC deferral, macro PIT, sentiment placeholder).
- [x] **P1.0.2 [plan]** Write `plan.md` capturing 6 sub-features, sequencing, exit criteria.
- [x] **P1.0.3 [plan]** Write this `tasks.md`.
- [ ] **P1.0.4 [doc]** Open PR titled "Phase 1 foundation plan + tasks" referencing this directory; merge after review.

### P1.1 — `data-foundation-spec.md` (sub-feature 1)

Critical path. Unblocks every other sub-feature.

- [ ] **P1.1.spec [plan]** Author `data-foundation-spec.md` covering:
  - Connector inventory (yfinance, finnhub, FRED, BLS, TreasuryDirect, CBOE indices) with rate-limit + fallback strategy
  - Parquet layout (`data/parquet/ohlcv/{symbol}/{year}.parquet`, `data/parquet/macro/{indicator}/{year}.parquet`)
  - PIT discipline contract (every macro row carries `as_of_release_date` and `reference_date`)
  - Storage-adapter API surface (read, write, list, gaps, dedupe)
  - Free-tier rate-limit + backoff + partial-coverage fail-loud behavior
  - Multi-source PIT consistency rule (use the conservative latest `release_date` when joining series across providers)
  → P1.0
- [ ] **P1.1.plan [plan]** Author `data-foundation-plan.md` (per-task breakdown, ordering, owner streams). → P1.1.spec
- [ ] **P1.1.tasks [plan]** Author `data-foundation-tasks.md` with PR-sized chunks. → P1.1.plan
- [ ] **P1.1.code.skeleton [code]** Implement `services/trader/data/` connector skeleton; first connector wires (yfinance + FRED). → P1.1.plan
- [ ] **P1.1.code.parquet [code]** Implement parquet writers + reader with PIT-correct view. → P1.1.code.skeleton
- [ ] **P1.1.test [test]** Round-trip ingest tests + PIT discipline test (inject future-dated row, assert reader rejects). → P1.1.code.parquet

### P1.2 — `universe-spec.md` (sub-feature 2)

- [ ] **P1.2.spec [plan]** Author `universe-spec.md` covering S&P 500 + Russell 1000 PIT constituents from SEC EDGAR; ETF allowlist YAML schema; index-reconstitution event log. → P1.1.spec
- [ ] **P1.2.plan + tasks [plan]** Companion plan + tasks files. → P1.2.spec
- [ ] **P1.2.code [code]** Implement universe service; reproduce a known historical index level as audit. → P1.1.code.skeleton + P1.2.plan
- [ ] **P1.2.test [test]** Index-level reproduction test in CI. → P1.2.code

### P1.3 — `vault-embargo-spec.md` (sub-feature 3) ‖ P1.2

- [ ] **P1.3.spec [plan]** Author `vault-embargo-spec.md`: storage-layer guard, `vault_override` flag with audit warning, deliberate-leak canary test design. → P1.1.spec
- [ ] **P1.3.plan + tasks [plan]** → P1.3.spec
- [ ] **P1.3.code [code]** Implement guard inside the storage adapter so the protection is impossible to bypass without the explicit override. → P1.1.code.parquet + P1.3.plan
- [ ] **P1.3.test [test]** Canary leak test runs in CI; deliberate-leak fixture verifies hard rejection without override. → P1.3.code

### P1.4 — `feature-pipeline-spec.md` (sub-feature 4) ‖ P1.5

- [ ] **P1.4.spec [plan]** Author `feature-pipeline-spec.md`: 70+ features across 7 categories; sentiment placeholder column behavior; multi-source PIT join rule; backtest-harness opt-in `allow_placeholder_features` flag. → P1.2.spec + P1.3.spec
- [ ] **P1.4.plan + tasks [plan]** → P1.4.spec
- [ ] **P1.4.code [code]** Implement features incrementally (trend → momentum → volatility → volume → statistical → macro → sentiment-placeholder). → P1.4.plan + P1.2.code + P1.3.code
- [ ] **P1.4.test [test]** Per-feature unit tests + a feature-vs-known-fixture regression test (e.g. RSI on a synthetic series matches a reference implementation). → P1.4.code

### P1.5 — `regime-detector-spec.md` (sub-feature 5) ‖ P1.4

- [ ] **P1.5.spec [plan]** Author `regime-detector-spec.md`: MACRO/MESO/MICRO taxonomy + label set; deterministic Python classifier signature; ≥75% accuracy on labeled sample target; the LLM-narration prompts (`services/trader/prompts/researcher/macro-rates-monitor.md`, `option-vol-analysis.md`) are documented as the Phase-3 narration path, NOT used by the v1 detector. → P1.4.spec (subset of features needed)
- [ ] **P1.5.plan + tasks [plan]** → P1.5.spec
- [ ] **P1.5.label-set [doc]** Hand-labeled regime sample finalized; calibrated against 2018 vol regime, 2020 COVID, 2022 inflation, etc.; operator review. → P1.5.spec
- [ ] **P1.5.code [code]** Implement v1 classifier consuming the regime-relevant feature subset. → P1.5.label-set + P1.4.code
- [ ] **P1.5.test [test]** Accuracy validation against held-out labels; ≥75% threshold gate. → P1.5.code

### P1.6 — `backtest-harness-spec.md` (sub-feature 6)

- [ ] **P1.6.spec [plan]** Author `backtest-harness-spec.md`: vectorbt wrapper API; `Strategy` ABC; placeholder `FitnessReport` shape; integration with the `audit-xls` reviewer prompt's hard-limit checks (already merged at `services/trader/prompts/reviewer/audit-xls.md`). → P1.4.spec + P1.5.spec
- [ ] **P1.6.plan + tasks [plan]** → P1.6.spec
- [ ] **P1.6.code [code]** Implement the wrapper; stub Strategy + placeholder FitnessReport; <30 s runtime on a representative sample. → P1.4.code + P1.5.code + P1.6.plan
- [ ] **P1.6.test [test]** End-to-end test: stub strategy + sample feature parquet → FitnessReport. → P1.6.code

### P1.exit — Phase 1 closure

- [ ] **P1.exit.tests [test]** All `tests/integration/phase-1/` tests green in CI.
- [ ] **P1.exit.doc [doc]** Author `docs/measurements/phase-1-exit-verification.md` (analogous to Phase 0's).
- [ ] **P1.exit.tag [doc]** Tag `phase-1-complete` and push. → all P1.x.test items green.

### P1.7 — `btc-data-spec.md` (deferred sub-feature)

NOT a phase-exit gate. Lands when (a) a free 15Y BTCUSD API is sourced and (b) capacity allows.

- [ ] **P1.7.research [doc]** Survey free APIs offering 15Y BTCUSD daily/intraday history (CoinGecko, CryptoCompare, Coin Metrics, Yahoo Finance for BTC-USD, others). Decide: spot-proxy stitching vs post-2024-only vs hybrid. → user direction at the time
- [ ] **P1.7.spec [plan]** Author `btc-data-spec.md` with the chosen approach. → P1.7.research + P1.1.spec
- [ ] **P1.7.code + test [code/test]** Implement BTC-ETF + BTC-spot connectors; PIT discipline applied identically to equities. → P1.7.spec + P1.1.code

## Parallelism summary

After P1.1 lands, three streams run in parallel:

- **Stream A** (data plumbing): P1.2 + P1.3 sequentially or in parallel (they touch different layers)
- **Stream B** (features): P1.4 starts as soon as Stream A's P1.2 + P1.3 land
- **Stream C** (regime): P1.5 starts in parallel with P1.4 once a subset of features is available

P1.6 waits for both P1.4 and P1.5 to land. P1.7 can run any time after P1.1 but is not a phase-exit gate.

## Next concrete deliverable

After this plan PR merges:

→ **Author `data-foundation-spec.md` on a new branch `phase-1-data-foundation-spec`.** That sub-feature design unblocks streams A, B, C, and is the first piece of actual data infrastructure to land.
