# Phase 2.1 — Wall Framework Plan

**Status:** Drafted 2026-06-07
**Spec:** [`wall-framework-spec.md`](wall-framework-spec.md)
**Parent:** [`plan.md`](plan.md), [`tasks.md`](tasks.md)

---

## 1. Summary

Deliver the `Wall` ABC, `WallReport`, and `EvaluationContext` in
`services/trader/walls/`. This is the critical-path sub-feature:
every subsequent wall (P2.2–P2.6) imports from here, so it must land
first with a stable interface.

Scope is intentionally minimal — the framework ships the contract and
test doubles only. No strategy-specific logic lives here.

## 2. Chunks

### Chunk C1 — Package skeleton + base types

**Files:**
- `services/trader/walls/__init__.py`
- `services/trader/walls/base.py`

**What ships:**
- `EvaluationContext` frozen dataclass
- `WallReport` frozen dataclass
- `Wall` ABC with `evaluate()` abstract method

**What doesn't ship:** any concrete wall logic, any imports from
`services.trader.backtest` beyond type hints.

### Chunk C2 — Test doubles

**Files:**
- `services/trader/walls/doubles.py`

**What ships:**
- `AlwaysPassWall`
- `AlwaysFailWall`

### Chunk C3 — Unit tests

**Files:**
- `services/trader/walls/tests/test_base.py`

**Tests:**
- `WallReport` is frozen (`FrozenInstanceError` on mutation)
- `Wall` subclass missing `evaluate()` raises `TypeError` at instantiation
- `AlwaysPassWall().evaluate(ctx).passed` is `True`
- `AlwaysFailWall().evaluate(ctx).passed` is `False`
- `wall_name` on both doubles matches their `name` class var
- `EvaluationContext` is frozen

**Fixtures:** `EvaluationContext` stub built from dummy values — no
real Postgres or parquet needed. Unit tests only.

### Chunk C4 — Integration test

**Files:**
- `tests/integration/phase-2/wall_framework/test_framework.py`
- `tests/integration/phase-2/__init__.py` (new)
- `tests/integration/phase-2/wall_framework/__init__.py` (new)

**Test:**
- Build a real `EvaluationContext` from the Phase-1 in-memory fixtures
  (same mock data used by the backtest integration test).
- Call `AlwaysPassWall().evaluate(ctx)` — assert `passed=True`.
- Call `AlwaysFailWall().evaluate(ctx)` — assert `passed=False`.
- Assert both `WallReport`s are frozen.

No new Postgres migrations. No new parquet writes. The test reads
from the same fixture data as `tests/integration/phase-1/backtest/`.

### Chunk C5 — CI wiring

**Files:**
- `.github/workflows/ci.yml` — add `tests/integration/phase-2/` to
  the `integration-smoke` job's discovery path

## 3. Sequencing

C1 → C2 → C3 (unit) → C4 (integration) → C5 (CI) — all sequential.
Total estimated time: 1–2 hours.

## 4. PR plan

One PR: "feat(walls): P2.1 — Wall ABC + WallReport + EvaluationContext
+ test doubles". Merges C1–C5 together. Title follows the P1.6
precedent of shipping spec + implementation in a single feature PR.

## 5. Definition of done

- All unit tests in `services/trader/walls/tests/` pass.
- Integration test in `tests/integration/phase-2/wall_framework/` passes
  against real fixtures (Postgres + parquet mocks from Phase-1 harness).
- `integration-smoke` CI job green with the new path included.
- P2.1 tasks ticked in `tasks.md`.
