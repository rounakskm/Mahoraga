# Phase 2 — Five-Wall Fortress Spec

**Status:** Approved 2026-04-26
**Type:** Phase-level spec
**Phase duration:** 6 weeks
**Anchor specs:** [`2026-04-25-mahoraga-architecture-decomposition.md`](2026-04-25-mahoraga-architecture-decomposition.md)
**Predecessor:** Phase 1

---

## 1. Goal

Build the **anti-overfitting fortress**: 5 independent walls plus 3-gate system, all as testable predicates with empirical calibration. Synthetic-data library for adversarial scenarios (incl. BTC-ETF–aware jump distributions). By Phase 2 exit, any candidate strategy can be evaluated against walls and gates in <30s.

## 2. Major Sub-Features

Each will get its own SDD feature spec:

1. **Wall 1 — Statistical Rigor.** Deflated Sharpe Ratio (DSR), Probability of Backtest Overfitting (PBO < 0.30 required), Monte Carlo permutation testing (real must beat 95% of shuffles), bootstrap confidence intervals.
2. **Wall 2 — Data Discipline.** Already partially done in Phase 1 (vault embargo at storage); this phase adds combinatorial purged cross-validation (PCV) and PIT-window enforcement at evaluation time.
3. **Wall 3 — Complexity Control.** Sensitivity analysis (parameter perturbation must not destroy edge), stability testing across rolling windows, Minimum Description Length (MDL) penalty.
4. **Wall 4 — Generalization.** Cross-asset testing (does it work on similar names?), multi-regime validation, ensemble diversity check via `synthetic-data` perturbation.
5. **Wall 5 — Meta-Awareness.** Trial-budget tracking (multiple-comparison correction), KB forbidden-pattern check (don't re-explore dead ends), search-process introspection.
6. **Three-gate system.** Fitness gate, robustness gate, risk gate; all three must pass for promotion. Outputs structured `GateReport` consumed by integration spec §6.4.
7. **`synthetic-data` library.** GBM with regime switching, jump-diffusion crash scenarios, historical-analogue path generation, BTC-aware jump distributions (BTC ETFs inherit underlying spot BTC vol characteristics — fatter tails, larger jumps).
8. **Calibration suite.** Known-good (e.g., a published 12-1 momentum) and known-bad (deliberately overfit on a specific window) historical strategies; Phase 2 exit requires walls correctly classifying both.

## 3. Exit Criteria

- Each of 5 walls is a callable predicate with deterministic unit tests
- Deliberate-overfit canary strategy is rejected by Wall 1 (PBO test) — automated assertion in `tests/integration/phase-2/`
- Three-gate system passes calibration: known-good strategy promoted, known-bad rejected
- `synthetic-data` library produces statistically faithful scenarios (realized stats per regime within tolerance of historical)
- Full evaluation pipeline runs <30s per candidate

## 4. Dependencies

- Phase 1 (data + features + regime detector + backtest harness skeleton)

## 5. Timeline & Sequencing — 6 weeks, 3 parallel streams

| Week | Stream A (Walls 1, 3, 5) | Stream B (Wall 4 + synthetic-data) | Stream C (Gates) |
|---|---|---|---|
| 1 | Wall 1 (DSR + PBO) | synthetic-data: GBM + regime switching | gate skeleton |
| 2 | Wall 1 (Monte Carlo + bootstrap) | synthetic-data: jump-diffusion (incl. BTC) | fitness gate |
| 3 | Wall 3 (sensitivity + MDL) | Wall 4 (cross-asset + multi-regime) | robustness gate |
| 4 | Wall 5 (trial budget + KB forbidden) | Wall 4 (ensemble perturbation) | risk gate |
| 5 | Wall integration tests | synthetic-data validation | gate calibration |
| 6 | Canary strategy + integration | known-good/known-bad calibration | full pipeline integration |

## 6. Phase-Specific Risks

- **Wall 1 statistical rigor is research-heavy.** PBO and DSR are real research math. Mitigation: implement against published references (Bailey & López de Prado for DSR; López de Prado for PBO); validate against published examples.
- **Synthetic-data fidelity.** If GBM doesn't match real return distributions, Wall 4 ensemble perturbation is misleading. Mitigation: per-regime realized stats validation; BTC-ETF distribution explicitly fatter-tailed.
- **Performance.** Walls must run fast or autoresearch loop is throttled. Mitigation: vectorize with numpy/pandas; profile and optimize the slowest wall.
- **Wall calibration drift.** Today's known-good strategy may not be known-good a decade from now. Mitigation: calibration suite versioned in git; review annually.

## 7. Open Questions for This Phase

- Threshold for "known-good" calibration strategy. Mitigation: pick a published strategy (12-1 momentum or RSI-2 mean-reversion) with documented historical performance.
- Wall 5 KB forbidden-pattern lookup: embedding similarity threshold. Decided in Phase 3 KB integration.
- Synthetic-data validation tolerance — what % deviation in realized stats is acceptable? Decided in `synthetic-data-spec.md`.
