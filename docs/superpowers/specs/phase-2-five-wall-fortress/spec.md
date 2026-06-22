# Phase 2 — Anti-Overfitting Fortress Spec

**Status:** Approved 2026-04-26; **revised 2026-06-22** (real-data-only, proven stat libs, 4 walls + 3 gates — see §0)
**Type:** Phase-level spec
**Anchor specs:** [`../2026-04-25-mahoraga-architecture-decomposition.md`](../2026-04-25-mahoraga-architecture-decomposition.md)
**Predecessor:** Phase 1; P2.1 wall framework merged (PR #40)

---

## 0. 2026-06-22 revision (what changed from the original)

Operator decisions reshaped this phase. The original five-wall plan assumed synthetic data, hand-rolled statistics, and a cross-sectional universe. Now:

- **Real data only — no synthetic-data library.** Backtest on actual SPY history. (Original sub-feature "synthetic-data" is **dropped**; cross-asset Wall-4 perturbation is deferred until we trade >1 instrument.)
- **Proven stat libraries, not hand-rolled.** **RiskLabAI** (BSD-3 — DSR/PSR/PBO/CPCV, validated correct) + **quantstats** (Apache-2.0). Avoid `mlfinlab` (proprietary) and `pypbo` (AGPL).
- **Latest pandas/numpy** (3.0.3 / 2.4.6); Phase-1 suite verified green on them.
- **4 walls + 3 gates** (was 5): old "Wall 2 Data Discipline" is folded into Wall 1 (RiskLabAI's CPCV *is* the data-discipline core).
- **Fundamentals are a future selection layer, not a wall** (separate design). A wall validates; it does not pick stocks or generate alpha.

## 1. Goal

Build the **anti-overfitting fortress**: 4 independent walls + a 3-gate system, each a deterministic, testable predicate. A wall answers *"is this strategy's edge real, or an artifact of overfitting / luck / fragility?"* — it is the **fitness predicate the Phase-3 autoresearch loop evaluates every learned candidate against**. By Phase 2 exit, any candidate strategy is evaluable against walls + gates in <30 s, and a real-data calibration suite proves the fortress accepts a known-good strategy and rejects a deliberate-overfit canary.

## 2. Major Sub-Features

Each gets its own SDD feature spec under this directory.

1. **Wall framework + `Wall` ABC** — `Wall.evaluate(ctx) → WallReport`, `EvaluationContext`, test doubles. **(P2.1, merged.)**
2. **Wall 1 — Statistical Rigor.** PBO (the headline overfitting metric, reject if ≥ 0.30), DSR/PSR, combinatorial purged + embargoed CV, PIT-eval leak check. Built on **RiskLabAI** + quantstats.
3. **Wall 2 — Complexity Control.** Parameter-sensitivity perturbation (±10/20% must not destroy edge), rolling-window stability, MDL penalty for parameter count.
4. **Wall 3 — Generalization.** Walk-forward / out-of-sample on the SPY history + multi-regime validation (Phase-1 regime detector). *(Cross-asset rotation deferred until >1 instrument.)*
5. **Wall 4 — Meta-Awareness.** Trial-budget tracking (multiple-comparison count feeding Wall 1's PBO/DSR #-trials); KB forbidden-pattern stub (Hindsight wiring in Phase 3).
6. **Three-gate system.** Fitness / Robustness / Risk gates; AND aggregation over `WallReport`s → `GateReport`.
7. **Calibration suite.** Real-data known-good (**Faber 200-day SMA timing on SPY** — Faber 2007) + known-bad (deliberate overfit on one window, e.g. 2020 COVID); Phase-2 exit requires walls/gates promote the good one and reject the bad one.

## 3. How walls are validated (no hand-picked strategy required)

A statistical gate is unit-tested with **controlled return-series fixtures with known ground truth** — the way the RiskLabAI validation worked:

- **pure-noise returns → walls REJECT** (PBO ≈ 0.5, DSR low),
- **injected persistent-edge returns → walls PASS.**

This proves wall *correctness* without choosing any trading strategy. The calibration suite (§2.7) then proves *integration* end-to-end on real SPY data.

## 4. Exit Criteria

- Each of the 4 walls is a callable, deterministic predicate with unit tests on known-ground-truth fixtures.
- **PBO is the discriminator:** the overfit canary is rejected; Faber-SMA passes — an automated assertion in `tests/integration/phase-2/calibration/` (runs in `integration-smoke`).
- Three-gate system passes calibration on **real SPY data**: known-good promoted, known-bad rejected.
- Full evaluation pipeline runs <30 s per candidate (measured).
- `docs/measurements/phase-2-exit-verification.md` authored; `phase-2-complete` tag (operator confirmation).

## 5. Dependencies

- Phase 1 (data + features + regime detector + backtest harness). SPY ~10yr daily already loaded (`data/parquet/ohlcv/SPY/`, `scripts/pull_spy_daily.py`).
- New deps: `RiskLabAI` (BSD-3), `quantstats` (Apache-2.0). Already on pandas 3.0.3 / numpy 2.4.6.

## 6. Phase-Specific Risks

- **RiskLabAI correctness caveats (validated).** No one-call DSR (assemble from `benchmark_sharpe_ratio` + `probabilistic_sharpe_ratio`); it uses raw trial-count N (anti-conservative DSR for correlated strategies → we feed an effective-independent-trials count); NaN in the PBO matrix propagates silently (→ NaN-guard inputs). All three handled in a thin wrapper. RiskLabAI itself reproduces Bailey & López de Prado values exactly.
- **Performance.** Walls must run fast or the Phase-3 loop is throttled. Vectorize; profile the slowest (PBO/CPCV) first.
- **Single instrument.** Only SPY → Wall 3 is walk-forward/multi-regime, not cross-asset (deferred). Calibration is single-asset timing rules, not cross-sectional.
- **Calibration drift.** Today's known-good may not hold in a decade. Calibration suite versioned in git; annual operator review.

## 7. Open Questions

- PBO reject threshold (default 0.30) and DSR threshold — tune against the calibration pair.
- Effective-independent-trials estimator for DSR (correlation-adjusted N) — decide in the Wall-1 sub-spec.
- Wall-4 KB forbidden-pattern similarity threshold — decided in Phase-3 KB integration.
