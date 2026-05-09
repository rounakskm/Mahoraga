# Phase 1 — Feature Pipeline Spec (sub-feature 4)

**Status:** Drafted 2026-05-09
**Parent:** [`spec.md`](spec.md), [`plan.md`](plan.md), [`tasks.md`](tasks.md)
**Predecessors:** P1.1 data-foundation (merged), P1.2 universe (merged), P1.3 vault embargo (merged)
**Owner stream:** B (features) — runs in parallel with P1.5 regime detector

---

## 1. Goal

Compute the **70+ engineered features** the autoresearch loop, regime detector, and Phase-3+ strategies will train on, persist them to parquet, and feed them through the same PIT-correct read primitive as raw OHLCV.

A feature is a pure deterministic function of:

- The PIT-correct OHLCV history for a ticker (≤ `bar_timestamp`)
- Optionally: PIT-correct macro indicators (≤ `as_of_release_date`)
- Constants / hyperparameters baked into the feature definition

Every feature has a stable name, a stable schema, and a known computation. Re-running the pipeline on the same inputs produces bit-identical output (modulo float-rounding noise).

By exit, the autoresearch loop can call `read(kind="features", keys=[ticker], start, end, asof)` and get a dataframe with columns for every feature, gated by the same vault embargo + PIT correctness as raw OHLCV.

## 2. Feature taxonomy (7 categories, 70+ features)

This list is the **floor**. The pipeline's design lets us add more features in later chunks without breaking the contract.

### Trend (10)

- `ema_20`, `ema_50`, `ema_200` — exponential moving averages of close
- `sma_20`, `sma_50` — simple moving averages
- `adx_14` — Average Directional Index, 14-period
- `macd_12_26`, `macd_signal_9`, `macd_hist` — MACD and its signal/hist
- `regression_slope_20` — linear-regression slope of close over 20 bars

### Momentum (10)

- `rsi_14`, `rsi_5` — Relative Strength Index
- `roc_5`, `roc_10`, `roc_20` — Rate of Change over N bars
- `stoch_k_14`, `stoch_d_14` — Stochastic %K and %D
- `williams_r_14` — Williams %R
- `momentum_10`, `momentum_20` — `close[t] - close[t-N]`

### Volatility (10)

- `atr_14` — Average True Range, 14-period
- `bb_upper_20`, `bb_middle_20`, `bb_lower_20`, `bb_width_20` — Bollinger Bands
- `realized_vol_20`, `realized_vol_60` — close-to-close stdev × √252
- `realized_vol_pct_60` — realized_vol_60 percentile within trailing 252 bars
- `parkinson_vol_20` — Parkinson high-low volatility estimator
- `garman_klass_20` — Garman-Klass volatility estimator

### Volume (10)

- `obv` — On-Balance Volume
- `vwap_dev_5`, `vwap_dev_20` — close minus 5/20-bar VWAP, normalized by close
- `mfi_14` — Money Flow Index
- `volume_sma_20`, `volume_sma_50` — volume moving averages
- `volume_z_20` — z-score of volume vs trailing 20-bar mean
- `dollar_volume_20` — close × volume, 20-bar mean
- `cmf_20` — Chaikin Money Flow
- `force_index_13` — Force Index, 13-period

### Statistical (10)

- `hurst_60`, `hurst_120` — Hurst exponent over 60/120 bars
- `autocorr_lag1_20`, `autocorr_lag5_20` — autocorrelation at lag 1 and 5
- `skew_60`, `kurt_60` — return skewness / kurtosis over 60 bars
- `zscore_20`, `zscore_60` — close z-score over 20/60-bar mean
- `min_60`, `max_60` — rolling min/max of close

### Macro (10)

These read from the macro side of the parquet store via the same PIT primitive.

- `vix_level`, `vix_change_5d` — VIX latest + 5-day change
- `vix_regime` — `low|normal|elevated|crisis` per `services/trader/prompts/researcher/option-vol-analysis.md` thresholds
- `yield_2y`, `yield_10y`, `yield_2s10s` — Treasury yields + slope
- `yield_curve_regime` — `normal|flat|inverted|humped`
- `dxy_level`, `dxy_change_20d` — DXY proxy (TWEXAFEGSMTH or yfinance UUP)
- `spy_qqq_rs_20d` — relative strength of QQQ vs SPY over 20 bars

### Sentiment placeholder (1)

- `sentiment_score` — always `0.0`, with a `placeholder=True` metadata flag (see §6)

**Total: ~61 named features in the floor**, leaving headroom for Phase 1 to add ad-hoc additions while staying ≥70 by exit.

## 3. Architecture

