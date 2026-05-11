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
- [x] **P1.0.4 [doc]** Open PR titled "Phase 1 foundation plan + tasks" referencing this directory; merge after review.  (PR #7, merged 2026-05-09)

### P1.1 — `data-foundation-spec.md` (sub-feature 1)

Critical path. Unblocks every other sub-feature. **All five chunks merged 2026-05-09 (PRs #8, #9, #10, #11, #12, #13).**

- [x] **P1.1.spec [plan]** Author `data-foundation-spec.md` covering:
  - Connector inventory (yfinance, finnhub, FRED, BLS, TreasuryDirect, CBOE indices) with rate-limit + fallback strategy
  - Parquet layout (`data/parquet/ohlcv/{symbol}/{year}.parquet`, `data/parquet/macro/{indicator}/{year}.parquet`)
  - PIT discipline contract (every macro row carries `as_of_release_date` and `reference_date`)
  - Storage-adapter API surface (read, write, list, gaps, dedupe)
  - Free-tier rate-limit + backoff + partial-coverage fail-loud behavior
  - Multi-source PIT consistency rule (use the conservative latest `release_date` when joining series across providers)
  → P1.0
- [x] **P1.1.plan [plan]** Author `data-foundation-plan.md` (per-task breakdown, ordering, owner streams). → P1.1.spec  (PR #8)
- [x] **P1.1.tasks [plan]** Author `data-foundation-tasks.md` with PR-sized chunks. → P1.1.plan  (PR #8)
- [x] **P1.1.A connector skeleton + yfinance** [code+test] — Connector ABC, RateLimiter, ConnectorResult, errors; YFinanceConnector with rate-limit + backoff; 23 mocked-HTTP tests.  (PR #9)
- [x] **P1.1.B parquet writer + PIT view** [code+test] — `ParquetAdapter` with append-only writes + PIT-correct reads; `pit_view_ohlcv` / `pit_view_macro`; round-trip + PIT-correctness + append-only + multi-source consistency tests.  (PR #10)
- [x] **P1.1.C FRED connector + release-calendar** [code+test] — `FredConnector` + `ReleaseCalendar` populating `as_of_release_date` from FRED's release-calendar API; 18 mocked-HTTP tests.  (PR #11)
- [x] **P1.1.D coverage + audit + ingest orchestrator** [code+test] — NYSE-trading-calendar-aware coverage monitor; hash-chained Postgres audit logger + manifest-parquet writer; `Ingest` orchestrator with FRESH/BACKFILL modes; pure-unit + Postgres-integration tests.  (PR #12)
- [x] **P1.1.E end-to-end integration test + CI** [test+infra] — `tests/integration/phase-1/data_foundation/test_end_to_end.py` round-trips yfinance + FRED through the full path with mocked HTTP + real Postgres; CI workflow runs it in `integration-smoke`.  (PR #13, this PR)

### P1.2 — `universe-spec.md` (sub-feature 2) — **CLOSED 2026-05-09**

- [x] **P1.2.spec [plan]** Authored at `phase-1-foundation/universe-spec.md` (PR #14). Pivoted from the parent spec's "EDGAR" framing to a Wikipedia + FTSE Russell PR bootstrap with hand-curated YAML at runtime.
- [x] **P1.2.plan + tasks [plan]** Bundled in `universe-and-vault-plan.md` + `universe-and-vault-tasks.md` (PR #14).
- [x] **P1.2.A YAML schema + loader** [code+test] — `Universe.load()` API, schema validators, 18 tests, hand-curated S&P 500 + Russell 1000 + ETF YAML bootstrap. (PR #16)
- [x] **P1.2.B bootstrap parsers + script + manifest** [code+test] — `services/trader/universe/bootstrap.py` parsers, `scripts/build_sp500_universe.py`, `RebuildManifestWriter`, 17 tests. Russell 1000 deferred to a follow-up. (PR #19)
- [x] **P1.2.C index-reproduction audit** [test+doc] — `services/trader/universe/index_replay.py` mechanism + CI-runnable synthetic test + opt-in (`MAHORAGA_LIVE_AUDIT=1`) live audit at `tests/integration/phase-1/universe/test_index_reproduction.py`. (PR #20, this PR)

### P1.3 — `vault-embargo-spec.md` (sub-feature 3) — **CLOSED 2026-05-09**

- [x] **P1.3.spec [plan]** Authored at `phase-1-foundation/vault-embargo-spec.md`; bundled with universe-spec in PR #14.
- [x] **P1.3.plan + tasks [plan]** Bundled in `universe-and-vault-{plan,tasks}.md` (PR #14).
- [x] **P1.3.A storage hook + canary** [code+test] — `VaultEmbargoError`, `assess_vault()`, `ParquetAdapter` `vault_cutoff_days` + `vault_override` kwargs, 12 tests. (PR #15)
- [x] **P1.3.B audit-writer wire-up** [code+test] — required `vault_override_reason`, hash-chained audit row, 12 new tests + Postgres integration. (PR #17)
- [x] **P1.3.C default flip + sweep** [code+test+doc] — `vault_cutoff_days` defaults to 180; existing tests opt out explicitly where appropriate. (PR #18)

### P1.4 — `feature-pipeline-spec.md` (sub-feature 4) ‖ P1.5

- [x] **P1.4.spec [plan]** Authored at `phase-1-foundation/feature-pipeline-spec.md` (PR #22 series). 70+ features across 7 categories; sentiment placeholder behavior; multi-source PIT join rule; `allow_placeholder_features` opt-in.
- [x] **P1.4.plan + tasks [plan]** `feature-pipeline-{plan,tasks}.md`.
- [x] **P1.4.code [code]** F1 trend (#22), F2 momentum + volatility (#23), F3 volume + statistical (#24), F4 macro (#25), F5 sentiment + coverage + audit (#26).
- [x] **P1.4.test [test]** Per-feature unit tests + F6 end-to-end integration (#27).

### P1.5 — `regime-detector-spec.md` (sub-feature 5) ‖ P1.4

- [x] **P1.5.spec [plan]** Authored at `phase-1-foundation/regime-detector-spec.md` (PR #28). Phase 1 scope = MESO + starter MACRO lens (daily bars); MICRO deferred to Phase 4.
- [x] **P1.5.plan + tasks [plan]** `regime-detector-{plan,tasks}.md` (PR #28).
- [ ] **P1.5.label-set [doc]** Hand-labeled regime sample. *Deferred to Phase 4* — Phase 1 ships a deterministic rule-based classifier and per-bar fixtures cover label correctness; full hand-labeled sample + ≥75% accuracy gate move into Phase 4 once we have a model to calibrate against.
- [x] **P1.5.code [code]** R1 skeleton + MESO (#29), R2 MACRO + composite (#30), R3 RegimeStore + audit (#31).
- [x] **P1.5.test [test]** Per-lens unit tests + R4 end-to-end integration (#32). Accuracy gate replaced with deterministic per-label fixtures + a 4×3 composite-sweep test in `services/trader/regime/tests/test_composite.py`.

### P1.6 — `backtest-harness-spec.md` (sub-feature 6)

- [x] **P1.6.spec [plan]** Authored at `phase-1-foundation/backtest-harness-spec.md` (PR #33). **Departure from sketch**: pure pandas / numpy engine, not vectorbt. FitnessReport contract is engine-agnostic; Phase 2 can swap if throughput demands.
- [x] **P1.6.plan + tasks [plan]** `backtest-harness-{plan,tasks}.md` (PR #33).
- [x] **P1.6.code [code]** B1 skeleton + Strategy ABC + BuyAndHold + placeholder gate (#34); B2 engine + risk-limit firewall stub (#35).
- [x] **P1.6.test [test]** B3 end-to-end integration (#36) — full chain ingest → features → regime → backtest under Postgres with 4-row audit hash chain.

### P1.exit — Phase 1 closure

- [x] **P1.exit.tests [test]** All `tests/integration/phase-1/{data_foundation,universe,feature_pipeline,regime,backtest}/` suites green in CI's `integration-smoke` job as of PR #36.
- [ ] **P1.exit.doc [doc]** Author `docs/measurements/phase-1-exit-verification.md` (analogous to Phase 0's). *Pending — to be written before tagging.*
- [ ] **P1.exit.tag [doc]** Tag `phase-1-complete` and push. *Awaiting user confirmation + exit-verification doc.*

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
