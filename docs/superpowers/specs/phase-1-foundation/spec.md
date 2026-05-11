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

- ✅ OHLCV ingest path with PIT + hash-chained audit (P1.1, PRs #9–#13). 8-year backfill is an operator action, not a code gate — the pipeline supports it.
- ✅ 70+ engineered features across 7 categories computed + persisted (P1.4, PRs #22–#27).
- ✅ Vault embargo demonstrably enforced — `VaultEmbargoError` on read; `vault_override=True` requires a non-empty reason and emits an audit warning (P1.3, PRs #15 / #17 / #18; canaries in the integration-smoke job).
- ⚠ Regime detector: deterministic rule-based v1 with MESO + MACRO lenses ships in P1.5 (PRs #28–#32). The ≥75%-accuracy gate is **deferred to Phase 4** since Phase 1 has no labeled training corpus; the gate is replaced by deterministic per-label fixtures + a 4×3 composite-sweep test. MICRO lens deferred to Phase 4 (needs intraday data).
- ✅ Backtest harness wraps a stub `Strategy` and returns a `FitnessReport` in <30 s. **Departure from sketch**: pure pandas / numpy engine, not vectorbt (FitnessReport contract is engine-agnostic; Phase 2 can swap if throughput demands).
- ✅ All Phase 1 exit-criteria tests in `tests/integration/phase-1/{data_foundation,universe,feature_pipeline,regime,backtest}/` passing in CI's `integration-smoke` job as of PR #36 (Phase 1 closure).

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

## 8. Open Questions — resolved 2026-05-09

| Question | Resolution |
|---|---|
| **BTC-ETF pre-2024 history** | **Deferred.** Phase 1 ingests equities + ETFs first. BTC-ETF data work is descoped to a later sub-feature inside Phase 1 (or pushed to Phase 2 if other work runs long). When we resume, the choice between (a) free 15Y-history BTCUSD API + spot-proxy stitching, (b) post-2024-only ETF history, or (c) hybrid will be made in `btc-data-spec.md` based on what free API we can actually source. Strategies that need BTC exposure pre-Jan 2024 do not run until that sub-feature lands. |
| **Macroeconomic PIT discipline** | **Approved as proposed.** Every macro feature carries `as_of_release_date` (publication date) alongside `reference_date` (the period the value covers). The feature pipeline only uses values where `release_date <= bar_timestamp`. Enforcement lives in the storage adapter, not the strategy code — same posture as the vault embargo. The `audit-xls` reviewer prompt's look-ahead-bias check verifies this on every backtest output. |
| **Sentiment-feature placeholder** | **Approved as proposed.** The sentiment-feature column always returns `0.0` (neutral) with a `placeholder=True` flag. Strategies that depend on sentiment must explicitly opt in via `allow_placeholder_features=True` in their config; otherwise the backtest harness rejects them at scoring time. This forces Phase 4 to deliver real sentiment before any sentiment-dependent strategy can train. |

## 9. Phase 1 universe scope (revision 2026-05-09)

| Asset class | Phase 1 status | Notes |
|---|---|---|
| US equities (S&P 500 + Russell 1000, PIT) | **In scope, primary** | First-class deliverable. 8+ years history. |
| ETFs (broad / sector / commodity / thematic) | **In scope, primary** | First-class deliverable alongside equities. |
| BTC ETFs (IBIT, FBTC, GBTC, BITB, ARKB) | **Deferred** | Tracked by a follow-up sub-feature spec inside Phase 1. The data work is straightforward post-2024 ETF series; the open question is how (or whether) to backfill pre-2024 from free BTCUSD spot data. |

This revision changes only the *sequencing* of when BTC data work happens — the universe defined in §2 still represents the Phase 1 + Phase 5+ scope.