```
services/trader/features/
├── __init__.py            public Feature ABC + registry + FeaturePipeline
├── base.py                Feature ABC, FeatureContext, FeatureFrame schema
├── trend.py               trend-category Feature implementations
├── momentum.py            momentum-category Feature implementations
├── volatility.py          volatility-category Feature implementations
├── volume.py              volume-category Feature implementations
├── statistical.py         statistical-category Feature implementations
├── macro.py               macro Features (read macro side via the adapter)
├── sentiment.py           PlaceholderFeature("sentiment_score") only
├── pipeline.py            FeaturePipeline orchestrator (read OHLCV → compute → write)
└── tests/                 per-category unit tests + a pipeline integration test
```

Storage layout (uses the same `ParquetAdapter` write pattern as OHLCV):

```
data/parquet/features/
└── <TICKER>/
    └── <YEAR>.parquet
```

Schema:

```
ticker:        string             non-null
bar_timestamp: timestamp[us, UTC] non-null
<feature_1>:   float64            null OK (when input window insufficient)
<feature_2>:   float64
...
source:        string             non-null  "feature-pipeline"
fetched_at:    timestamp[us, UTC] non-null
revision_at:   timestamp[us, UTC] null OK   (same restatement model as OHLCV)
```

## 4. Feature ABC

```python
class Feature(Protocol):
    name: str
    category: Literal["trend", "momentum", "volatility", "volume",
                      "statistical", "macro", "sentiment"]
    placeholder: bool                 # True only for sentiment_score in Phase 1

    def required_history_bars(self) -> int:
        """Minimum number of bars before this feature returns a non-null value."""

    def compute(self, ctx: FeatureContext) -> pd.Series:
        """Return a value per bar over `ctx.frame`. Indices match `ctx.frame.bar_timestamp`."""
```

`FeatureContext` carries the OHLCV frame, ticker, and (for macro features) a callback to fetch macro series via the adapter:

```python
@dataclass(frozen=True)
class FeatureContext:
    ticker: str
    frame: pd.DataFrame                # OHLCV with bar_timestamp index, sorted ascending
    asof: datetime                     # PIT cutoff for any macro lookups
    macro_fetcher: Callable[[str], pd.DataFrame]  # series_id -> PIT-correct macro df
```

Constraints:

- **No look-ahead.** A `compute` implementation that reads `ctx.frame[i]` for any `i > current_bar_index` is a bug; the audit-xls reviewer prompt's look-ahead check (already on main) catches it on every backtest.
- **No external state.** Features must not read from the filesystem, the network, or globals. Tests rely on this for reproducibility.

## 5. Pipeline orchestrator

```python
class FeaturePipeline:
    def __init__(
        self,
        *,
        adapter: ParquetAdapter,          # for OHLCV reads + feature writes
        macro_adapter: ParquetAdapter | None = None,
        features: list[Feature],          # registry; defaults to BUILTIN_FEATURES
        run_id: str | None = None,
    ) -> None: ...

    def compute(
        self,
        *,
        tickers: list[str],
        start: date,
        end: date,
        asof: datetime | None = None,
    ) -> FeatureRunResult: ...
```

Algorithm:

1. For each ticker, read OHLCV via `adapter.read(kind="ohlcv", asof)`. The vault embargo applies — if the requested window overlaps the vault and the adapter is configured for enforcement, the orchestrator surfaces the `VaultEmbargoError` (no implicit override).
2. For each feature in the registry, call `compute(ctx)` and assemble columns.
3. Write the resulting frame back via `adapter.write(kind="features", ...)`.
4. Emit a manifest row + audit-events row identical in shape to the data-foundation manifest (delegated to `services/trader/data/audit.py`).

The orchestrator uses the same `IngestRun` shape from chunk 4 of P1.1. Coverage gating reuses `services/trader/data/coverage.py` against the trading calendar — features should land for every trading day OHLCV exists.

## 6. Sentiment placeholder + backtest-harness opt-in

Per parent `plan.md` §3 decision:

- The pipeline always computes `sentiment_score` and sets it to `0.0` for every bar.
- `BUILTIN_FEATURES` includes a `PlaceholderFeature("sentiment_score")` instance whose `placeholder=True`.
- The backtest harness (P1.6) reads the registry. When a strategy declares `requires_features = [...]`, the harness enforces:
  - If any required feature has `placeholder=True` and the strategy does NOT set `allow_placeholder_features=True`, the harness rejects the strategy at scoring time.
  - This forces Phase 4 to ship real sentiment before any sentiment-dependent strategy can train.

The flag is declared in P1.4 (this spec) and enforced in P1.6.

