# Phase 2 — Exit Verification

**Date completed:** 2026-06-22
**Spec:** [`../superpowers/specs/phase-2-five-wall-fortress/spec.md`](../superpowers/specs/phase-2-five-wall-fortress/spec.md) (revised 2026-06-22)
**Predecessor:** [`phase-1-exit-verification.md`](phase-1-exit-verification.md)

## Summary

The anti-overfitting fortress is built and proven on **real SPY data**: 4 walls + a
3-gate system that, by exit, **promote a known-good strategy (Faber 200-day SMA
timing) and reject a deliberate-overfit canary (best-of-16 SMA-crossover grid)** —
with **PBO (Probability of Backtest Overfitting) as the discriminator**, exactly as
the redesign specified. A full evaluation runs in **~1.25 s/candidate** (target < 30 s).

The walls are the **fitness predicate the Phase-3 autoresearch loop will evaluate
every learned candidate against**. Strategies are *learned* in Phase 3; the
calibration strategies here are throwaway integration fixtures, not "Mahoraga's
strategy".

| Exit criterion | Status | Evidence |
|---|---|---|
| 4 walls, each a deterministic predicate w/ unit tests on known-ground-truth fixtures | ✓ | `services/trader/walls/` (29 wall tests); PRs #40, #44, #45 |
| PBO discriminator: overfit canary rejected, Faber promoted on real SPY | ✓ | `tests/integration/phase-2/calibration/test_calibration.py` — canary PBO=0.84 (reject), Faber DSR=0.999 (promote) |
| Three-gate system (fitness/robustness/risk), AND-aggregated | ✓ | `services/trader/gates/`; PR #46 |
| Calibration is a CI assertion (not an operator script) | ✓ | runs in `integration-smoke` on a committed real-SPY CSV fixture (no Postgres needed) |
| Full evaluation < 30 s/candidate | ✓ | measured median **1.25 s** (4 walls + 3 gates incl. PBO over 16 strategies) |
| RiskLabAI stat library trustworthy | ✓ | validated 2026-06-22: bit-identical to the rubenbriones reference; reproduces Bailey-LdP PSR textbook 0.96901 |

## The fortress

| Wall / Gate | Question | Backed by |
|---|---|---|
| W1 Statistical Rigor | Is the edge statistically real, not multiple-testing luck? | RiskLabAI **PBO / DSR / PSR** (wrapper handles the validated ergonomic caveats) |
| W2 Complexity Control | Robust to its own parameters? | sensitivity perturbation + rolling stability + MDL penalty |
| W3 Generalization | Holds out-of-sample / across regimes? | walk-forward OOS folds + multi-regime |
| W4 Meta-Awareness | Fooling ourselves across the search? | trial-budget check + KB forbidden stub |
| Fitness gate | ← W1 | |
| Robustness gate | ← W2 ∧ W3 | |
| Risk gate | ← W4 ∧ max-drawdown ≤ 25 % | |

All walls are **pure predicates over `EvaluationContext` + `ctx.metadata`** — the
expensive re-backtesting (perturbations, walk-forward, trial matrices) is the
harness's/loop's job, which keeps the walls fast and deterministic.

## Calibration result (real SPY, 2015-2026)

```
FABER 200d SMA  → PROMOTED   DSR=0.999, OOS 100% positive folds, max_dd -19.8%
OVERFIT canary  → REJECTED   PBO=0.84 (fitness gate) + max_dd -28.9% (risk gate)
```

## Known deviations from the original five-wall plan (all per the 2026-06-22 redesign)

1. **Synthetic-data library dropped** — real data only (operator decision). Wall
   validation uses controlled noise/edge fixtures; calibration uses real SPY.
2. **5 walls → 4** — original "Wall 2 Data Discipline" (combinatorial purged CV) is
   folded into Wall 1 (RiskLabAI's CPCV is the data-discipline core).
3. **Cross-asset generalization deferred** — single instrument (SPY). Wall 3 is
   walk-forward + multi-regime; cross-asset rotation returns with >1 instrument.
4. **Wall 4 Postgres trial-counter deferred to Phase 3** — the wall is a pure
   predicate over the count; the loop that increments/persists it is Phase 3.
5. **Fundamentals = a future selection layer, not a wall** — separate design.

## Stack added

`RiskLabAI` (BSD-3, PBO/DSR/PSR/CPCV) + `quantstats` (Apache-2.0); pandas 3.0.3 /
numpy 2.4.6. `uv.lock` committed (reproducible CI). RiskLabAI's numba dep installs
cleanly in CI.

## CI evidence

```
integration-smoke (PR #46 -> main): pass
  ├── phase-1/{data_foundation,universe,feature_pipeline,regime,backtest}
  └── phase-2/{wall_framework, calibration}   ← calibration = the exit proof
```

Merged Phase-2 PRs: #39 (parent plan), #40 (P2.1 framework), #43 (redesign),
#44 (Wall 1), #45 (Walls 2-4), #46 (gates + calibration).

## Phase 3 readiness — GO

The walls + gates are the predicate the autoresearch loop evaluates candidates
against; `ctx.metadata` is the contract the loop fills (trial matrix, perturbations,
walk-forward folds, trial count). Phase 3 builds the loop that *learns* strategies
and feeds them through this fortress.

## Tag

Ready to tag after operator confirmation:

```bash
git tag -a phase-2-complete -m "Phase 2: anti-overfitting fortress — 4 walls + 3 gates, RiskLabAI, real-SPY calibration"
git push origin phase-2-complete
```
