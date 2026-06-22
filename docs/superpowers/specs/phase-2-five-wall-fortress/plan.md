# Phase 2 — Anti-Overfitting Fortress Plan

**Status:** Drafted 2026-05-11; **revised 2026-06-22** (real-data, RiskLabAI stack, 4 walls + 3 gates)
**Spec:** [`spec.md`](spec.md)
**Predecessor:** Phase 1 complete; P2.1 wall framework merged (PR #40)

---

## 1. Plan summary

Ship the anti-overfitting fortress as **6 sub-features** (was 8 — synthetic-data dropped, Data-Discipline folded into Wall 1), each its own `spec → plan → tasks` chain. By exit, any candidate strategy is evaluable against **4 walls + a 3-gate system** in <30 s, and a **real-data** calibration suite proves the fortress accepts a known-good strategy (Faber 200-day SMA on SPY) and rejects a deliberate-overfit canary, with **PBO as the discriminator**.

Downstream (Phase 3) consumes:
- `Wall.evaluate(ctx) → WallReport` per wall (4, deterministic, unit-tested).
- `GateSystem.evaluate(ctx) → GateReport` (3 gates, AND-aggregated).
- A versioned real-data calibration suite the autoresearch loop reads directly.

The walls are the **fitness predicate** of the Phase-3 loop — strategies are *learned* there, not hand-authored here; the walls must exist first.

## 2. Sub-features (6 total)

| # | Sub-feature | Depends on | Spec filename |
|---|---|---|---|
| 1 | **Wall framework + `Wall` ABC** | Phase 1 P1.6 | `wall-framework-spec.md` ✅ merged |
| 2 | **Wall 1 — Statistical Rigor** (PBO + DSR/PSR + CPCV + PIT-eval leak check; RiskLabAI + quantstats) | (1) | `wall-1-statistical-rigor-spec.md` |
| 3 | **Wall 2 — Complexity Control** (sensitivity + stability + MDL) | (1) + Phase 1 P1.6 | `wall-2-complexity-control-spec.md` |
| 4 | **Wall 3 — Generalization** (walk-forward + multi-regime; cross-asset deferred) | (1) + Phase 1 P1.5 | `wall-3-generalization-spec.md` |
| 5 | **Wall 4 — Meta-Awareness** (trial-budget tracker + KB forbidden stub) | (1) | `wall-4-meta-awareness-spec.md` |
| 6 | **Three-gate system + real-data calibration** (fitness/robustness/risk + Faber/overfit suite) | (2)–(5) | `gate-system-spec.md` |

**Dropped:** synthetic-data library. **Folded:** original Wall-2 Data-Discipline → Wall 1 (CPCV). **Deferred:** cross-asset Wall-3 rotation (needs >1 instrument); fundamentals selection layer (separate design, not a wall).

## 3. Decisions to lock at sub-spec time

| Decision | Default |
|---|---|
| **PBO reject threshold** | 0.30; tune against the calibration pair |
| **CPCV split count** | RiskLabAI CSCV, S (n_partitions) even, e.g. 16 → C(16,8) paths; tune for variance vs cost |
| **Effective-independent-trials (DSR)** | correlation-adjusted N (RiskLabAI uses raw N → anti-conservative); estimator chosen in the Wall-1 sub-spec |
| **Calibration known-good** | **Faber 200-day SMA timing on SPY** (Faber 2007) — published, replicable, single-asset |
| **Calibration known-bad** | deliberate over-fit (multi-param SMA/threshold grid-searched to one window, e.g. 2020 COVID) |
| **Trial-budget tracking (Wall 4)** | local Postgres counter for Phase 2; Hindsight wiring in Phase 3 |

## 4. Stack

- **RiskLabAI** (BSD-3): PBO/CSCV, DSR/PSR, CPCV. Validated mathematically correct.
- **quantstats** (Apache-2.0): Sharpe/Sortino/CVaR/drawdown/tearsheets.
- pandas 3.0.3 / numpy 2.4.6 (already resolved; Phase-1 suite green).
- **RiskLabAI wrapper** (`services/trader/walls/`): assemble DSR (no one-call fn); feed effective-independent-N; NaN-guard PBO inputs.

## 5. Mahoraga-specific notes

- **Substrate-portable:** every wall + gate lives at `services/trader/walls/`, `services/trader/gates/`. No NemoClaw/OpenShell imports; Phase-3 adapters call them as plain functions.
- **Phase-1 deps the walls consume:** `backtest.FitnessReport` + the per-bar return series; `regime.CompositeRegime` (multi-regime, Wall 3); `features.BUILTIN_FEATURES` (sensitivity, Wall 2).
- **Calibration is a CI gate:** the "known-good promoted / known-bad rejected" assertion lands in `tests/integration/phase-2/calibration/` and runs in `integration-smoke` on real SPY data — not an operator script.

## 6. Sequencing

P2.1 (framework) ✅ → **P2.2 Wall 1** (next) → P2.3 Wall 2 ‖ P2.4 Wall 3 ‖ P2.5 Wall 4 (parallel after Wall 1) → P2.6 gates + calibration → exit. Wall validation uses controlled noise/edge fixtures; the gate calibration uses real SPY.

## 7. Definition of done

- All 6 sub-features' spec/plan/tasks + implementations merged.
- Walls unit-tested on known-ground-truth fixtures.
- Calibration green in CI on real SPY: Faber-SMA promoted, overfit canary rejected (PBO discriminator).
- Full evaluation pipeline <30 s/candidate (measured).
- All `tests/integration/phase-2/` green; `docs/measurements/phase-2-exit-verification.md` authored; `phase-2-complete` tag (operator confirmation).

After Phase 2: **Phase 3 — autoresearch loop**, which learns strategies and evaluates each against these walls + gates.
