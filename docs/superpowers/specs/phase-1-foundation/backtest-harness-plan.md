# Backtest Harness — Implementation Plan

**Status:** Drafted 2026-05-11
**Spec:** [`backtest-harness-spec.md`](backtest-harness-spec.md)
**Parent plan:** [`plan.md`](plan.md)

Three PR-sized chunks, each 30–60 min review. B1 lands the contract;
B2 wires the engine + risk limits; B3 closes Phase 1 with the
integration test.

```
[B1 Strategy ABC + FitnessReport + BuyAndHold]
       │
       ▼
[B2 Backtest engine + risk-limit firewall]
       │
       ▼
[B3 End-to-end integration test + CI; closes Phase 1]
```

B2 depends on B1's dataclasses. B3 depends on B2's engine.

## 1. Chunk B1 — Skeleton + BuyAndHold

**Branch:** `phase-1-backtest-skeleton`
**Target review time:** ~35 min

Lands:
- `services/trader/backtest/__init__.py`, `base.py` — `Strategy` ABC,
  `FitnessReport` dataclass
- `services/trader/backtest/strategies.py` — `BuyAndHold` stub (target
  weight = `1.0 / len(universe)` for every bar)
- `services/trader/backtest/tests/test_base.py` — ABC contract,
  placeholder-features gate logic (independent of the engine)
- `services/trader/backtest/README.md`

Acceptance:
- `pytest services/trader/backtest/tests/test_base.py` green
- `Strategy` ABC enforces `name`, `requires_features`,
  `allow_placeholder_features`
- `FitnessReport` is hashable + frozen + has the spec's fields

## 2. Chunk B2 — Engine + risk

**Branch:** `phase-1-backtest-engine-and-risk`
**Target review time:** ~55 min

Lands:
- `services/trader/backtest/engine.py` — `Backtest` orchestrator:
  PIT reads, one-bar execution lag, mark-to-market, commission +
  slippage, FitnessReport assembly
- `services/trader/backtest/risk.py` — clip rules (5% per-position,
  20% per-sector) + halt rules (2% daily loss, 10% monthly
  drawdown, regime confidence < 40%)
- Per-component unit tests:
  - Clip: contrived signal → expected post-clip weights
  - Halt: contrived PnL → expected halt timestamps
  - One-bar lag: signal at T executes at close of T+1
  - Commission / slippage math
  - FitnessReport math: hand-derived sharpe / max-drawdown on a small
    synthetic equity curve
  - `test_no_lookahead.py` — future-sentinel injection

Acceptance:
- All unit tests green
- BuyAndHold on 30-bar synthetic SPY produces a deterministic
  FitnessReport in <30 s

## 3. Chunk B3 — End-to-end integration

**Branch:** `phase-1-backtest-integration`
**Target review time:** ~45 min

Lands:
- `tests/integration/phase-1/backtest/test_end_to_end.py` — full
  chain: yfinance fake → ParquetAdapter → FeaturePipeline →
  RegimeDetector → Backtest; verifies report shape + emits one
  `audit.events` row with `actor='backtest-harness'`, `action='run'`
- CI workflow extension to run the new suite in the
  `integration-smoke` job
- Update parent `tasks.md` to mark P1.6 complete with PR numbers
- Update `phase-1-foundation/spec.md` exit-criteria checklist

Acceptance:
- `pytest tests/integration/phase-1/backtest -v` green in CI
- All Phase 1 exit-criteria in `phase-1-foundation/spec.md` ticked
- The 4-row audit chain (`ingest`, `compute`, `classify`, `run`)
  verifies link-by-link end-to-end

## 4. Per-chunk PR template

Same as P1.5 cadence:

```
## Summary
1-3 bullets — what this chunk lands.

## Scope
- In-scope:
- Out-of-scope (deferred to chunk N):

## Test plan
- [ ] pytest <path>
- [ ] CI green on lint + unit-tests + integration-smoke
- [ ] Cross-check against backtest-harness-spec.md §<section>
```

## 5. Risks during implementation

| Risk | Mitigation |
|---|---|
| Look-ahead bug in engine math | `test_no_lookahead.py` injects a future sentinel; audit-xls reviewer also runs on every report |
| Risk-limit math subtle | Per-clip + per-halt fixtures with hand-derived expected outputs |
| Sharpe / drawdown math drift | Hand-derived expected values on small synthetic curves |
| Performance > 30 s | Profile B2 on a 5-year window; if slow, switch engine to numpy-vectorized loop (no pandas overhead) |
| Audit chain breaks under per-bar lock contention | Phase 1 runs backtests serially; per-actor sharding deferred |

## 6. Definition of done

P1.6 done when B1–B3 are merged, `Backtest.run(strategy=BuyAndHold())`
produces a deterministic `FitnessReport` in <30 s, the
placeholder-features gate rejects a sentiment-requiring strategy
without the opt-in, and the end-to-end integration test is green in
CI.

Once P1.6 is merged, **Phase 1 is complete.** The autoresearch loop
(Phase 3) can begin proposing strategy mutations against this harness.
