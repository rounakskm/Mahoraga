# Phase 1 — Foundation Spec

**Status:** Approved 2026-04-26
**Type:** Phase-level spec
**Phase duration:** 8 weeks
**Anchor specs:** [`../2026-04-25-mahoraga-architecture-decomposition.md`](../2026-04-25-mahoraga-architecture-decomposition.md)
**Predecessor:** Phase 0

---

## 1. Goal

Build the **data and regime foundation**: historical OHLCV + engineered features + regime detector for the full trading universe (equities + ETFs + BTC ETFs). Vault embargo enforced at the storage layer. By Phase 1 exit, downstream phases have point-in-time-correct data and a regime label for every trading day.

## 2. Universe (this phase formalizes scope)

- **US equities:** S&P 500 + Russell 1000 with point-in-time constituents (survivorship-bias corrected)
- **ETFs:** broad market (SPY, QQQ, IWM), sector (XLF, XLK, XLE, XLV, XLY, XLP, XLB, XLU, XLRE, XLC), commodity (GLD, USO), thematic as filtered by data availability
- **BTC ETFs:** IBIT, FBTC, GBTC, BITB, ARKB and similar — the in-scope path to Bitcoin exposure for Phases 1–7

## 3. Major Sub-Features

Each will get its own SDD feature spec:

1. **`data-ingest` service** — connectors for free APIs first (yfinance, Alpaca free tier, FRED for macro, Stooq, Tiingo free tier); paid (Polygon) only if free is insufficient. 1-minute granularity max; per-tick not required. Writes parquet to `data/parquet/ohlcv/{symbol}/{year}.parquet`.
2. **Universe management** — S&P 500 + Russell 1000 historical constituents from authoritative source (SEC EDGAR for index reconstitutions); ETF universe maintained as a YAML allowlist with active/delisted markers; BTC-ETF universe tracked similarly.
3. **Feature engineering pipeline** — 70+ features across 7 categories: trend (EMA 20/50/200, ADX, MACD, regression slope), momentum (RSI, ROC, Stoch, Williams %R), volatility (ATR, BBands, realized vol percentile), volume (OBV, VWAP deviation, MFI), statistical (Hurst, Z-score, autocorr, skew, kurt), macro (VIX regime, yield curve, DXY, SPY/QQQ relative strength), sentiment-placeholder. Persisted to parquet.
4. **Vault embargo enforcement** — last 6 months of data unreadable except with `vault_override` flag that emits audit warning; embargo tested by injecting future data and asserting hard rejection.
5. **Regime detector v1** — MACRO / MESO / MICRO lens implementation; outputs labeled regime per trading day; ≥75% accuracy on labeled historical sample.
6. **Backtest harness skeleton** — vectorbt wrapper consuming a stub `Strategy` ABC and producing a placeholder `FitnessReport` (full FitnessReport lands in Phase 2 with the walls).

## 4. Exit Criteria

- 8+ years OHLCV ingested for full universe (equities + ETFs + BTC ETFs subject to BTC-ETF inception dates)
- 70+ engineered features computed and persisted
- Vault embargo demonstrably enforced (test: `read(vault_dates)` raises; with `vault_override=True` warns and returns)
- Regime detector ≥75% accuracy on labeled sample
- Vectorbt backtest harness wraps a stub `Strategy` and returns a placeholder report in <30s
- All Phase 1 exit-criteria tests in `tests/integration/phase-1/` passing in CI

## 5. Dependencies

- Phase 0 substrate live (compose stack, Postgres, etc.)
- Free-tier API keys provisioned in `.env`

## 6. Timeline & Sequencing — 8 weeks, 3 parallel streams

| Week | Stream A (data) | Stream B (features) | Stream C (regime) |
|---|---|---|---|
| 1–2 | data-ingest skeleton + free-API connectors | (waiting on data) | regime taxonomy & label set design |
| 3–4 | universe management + parquet writers | feature pipeline skeleton | hand-label sample |
| 5–6 | vault embargo enforcement | core 70 features | MACRO lens |
| 7 | data quality tests | feature validation tests | MESO + MICRO lens |
| 8 | backtest harness skeleton | feature integration tests | regime accuracy validation; integration |

## 7. Phase-Specific Risks

- **BTC-ETF data depth.** IBIT/FBTC listed Jan 2024; pre-2024 history doesn't exist. Mitigation: use spot BTC as proxy continuation for backtest pre-2024, documented in `data-foundation-spec.md`; OR limit BTC-ETF strategies to 2024+. Decision deferred to that spec.
- **Universe survivorship bias.** Mitigation: point-in-time constituents from SEC EDGAR; audit by reproducing a known historical index level.
- **Silent vault leakage.** Mitigation: vault enforcement tested in every Phase 1 sub-spec via fixture verifying `vault_override=False` blocks; deliberate-leak canary test.
- **Regime label calibration.** Hand-labels are subjective. Mitigation: calibrated against major historical events (2020 COVID, 2022 inflation, 2018 vol regime); reviewed by operator.
- **Free-API rate limits.** Some illiquid Russell 1000 names may need slow ingestion. Mitigation: backoff + parallelism control; monitor coverage.

## 8. Open Questions for This Phase

- BTC ETF history pre-2024: spot-BTC proxy vs limit to post-2024? Decided in `data-foundation-spec.md`.
- Macroeconomic data lag handling — CPI for Jan released mid-Feb; PIT representation. Decided in `data-foundation-spec.md`.
- Sentiment-feature placeholder strategy until Phase 4 brings real sentiment online.
