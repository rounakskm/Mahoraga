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
├── macro.py           MacroLens (rule-based, yield_2s10s + vix_level + dxy_change_20d)
├── detector.py        RegimeDetector orchestrator (storage + manifest + audit)
├── store.py           RegimeStore parquet I/O with PIT view + vault enforcement
└── tests/             per-lens + detector + store + composite unit tests
```

## Usage (R1 — in-memory only)

```python
from services.trader.regime import (
    MacroLens, MesoLens, RegimeDetector, RegimeStore,
)
from services.trader.data.audit import PostgresAuditWriter

store = RegimeStore("data/parquet", vault_cutoff_days=180)
detector = RegimeDetector(
    lenses=[MesoLens(), MacroLens()],
    store=store,
    manifest_root="data/parquet",
    audit_writer=PostgresAuditWriter(dsn=os.environ.get("MAHORAGA_AUDIT_DSN")),
)
result = detector.classify(
    scope="universe",
    feature_frame=feature_df,
    macro_frame=macro_df,
)
for row in result.rows:
    print(row.meso, row.macro, row.composite_conf)
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

### MACRO lens (R2) — 3 labels

| Label | Trigger (`macro_score` ∈ [-1, 1]) |
|---|---|
| `bull`          | `macro_score >= 0.50`  |
| `bear`          | `macro_score <= -0.50` |
| `transitioning` | otherwise              |

`macro_score = (curve_signal + vix_signal + dxy_signal) / 3` where each
signal is `±1` (or `0` for VIX in the 18–25 band). `macro_conf = abs(macro_score)`.

## Confidence

Per-lens confidence is the minimum of the per-axis normalized
distances to the rule thresholds; composite confidence is the
minimum across lenses. Conservative by design: when either lens is
uncertain, the composite is uncertain. The Phase-7 hard-limit firewall
reads this directly (`composite_conf < 0.40` → halt new entries).

## Status

| Chunk | Branch | Status |
|---|---|---|
| R1. Skeleton + MESO lens | `phase-1-regime-skeleton` | Merged |
| R2. MACRO lens + composite | `phase-1-regime-macro` | Merged |
| R3. RegimeStore + audit | `phase-1-regime-store-and-audit` | Merged |
| R4. End-to-end integration | `phase-1-regime-integration` | **In review (this PR)** |

## Substrate-portability

Pure Python. No NemoClaw / OpenClaw / OpenShell imports. Lenses are
pure functions of pre-fetched feature rows; the orchestrator is the
only piece that knows about parquet I/O. R3 wires the storage layer.
