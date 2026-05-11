<!-- SPDX-License-Identifier: Apache-2.0 -->

# `services/trader/features` — Feature Pipeline

Phase 1 sub-feature 4. Computes 70+ engineered features over the trading
universe and persists them to parquet with the same vault-embargo + PIT
correctness guarantees as raw OHLCV.

Design docs:

- [`docs/superpowers/specs/phase-1-foundation/feature-pipeline-spec.md`](../../../docs/superpowers/specs/phase-1-foundation/feature-pipeline-spec.md)
- [`docs/superpowers/specs/phase-1-foundation/feature-pipeline-plan.md`](../../../docs/superpowers/specs/phase-1-foundation/feature-pipeline-plan.md)
- [`docs/superpowers/specs/phase-1-foundation/feature-pipeline-tasks.md`](../../../docs/superpowers/specs/phase-1-foundation/feature-pipeline-tasks.md)

## Layout

```
services/trader/features/
├── base.py            Feature ABC + FeatureContext + registry + Arrow schema helpers
├── pipeline.py        FeaturePipeline orchestrator (read OHLCV → compute → write)
├── store.py           FeatureStore parquet I/O with PIT view + vault enforcement
├── trend.py           Trend-category Feature implementations (10 features)
├── momentum.py        Momentum-category (10 features)
├── volatility.py      Volatility-category (10 features)
├── volume.py          Volume-category (chunk F3, planned)
├── statistical.py     Statistical-category (chunk F3, planned)
├── macro.py           Macro features w/ PIT macro fetch (chunk F4, planned)
├── sentiment.py       Placeholder sentiment_score (chunk F5, planned)
└── tests/             Per-category unit tests + pipeline test
```

## Usage

```python
from datetime import UTC, date, datetime
from services.trader.data.storage import ParquetAdapter
from services.trader.features import FeaturePipeline
from services.trader.features.store import FeatureStore

# OHLCV adapter (P1.1) — vault-aware by default; pass vault_cutoff_days=None
# only for backfill/synthetic flows.
adapter = ParquetAdapter("data/parquet")

# Feature store — separate from OHLCV; same on-disk layout, dynamic schema.
store = FeatureStore("data/parquet/features", vault_cutoff_days=180)

pipeline = FeaturePipeline(adapter=adapter, store=store)
result = pipeline.compute(
    tickers=["SPY", "QQQ", "IWM"],
    start=date(2024, 1, 1),
    end=date(2025, 12, 31),
)
print(f"wrote {result.rows_written} feature rows; non-null counts: {result.per_feature_non_null}")
```

PIT-correct read:

```python
from services.trader.features import BUILTIN_FEATURES
df = store.read(
    keys=["SPY"],
    start=datetime(2024, 1, 1, tzinfo=UTC),
    end=datetime(2025, 12, 31, tzinfo=UTC),
    asof=datetime(2026, 5, 1, tzinfo=UTC),
    features=BUILTIN_FEATURES,
)
```

## Status

| Chunk | Branch | Status |
|---|---|---|
| F1. Skeleton + 10 trend features | `phase-1-features-skeleton` | Merged |
| F2. Momentum + volatility (20 features) | `phase-1-features-momentum-volatility` | **In review (this PR)** |
| F3. Volume + statistical | `phase-1-features-volume-statistical` | Planned |
| F4. Macro | `phase-1-features-macro` | Planned |
| F5. Sentiment placeholder + coverage + audit | `phase-1-features-sentiment-and-coverage` | Planned |
| F6. End-to-end integration | `phase-1-features-integration` | Planned |

## Substrate-portability

Pure Python. No NemoClaw / OpenClaw / OpenShell imports. Every feature is
a deterministic function of OHLCV (and optionally PIT-correct macro data);
tests rely on this for reproducibility. The `audit-xls` reviewer prompt's
look-ahead-bias check (already on main at `services/trader/prompts/reviewer/
audit-xls.md`) catches any feature implementation that reads "future" bars.
