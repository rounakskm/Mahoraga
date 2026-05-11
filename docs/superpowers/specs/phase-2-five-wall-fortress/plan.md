# Phase 2 — Five-Wall Fortress Plan

**Status:** Drafted 2026-05-11
**Spec:** [`spec.md`](spec.md) (approved 2026-04-26)
**Anchor specs:** [`../2026-04-25-mahoraga-architecture-decomposition.md`](../2026-04-25-mahoraga-architecture-decomposition.md)
**Predecessor:** Phase 1 (implementation-complete; `phase-1-complete` tag pending operator confirmation)
**Phase duration:** 6 weeks, 3-stream parallelism

---

## 1. Plan summary

Ship the anti-overfitting fortress in **eight sub-features**, each
with its own `<feature>-spec.md` + `<feature>-plan.md` + `<feature>-tasks.md`
under this directory. By Phase 2 exit, any candidate strategy can be
evaluated against five walls + a three-gate system in <30 s, and the
calibration suite proves the fortress correctly accepts a known-good
strategy and rejects a deliberate-overfit canary.

By Phase 2 exit, downstream phases consume:

- A `Wall.evaluate(strategy, backtest_result) → WallReport` predicate
  per wall, all 5 deterministic and unit-tested.
- A `GateSystem.evaluate(strategy, backtest_result) → GateReport`
  that runs the 3 gates and aggregates pass/fail.
- A `synthetic-data` library that produces statistically faithful
  scenarios (GBM with regime switching, jump-diffusion crashes,
  historical-analogue paths, BTC-aware fat-tail variants).
- A calibration suite — versioned known-good + known-bad strategies
  — that any Phase-3 mutation engine can read directly.

## 2. Sub-features (8 total)

Each becomes its own spec → plan → tasks chain inside
`phase-2-five-wall-fortress/`. Streams A (walls 1/3/5), B (wall 4 +
synthetic-data), and C (gates + calibration) run in parallel after
the wall ABC ships in P2.0.

| # | Sub-feature | Stream | Depends on | Spec filename |
|---|---|---|---|---|
| 1 | **Wall framework + `Wall` ABC** | A (critical path) | Phase 1 P1.6 (Backtest) | `wall-framework-spec.md` |
| 2 | **Wall 1 — Statistical Rigor** (DSR + PBO + Monte Carlo + bootstrap) | A | (1) | `wall-1-statistical-rigor-spec.md` |
| 3 | **Wall 2 — Data Discipline** (combinatorial PCV + PIT-eval enforcement) | A | (1) + Phase 1 P1.3 | `wall-2-data-discipline-spec.md` |
| 4 | **Wall 3 — Complexity Control** (sensitivity + stability + MDL) | A | (1) | `wall-3-complexity-control-spec.md` |
| 5 | **Wall 4 — Generalization** (cross-asset + multi-regime + ensemble diversity) | B | (1) + (8) `synthetic-data` | `wall-4-generalization-spec.md` |
| 6 | **Wall 5 — Meta-Awareness** (trial-budget tracking + KB forbidden-pattern check) | A | (1); Hindsight integration deferred to Phase 3 | `wall-5-meta-awareness-spec.md` |
| 7 | **Three-gate system + integration** (fitness / robustness / risk gates + canary calibration) | C | (2)–(6) | `gate-system-spec.md` |
| 8 | **`synthetic-data` library** | B | Phase 1 P1.5 regime detector (regime taxonomy) | `synthetic-data-spec.md` |

## 3. Decisions to lock at sub-spec time

| Decision | Default if undecided |
|---|---|
| **PBO threshold** (Wall 1 reject if PBO ≥ ?) | 0.30 per spec.md §2. Tune after calibration. |
| **Monte Carlo permutation count** | 1,000 shuffles minimum per evaluation; 10,000 if profile says we can afford it. |
| **PCV split count** | 6 train / 2 test combinatorial splits (López de Prado default). |
| **Synthetic-data per-regime tolerance** | ±15% on realized vol vs the historical regime sample. Calibrated against the Phase-1 vault holdout. |
| **Calibration "known-good" strategy** | 12-1 momentum (Jegadeesh-Titman) — published, replicable, baseline. |
| **Calibration "known-bad" strategy** | Deliberate over-fit on a specific 2020-Q1 vol window. |
| **Trial-budget tracking shape (Wall 5)** | Local Postgres counter for Phase 2; Hindsight integration ships in Phase 3 alongside the autoresearch-loop curator. |

## 4. Sequencing — 6 weeks, 3 streams

Same week-by-week table as spec §5, refined with concrete sub-feature
filenames:

