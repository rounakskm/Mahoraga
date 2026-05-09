# Phase 1 — Foundation Plan

**Status:** Approved 2026-05-09
**Spec:** [`spec.md`](spec.md) (approved 2026-04-26, scope revised 2026-05-09)
**Anchor specs:** [`../2026-04-25-mahoraga-architecture-decomposition.md`](../2026-04-25-mahoraga-architecture-decomposition.md), [`../2026-05-03-hindsight-memory-layer-revision.md`](../2026-05-03-hindsight-memory-layer-revision.md)
**Predecessor:** Phase 0 (closed `phase-0-complete` tag, 2026-05-09)
**Phase duration:** 8 weeks, 3-stream parallelism

---

## 1. Plan summary

Ship the data-and-regime foundation in six sub-features, each with its own `<feature>-spec.md` + `<feature>-plan.md` + `<feature>-tasks.md` under this directory. Critical-path is data-ingest → universe + vault → features → regime → backtest-harness. BTC-ETF data is descoped to a follow-up sub-feature based on the user's 2026-05-09 directive (focus on stocks first; revisit BTC when we find a free 15Y BTCUSD API).

By Phase 1 exit, downstream phases consume:
- Point-in-time-correct OHLCV + macro + features for the equity + ETF universe (8+ years).
- A regime label per trading day with ≥75% accuracy on a labeled historical sample.
- A vectorbt-backed backtest skeleton that runs a stub strategy and emits a placeholder `FitnessReport`.
- Vault embargo enforced at the storage layer with a deliberate-leak canary test in CI.

## 2. Sub-features (6 total)

Each becomes its own spec → plan → tasks chain inside `phase-1-foundation/`. The first three live on the critical path; streams B and C parallelize after the data-ingest skeleton lands.

| # | Sub-feature | Stream | Depends on | Spec filename |
|---|---|---|---|---|
| 1 | **data-ingest service** | A (critical path) | — | `data-foundation-spec.md` |
| 2 | **universe management** | A | (1) skeleton | `universe-spec.md` |
| 3 | **vault embargo** | A | (1) writers | `vault-embargo-spec.md` |
| 4 | **feature engineering pipeline** | B | (1) writers + (2) | `feature-pipeline-spec.md` |
| 5 | **regime detector v1** | C | subset of (4) | `regime-detector-spec.md` |
| 6 | **backtest harness skeleton** | A | (4) + (5) | `backtest-harness-spec.md` |
| 7 *(deferred)* | **BTC-ETF data + history** | A | (1) + free 15Y BTCUSD API located | `btc-data-spec.md` (open until then) |

## 3. Decisions locked at plan time (resolution of spec §8)

| Decision | Implementation expectation |
|---|---|
| **BTC pre-2024 history** | Deferred. The data-ingest service architecture must NOT bake in BTC-ETF assumptions; the connector layer is generic enough that a `btc-data-spec.md` can land later without a redesign. |
| **Macro PIT** | Storage-layer enforcement: every macro row in parquet carries `as_of_release_date` and `reference_date`. The feature pipeline reads via a PIT-correct view that filters `release_date <= bar_timestamp`. The `audit-xls` reviewer prompt's look-ahead check (already merged to `services/trader/prompts/reviewer/audit-xls.md`) verifies on every backtest output. |
| **Sentiment placeholder** | Single-column `sentiment_score` always returns `0.0` with `placeholder=True` until Phase 4. Backtest harness rejects strategies that read placeholder columns unless `allow_placeholder_features=True` is set in the strategy config. |

## 4. Sequencing — 8 weeks, 3 streams

Same week-by-week table as spec §6 with concrete sub-feature names slotted in:

| Week | Stream A (data) | Stream B (features) | Stream C (regime) |
|---|---|---|---|
| 1–2 | `data-foundation-spec.md` written + reviewed; data-ingest skeleton + free-API connectors (yfinance, FRED, BLS); parquet writers; PIT enforcement scaffolding | (waiting on data) | `regime-detector-spec.md` written; regime taxonomy & label set; hand-label sample drafted |
| 3–4 | `universe-spec.md` written; S&P 500 + Russell 1000 PIT constituents from SEC EDGAR; ETF allowlist YAML | `feature-pipeline-spec.md` written; feature pipeline skeleton; first 10–15 features (trend + momentum subset) | hand-label sample finalized; MACRO-lens v1 draft |
| 5–6 | `vault-embargo-spec.md` written; vault enforcement landing in storage adapter; canary leak test in CI | core 70 features land (trend, momentum, volatility, volume, statistical) | MACRO lens implemented & validated against labeled sample |
| 7 | data-quality test suite (coverage, gap detection, dedupe, PIT discipline) | feature validation tests; macro features (with PIT) integrated | MESO + MICRO lens implemented |
| 8 | `backtest-harness-spec.md` written; vectorbt skeleton; stub `Strategy` ABC + placeholder `FitnessReport` | feature integration tests; full feature parquet lineage | regime accuracy validation against labels (≥75% target); integration test with backtest harness |

## 5. Mahoraga-specific implementation notes

### 5.1 Cherry-picks already on `main` that this phase consumes

- **`vendor/tradingagents/`** — connector patterns for yfinance, finnhub, reddit, simfin. The data-ingest service may cherry-pick adapters into `services/trader/data/` with attribution per the existing `vendor/tradingagents/MAHORAGA_NOTES.md` Port log; do not import from `vendor/` on the runtime path.
- **`services/trader/prompts/researcher/macro-rates-monitor.md`** — analytical scaffold for the MACRO regime narration. The deterministic v1 regime detector is Python only; the prompt is reserved for the LLM-narration path that lands in Phase 3 (autoresearch loop).
- **`services/trader/prompts/researcher/option-vol-analysis.md`** — analytical scaffold for the MICRO regime + position-sizing scalar. Same Phase-3 deferral as macro-rates-monitor.
- **`services/trader/prompts/researcher/catalyst-calendar.md`** — directly load-bearing for Phase 1's regime-detector and the firewall (Phase 5+); generation of the catalyst calendar is an early Phase 1 deliverable so the firewall has data to consume when Phase 5 wires it up.

