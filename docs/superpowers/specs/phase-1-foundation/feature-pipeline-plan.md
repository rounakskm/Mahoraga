# Feature Pipeline — Implementation Plan

**Status:** Drafted 2026-05-09
**Spec:** [`feature-pipeline-spec.md`](feature-pipeline-spec.md)
**Parent plan:** [`plan.md`](plan.md)

Six PR-sized chunks, each <60-min review. F1 lands the contract; F2–F4 add
feature categories independently; F5 wires the sentiment placeholder + the
audit / coverage path; F6 closes the sub-feature with an end-to-end test.

```
[F1 skeleton + 10 trend features]
       │
       ├──▶ [F2 momentum + volatility]
       │
       ├──▶ [F3 volume + statistical]
       │
       ├──▶ [F4 macro]
       │
       ├──▶ [F5 sentiment placeholder + coverage + audit]
       │
       ▼
[F6 end-to-end integration test + CI]
```

F2, F3, F4, F5 can be developed in parallel after F1 lands — they touch
different files. F6 waits for all five.

## 1. Chunk F1 — Skeleton + trend category

**Branch:** `phase-1-features-skeleton`
**Target review time:** ~50 min

Lands:
- `services/trader/features/__init__.py`, `base.py` (Feature ABC, FeatureContext, schemas)
- `services/trader/features/pipeline.py` (FeaturePipeline orchestrator)
- `services/trader/features/trend.py` (10 trend features per spec §2)
- Per-feature unit tests against synthetic OHLCV with hand-computed reference values for at least 3 trend features (e.g. EMA-20 against numpy's `ewm`, ADX-14 against a known reference, MACD against a hand-traced example)
- Pipeline-skeleton test: 1 ticker, 5 features, asserts the right columns + non-null counts after `required_history_bars`
- README under `services/trader/features/`

Acceptance:
- `pytest services/trader/features/tests/` green
- `Feature` ABC enforces `category` + `placeholder` discriminators
- Storage write goes through `ParquetAdapter` (no new chokepoint)

## 2. Chunks F2 / F3 / F4 — Feature categories

Each chunk follows the same pattern:
- Add a category file (`momentum.py`, `volatility.py`, `volume.py`, `statistical.py`, `macro.py`)
- Add per-feature unit tests with at least one hand-computed reference per file
- Update the registry in `__init__.py`
- ~40-min review each

### F2 (`phase-1-features-momentum-volatility`)
Momentum: 10 features (RSI, ROC, Stoch, Williams %R, momentum)
Volatility: 10 features (ATR, BBands, realized vol, Parkinson, Garman-Klass)

### F3 (`phase-1-features-volume-statistical`)
Volume: 10 features (OBV, VWAP-dev, MFI, CMF, Force Index, volume z-score, dollar volume)
Statistical: 10 features (Hurst, autocorr, skew, kurt, zscore, min/max)

### F4 (`phase-1-features-macro`)
Macro: 10 features pulling Treasury yields, VIX, DXY, SPY/QQQ relative strength via the macro side of `ParquetAdapter`. Reuses the multi-source PIT consistency rule from P1.1 §8.

## 3. Chunk F5 — Sentiment placeholder + coverage + audit

**Branch:** `phase-1-features-sentiment-and-coverage`
**Target review time:** ~40 min

Lands:
- `services/trader/features/sentiment.py` — single `PlaceholderFeature("sentiment_score")` always returning 0.0
- Pipeline writes an `IngestRun`-shaped manifest row to `data/parquet/manifests/feature-runs.parquet` and a hash-chained `audit.events` row with `actor='feature-pipeline'`, `action='compute'` (delegating to `services/trader/data/audit.py`)
- Coverage extension: `report_features` per-column null-rate + per-bar present-count
- Tests: placeholder round-trips with `placeholder=True` flag preserved; manifest gets one row per run

## 4. Chunk F6 — End-to-end integration

**Branch:** `phase-1-features-integration`
**Target review time:** ~30 min

Lands:
- `tests/integration/phase-1/features/test_end_to_end.py` — synthetic 3-ticker universe + synthetic OHLCV → run pipeline → read features back via `adapter.read(kind="features", ...)` → assert ≥70 columns + PIT correctness preserved
- CI workflow extension to run the new integration test in the integration-smoke job

Acceptance:
- `pytest tests/integration/phase-1/features -v` green in CI
- `data-foundation-spec.md` §10-style acceptance row for P1.4 ticked

## 5. Per-chunk PR template

Same as P1.1 / P1.2 / P1.3:

```
## Summary
1-3 bullets — what this chunk lands.

## Scope
- In-scope:
- Out-of-scope (deferred to chunk N):

## Test plan
- [ ] pytest <path>
- [ ] CI green on lint + unit-tests + integration-smoke
- [ ] Cross-check against feature-pipeline-spec.md §<section>
```

## 6. Risks during implementation

| Risk | Mitigation |
|---|---|
| Feature math drifts vs published references | Per-feature unit test with a hand-computed reference; ratio tolerance `1e-9`, absolute price tolerance `1e-6` |
| Look-ahead bug in a rolling-window calc | Dedicated `test_no_lookahead.py` injects a "future" sentinel and asserts no feature reads it |
| Macro data shape varies by source | F4 normalizes at read time; per-source unit tests + multi-source consistency test (FRED + BLS for the same indicator) |
| Pipeline run-time grows with universe size | Phase 1 stays single-process; profile in Phase 2 if it matters |
| Sentiment placeholder accidentally promoted to non-placeholder | Schema test in F5 asserts `PlaceholderFeature.placeholder is True`; harness in P1.6 will gate strategies on it |

## 7. Definition of done

P1.4 done when chunks F1–F6 are all merged, ≥70 unique feature columns are produced by the pipeline, the placeholder is round-tripped through the registry, and the end-to-end integration test is green in CI.

After P1.4: P1.5 (regime detector) only needs a subset of features (volatility + macro mostly) and can run in parallel from F2 onward; P1.6 (backtest harness) waits for both P1.4 and P1.5.
