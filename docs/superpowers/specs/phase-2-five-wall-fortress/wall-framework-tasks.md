# Phase 2.1 — Wall Framework Tasks

**Status:** Drafted 2026-06-07
**Plan:** [`wall-framework-plan.md`](wall-framework-plan.md)
**Spec:** [`wall-framework-spec.md`](wall-framework-spec.md)

## Legend

- `[plan]` = design artifact
- `[code]` = implementation
- `[test]` = test
- `→` = depends on

## Dependency graph

```
[P2.1.spec (this file)]
         │
         ▼
[C1 base types (Wall ABC + WallReport + EvaluationContext)]
         │
         ▼
[C2 test doubles (AlwaysPassWall + AlwaysFailWall)]
         │
         ▼
[C3 unit tests]
         │
         ▼
[C4 integration test]
         │
         ▼
[C5 CI wiring + PR]
```

## Tasks

- [x] **P2.1.spec [plan]** Author `wall-framework-spec.md`. → P2.0 merged  *(this file)*
- [x] **P2.1.plan [plan]** Author `wall-framework-plan.md` + this `wall-framework-tasks.md`. → P2.1.spec
- [x] **P2.1.C1 [code]** `services/trader/walls/__init__.py` + `base.py`:
  - `EvaluationContext` frozen dataclass (fields: strategy, backtest_result, returns, feature_frame, regime_frame, universe, metadata)
  - `WallReport` frozen dataclass (fields: wall_name, passed, score, reason, sub_results, metadata)
  - `Wall` ABC with `name: ClassVar[str]` and `evaluate(self, ctx) → WallReport` abstract method
  → P2.1.plan
- [x] **P2.1.C2 [code]** `services/trader/walls/doubles.py`:
  - `AlwaysPassWall` (name="always_pass", passed=True, score=1.0)
  - `AlwaysFailWall` (name="always_fail", passed=False, score=0.0)
  → P2.1.C1
- [x] **P2.1.C3 [test]** `services/trader/walls/tests/test_base.py` — unit tests (no Postgres):
  - WallReport is frozen (FrozenInstanceError on mutation)
  - Wall subclass without evaluate() raises TypeError at instantiation
  - AlwaysPassWall().evaluate(stub_ctx).passed is True
  - AlwaysFailWall().evaluate(stub_ctx).passed is False
  - wall_name matches name class var on both doubles
  - EvaluationContext is frozen
  → P2.1.C2
- [x] **P2.1.C4 [test]** `tests/integration/phase-2/wall_framework/test_framework.py` — integration test with real fixtures (mocked HTTP + real Postgres + in-memory parquet same as phase-1 backtest fixtures):
  - Build EvaluationContext from Phase-1 fixture data
  - AlwaysPassWall passes, AlwaysFailWall fails
  - Both WallReports frozen
  → P2.1.C3
- [x] **P2.1.C5 [test+infra]** Add `tests/integration/phase-2/` to `integration-smoke` CI job discovery path. Open and merge PR. → P2.1.C4
