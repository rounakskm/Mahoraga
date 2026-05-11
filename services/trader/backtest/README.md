<!-- SPDX-License-Identifier: Apache-2.0 -->

# `services/trader/backtest` — Backtest Harness

Phase 1 sub-feature 6 — the last sub-feature of Phase 1. Provides a
PIT-correct, hard-limit-aware backtest engine that reads features +
regime classifications through the Phase-1 storage primitives and
emits a `FitnessReport`. Phase 3+ extends this with the autoresearch
loop's mutation engine.

Design docs:

- [`docs/superpowers/specs/phase-1-foundation/backtest-harness-spec.md`](../../../docs/superpowers/specs/phase-1-foundation/backtest-harness-spec.md)
- [`docs/superpowers/specs/phase-1-foundation/backtest-harness-plan.md`](../../../docs/superpowers/specs/phase-1-foundation/backtest-harness-plan.md)
- [`docs/superpowers/specs/phase-1-foundation/backtest-harness-tasks.md`](../../../docs/superpowers/specs/phase-1-foundation/backtest-harness-tasks.md)

## Layout

```
services/trader/backtest/
├── base.py            Strategy ABC + FitnessReport + validate_strategy()
├── strategies.py      BuyAndHold stub
├── engine.py          Backtest orchestrator (B2)
├── risk.py            Hard-limit firewall stub (B2)
└── tests/             per-component unit tests
```

## Usage

```python
from services.trader.backtest import Backtest, BuyAndHold
from services.trader.data.storage import ParquetAdapter
from services.trader.features.store import FeatureStore
from services.trader.regime.store import RegimeStore

bt = Backtest(
    feature_store=FeatureStore("data/parquet"),
    regime_store=RegimeStore("data/parquet"),
    ohlcv_adapter=ParquetAdapter("data/parquet"),
)
report = bt.run(
    strategy=BuyAndHold(),
    universe=["SPY", "QQQ"],
    start=date(2024, 1, 1),
    end=date(2025, 12, 31),
)
print(report.total_return, report.sharpe, report.max_drawdown)
print(report.per_regime["trending_low_vol"])  # {"return": ..., "sharpe": ..., "n_bars": ...}
```

## Placeholder-feature gate (P1.4 §6)

`validate_strategy()` rejects a `Strategy` that lists
`sentiment_score` (or any other `placeholder=True` feature) in
`requires_features` without setting `allow_placeholder_features=True`.
Phase 4 ships real sentiment; until then, sentiment-dependent
strategies must opt in explicitly to acknowledge they're training on
a placeholder.

## Status

| Chunk | Branch | Status |
|---|---|---|
| B1. Skeleton + BuyAndHold | `phase-1-backtest-skeleton` | Merged |
| B2. Engine + risk-limit firewall | `phase-1-backtest-engine-and-risk` | Merged |
| B3. End-to-end integration (closes Phase 1) | `phase-1-backtest-integration` | **In review (this PR — closes Phase 1)** |

## Substrate-portability

Pure Python. No NemoClaw / OpenClaw / OpenShell imports. The engine
uses pandas + numpy only; vectorbt was rejected for Phase 1 because
it introduces a heavy C dependency without justifying itself at this
scope. The `audit-xls` reviewer prompt at
`services/trader/prompts/reviewer/audit-xls.md` catches look-ahead
bias on every backtest output (already merged).
