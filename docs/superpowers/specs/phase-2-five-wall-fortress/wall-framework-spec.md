# Phase 2 — Wall Framework Spec (sub-feature 1)

**Status:** Drafted 2026-06-07
**Parent:** [`spec.md`](spec.md), [`plan.md`](plan.md), [`tasks.md`](tasks.md)
**Predecessors:** P1.6 backtest harness merged (`main`, PR #36)
**Closes:** P2.1

---

## 1. Goal

Ship the **shared wall contract** that all five anti-overfitting walls
implement. By P2.1 exit, every subsequent wall (P2.2–P2.6) can be
coded against a single, stable interface without knowing about the
others. The gate system (P2.7) aggregates `WallReport`s produced by
this interface.

By exit, downstream code calls each wall identically:

```python
from services.trader.walls import EvaluationContext, WallReport
from services.trader.walls.wall_1_statistical import StatisticalRigorWall

ctx = EvaluationContext(
    strategy=my_strategy,
    backtest_result=fitness_report,   # FitnessReport from P1.6
    returns=per_bar_returns,          # pd.Series indexed by date
    feature_frame=feature_df,         # from FeatureStore
    regime_frame=regime_df,           # from RegimeStore
)
report: WallReport = StatisticalRigorWall().evaluate(ctx)
print(report.passed, report.score, report.reason)
```

---

## 2. `EvaluationContext` dataclass

```python
@dataclass(frozen=True)
class EvaluationContext:
    strategy: Strategy                  # P1.6 Strategy ABC
    backtest_result: FitnessReport      # P1.6 FitnessReport (frozen dataclass)
    returns: pd.Series                  # per-bar portfolio returns; DatetimeIndex
    feature_frame: pd.DataFrame         # full feature frame (PIT-correct, asof=end)
    regime_frame: pd.DataFrame          # full regime frame (PIT-correct, asof=end)
    universe: list[str]                 # tickers evaluated in the backtest
    metadata: dict[str, object] = field(default_factory=dict)
```

### Field contracts

| Field | Type | Contract |
|---|---|---|
| `strategy` | `Strategy` | The exact strategy instance that produced `backtest_result`. Walls may call `strategy.name`, `strategy.requires_features`, and `strategy.allow_placeholder_features`. They must not call `generate_signals()` (that is the backtest engine's job). |
| `backtest_result` | `FitnessReport` | Produced by P1.6 `Backtest.run()`. Walls may read any field: `sharpe`, `total_return`, `max_drawdown`, `win_rate`, `num_trades`, `per_regime`, `halted_at`, `rejected_reason`. |
| `returns` | `pd.Series[float]` | Portfolio-level daily return per bar, already net of commission + slippage. Index is `DatetimeIndex`. Length = number of bars in the backtest window. Never empty. |
| `feature_frame` | `pd.DataFrame` | Full PIT-correct feature matrix from `FeatureStore.read()` for the strategy's `requires_features` columns + all BUILTIN_FEATURES that the wall needs (e.g. Wall 3 reads ADX to perturb). Multi-level columns `(ticker, feature_name)` or flat depending on FeatureStore's output shape. Walls must not read columns beyond the documented set for that wall — enforced by assertion in tests. |
| `regime_frame` | `pd.DataFrame` | Full PIT-correct regime classifications from `RegimeStore.read()`. Wall 4 uses this for multi-regime split testing. |
| `universe` | `list[str]` | Ordered list of ticker symbols. Same tickers as those in `returns.columns` (if multi-ticker) or the primary ticker. Stable across the evaluation session. |
| `metadata` | `dict` | Optional pass-through for callers to attach experiment metadata (trial-id, parameter snapshot, etc.) for Wall 5's trial-budget tracker. Not required; defaults to `{}`. |

---

## 3. `WallReport` dataclass

```python
@dataclass(frozen=True)
class WallReport:
    wall_name: str           # machine-readable; matches Wall.name class var
    passed: bool             # True = strategy clears this wall
    score: float             # 0.0–1.0; higher = more confidence in the strategy
    reason: str              # human-readable one-sentence verdict
    sub_results: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
```

### Field contracts

| Field | Type | Contract |
|---|---|---|
| `wall_name` | `str` | Must equal `Wall.name` of the producing wall. The gate system uses this to index reports. |
| `passed` | `bool` | **The gate system aggregates these with AND.** A strategy clears the fortress only if every wall returns `passed=True`. |
| `score` | `float` | Continuous quality signal in [0, 1]. Used by the calibration suite and Phase-3 mutation engine to rank candidates. `score >= 0.5` is the passing half-space, but the hard gate is `passed`, not `score`. |
| `reason` | `str` | One sentence explaining the verdict in human-readable terms, e.g. `"DSR=0.03 (threshold 0.05) — 42 effective trials"`. Written for the Hindsight fact store and the audit log. |
| `sub_results` | `dict` | Wall-specific evidence: numeric sub-test scores, p-values, CIs, sensitivity deltas. Schema defined per wall. Gate system forwards these verbatim to the caller. |
| `metadata` | `dict` | Timing, iteration counts, seed values for reproducibility. |

### Canonical sub_results schemas (per wall)

Each wall's spec defines its `sub_results` keys. The framework does
not validate them — that is the wall's own responsibility. The gate
system exposes them read-only.

---

## 4. `Wall` ABC

```python
from abc import ABC, abstractmethod
from typing import ClassVar

class Wall(ABC):
    name: ClassVar[str]   # snake_case; unique across all walls

    @abstractmethod
    def evaluate(self, ctx: EvaluationContext) -> WallReport: ...
```

### Contracts

1. **Deterministic.** `evaluate(ctx)` must return the same `WallReport`
   for the same `ctx` (same strategy + same data). If randomness is
   needed (Monte Carlo), the wall must accept a `seed: int` constructor
   argument and use it to seed a local RNG. Default seed is `42`.

2. **Performance.** Each wall must complete in **< 5 seconds** per
   evaluation on the CI host (GitHub Actions ubuntu-latest with 2 vCPU).
   The full five-wall pipeline target is < 30 s/candidate (P2.7 gate
   calibration measures this). Profiling is the wall author's
   responsibility.

3. **No side effects.** Walls must not write to disk, network, or
   database. They read from `ctx` only. Audit persistence is the
   caller's (gate system's) job.

4. **Exception policy.** A wall that cannot complete its computation
   (bad data, numerical error, timeout) must return a `WallReport`
   with `passed=False`, `score=0.0`, and a `reason` describing the
   error. It must not raise. This prevents a single wall failure from
   crashing the evaluation pipeline.

5. **No cross-wall dependencies.** A wall must not call another wall's
   `evaluate()`. Coordination is the gate system's job.

---

## 5. `AlwaysPassWall` test double

```python
class AlwaysPassWall(Wall):
    name: ClassVar[str] = "always_pass"

    def evaluate(self, ctx: EvaluationContext) -> WallReport:
        return WallReport(
            wall_name=self.name,
            passed=True,
            score=1.0,
            reason="AlwaysPassWall — test double only",
        )
```

And the symmetric counterpart:

```python
class AlwaysFailWall(Wall):
    name: ClassVar[str] = "always_fail"

    def evaluate(self, ctx: EvaluationContext) -> WallReport:
        return WallReport(
            wall_name=self.name,
            passed=False,
            score=0.0,
            reason="AlwaysFailWall — test double only",
        )
```

Both live in `services/trader/walls/doubles.py`. Never imported
outside `tests/`.

---

## 6. Package layout

```
services/trader/walls/
├── __init__.py         # exports: Wall, WallReport, EvaluationContext
├── base.py             # Wall ABC + EvaluationContext + WallReport
├── doubles.py          # AlwaysPassWall, AlwaysFailWall (test doubles)
├── wall_1_statistical.py   # P2.2
├── wall_2_data.py          # P2.3
├── wall_3_complexity.py    # P2.4
├── wall_4_generalization.py# P2.5
└── wall_5_meta.py          # P2.6
```

`__init__.py` re-exports only `Wall`, `WallReport`, `EvaluationContext`
— callers import the concrete walls by name.

---

## 7. `__init__.py` public surface

```python
from services.trader.walls.base import (
    Wall,
    WallReport,
    EvaluationContext,
)

__all__ = ["Wall", "WallReport", "EvaluationContext"]
```

Concrete walls are **not** re-exported from `__init__`. Callers import
them explicitly:

```python
from services.trader.walls.wall_1_statistical import StatisticalRigorWall
```

This keeps the root namespace clean and makes it trivial to add walls
without changing the public API.

---

## 8. Typing + Pydantic policy

`EvaluationContext` and `WallReport` are `dataclasses` with
`frozen=True` (not Pydantic models) for the same reason as
`FitnessReport` in Phase 1: they are value objects, not config. They
hold pandas DataFrames which Pydantic cannot validate meaningfully.

`Wall` is a plain ABC. No Pydantic.

All type annotations use `from __future__ import annotations` for
forward-reference compatibility.

---

## 9. Integration with the gate system (P2.7 preview)

The gate system (P2.7) will call each wall in sequence (or in
parallel — TBD at P2.7 spec time based on the 30 s budget):

```python
wall_reports: list[WallReport] = [
    wall.evaluate(ctx)
    for wall in [
        StatisticalRigorWall(),
        DataDisciplineWall(),
        ComplexityControlWall(),
        GeneralizationWall(),
        MetaAwarenessWall(),
    ]
]
```

The `GateSystem` (P2.7) then runs three gates over the
`wall_reports`, each gate being an aggregator that reads specific
`WallReport.sub_results` fields. P2.7 owns the AND aggregation logic.

---

## 10. Exit criteria

| Criterion | Measure |
|---|---|
| `Wall`, `WallReport`, `EvaluationContext` importable from `services.trader.walls` | `from services.trader.walls import Wall, WallReport, EvaluationContext` succeeds |
| `AlwaysPassWall().evaluate(ctx).passed` is `True` | Unit test |
| `AlwaysFailWall().evaluate(ctx).passed` is `False` | Unit test |
| `AlwaysPassWall` round-trips through a minimal evaluation harness | Integration test: build a real `EvaluationContext` from the Phase-1 fixtures; call `AlwaysPassWall().evaluate(ctx)`; assert `passed=True`, `score=1.0` |
| `WallReport` is frozen (mutation raises `FrozenInstanceError`) | Unit test |
| A `Wall` subclass that omits `evaluate()` raises `TypeError` at instantiation | Unit test |
