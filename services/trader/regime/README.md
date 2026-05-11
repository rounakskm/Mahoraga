<!-- SPDX-License-Identifier: Apache-2.0 -->

# `services/trader/regime` — Regime Detector

Phase 1 sub-feature 5. Produces a daily, PIT-correct **composite
regime label** + `0.0–1.0` **confidence score** for the US-equity
universe, derived from the features the pipeline emits.

Design docs:

- [`docs/superpowers/specs/phase-1-foundation/regime-detector-spec.md`](../../../docs/superpowers/specs/phase-1-foundation/regime-detector-spec.md)
- [`docs/superpowers/specs/phase-1-foundation/regime-detector-plan.md`](../../../docs/superpowers/specs/phase-1-foundation/regime-detector-plan.md)
- [`docs/superpowers/specs/phase-1-foundation/regime-detector-tasks.md`](../../../docs/superpowers/specs/phase-1-foundation/regime-detector-tasks.md)

## Layout

```
services/trader/regime/
├── base.py            Lens ABC + ClassificationResult + CompositeRegime dataclasses
├── meso.py            MesoLens (rule-based, ADX × realized_vol_pct_60)
├── detector.py        RegimeDetector orchestrator (in-memory; R3 adds storage)
└── tests/             per-lens + detector unit tests
```

## Usage (R1 — in-memory only)

```python
from services.trader.regime import RegimeDetector, MesoLens

detector = RegimeDetector(lenses=[MesoLens()])
result = detector.classify(scope="universe", feature_frame=feature_df)
for row in result.rows:
    print(row.meso, row.composite_conf)
```

`feature_df` must include columns named by each lens's
`required_features()`. R3 wires `RegimeDetector` to read directly
from `FeatureStore` + `ParquetAdapter`.

## Regime taxonomy

### MESO lens (R1) — 4 labels

| Label | Trigger |
|---|---|
| `trending_low_vol`  | `adx_14 >= 25` AND `realized_vol_pct_60 <= 0.40` |
| `trending_high_vol` | `adx_14 >= 25` AND `realized_vol_pct_60 > 0.40`  |
| `ranging_low_vol`   | `adx_14 < 25`  AND `realized_vol_pct_60 <= 0.40` |
| `ranging_high_vol`  | `adx_14 < 25`  AND `realized_vol_pct_60 > 0.40`  |

`UNDEFINED_LABEL` when either input is NaN.

### MACRO lens (R2) — `bull` / `bear` / `transitioning`

Lands in chunk R2 (see plan).

## Confidence

Per-lens confidence is the minimum of the per-axis normalized
distances to the rule thresholds; composite confidence is the
minimum across lenses. Conservative by design: when either lens is
uncertain, the composite is uncertain. The Phase-7 hard-limit firewall
reads this directly (`composite_conf < 0.40` → halt new entries).

## Status

| Chunk | Branch | Status |
|---|---|---|
| R1. Skeleton + MESO lens | `phase-1-regime-skeleton` | **In review (this PR)** |
| R2. MACRO lens + composite | `phase-1-regime-macro` | Planned |
| R3. RegimeStore + audit | `phase-1-regime-store-and-audit` | Planned |
| R4. End-to-end integration | `phase-1-regime-integration` | Planned |

## Substrate-portability

Pure Python. No NemoClaw / OpenClaw / OpenShell imports. Lenses are
pure functions of pre-fetched feature rows; the orchestrator is the
only piece that knows about parquet I/O. R3 wires the storage layer.
