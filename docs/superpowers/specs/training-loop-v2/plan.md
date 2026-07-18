# Training Loop v2 — Richer Inputs, Regime Detection v2, Chart Verification, LLM Priority

> **For agentic workers:** subagent-driven, TDD, checkbox steps. Dependency graph in [`tasks.md`](tasks.md).

**Goal:** Make the training environment's inputs match the system's ambition: a volume-profile feature family, a multi-feature regime detector (beyond ADX+vol), TradingView-grade chart verification in the dashboard, and the operator's LLM priority (Claude → NVIDIA Build → Ollama) for the autoresearch mutator.

**Why now (operator directive 2026-07-18):** the loop's inputs are too thin — it trades on close-vs-SMA over regimes labeled by just two indicators, while a 62-feature PIT library sits unused. Regime detection quality is the thesis; enrich it first, verify it visually, and let the best available LLM drive mutations.

## Global constraints
Python 3.11+, full type hints, ruff clean (E,F,W,I,N,UP,B,SIM,RET), `uv`, tests next to code, TDD. **PIT/no-look-ahead is absolute** — every new feature computes from bars ≤ i only (tamper test required). Graceful-offline everywhere. Nothing under `services/` imports streamlit. All detector changes keep the 4-quadrant MESO taxonomy as the backbone (the fleet, strategy template, walls, and attribution all key on those labels) — v2 *refines how bars get labeled*, it does not rename the labels. Backward compat: the v1 detector (adx_14 + realized_vol_pct_60 thresholds) must keep working — v2 is opt-in via config/flag until it beats v1 on vault-holdout evidence.

---

### Task A — Volume-profile feature family

**Files:** `services/trader/features/volume_profile.py`, `services/trader/features/tests/test_volume_profile.py`

Rolling price-level volume distribution over a trailing window (default 60 bars, 24 price bins between the window's low/high; volume assigned to each bar's close bin — `# ponytail:` close-bin approximation, intrabar H-L smearing is the upgrade):
- `poc_distance_60` — (close − point-of-control price) / close. Signed distance from the highest-volume price level. category="volume".
- `value_area_pos_60` — where close sits in the 70% value area: 0 at VAL, 1 at VAH, clipped [−0.5, 1.5] (below/above VA). category="volume".
- `hvn_lvn_ratio_60` — volume at the close's bin vs the window's mean bin volume (high-volume-node vs low-volume-node context). category="volume".
All three: `required_history_bars()=60`, registered via `register_feature`, NaN warmup only, PIT tamper test (bars after i altered → values ≤ i unchanged), plus a hand-computed 3-bin toy case asserting POC/VAH/VAL math exactly. Export a reusable `volume_profile(frame, window, bins) -> ProfileResult` helper (poc_price, vah, val, bin_volumes) for the dashboard overlay (Task C) and future strategy templates.

---

### Task B — Regime detection v2 (multi-feature, learnable, confidence-bearing)

**Files:** `services/trader/regime/meso_v2.py`, `services/trader/regime/tests/test_meso_v2.py`, `services/trader/training/regime.py` (extend), `services/trader/training/strategy_template.py` (extend mutation surface), `services/trader/training/tests/` (extend)