### 5.2 Hindsight integration during Phase 1

- Each daily regime label written as a World Fact in the `mahoraga-trader` bank (subject + date + MACRO/MESO/MICRO + confidence).
- Each PIT-corrected macro-data event written as a World Fact (release_date + reference_date + indicator + value).
- Backtest output (Phase 1 stub) writes the per-run digest as an Experience Fact; Phase 3 expands this.
- No Mental Model writes in Phase 1; that begins in Phase 3 with the autoresearch-loop's reflect step.

### 5.3 Postgres schema use

- `audit.events` records every PIT view query that returns a row whose `release_date > bar_timestamp` would have been served — these are caught and rejected, but the *attempted* query is audit-logged (helps detect strategy code that's silently look-ahead-prone).
- `strategies.*` is unused in Phase 1 except for migration scaffolding; first writes in Phase 2 with the walls.

### 5.4 Substrate-portability discipline

Per CLAUDE.md item 7 ("Substrate-portable application code"): all Phase 1 code lands at `services/trader/` as plain Python with clean interfaces. No NemoClaw or OpenClaw glue in this phase — the sandbox doesn't yet have anything to do with data ingestion or feature engineering. The regime detector's deterministic Python classifier is ABS-portable; the LLM narration that uses the merged prompts is Phase 3+.

## 6. Per-sub-feature exit criteria (rolled up to phase exit)

Phase 1 closes when **all** of:

- ✅ Sub-feature 1 (`data-ingest`): 8+ years OHLCV ingested for full equity + ETF universe; PIT discipline tested; macro data with `as_of_release_date` ingested
- ✅ Sub-feature 2 (`universe`): S&P 500 + Russell 1000 PIT constituents reproducible; ETF allowlist managed
- ✅ Sub-feature 3 (`vault-embargo`): canary leak test in CI passes; deliberate-leak fixture verifies hard rejection without `vault_override`
- ✅ Sub-feature 4 (`feature-pipeline`): 70+ features computed; sentiment placeholder behaves per decision §3
- ✅ Sub-feature 5 (`regime-detector v1`): ≥75% accuracy on labeled sample
- ✅ Sub-feature 6 (`backtest-harness`): vectorbt wraps stub `Strategy`, returns placeholder `FitnessReport` in <30 s
- ✅ All Phase 1 integration tests in `tests/integration/phase-1/` green in CI
- ✅ Phase 1 exit verification doc filled in (analogous to Phase 0's `docs/measurements/phase-0-exit-verification.md`) and tagged `phase-1-complete`

The deferred sub-feature 7 (`btc-data`) is **not** required for Phase 1 closure — it can land before or after the `phase-1-complete` tag depending on when we source the free 15Y BTCUSD API.

## 7. PR cadence

Per the user's 2026-05-09 sequencing question: **one PR per artifact, not per phase**. Three classes of PR:

| PR class | Branch pattern | Contents | Reviewer cadence |
|---|---|---|---|
| Plan PR (this one) | `phase-1-foundation-plan` | spec revision + plan.md + tasks.md | Once for the phase |
| Sub-feature design PR | `phase-1-foundation-<feature>-spec` | `<feature>-spec.md` + `<feature>-plan.md` + `<feature>-tasks.md` | Once per sub-feature (×6) |
| Implementation PR | `phase-1-<feature>-<chunk>` | Code + tests + measurements | One or more per sub-feature, sized to be reviewable in <60 min |

This keeps each PR's review surface manageable and lets the user halt the phase at any sub-feature boundary if priorities shift.

## 8. Risks (from spec §7, with current-state notes)

| Risk | Status / mitigation |
|---|---|
| BTC-ETF data depth | Resolved: deferred to sub-feature 7 (or Phase 2). Out of Phase 1 critical path. |
| Universe survivorship bias | Open. Addressed in `universe-spec.md`. PIT constituents from SEC EDGAR; audit by reproducing a known historical index level. |
| Silent vault leakage | Open. Addressed in `vault-embargo-spec.md`. Storage-layer enforcement + deliberate-leak canary test in CI. |
| Regime label calibration | Open. Addressed in `regime-detector-spec.md`. Hand-labels validated against major historical events (2020 COVID, 2022 inflation, 2018 vol regime); operator review before merging the labeled set. |
| Free-API rate limits | Open. Addressed in `data-foundation-spec.md`. Backoff + parallelism control; coverage monitor; partial-coverage fail-loud. |
| Multi-source PIT consistency | New, surfaced by the merged macro-rates-monitor prompt: FRED CPI release timing differs from BLS release timing for related indicators. Mitigation: every connector records its source's published release schedule; the feature pipeline picks the conservative (latest) `release_date` when joining series from different sources. |

## 9. What lands in this PR

- spec §8 and §9 updated with the resolved decisions and the 2026-05-09 scope revision.
- This `plan.md`.
- `tasks.md` with the dependency graph.

What does NOT land in this PR (separate PRs follow):
- The 6 sub-feature specs (each in its own PR per §7).
- Any code changes — `services/trader/data/`, `services/trader/features/`, `services/trader/regime/`, etc. all wait for their respective sub-feature specs to land first.

## 10. Acceptance for this plan PR

- spec.md §8 / §9 reflect the user's 2026-05-09 decisions.
- plan.md (this file) approved.
- tasks.md (next file) shows the dependency graph and the next concrete deliverable: `data-foundation-spec.md`.
