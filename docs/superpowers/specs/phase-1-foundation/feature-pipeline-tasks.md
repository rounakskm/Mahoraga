# Feature Pipeline — Tasks

**Status:** Drafted 2026-05-09
**Spec:** [`feature-pipeline-spec.md`](feature-pipeline-spec.md)
**Plan:** [`feature-pipeline-plan.md`](feature-pipeline-plan.md)

Task IDs use prefix `P1.4.x` to match the parent [`tasks.md`](tasks.md).

## Legend

- `[code]` = implementation
- `[test]` = pytest fixture / test
- `[doc]` = README / methodology note
- `[infra]` = config / CI
- `→` = depends on

---

## P1.4.F1 — Skeleton + trend category

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.4.F1.1** | [code] | `services/trader/features/__init__.py` + `base.py` — `Feature` ABC, `FeatureContext`, `BUILTIN_FEATURES` registry, `FEATURE_FRAME_SCHEMA` PyArrow schema | — |
| **P1.4.F1.2** | [code] | `services/trader/features/pipeline.py` — `FeaturePipeline` orchestrator: read OHLCV, run features, write features parquet, manifest + audit | P1.4.F1.1 |
| **P1.4.F1.3** | [code] | `services/trader/features/trend.py` — 10 trend features (EMA 20/50/200, SMA 20/50, ADX-14, MACD 12/26/9, regression slope-20) | P1.4.F1.1 |
| **P1.4.F1.4** | [test] | `services/trader/features/tests/test_base.py` — ABC contract, FeatureContext, registry filtering | P1.4.F1.1 |
| **P1.4.F1.5** | [test] | `services/trader/features/tests/test_trend.py` — hand-computed references for EMA-20, ADX-14, MACD against a synthetic series | P1.4.F1.3 |
| **P1.4.F1.6** | [test] | `services/trader/features/tests/test_pipeline.py` — single-ticker, 5-feature, 30-bar synthetic run; verify schema + non-null counts after `required_history_bars` | P1.4.F1.2 + P1.4.F1.3 |
| **P1.4.F1.7** | [doc]  | `services/trader/features/README.md` — package layout + chunk status table + Feature ABC usage example | P1.4.F1.1 |

PR: `phase-1-features-skeleton`.

## P1.4.F2 — Momentum + volatility

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.4.F2.1** | [code] | `services/trader/features/momentum.py` — RSI 14/5, ROC 5/10/20, Stoch K/D-14, Williams %R-14, momentum 10/20 | P1.4.F1 done |
| **P1.4.F2.2** | [code] | `services/trader/features/volatility.py` — ATR-14, Bollinger 20, realized vol 20/60, realized-vol percentile, Parkinson, Garman-Klass | P1.4.F1 done |
| **P1.4.F2.3** | [test] | `tests/test_momentum.py` — hand-computed references for RSI, Stochastic, Williams %R | P1.4.F2.1 |
| **P1.4.F2.4** | [test] | `tests/test_volatility.py` — references for ATR, Bollinger, realized vol | P1.4.F2.2 |
| **P1.4.F2.5** | [code] | Update registry in `__init__.py` to include the new categories | P1.4.F2.1 + P1.4.F2.2 |

PR: `phase-1-features-momentum-volatility`.

## P1.4.F3 — Volume + statistical

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.4.F3.1** | [code] | `services/trader/features/volume.py` — OBV, VWAP-dev 5/20, MFI-14, volume SMA/Z, dollar volume, CMF, Force Index | P1.4.F1 done |
| **P1.4.F3.2** | [code] | `services/trader/features/statistical.py` — Hurst 60/120, autocorr lag 1/5, skew/kurt 60, zscore 20/60, rolling min/max | P1.4.F1 done |
| **P1.4.F3.3** | [test] | Per-category tests with hand-computed references | P1.4.F3.1 + P1.4.F3.2 |
| **P1.4.F3.4** | [code] | Registry update | P1.4.F3.1 + P1.4.F3.2 |

PR: `phase-1-features-volume-statistical`.

## P1.4.F4 — Macro

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.4.F4.1** | [code] | `services/trader/features/macro.py` — VIX level/change/regime, Treasury 2y/10y/2s10s + curve regime, DXY level/change, SPY/QQQ relative strength | P1.4.F1 done |
| **P1.4.F4.2** | [code] | Macro adapter wiring — `FeatureContext.macro_fetcher` callback resolves to a separate `ParquetAdapter` configured for macro reads | P1.4.F1.2 |
| **P1.4.F4.3** | [test] | `tests/test_macro.py` — synthetic macro fixture (FRED-style frame); test PIT correctness across asof boundaries; multi-source consistency | P1.4.F4.1 |
| **P1.4.F4.4** | [code] | Registry update | P1.4.F4.1 |

PR: `phase-1-features-macro`.

## P1.4.F5 — Sentiment placeholder + coverage + audit

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.4.F5.1** | [code] | `services/trader/features/sentiment.py` — `PlaceholderFeature("sentiment_score")` always returning 0.0 with `placeholder=True` | P1.4.F1 done |
| **P1.4.F5.2** | [code] | Pipeline emits manifest row + `audit.events` row with `actor='feature-pipeline'`, `action='compute'` (reuses `services/trader/data/audit.py`) | P1.4.F1.2 |
| **P1.4.F5.3** | [code] | Coverage extension: `services/trader/data/coverage.py::report_features` returns per-column null rate + per-bar present count | P1.4.F1.2 + existing `services/trader/data/coverage.py` |
| **P1.4.F5.4** | [test] | Placeholder round-trips with metadata flag preserved; manifest gets exactly one row per pipeline run; coverage flags a deliberate gap | P1.4.F5.1–P1.4.F5.3 |

PR: `phase-1-features-sentiment-and-coverage`.

## P1.4.F6 — End-to-end integration

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.4.F6.1** | [test] | `tests/integration/phase-1/features/__init__.py` + `test_end_to_end.py` — synthetic 3-ticker universe + synthetic OHLCV; run pipeline; read features back; assert ≥70 columns + PIT correctness preserved (i.e. `asof` shifting filters expected rows) | P1.4.F5 done |
| **P1.4.F6.2** | [infra] | Extend `.github/workflows/ci.yml` integration-smoke job to run the new path | P1.4.F6.1 |
| **P1.4.F6.3** | [doc]  | Tick parent `tasks.md` P1.4 row complete with PR-number references | P1.4.F6.2 |

PR: `phase-1-features-integration`.

---

## Cross-chunk parallelism

After F1 lands, F2 / F3 / F4 / F5 can be developed in parallel. F5's audit + coverage extension touches the pipeline, but the per-category files in F2–F4 don't conflict.

P1.5 (regime detector) needs only a subset of features (volatility + macro mostly), so it can start as soon as F2 + F4 are merged — no need to wait for the entire P1.4.

## Task ownership note

F1 is single-thread (it ships the contract). F2–F5 can be parallelized with subagent dispatch if useful — they're cleanly separated by file. F6 is single-thread.
