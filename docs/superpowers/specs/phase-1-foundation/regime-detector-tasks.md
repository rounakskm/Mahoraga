# Regime Detector — Tasks

**Status:** Drafted 2026-05-11
**Spec:** [`regime-detector-spec.md`](regime-detector-spec.md)
**Plan:** [`regime-detector-plan.md`](regime-detector-plan.md)

Task IDs use prefix `P1.5.x` to match the parent [`tasks.md`](tasks.md).

## Legend

- `[code]` = implementation
- `[test]` = pytest fixture / test
- `[doc]` = README / methodology note
- `[infra]` = config / CI
- `→` = depends on

---

## P1.5.R1 — Skeleton + MESO lens

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.5.R1.1** | [code] | `services/trader/regime/__init__.py` + `base.py` — `Lens` ABC, `ClassificationResult`, `CompositeRegime`, `RegimeRunResult` | — |
| **P1.5.R1.2** | [code] | `services/trader/regime/meso.py` — `MesoLens` rule-based detector using `adx_14` + `realized_vol_pct_60`; returns one of the four MESO labels + confidence | P1.5.R1.1 |
| **P1.5.R1.3** | [code] | `services/trader/regime/detector.py` — `RegimeDetector` skeleton: reads required feature columns + macro row at `asof`, dispatches to lenses, composes result in memory (no storage yet) | P1.5.R1.1 + P1.5.R1.2 |
| **P1.5.R1.4** | [test] | `services/trader/regime/tests/test_base.py` — ABC contract, dataclass roundtrip, NaN-undefined path | P1.5.R1.1 |
| **P1.5.R1.5** | [test] | `services/trader/regime/tests/test_meso.py` — one fixture per MESO label + confidence math against hand-derived expected values | P1.5.R1.2 |
| **P1.5.R1.6** | [doc]  | `services/trader/regime/README.md` — package layout + chunk status table + `RegimeDetector` usage example | P1.5.R1.1 |

PR: `phase-1-regime-skeleton`.

## P1.5.R2 — MACRO lens + composite confidence

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.5.R2.1** | [code] | `services/trader/regime/macro.py` — `MacroLens` using `yield_2s10s` + `vix_level` + `dxy_change_20d`; returns `bull`/`bear`/`transitioning` + confidence | P1.5.R1 done |
| **P1.5.R2.2** | [code] | `RegimeDetector` composes MESO + MACRO; `composite_conf = min(meso_conf, macro_conf)` | P1.5.R2.1 + P1.5.R1.3 |
| **P1.5.R2.3** | [test] | `services/trader/regime/tests/test_macro.py` — one fixture per MACRO label + the transitioning boundary | P1.5.R2.1 |
| **P1.5.R2.4** | [test] | `services/trader/regime/tests/test_composite.py` — 4×3 label-matrix sweep + NaN-injection asserting `composite_conf == 0.0` when either lens undefined | P1.5.R2.2 |
| **P1.5.R2.5** | [doc]  | Update `services/trader/regime/README.md` with the macro labels | P1.5.R2.1 |

PR: `phase-1-regime-macro`.

## P1.5.R3 — RegimeStore + audit

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.5.R3.1** | [code] | `services/trader/regime/store.py` — `RegimeStore` parquet writer: layout `<root>/regime/<SCOPE>/<YEAR>.parquet`; dynamic schema driven by the active lens names | P1.5.R2 done |
| **P1.5.R3.2** | [code] | `RegimeStore.read` PIT view + vault enforcement (same shape as `FeatureStore`) | P1.5.R3.1 |
| **P1.5.R3.3** | [code] | `RegimeDetector` wires `manifest_root` + `audit_writer` kwargs; emits one `IngestRun` row + one `audit.events` row per `classify()` invocation | P1.5.R3.1 + P1.5.R2.2 |
| **P1.5.R3.4** | [test] | `services/trader/regime/tests/test_store.py` — round-trip, vault embargo + override, idempotent re-run dedupe on `(scope, asof)` | P1.5.R3.1 + P1.5.R3.2 |
| **P1.5.R3.5** | [test] | `services/trader/regime/tests/test_detector_audit.py` — `_FakeAuditWriter` records exactly one `classify` row per run | P1.5.R3.3 |

PR: `phase-1-regime-store-and-audit`.

## P1.5.R4 — End-to-end integration

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.5.R4.1** | [test] | `tests/integration/phase-1/regime/__init__.py` + `test_end_to_end.py` — full path: yfinance fake → ParquetAdapter → FeaturePipeline → RegimeDetector; verify parquet on disk + manifest rows + audit-events chain across (ingest, compute, classify) | P1.5.R3 done |
| **P1.5.R4.2** | [test] | Known-regime fixture: hand-asserted labels for 2017-summer / 2018-Q4 / 2020-Q1 synthetic series mirroring the regimes | P1.5.R4.1 |
| **P1.5.R4.3** | [infra] | Extend `.github/workflows/ci.yml` integration-smoke job to run the new path | P1.5.R4.1 |
| **P1.5.R4.4** | [doc]  | Tick parent `tasks.md` P1.5 row complete with PR-number references | P1.5.R4.3 |

PR: `phase-1-regime-integration`.

---

## Cross-chunk parallelism

R1 is single-thread (it ships the contract + MESO lens). R2 depends
on R1 only for the dataclass definitions, so R2 cannot start until R1
is merged. R3 depends on the composite output (R2). R4 closes.

This is a fully serial chain — the regime detector is a single
self-consistent abstraction; splitting it across more parallel
branches than four was rejected during planning as not worth the merge
overhead.

## Task ownership note

All four chunks are sized for a single subagent; the optional
parallelism that the feature pipeline benefited from (independent
category files) doesn't apply here — each lens depends on the
composite definition shipped in R1 / R2.
