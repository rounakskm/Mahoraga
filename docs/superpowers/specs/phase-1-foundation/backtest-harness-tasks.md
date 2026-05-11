# Backtest Harness — Tasks

**Status:** Drafted 2026-05-11
**Spec:** [`backtest-harness-spec.md`](backtest-harness-spec.md)
**Plan:** [`backtest-harness-plan.md`](backtest-harness-plan.md)

Task IDs use prefix `P1.6.x` to match the parent [`tasks.md`](tasks.md).

## Legend

- `[code]` = implementation
- `[test]` = pytest fixture / test
- `[doc]` = README / methodology note
- `[infra]` = config / CI
- `→` = depends on

---

## P1.6.B1 — Skeleton + BuyAndHold

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.6.B1.1** | [code] | `services/trader/backtest/__init__.py` + `base.py` — `Strategy` ABC + `FitnessReport` dataclass | — |
| **P1.6.B1.2** | [code] | `services/trader/backtest/strategies.py` — `BuyAndHold` stub (equal-weight) | P1.6.B1.1 |
| **P1.6.B1.3** | [test] | `services/trader/backtest/tests/test_base.py` — ABC contract, placeholder-features gate logic | P1.6.B1.1 |
| **P1.6.B1.4** | [doc]  | `services/trader/backtest/README.md` — package layout + chunk status + Strategy usage | P1.6.B1.1 |

PR: `phase-1-backtest-skeleton`.

## P1.6.B2 — Engine + risk

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.6.B2.1** | [code] | `services/trader/backtest/risk.py` — clip rules (5% per-position, 20% per-sector) + halt rules (2% daily, 10% monthly drawdown, regime confidence < 40%) | P1.6.B1 done |
| **P1.6.B2.2** | [code] | `services/trader/backtest/engine.py` — `Backtest` orchestrator: PIT reads, one-bar execution lag, mark-to-market, commission + slippage, FitnessReport assembly | P1.6.B1 done + P1.6.B2.1 |
| **P1.6.B2.3** | [test] | `services/trader/backtest/tests/test_risk.py` — per-clip + per-halt fixtures with hand-derived expected outputs | P1.6.B2.1 |
| **P1.6.B2.4** | [test] | `services/trader/backtest/tests/test_engine.py` — one-bar lag fixture, commission / slippage math, sharpe / max-drawdown hand-derived on synthetic equity curve, BuyAndHold on 30-bar synthetic SPY runs deterministically | P1.6.B2.2 |
| **P1.6.B2.5** | [test] | `services/trader/backtest/tests/test_no_lookahead.py` — future-sentinel injection fixture asserts engine does not consume bar `T+k` when computing positions at bar `T` | P1.6.B2.2 |

PR: `phase-1-backtest-engine-and-risk`.

## P1.6.B3 — End-to-end integration

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.6.B3.1** | [test] | `tests/integration/phase-1/backtest/__init__.py` + `test_end_to_end.py` — full chain: yfinance fake → ParquetAdapter → FeaturePipeline → RegimeDetector → Backtest; verifies FitnessReport shape + emits one `audit.events` row with `actor='backtest-harness'`, `action='run'`; hash chain verifies the 4-row sequence | P1.6.B2 done + P1.5.R4 merged |
| **P1.6.B3.2** | [infra] | Extend `.github/workflows/ci.yml` integration-smoke job to run the new path | P1.6.B3.1 |
| **P1.6.B3.3** | [doc]  | Update parent `tasks.md` to mark P1.6 complete with PR-number references; tick `phase-1-foundation/spec.md` exit criteria | P1.6.B3.2 |

PR: `phase-1-backtest-integration`. **Merging this PR closes Phase 1.**

---

## Cross-chunk parallelism

B1 ships the contract single-thread. B2 cannot start until B1 lands
(the engine writes FitnessReport). B3 cannot start until B2 lands.
Fully serial chain — three sequential PRs.

## Task ownership note

All three chunks are sized for a single subagent. The engine in B2
is the largest piece (~400 lines including risk.py + tests); the
others are 150–250 lines each.
