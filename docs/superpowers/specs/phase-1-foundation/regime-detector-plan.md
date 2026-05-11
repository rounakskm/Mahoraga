# Regime Detector — Implementation Plan

**Status:** Drafted 2026-05-11
**Spec:** [`regime-detector-spec.md`](regime-detector-spec.md)
**Parent plan:** [`plan.md`](plan.md)

Four PR-sized chunks, each ~30-50 min review. R1 lands the contract +
the MESO lens (the simpler of the two). R2 adds the MACRO lens. R3
wires storage + audit. R4 closes with an end-to-end integration test.

```
[R1 skeleton + MESO lens]
       │
       ▼
[R2 MACRO lens + composite confidence wiring]
       │
       ▼
[R3 RegimeStore parquet + manifest + audit-events]
       │
       ▼
[R4 end-to-end integration test + CI]
```

R3 depends on R2 (composite output is what gets stored). R2 depends on
R1 (Lens ABC + composite dataclass). R4 closes the chain.

## 1. Chunk R1 — Skeleton + MESO lens

**Branch:** `phase-1-regime-skeleton`
**Target review time:** ~45 min

Lands:
- `services/trader/regime/__init__.py`, `base.py` (`Lens` ABC,
  `ClassificationResult`, `CompositeRegime` dataclasses)
- `services/trader/regime/meso.py` (`MesoLens` rule-based detector)
- `services/trader/regime/detector.py` (`RegimeDetector` skeleton —
  composes lenses but stores nothing yet; returns
  `RegimeRunResult` in memory)
- `services/trader/regime/tests/test_meso.py` covering all 4 labels +
  the NaN-undefined path + confidence math
- README under `services/trader/regime/`

Acceptance:
- `pytest services/trader/regime/tests/` green
- `Lens` ABC enforces `name`, `required_features`, `classify`
- `MesoLens` returns deterministic labels on hand-built synthetic
  series (one fixture per label)

## 2. Chunk R2 — MACRO lens + composite confidence

**Branch:** `phase-1-regime-macro`
**Target review time:** ~40 min

Lands:
- `services/trader/regime/macro.py` (`MacroLens` rule-based detector
  using 2s10s + VIX + DXY)
- Per-lens unit tests for bull / bear / transitioning labels
- Detector composes MESO + MACRO; `composite_conf = min(...)` is
  exercised by a test
- README updated with the macro labels

Acceptance:
- `pytest services/trader/regime/tests/` green
- A 4×3 = 12-cell label-matrix test sweeps every MESO × MACRO pair on
  synthetic inputs and asserts the right composite
- A NaN-injection test asserts `composite_conf == 0.0` when either
  lens returns `undefined`

## 3. Chunk R3 — RegimeStore + audit

**Branch:** `phase-1-regime-store-and-audit`
**Target review time:** ~45 min

Lands:
- `services/trader/regime/store.py` (`RegimeStore` parquet writer —
  same on-disk layout pattern as `FeatureStore`; dynamic schema
  driven by the lens names)
- Detector wires `ManifestWriter` + `PostgresAuditWriter` per the
  P1.4 F5 pattern; `manifest_root` + `audit_writer` kwargs on
  `RegimeDetector.__init__`
- Tests:
  - `RegimeStore` round-trip on synthetic input
  - `RegimeStore` vault embargo with override
  - `RegimeDetector` writes 1 manifest row + 1 audit-events row per
    `classify()` invocation (uses a `_FakeAuditWriter`)
  - Idempotent re-run: same `(scope, asof)` keeps the latest
    `fetched_at`

Acceptance:
- All unit tests green
- Hash-chain verification piggybacks on the existing audit utilities
  — no new chokepoint

## 4. Chunk R4 — End-to-end integration

**Branch:** `phase-1-regime-integration`
**Target review time:** ~40 min

Lands:
- `tests/integration/phase-1/regime/test_end_to_end.py` — full chain:
  yfinance fake → ParquetAdapter → FeaturePipeline → RegimeDetector
  → parquet + manifest + audit-events; hash chain links across
  (`ingest`, `compute`, `classify`) rows
- CI workflow extension to run the new suite in the
  `integration-smoke` job
- Update `tasks.md` to mark P1.5 complete

Acceptance:
- `pytest tests/integration/phase-1/regime -v` green in CI
- Audit hash chain verifies row-by-row from the test's seed across
  all three action types

## 5. Per-chunk PR template

Same as P1.1 / P1.2 / P1.3 / P1.4:

```
## Summary
1-3 bullets — what this chunk lands.

## Scope
- In-scope:
- Out-of-scope (deferred to chunk N):

## Test plan
- [ ] pytest <path>
- [ ] CI green on lint + unit-tests + integration-smoke
- [ ] Cross-check against regime-detector-spec.md §<section>
```

## 6. Risks during implementation

| Risk | Mitigation |
|---|---|
| Threshold values misclassify historical regimes | R4 includes a known-regime fixture (2020-Q1, 2017-summer, 2018-Q4) with hand-asserted labels; threshold tweaks need a justifying commit |
| NaN cascade during warmup | Lens returns `undefined / 0.0`; the detector logs + records gaps; tests cover the warmup path |
| Hash chain breaks under parallel writes | Phase 1 detector runs serially; per-actor sharding deferred to Phase 3 |
| Composite collapses to 0 when one lens is undefined | By design; documented; the operator notices in the daily manifest |

## 7. Definition of done

P1.5 done when chunks R1–R4 are all merged, both MESO and MACRO lenses
produce deterministic labels on the per-label fixtures, the
known-regime fixture passes, idempotent re-runs preserve the latest
classification, and the end-to-end integration test is green in CI.

After P1.5: P1.6 (backtest harness) can wire `RegimeDetector` as a
read-only dependency — the harness asks the detector for the
classification at every backtest bar, no recomputation.