Design (keeps the 4 quadrants; replaces two-threshold labeling with two learnable composite scores):
- **Trend score** = weighted vote of: adx_14 (normalized /50), |regression_slope_20| (normalized by realized_vol_20), macd_hist sign-consistency (rolling 10-bar fraction), hurst_60 (>0.5 → trending). Weights learnable, default equal.
- **Vol score** = weighted vote of: realized_vol_pct_60 (/100), bb_width_20 percentile, atr_14 percentile (rolling 252-bar rank). Weights learnable, default equal.
- Label = quadrant of (trend_score ≥ trend_cut, vol_score ≥ vol_cut); cuts learnable (defaults 0.5). **Confidence** = product of |score − cut| distances, normalized [0,1] — flows into `regime_confidence` (the firewall's 40% floor finally gets a real signal, replacing the crude distance blend).
- `MesoV2Lens(Lens)` with `required_features()` naming the exact registry features; pure `classify(feature_row)`.
- Training integration: `detector_features_v2(ohlcv) -> pd.DataFrame` (the named columns, PIT); `RegimeConditionalStrategy` gains optional `detector_weights`/`detector_cuts` fields — mutation surface extends to nudging one weight/cut (only in `--learn-detector-v2` mode; v1 path untouched). `regimes_for_v2(features_df)` labels per-candidate.
- **Evidence gate:** an A/B runner comparison (same seeds, v1 vs v2 detector, 150 iters) must show v2's best vault-holdout ≥ v1's before v2 becomes the default anywhere. Record both in the registry; report the table. This is the "carefully" in carefully plan — no silent thesis-core swap.

---

### Task C — Chart verification in the dashboard (TradingView Lightweight Charts)

**Files:** `scripts/dashboard.py` (extend), `services/trader/ops/chart_data.py`, `services/trader/ops/tests/test_chart_data.py`

TradingView's **Lightweight Charts** OSS library (no Premium/API dependency; embedded via `streamlit.components.v1.html` with the standalone JS bundle) rendering from OUR data — the operator's TV Premium stays the manual cross-check against the same indicator settings:
- `chart_data.py` (pure, tested): `candles(ohlcv) -> list[dict]` (LWC time/open/high/low/close shape), `sma_overlay(close, window)`, `regime_bands(labels)` (contiguous label spans → colored背景 areas), `trade_markers(orders_rows)` (BUY/SELL arrows from trades.orders shapes), `volume_profile_overlay(frame)` (Task A helper → horizontal histogram data). All offline-testable with injected frames/rows; DDL cross-check for the orders columns.
- Dashboard gains a **Chart** panel: SPY candles + the active strategy's per-regime SMA windows + regime background bands (v1 and, when present, v2 labels toggleable) + trade markers + volume-profile histogram. Purpose: *visually verify the system's regime labels and signals are correct* — the operator's stated need. Streamlit stays lazy; the JS bundle is vendored under `scripts/assets/` (no CDN dependency at runtime, one fetch script documented).

---

### Task D — LLM priority chain for the training mutator (Claude → NVIDIA → Ollama)

**Files:** `infra/litellm/config.yaml` (extend), `services/trader/training/llm.py` (default routing change), tests extend, `.env.example` docs

- LiteLLM gains a router alias **`mahoraga-trainer`**: primary `anthropic/claude-opus-4-7` (ANTHROPIC_API_KEY — already set), `fallbacks: [nvidia/nemotron-super, ollama/gemma4]` (LiteLLM native fallback chain; a failed/missing key or 4xx/5xx cascades automatically).
- `LLMMutator` default flips to the **gateway**: base_url default `http://localhost:4000/v1` (env `MAHORAGA_LLM_BASE_URL` still overrides; direct-NVIDIA remains reachable by setting it), api_key default `LITELLM_MASTER_KEY`, model default `mahoraga-trainer`. The mechanical-mutation safety fallback is unchanged and remains the final backstop.
- `.env.example`: document the chain + the optional operator step `claude setup-token` (OAuth for subscription auth — interactive, operator-run; note it is NOT officially a raw API key substitute, ANTHROPIC_API_KEY is the supported path and is already present).
- Verification: one live `--llm --iterations 3` run logging which provider actually served (LiteLLM response header/model field printed), plus a pulled-key test proving the cascade (Claude key blanked in a scratch env → NVIDIA serves).

---

## Self-review
- The four workstreams are independent except C's volume-profile overlay consumes A's helper (C degrades gracefully without it) and B consumes existing registry features only (A's features become detector inputs in a later evidence-gated iteration — deliberately NOT in v2's first cut, to keep the A/B clean).
- The two riskiest moves are guarded: regime-v2 is opt-in behind an A/B evidence gate (thesis core, no silent swap); LLM default-route change keeps env override + mechanical backstop.
- TradingView Premium is used as the *manual verification* surface, not a data/API dependency — TV has no supported programmatic data API, and our PIT guarantees require our own feature pipeline. Lightweight Charts gives the TV-grade visual without ToS risk.
- Deferred consciously: intrabar volume smearing for profiles, strategy templates that *trade* on the new features (next research cycle, after the detector A/B), TV webhook alerts→halt (small, optional, listed in tasks as stretch).