## 7. Substrate-portability + Hindsight + audit

- Pure Python at `services/trader/features/`. No NemoClaw imports.
- Each pipeline run writes a hash-chained `audit.events` row with `actor='feature-pipeline'`, `action='compute'` and a payload covering tickers/window/feature-count/coverage stats.
- Hindsight ingestion (Phase 3+): each feature run summary becomes an Experience Fact in the `mahoraga-trader` bank — out of scope for this spec but the manifest schema is forward-compatible.

## 8. PIT discipline (mandatory)

Every feature value must respect:

- For OHLCV-only features: the value at `bar_timestamp = T` may use only OHLCV with `bar_timestamp ≤ T` (and any restatement only if `revision_at ≤ asof`).
- For macro features: the value at `bar_timestamp = T` may use macro rows whose `as_of_release_date ≤ T` (the multi-source consistency rule from P1.1 §8 still applies; cross-source joins use the conservative latest release).

The PIT primitive in `ParquetAdapter.read()` enforces both for raw inputs; feature implementations must not break the contract by reading future bars.

## 9. Acceptance / exit criteria

- ✅ `services/trader/features/` package exists with the layout in §3
- ✅ `Feature` ABC + `BUILTIN_FEATURES` registry + `FeaturePipeline` orchestrator
- ✅ ≥61 named features implemented across the 7 categories (the floor); pipeline computes ≥70 unique columns when ad-hoc additions are counted
- ✅ Per-feature unit tests against synthetic OHLCV with hand-computed reference values for at least one feature per category
- ✅ Pipeline integration test: writes feature parquet for a small synthetic universe + reads back via the adapter without breaking the PIT contract
- ✅ Sentiment placeholder is the only feature with `placeholder=True`; placeholder metadata round-trips through the registry
- ✅ Coverage monitor extended to flag missing per-bar features (zero non-null values for a feature column over a window indicates an implementation bug)
- ✅ All `tests/integration/phase-1/features/` tests green in CI

## 10. Open questions

| Question | Default if undecided |
|---|---|
| TA-Lib (C dependency) vs pure pandas | Pure pandas + numpy for Phase 1; TA-Lib reserved for the rare feature where rolling-window math is non-trivial (Hurst, GARCH). Add only if profiling shows the pure-Python path is too slow. |
| Recompute on each run vs incremental | Recompute the entire requested window on each run. Phase 1's universe + history (~10 years × ~500 names × ~70 features × 252 days/yr × 8 bytes ≈ 5 GB) fits comfortably; Phase 2 can switch to incremental if it matters. |
| Per-feature null vs sentinel | Use proper `null` (NaN in pandas, null in parquet) when a feature's `required_history_bars` isn't satisfied. No sentinel values that downstream code might mistake for real data. |
| Macro feature failure modes | If macro source is missing for the requested asof, set the macro feature column to null and surface in the coverage report. Do not fall back to a default value. |

## 11. Plan summary (six chunks)

| # | Branch | What |
|---|---|---|
| F1 | `phase-1-features-skeleton` | Feature ABC + FeatureContext + registry + pipeline skeleton + first 10 trend features + per-trend tests |
| F2 | `phase-1-features-momentum-volatility` | Momentum (~10) + volatility (~10) categories + tests |
| F3 | `phase-1-features-volume-statistical` | Volume (~10) + statistical (~10) categories + tests |
| F4 | `phase-1-features-macro` | Macro features (~10) using PIT-correct macro lookups + tests |
| F5 | `phase-1-features-sentiment-and-coverage` | Sentiment placeholder + coverage extension + audit-events wiring |
| F6 | `phase-1-features-integration` | End-to-end integration test + CI extension |

Each chunk lands as its own PR per the cadence in `plan.md` §7. P1.5 (regime detector) starts in parallel as soon as F1+F2 land — the regime classifier needs only a subset of features, not all 70.

## 12. Risks specific to this sub-feature

- **Look-ahead in feature math.** Mitigation: a fixture in `services/trader/features/tests/test_no_lookahead.py` feeds the pipeline a synthetic series with a known "future" injection; if any feature value at bar `T` depends on bar `T+k`, the test catches it.
- **Float-precision drift across pandas/numpy versions.** Mitigation: per-feature reference values use absolute tolerance `1e-9` for ratios and `1e-6` for absolute prices; if a future numpy release shifts results we widen with documentation.
- **Macro-source outages making whole feature-category null.** Mitigation: coverage report flags `null_pct > 1%` per feature column; the operator decides whether to backfill or proceed.
- **Recompute cost balloons in Phase 2.** Out of scope; Phase 1 keeps recompute simple.