| Week | Stream A (Walls 1/2/3/5) | Stream B (Wall 4 + synthetic-data) | Stream C (Gates) |
|---|---|---|---|
| 1 | `wall-framework-spec.md` + `Wall` ABC + `WallReport` dataclass; `wall-1-statistical-rigor-spec.md`; DSR + PBO scaffolds | `synthetic-data-spec.md`; GBM + regime-switching baseline | `gate-system-spec.md` skeleton: ABC + `GateReport` dataclass |
| 2 | Wall 1: Monte Carlo permutation + bootstrap CI | synthetic-data: jump-diffusion + BTC-aware variants | Fitness gate (DSR + sharpe + win-rate thresholds) |
| 3 | `wall-2-data-discipline-spec.md`; combinatorial PCV + PIT-eval enforcement | Wall 4 (cross-asset + multi-regime testing) | Robustness gate (PCV + sensitivity must agree) |
| 4 | `wall-3-complexity-control-spec.md`; sensitivity + MDL + stability tests | Wall 4 (ensemble diversity via synthetic perturbation) | Risk gate (max-drawdown + tail-loss thresholds) |
| 5 | `wall-5-meta-awareness-spec.md`; trial-budget tracker + KB forbidden-pattern stub | synthetic-data validation (realized stats per regime) | Gate-system integration + canary calibration suite |
| 6 | All-walls integration test + perf measurement (target <30 s/candidate) | Synthetic-data fidelity report | Full pipeline integration; known-good promotion, known-bad rejection |

## 5. Mahoraga-specific implementation notes

### 5.1 Substrate-portable Python

Per CLAUDE.md §Practices: every wall + gate + synthetic-data lives
at `services/trader/walls/`, `services/trader/gates/`,
`services/trader/synthetic/`. No NemoClaw / OpenClaw / OpenShell
imports. Phase-3 autoresearch-loop adapters live in
`infra/nemoclaw/` and call the walls as Python functions.

### 5.2 Cherry-pick candidates from `vendor/`

- **López de Prado reference implementations** — if a third-party
  implementation of DSR / PBO / PCV exists under MIT/Apache in the
  ecosystem, cherry-pick into `services/trader/walls/` with
  attribution per the existing `vendor/_external_refs/` pattern.
  Otherwise implement against the published papers (Bailey & López
  de Prado 2014 for DSR; López de Prado 2015 for PBO).

### 5.3 Phase-1 dependencies

The walls consume:
- `services/trader/backtest/FitnessReport` — every wall takes one
  + the strategy ABC + the backtest's per-bar return series
- `services/trader/regime/CompositeRegime` for multi-regime
  validation (Wall 4) and synthetic-data regime-switching
- `services/trader/features/BUILTIN_FEATURES` registry — sensitivity
  testing perturbs feature inputs and re-runs the backtest

### 5.4 Calibration as a CI gate

The Phase-2 exit criterion §3 — "known-good strategy promoted,
known-bad rejected" — must be a CI assertion, not an operator-run
script. Lands in `tests/integration/phase-2/calibration/` and runs
in the `integration-smoke` job alongside the Phase-1 chains.

## 6. Risks (carried from spec §6 + new at plan time)

| Risk | Mitigation |
|---|---|
| Wall 1 statistical rigor is research-heavy | Implement against published references; validate against published examples; cherry-pick reference impls where licensing allows |
| Synthetic-data fidelity drift | Per-regime realized-stats validation; tolerance in `synthetic-data-spec.md`; BTC-aware fat-tail explicitly documented |
| Performance — 30 s/candidate target | Profile Wall 1 (Monte Carlo permutation) first; vectorize aggressively; fall back to parallel evaluation across walls if needed |
| Wall calibration drift over years | Calibration suite versioned in git; annual operator review documented in `wall-calibration-spec.md` §maintenance |
| Hindsight integration premature in Wall 5 | Phase-2 Wall 5 uses a local Postgres trial-counter; Hindsight wiring is a Phase-3 concern alongside the autoresearch-loop curator |

## 7. Definition of done

Phase 2 done when:

- All 8 sub-feature specs / plans / tasks committed
- All 8 sub-feature implementations merged to `main`
- Calibration suite green in CI: known-good promoted, known-bad rejected
- Full evaluation pipeline <30 s per candidate (measured)
- All `tests/integration/phase-2/` suites green in CI
- `docs/measurements/phase-2-exit-verification.md` authored
- `phase-2-complete` tag pushed with operator confirmation

After Phase 2: **Phase 3 — autoresearch loop core.** The walls + gates
become the predicate the mutation engine evaluates every candidate
against; the synthetic-data library powers ensemble-diversity
perturbations.
