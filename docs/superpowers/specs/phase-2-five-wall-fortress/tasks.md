# Phase 2 — Tasks

**Status:** ✅ **COMPLETE 2026-06-22** — all sub-features merged (PRs #40/#44/#45/#46). Exit proof on real SPY: Faber promoted, overfit canary rejected (PBO=0.84), 1.25 s/eval. See [`../../../measurements/phase-2-exit-verification.md`](../../../measurements/phase-2-exit-verification.md). Drafted 2026-05-11; revised 2026-06-22.
**Plan:** [`plan.md`](plan.md)

Work items as a dependency graph so independent items run in parallel. Items below each sub-feature line are owned by that sub-feature's own `<feature>-tasks.md`; re-listed here only to show cross-sub-feature edges.

## Legend

- `[plan]` design artifact · `[code]` implementation · `[test]` test/measurement · `[doc]` non-design docs
- `→` depends on · `‖` parallel-safe

## Top-level dependency graph

```
                    [P2.1 wall framework]  ✅ merged (PR #40)
                              │
                              ▼
              [P2.2 Wall 1 — Statistical Rigor (RiskLabAI)]
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
   [P2.3 Wall 2        [P2.4 Wall 3        [P2.5 Wall 4
    Complexity]         Generalization      Meta-Awareness]
            │            walk-forward]              │
            └─────────────────┼─────────────────┘
                              ▼
        [P2.6 Gate system + real-data calibration (Faber / overfit)]
                              │
                              ▼
              [P2.exit verification + measurements + tag]
```

## P2.1 — Wall framework ✅

- [x] `Wall` ABC + `WallReport` + `EvaluationContext` + test doubles; spec/plan/tasks; merged PR #40.

## P2.2 — `wall-1-statistical-rigor-spec.md` (next)

- [ ] **P2.2.spec [plan]** Author the spec: PBO (reject ≥0.30), DSR/PSR, combinatorial purged+embargoed CV, PIT-eval leak check. Built on **RiskLabAI** + quantstats. Document the wrapper (assemble DSR, effective-independent-N, NaN-guard PBO). → P2.1
- [ ] **P2.2.plan + tasks [plan]** → P2.2.spec
- [ ] **P2.2.code [code]** `services/trader/walls/wall_1_statistical.py` + a thin `risklabai_wrap.py`. Add `RiskLabAI` + `quantstats` deps. → P2.2.plan
- [ ] **P2.2.test [test]** Unit on known-ground-truth fixtures: noise → PBO≈0.5 / DSR low (REJECT); injected-edge → PASS. Cross-check DSR/PSR vs the RiskLabAI-validated values. → P2.2.code

## P2.3 — `wall-2-complexity-control-spec.md` ‖ P2.4 ‖ P2.5

- [ ] **P2.3.spec/plan/tasks [plan]** parameter-sensitivity perturbation (±10/20%), rolling-window stability, MDL penalty. → P2.2.spec
- [ ] **P2.3.code [code]** `services/trader/walls/wall_2_complexity.py`; sensitivity reuses the Phase-1 backtest engine in a loop. → P2.3.plan + Phase 1 P1.6
- [ ] **P2.3.test [test]** Brittle-strategy fixture (param perfectly fits one window) → REJECT. → P2.3.code

## P2.4 — `wall-3-generalization-spec.md` ‖ P2.3 ‖ P2.5

- [ ] **P2.4.spec/plan/tasks [plan]** walk-forward / OOS on SPY history + multi-regime split (Phase-1 regime detector). Cross-asset rotation explicitly deferred (single instrument). → P2.2.spec + Phase 1 P1.5
- [ ] **P2.4.code [code]** `services/trader/walls/wall_3_generalization.py`; reads `RegimeStore`. → P2.4.plan
- [ ] **P2.4.test [test]** Single-regime / in-sample-only fixture → fails cross-regime / walk-forward. → P2.4.code

## P2.5 — `wall-4-meta-awareness-spec.md` ‖ P2.3 ‖ P2.4

- [ ] **P2.5.spec/plan/tasks [plan]** trial-budget tracker (count feeds Wall-1 PBO/DSR #-trials); KB forbidden-pattern stub (returns False; Hindsight wiring Phase 3). → P2.2.spec
- [ ] **P2.5.code [code]** `services/trader/walls/wall_4_meta.py`; trial counter in a `walls.trial_budget` Postgres table (migration). → P2.5.plan
- [ ] **P2.5.test [test]** Trial-budget exhaustion fixture; KB stub returns False. → P2.5.code

## P2.6 — `gate-system-spec.md` + real-data calibration

- [ ] **P2.6.spec/plan/tasks [plan]** `Gate` ABC, `GateReport`, 3 gates (Fitness: Sharpe/DSR/win-rate; Robustness: CPCV + sensitivity agree; Risk: max-drawdown + tail-loss); AND aggregation. → P2.2–P2.5
- [ ] **P2.6.code [code]** `services/trader/gates/`. Calibration suite under `tests/integration/phase-2/calibration/`: **Faber 200-day SMA on SPY** (known-good) + **overfit canary** (known-bad), real SPY data. → P2.6.plan + all walls
- [ ] **P2.6.test [test]** CI assertion: Faber-SMA promoted, overfit canary rejected (**PBO discriminator**); full pipeline <30 s. → P2.6.code

## P2.exit — closure

- [ ] **P2.exit.tests [test]** All `tests/integration/phase-2/` green in CI (incl. calibration).
- [ ] **P2.exit.perf [test]** <30 s/candidate measured → `docs/measurements/phase-2-wall-perf.md`.
- [ ] **P2.exit.doc [doc]** `docs/measurements/phase-2-exit-verification.md`.
- [ ] **P2.exit.tag [doc]** Tag `phase-2-complete` (operator confirmation).

## Parallelism

After **P2.2 Wall 1** lands, **P2.3 + P2.4 + P2.5** run in parallel. **P2.6** waits on all walls. Suggested order: P2.2 → (P2.3 ‖ P2.4 ‖ P2.5) → P2.6 → exit. Each sub-feature lands as its own spec/plan/tasks + per-chunk PRs (Phase-1 cadence).
