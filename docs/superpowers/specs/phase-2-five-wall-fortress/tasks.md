# Phase 2 — Tasks

**Status:** Drafted 2026-05-11
**Plan:** [`plan.md`](plan.md)

This file enumerates Phase 2 work items as a dependency graph so
independent items can be picked up in parallel. Items below the
spec/plan/tasks line for each sub-feature are *placeholders* —
they're owned by that sub-feature's own `<feature>-tasks.md` and
re-listed here only to make the cross-sub-feature dependency edges
visible.

## Legend

- `[plan]` = design artifact (spec / plan / tasks markdown)
- `[code]` = implementation work
- `[test]` = test or measurement
- `[doc]` = non-design documentation (README, measurements log)
- `→` = depends on
- `‖` = parallel-safe (no dependency edge between siblings)

## Top-level dependency graph

```
                       [P2.0 plan PR (this PR)]
                                │
                                ▼
                       [P2.1 wall-framework-spec]
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
[P2.2 wall-1            [P2.8 synthetic-data    [P2.7 gate-system-spec]
 statistical-rigor       -spec]
 -spec]                       │                       │
        │                     │                       │
[P2.2.code DSR + PBO   [P2.8.code GBM +         [P2.7.code gate skeleton +
 + Monte Carlo +        regime-switching +        fitness gate]
 bootstrap]             jump-diffusion +
        │               BTC-aware variants]            │
        │                     │                       │
[P2.3 wall-2            (continues into            [P2.7.code robustness +
 data-discipline-spec]   Wall 4 and gate            risk gates]
        │                calibration)                  │
[P2.3.code PCV +              │                        │
 PIT-eval enforcement] [P2.5 wall-4                    │
        │               generalization-spec]            │
[P2.4 wall-3                  │                        │
 complexity-control    [P2.5.code cross-asset +         │
 -spec]                 multi-regime +                  │
        │               ensemble-diversity              │
[P2.4.code sensitivity  via synthetic perturbation]    │
 + MDL + stability]           │                        │
        │                     │                        │
[P2.6 wall-5                  │                        │
 meta-awareness-spec]         │                        │
        │                     │                        │
[P2.6.code trial-budget       │                        │
 tracker + KB forbidden       │                        │
 stub]                        │                        │
        │                     │                        │
        └─────────────────────┴────────────────────────┘
                                │
                                ▼
                       [P2.exit Phase 2 verification
                        + calibration in CI
                        + measurements doc + tag]
```

## P2.0 — Phase plan

- [x] **P2.0.1 [plan]** Read spec.md and tick the section §2 sub-feature list against this `tasks.md` for completeness.  (this PR)
- [x] **P2.0.2 [plan]** Write `plan.md` capturing 8 sub-features, sequencing, exit criteria.  (this PR)
- [x] **P2.0.3 [plan]** Write this `tasks.md`.  (this PR)
- [ ] **P2.0.4 [doc]** Open PR titled "Phase 2 fortress plan + tasks" referencing this directory; merge after operator confirmation.

## P2.1 — `wall-framework-spec.md` (sub-feature 1)

- [ ] **P2.1.spec [plan]** Author `wall-framework-spec.md`: `Wall` ABC (`evaluate(strategy, backtest_result) → WallReport`), `WallReport` dataclass, `EvaluationContext` carrying the strategy + FitnessReport + per-bar returns. → P2.0 merged
- [ ] **P2.1.plan + tasks [plan]** → P2.1.spec
- [ ] **P2.1.code [code]** `services/trader/walls/__init__.py` + `base.py` + `WallReport` dataclass + a stub `AlwaysPassWall` test double. → P2.1.plan
- [ ] **P2.1.test [test]** ABC contract; stub wall round-trips through the evaluation harness. → P2.1.code

## P2.2 — `wall-1-statistical-rigor-spec.md` (sub-feature 2) ‖ P2.5

- [ ] **P2.2.spec [plan]** Author `wall-1-statistical-rigor-spec.md`: DSR (Bailey & López de Prado 2014), PBO (López de Prado 2015), Monte Carlo permutation, bootstrap CI. Reference implementations cited; tolerance values. → P2.1.spec
- [ ] **P2.2.plan + tasks [plan]** → P2.2.spec
- [ ] **P2.2.code [code]** `services/trader/walls/wall_1_statistical.py` implementing the 4 sub-tests; vectorized; <5 s per evaluation. → P2.2.plan + P2.1.code
- [ ] **P2.2.test [test]** Per-sub-test against published examples; full Wall 1 test on a synthetic over-fit fixture asserts rejection. → P2.2.code

## P2.3 — `wall-2-data-discipline-spec.md` (sub-feature 3) ‖ P2.2

- [ ] **P2.3.spec [plan]** Author `wall-2-data-discipline-spec.md`: combinatorial purged cross-validation (CPCV) per López de Prado; PIT-eval-time check that the strategy never accesses bars > current evaluation bar. → P2.1.spec
- [ ] **P2.3.plan + tasks [plan]** → P2.3.spec
- [ ] **P2.3.code [code]** `services/trader/walls/wall_2_data.py`. CPCV uses the existing `ParquetAdapter.read(asof=)` primitive from Phase 1. → P2.3.plan + Phase 1 P1.3 (vault embargo) merged
- [ ] **P2.3.test [test]** Injected-leak fixture: strategy that reads bar `T+1` must fail Wall 2. → P2.3.code

## P2.4 — `wall-3-complexity-control-spec.md` (sub-feature 4) ‖ P2.2 / P2.3

- [ ] **P2.4.spec [plan]** Author `wall-3-complexity-control-spec.md`: parameter-sensitivity perturbation (±10%, ±20%); stability across rolling windows; Minimum Description Length penalty for parameter count. → P2.1.spec
- [ ] **P2.4.plan + tasks [plan]** → P2.4.spec
- [ ] **P2.4.code [code]** `services/trader/walls/wall_3_complexity.py`. Sensitivity reuses the Phase-1 backtest engine in a tight loop. → P2.4.plan + Phase 1 P1.6 merged
- [ ] **P2.4.test [test]** Brittle-strategy fixture (param value perfectly fits a single window): Wall 3 rejects. → P2.4.code

## P2.5 — `wall-4-generalization-spec.md` (sub-feature 5)

- [ ] **P2.5.spec [plan]** Author `wall-4-generalization-spec.md`: cross-asset rotation (run the strategy on N similar tickers); multi-regime validation against the Phase-1 regime detector; ensemble diversity via synthetic-data perturbation. → P2.1.spec + P2.8.spec
- [ ] **P2.5.plan + tasks [plan]** → P2.5.spec
- [ ] **P2.5.code [code]** `services/trader/walls/wall_4_generalization.py`. Reads regime classifications from P1.5 `RegimeStore`; perturbs via the synthetic-data library from P2.8. → P2.5.plan + P2.8.code
- [ ] **P2.5.test [test]** Single-regime strategy fixture: must fail cross-regime validation. → P2.5.code

## P2.6 — `wall-5-meta-awareness-spec.md` (sub-feature 6)

- [ ] **P2.6.spec [plan]** Author `wall-5-meta-awareness-spec.md`: trial-budget tracker (multiple-comparison correction over the autoresearch-loop's experiment count); KB forbidden-pattern check (Phase-2 stub returns False — Hindsight wiring lands in Phase 3); search-process introspection. → P2.1.spec
- [ ] **P2.6.plan + tasks [plan]** → P2.6.spec
- [ ] **P2.6.code [code]** `services/trader/walls/wall_5_meta.py`. Trial counter persists in a new `walls.trial_budget` Postgres table (migration added). → P2.6.plan
- [ ] **P2.6.test [test]** Trial-budget exhaustion fixture; KB-forbidden stub returns False every time. → P2.6.code

## P2.7 — `gate-system-spec.md` (sub-feature 7)

- [ ] **P2.7.spec [plan]** Author `gate-system-spec.md`: `Gate` ABC, `GateReport`, three concrete gates: Fitness (Sharpe/DSR/win-rate), Robustness (PCV + sensitivity agreement), Risk (max-drawdown + tail-loss); aggregation rule = AND. → P2.1.spec
- [ ] **P2.7.plan + tasks [plan]** → P2.7.spec
- [ ] **P2.7.code [code]** `services/trader/gates/`. Each gate is an aggregator over WallReports; calibration suite under `tests/integration/phase-2/calibration/`. → P2.7.plan + all walls merged
- [ ] **P2.7.test [test]** Calibration: 12-1 momentum promoted; deliberate-overfit canary rejected. End-to-end <30 s. → P2.7.code

## P2.8 — `synthetic-data-spec.md` (sub-feature 8)

- [ ] **P2.8.spec [plan]** Author `synthetic-data-spec.md`: GBM with regime switching (uses Phase-1 regime taxonomy), jump-diffusion (crash scenarios), historical-analogue path generation, BTC-aware fat-tail variants. Realized-stats tolerance per regime. → P2.1.spec + Phase 1 P1.5 merged
- [ ] **P2.8.plan + tasks [plan]** → P2.8.spec
- [ ] **P2.8.code [code]** `services/trader/synthetic/__init__.py` + per-model files (`gbm.py`, `jump_diffusion.py`, `historical_analogue.py`, `btc_fat_tail.py`). Deterministic seeds for reproducibility. → P2.8.plan
- [ ] **P2.8.test [test]** Realized-stats validation against historical regime samples within tolerance. → P2.8.code

## P2.exit — Phase 2 closure

- [ ] **P2.exit.tests [test]** All `tests/integration/phase-2/` tests green in CI (including the calibration suite under `tests/integration/phase-2/calibration/`).
- [ ] **P2.exit.perf [test]** Full evaluation pipeline measured at <30 s/candidate on host hardware; result recorded in `docs/measurements/phase-2-wall-perf.md`.
- [ ] **P2.exit.doc [doc]** Author `docs/measurements/phase-2-exit-verification.md` (analogous to Phase 0 / Phase 1).
- [ ] **P2.exit.tag [doc]** Tag `phase-2-complete` and push (operator confirmation).

## Parallelism notes

After **P2.1 wall-framework** lands, every other sub-feature can
proceed in parallel except for the chains noted above (P2.5 → P2.8;
P2.7 → all walls).

Suggested implementation order:
1. P2.1 wall-framework (single-thread; ships the contract)
2. P2.8 synthetic-data (single-thread; needed by P2.5)
3. P2.2 + P2.3 + P2.4 + P2.6 (parallel)
4. P2.5 wall-4 (after P2.8)
5. P2.7 gates + calibration (after all walls)
6. P2.exit verification + tag

Each sub-feature lands as its own spec / plan / tasks + per-chunk
PRs following the Phase 1 cadence (PR per chunk; 30–60 min review
each).
