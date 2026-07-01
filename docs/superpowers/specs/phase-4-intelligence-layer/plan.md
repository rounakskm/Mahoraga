# Phase 4 — Intelligence Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Dependency graph + parallel waves live in [`tasks.md`](tasks.md).

**Goal:** Add real-time market intelligence — a real news pipeline (Alpaca), a news classifier, 15-min sentiment state, a MICRO regime lens, a transition predictor, a web-research agent, Archivist L2/L3 synthesis, and a news-shock halt protocol — so Mahoraga is regime-aware in real time and the autoresearch loop can train on real sentiment.

**Architecture:** Everything is substrate-independent Python under `services/trader/{news,intel,features,regime}/`, reusing Phase-1's `Feature`/`Lens` contracts and Layer-3's `HaltControl` (shock halt), `hindsight_client` (World Facts / Mental Models / Observations), `llm.py` (LiteLLM synthesis), and the `researcher.md` subagent. The classifier defaults to a fast local **lexicon** backend (deterministic, no heavy dep, trivially <2s); FinBERT is an optional pluggable backend. Real sentiment replaces the placeholder feature, unblocking sentiment-dependent strategies in the loop.

**Tech Stack:** Python 3.11+, pandas 3.0.3 / numpy 2.4.6, httpx (Alpaca REST + websocket + macro sources), psycopg, pytest, uv, ruff. Alpaca news archive (~2020→present) via `data.alpaca.markets/v1beta1/news`; pre-2020 = price-action proxies. Hindsight bank `mahoraga-trader`. LiteLLM for medium-path synthesis. No FinBERT/torch unless the optional backend is explicitly enabled.

## Global Constraints

- Python 3.11+; full type hints in `services/`. Pydantic + YAML at config boundaries. ruff clean (repo enforces E401 one-import-per-line, E702 no-compound-statements, I001 sorted imports).
- pandas 3.0.3, numpy 2.4.6. Prefer proven libs over hand-rolling.
- **No look-ahead, ever.** The sentiment feature is PIT-correct: at `ctx.asof` it uses only news with `created_at <= asof`, and respects the vault embargo at the data-access boundary. A deliberate-leak canary test is required (news dated after `asof` must never affect the value).
- **Substrate-portable:** zero Hermes/NemoClaw glue in `services/trader/**`. The only substrate artifact is wiring the existing `infra/nemoclaw/subagents/researcher.md` to the Python `WebResearcher` + the egress allowlist under `infra/nemoclaw/policies/`.
- **Graceful-offline / no-key:** `AlpacaNewsClient` with no `ALPACA_API_KEY` → returns empty, never raises (the `ProvenanceWriter(None)` pattern). Every macro connector, Hindsight write, and LLM synthesis degrades to a safe no-op offline. Unit tests never hit the network — they use committed fixtures + injected transports.
- **Latency SLA:** the fast-path classifier is <2s per item — the lexicon backend is microseconds; the test asserts the classifier is a pure local call (no network in `classify()`).
- **Env schema:** `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_DATA_ENDPOINT` (news + market data), `ALPACA_PAPER_ENDPOINT` (Phase 5). Documented in `.env.example`; real values live only in gitignored `.env`.
- Tests next to code. TDD: failing test first. Conventional commits, branch per task-group, PR + CI green before merge, never `--no-verify`.

---

## File Structure

**News pipeline (`services/trader/news/`):**
- `alpaca_news.py` — `AlpacaNewsClient(key=None, secret=None, data_url=...)`: `.fetch(symbols, start, end) → list[NewsItem]` (REST archive, paginated), `.stream(symbols, on_item)` (websocket live, reconnect + polling fallback). No key → `.fetch` returns `[]`.
- `classifier.py` — `NewsClassifier(backend="lexicon")`: `.classify(item: NewsItem) → Classification(level, sentiment, impact)`; `LexiconClassifier` (default) + optional `FinbertClassifier`. `level ∈ {CRITICAL, MATERIAL, BACKGROUND}`; `sentiment ∈ [-1, 1]`; `impact ∈ [0, 1]`.
- `aggregator.py` — `SentimentAggregator(hindsight=None)`: `.ingest(items)` classifies + writes World Facts; `.state(symbol, asof) → SentimentState(score, n, window)` (rolling windows: 24h/7d/30d weighted); `.rolling_series(symbol, items, freq) → pd.Series` for the feature.
- `shock.py` — `NewsShockProtocol(halt, hold_minutes=10)`: `.on_classified(classification) → ShockAction`; a CRITICAL item → `halt.halt("news shock: <headline>")` + `tightened_stops=True` + a 10-min forced-exit hold timestamp.

**Macro connectors (`services/trader/data/connectors/`):** (`fred.py` exists)
- `edgar.py` — `EdgarConnector.recent_8k(cik_or_ticker, since) → list[Filing]`.
- `fed_rss.py` — `FedRssConnector.latest(feeds) → list[FedItem]`.
- `fedwatch.py` — `FedWatchConnector.probabilities(asof) → dict[str, float]` (rate-move probabilities).

**Features + regime (`services/trader/features/`, `services/trader/regime/`):**
- `sentiment.py` — REPLACE the placeholder: `SentimentFeature` (`category="sentiment"`, `placeholder=False`) computing a PIT rolling sentiment series from classified news history; keep a `PlaceholderFeature` fallback registered only when no news source is configured.
- `micro.py` (features) — `RocFeature(3)`, `RocFeature(5)`, `VolumeSurgeFeature` — the MICRO momentum/volume inputs.
- `regime/micro.py` — `MicroLens(Lens)`: `required_features()` = sentiment + roc_3/5 + volume_surge + realized_vol; `classify(feature_row, macro_row) → ClassificationResult` with label ∈ {momentum, reversal, shock}. Fills `CompositeRegime.micro`.

**Intelligence (`services/trader/intel/`):**
- `transition.py` — `TransitionPredictor(hindsight=None)`: `.predict(regime_history, feature_row) → Transition(prob, from_label, to_label, source)`; rules layer (always on) + Hunter-learned overlay from Hindsight Observations.
- `web_research.py` — `WebResearcher(connectors, llm=None, hindsight=None)`: `.weekly_brief(asof) → MacroBrief`; fetches macro sources, synthesizes a narrative via LiteLLM, writes a Mental Model to Hindsight. Egress-allowlisted.
- `archivist_synthesis.py` — `ArchivistSynthesis(hindsight=None)`: `.level2_weekly(asof)` (pattern extraction across recent Experience Facts), `.level3_monthly(asof)` (meta-principle synthesis across L2) — both via Hindsight `reflect()`.

**Config + integration:**
- `infra/nemoclaw/policies/presets/web-research.yaml` — egress allowlist (FRED, SEC EDGAR, Fed RSS, CME FedWatch); wire `researcher.md` to `WebResearcher`.
- `scripts/run_intel.py` — CLI to run the news-ingest + aggregation + weekly-brief cadences (graceful-offline).
- `tests/integration/phase-4/test_intel_pipeline.py` — end-to-end offline smoke.

---

### Task 1: `AlpacaNewsClient` — real news archive + live stream

**Files:** Create `services/trader/news/__init__.py`, `services/trader/news/alpaca_news.py`, `services/trader/news/tests/__init__.py`, `services/trader/news/tests/test_alpaca_news.py`; add fixture `services/trader/news/tests/fixtures/spy_news_sample.json` (a small real Alpaca `/v1beta1/news` response, committed).

**Interfaces:**
- Produces: `NewsItem` frozen dataclass (`id`, `created_at: pd.Timestamp`, `headline`, `summary`, `symbols: list[str]`, `source`, `url`); `AlpacaNewsClient(key=None, secret=None, data_url="https://data.alpaca.markets").fetch(symbols, start, end, limit=50) → list[NewsItem]` (paginates `next_page_token`); `.is_enabled() → bool`. No key → `is_enabled()` False, `fetch` returns `[]`. `.stream(symbols, on_item)` opens the websocket with reconnect; not exercised in unit tests.

- [ ] **Step 1: Write the failing test** — parse the committed fixture through the client's response-parser (`_parse_news(json)`) → assert it yields `NewsItem`s with tz-aware `created_at` and the SPY symbol; and `AlpacaNewsClient(None, None).fetch(...) == []` (disabled, no network).
- [ ] **Step 2: Run → fails** (module missing).
- [ ] **Step 3: Implement** — httpx GET with `APCA-API-KEY-ID`/`APCA-API-SECRET-KEY` headers, pagination on `next_page_token`, `_parse_news` maps JSON→`NewsItem` (`created_at = pd.Timestamp(x).tz_convert("UTC")`). Transport in `_get` overridable for tests; disabled path short-circuits before any network.
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `feat(news): AlpacaNewsClient — news archive fetch + live stream (graceful no-key)`

---

### Task 2: `NewsClassifier` — fast lexicon classifier (+ optional FinBERT)

**Files:** Create `services/trader/news/classifier.py`, `services/trader/news/tests/test_classifier.py`; `services/trader/news/lexicon.py` (finance sentiment + urgency word lists).

**Interfaces:**
- Consumes: `NewsItem` (Task 1).
- Produces: `Classification` frozen dataclass (`level: str` ∈ {CRITICAL, MATERIAL, BACKGROUND}, `sentiment: float` ∈ [-1,1], `impact: float` ∈ [0,1], `rationale: str`); `NewsClassifier(backend="lexicon").classify(item) → Classification`. `LexiconClassifier` scores headline+summary against signed finance lexicons + urgency triggers (FOMC, halt, bankruptcy, guidance cut, SEC, war → CRITICAL). Pure local, deterministic, no network. `backend="finbert"` lazily imports transformers (optional; skipped if absent).

- [ ] **Step 1: Write the failing test** — a hawkish-FOMC headline → `level==CRITICAL`, `sentiment<0`; a neutral "company names new CFO" → `BACKGROUND`, `abs(sentiment)` small; a strong-beat earnings headline → `sentiment>0`, `level in {MATERIAL,CRITICAL}`. Assert `classify` makes no network call (monkeypatch httpx to raise; still returns).
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** — lexicon scoring: `sentiment = clip((pos-neg)/max(pos+neg,1), -1, 1)`; `level` from urgency triggers + `impact` magnitude; `impact` from trigger weight + symbol count.
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `feat(news): NewsClassifier — fast lexicon backend (CRITICAL/MATERIAL/BACKGROUND + sentiment)`

---

### Task 3: macro connectors — EDGAR, Fed RSS, CME FedWatch

**Files:** Create `services/trader/data/connectors/edgar.py`, `fed_rss.py`, `fedwatch.py` + tests + committed fixtures for each (a sample response).

**Interfaces:**
- Produces: `EdgarConnector(user_agent).recent_8k(ticker, since) → list[Filing(cik, form, filed_at, url, items)]`; `FedRssConnector().latest(feeds=DEFAULT_FEEDS) → list[FedItem(title, published, url, kind)]`; `FedWatchConnector().probabilities(asof) → dict[str,float]`. Each parses a committed fixture in its test (no live network in units); each degrades to `[]`/`{}` on fetch error.

- [ ] **Step 1: Failing tests** — each connector's parser turns its fixture into the typed records; a fetch error path returns empty.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** — httpx GET + parse (EDGAR JSON submissions API; Fed RSS = feedparser-free manual XML parse via `xml.etree`; FedWatch = the CME JSON). Transport injectable.
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `feat(data): SEC EDGAR + Fed RSS + CME FedWatch connectors (fixture-tested, graceful)`

---

### Task 4: MICRO momentum + volume features

**Files:** Create `services/trader/features/micro.py`, `services/trader/features/tests/test_micro_features.py`.

**Interfaces:**
- Consumes: `Feature`, `FeatureContext`, `register_feature` (Phase-1 contract).
- Produces: `RocFeature(window)` (`name=f"roc_{window}"`, `category="momentum"`, `compute → close.pct_change(window)`), `VolumeSurgeFeature(window=20)` (`name="volume_surge"`, ratio of volume to its rolling mean). Registered as `roc_3`, `roc_5`, `volume_surge`. PIT-safe (only past bars via rolling/pct_change).

- [ ] **Step 1: Failing test** — `RocFeature(5).compute(ctx)` equals `close.pct_change(5)` aligned to the frame; `VolumeSurgeFeature` is `volume / volume.rolling(20).mean()`, ≥0, NaN in warmup only. All values at index i use only data ≤ i.
- [ ] **Step 2–5:** implement, test passes, ruff, commit `feat(features): MICRO momentum (roc_3/roc_5) + volume-surge features`.

---

### Task 5: real `SentimentFeature` — PIT sentiment from classified news

**Files:** Modify `services/trader/features/sentiment.py`; Test `services/trader/features/tests/test_sentiment_feature.py` (incl. leak canary).

**Interfaces:**
- Consumes: `AlpacaNewsClient` (T1), `NewsClassifier` (T2), `Feature`/`FeatureContext`.
- Produces: `SentimentFeature(news_client=None, classifier=None)` (`category="sentiment"`, `placeholder=False`, `name="sentiment_score"`): `.compute(ctx) → pd.Series` — for each bar date `d` in `ctx.frame` with `d <= ctx.asof`, the mean classified sentiment of `ctx.ticker` news with `created_at <= d`, EW-decayed over a trailing window, in [-1,1]; NaN→0.0 forward-fill on no-news days. `news_client=None` (no key) → falls back to the placeholder 0.0 series (so Phase-1 tests still pass). The module registers `SentimentFeature` when a client is configured, else the `PlaceholderFeature`.

- [ ] **Step 1: Write the failing tests (incl. leak canary)** — with an injected fake news source returning items dated across the frame, `compute` yields a sentiment series in [-1,1] that changes over time; **leak canary:** an item dated AFTER a bar `d` must not change the value at `d` (compute with and without a future-dated item → identical up to `d`). With `news_client=None`, the series is all 0.0 and `placeholder` semantics hold.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** — group classified sentiments by day, cumulative EW mean with `created_at <= bar_date <= asof`; reuse the Phase-1 registration seam.
- [ ] **Step 4: Run → passes.** Confirm the Phase-1 feature-pipeline tests still pass (placeholder fallback). ruff.
- [ ] **Step 5: Commit** — `feat(features): real PIT SentimentFeature from classified news (+ leak canary); placeholder fallback offline`

---

### Task 6: `MicroLens` — the MICRO regime lens

**Files:** Create `services/trader/regime/micro.py`, `services/trader/regime/tests/test_micro_lens.py`.

**Interfaces:**
- Consumes: `Lens`, `ClassificationResult` (regime/base), the Task-4/5 features.
- Produces: `MicroLens(Lens)` — `name="micro"`, `required_features() → ["sentiment_score","roc_3","roc_5","volume_surge","realized_vol_pct_60"]`; `classify(feature_row, macro_row=None) → ClassificationResult(label, confidence)` with `label ∈ {momentum, reversal, shock, undefined}`: **shock** when sentiment is extreme-negative AND volume_surge high; **momentum** when roc_3/roc_5 and sentiment agree in sign with strength; **reversal** when short-term momentum opposes sentiment; else low-confidence undefined on NaN inputs. Confidence from input magnitude/agreement.

- [ ] **Step 1: Failing test** — a strong-positive-momentum + positive-sentiment row → `momentum` (conf>0.5); an extreme-negative-sentiment + volume-spike row → `shock`; opposing roc-vs-sentiment → `reversal`; a NaN row → `undefined` (conf 0). `required_features()` lists the five names.
- [ ] **Step 2–5:** implement (mirror `MesoLens` structure), test passes, ruff, commit `feat(regime): MicroLens — momentum/reversal/shock MICRO lens filling CompositeRegime.micro`.

---

### Task 7: `SentimentAggregator` — 15-min rolling state + World Facts

**Files:** Create `services/trader/news/aggregator.py`, `services/trader/news/tests/test_aggregator.py`.

**Interfaces:**
- Consumes: `NewsItem`, `NewsClassifier`, `hindsight_client.HindsightClient`.
- Produces: `SentimentState` frozen (`symbol`, `score`, `n`, `asof`, `windows: dict`); `SentimentAggregator(classifier=None, hindsight=None)`: `.ingest(items) → list[Classification]` (classifies + `hindsight.retain` a World Fact per MATERIAL/CRITICAL item), `.state(symbol, asof) → SentimentState` (weighted 24h/7d/30d rolling), `.rolling_series(symbol, items, freq="15min") → pd.Series`. `hindsight=None` → no retain, state still computed.

- [ ] **Step 1: Failing test** — ingest a set of dated items → `.state("SPY", asof)` returns a weighted score in [-1,1] and `n` = count within 30d; with a fake Hindsight, `.ingest` calls `retain` once per MATERIAL+ item and never for BACKGROUND; `.rolling_series` is 15-min indexed and monotonic in time.
- [ ] **Step 2–5:** implement, test passes, ruff, commit `feat(news): SentimentAggregator — 15-min rolling state + Hindsight World Facts`.

---

### Task 8: `NewsShockProtocol` — CRITICAL → 10s entry-halt

**Files:** Create `services/trader/news/shock.py`, `services/trader/news/tests/test_shock.py`.

**Interfaces:**
- Consumes: `Classification` (T2), `ops.halt.HaltControl`.
- Produces: `ShockAction` frozen (`halted: bool`, `tightened_stops: bool`, `hold_until: pd.Timestamp | None`, `reason: str`); `NewsShockProtocol(halt, hold_minutes=10).on_classified(classification, headline, now) → ShockAction` — a CRITICAL classification trips `halt.halt(...)`, sets `tightened_stops=True`, and `hold_until = now + hold_minutes` (no forced exits before then); MATERIAL/BACKGROUND → no-op action. Reuses the Layer-3 kill-switch (`HaltControl`), so `/resume` clears it.

- [ ] **Step 1: Failing test** — a CRITICAL classification → `halt.is_halted()` True, `action.tightened_stops` True, `action.hold_until == now + 10min`; a BACKGROUND item → no halt, no-op action. (Uses an isolated `HaltControl(tmp flag)`.)
- [ ] **Step 2–5:** implement, test passes, ruff, commit `feat(news): NewsShockProtocol — CRITICAL news trips the kill-switch + 10-min hold`.

---

### Task 9: `TransitionPredictor` — rules + Hunter-learned overlay

**Files:** Create `services/trader/intel/__init__.py`, `services/trader/intel/transition.py`, `services/trader/intel/tests/test_transition.py`.

**Interfaces:**
- Consumes: `CompositeRegime`/regime labels, `hindsight_client.HindsightClient`.
- Produces: `Transition` frozen (`prob: float`, `from_label`, `to_label`, `source: str`); `TransitionPredictor(hindsight=None).predict(regime_history: list[str], feature_row) → Transition` — a deterministic rules layer (e.g. rising vol + sentiment flip → elevated transition prob toward high-vol/shock) always on; when `hindsight` is enabled, blends a learned prior from Observations recall (`source="rules+learned"`), else `source="rules"`. Never raises offline.

- [ ] **Step 1: Failing test** — a rising-vol + negative-sentiment-flip history → `prob` elevated (>0.5) toward a high-vol/shock `to_label`, `source=="rules"` when `hindsight=None`; a stable trending history → low `prob`. With a fake Hindsight returning a learned prior, `source=="rules+learned"` and the prob shifts toward it.
- [ ] **Step 2–5:** implement, test passes, ruff, commit `feat(intel): TransitionPredictor — rules layer + Hindsight-learned overlay`.

---

### Task 10: `WebResearcher` — weekly macro brief → Hindsight Mental Model

**Files:** Create `services/trader/intel/web_research.py`, `services/trader/intel/tests/test_web_research.py`.

**Interfaces:**
- Consumes: Task-3 connectors, `llm` synthesis (LiteLLM), `hindsight_client`.
- Produces: `MacroBrief` frozen (`asof`, `narrative`, `sources: list[str]`, `signals: dict`); `WebResearcher(connectors, llm=None, hindsight=None).weekly_brief(asof) → MacroBrief` — pulls the macro connectors, composes a structured context, synthesizes a narrative via the injected `llm` (deterministic template fallback when `llm=None`), writes a Mental Model to Hindsight when enabled. Egress limited to the allowlist (Task 12 enforces at the substrate).

- [ ] **Step 1: Failing test** — with stub connectors (returning fixture records) and `llm=None`, `weekly_brief(asof)` returns a `MacroBrief` whose `sources` names the connectors used and `narrative` is a non-empty deterministic template; with a fake Hindsight, a Mental Model is retained once. No network.
- [ ] **Step 2–5:** implement, test passes, ruff, commit `feat(intel): WebResearcher — weekly macro brief synthesis + Hindsight Mental Model`.

---

### Task 11: `ArchivistSynthesis` — Hindsight L2/L3

**Files:** Create `services/trader/intel/archivist_synthesis.py`, `services/trader/intel/tests/test_archivist_synthesis.py`.

**Interfaces:**
- Consumes: `hindsight_client.HindsightClient`.
- Produces: `ArchivistSynthesis(hindsight=None).level2_weekly(asof) → dict|None` (recall recent Experience Facts → `reflect()` → an Observation), `.level3_monthly(asof) → dict|None` (recall L2 Observations → `reflect()` → a Mental Model). `hindsight=None` → returns None, no-op.

- [ ] **Step 1: Failing test** — with a fake Hindsight (recall returns stub facts, reflect returns a synthesized dict), `level2_weekly` calls recall+reflect and returns the Observation; `level3_monthly` likewise; both return `None` when `hindsight=None`.
- [ ] **Step 2–5:** implement, test passes, ruff, commit `feat(intel): ArchivistSynthesis — Hindsight L2 weekly / L3 monthly`.

---

### Task 12: web-research egress allowlist + researcher wiring

**Files:** Create `infra/nemoclaw/policies/presets/web-research.yaml`; Modify `infra/nemoclaw/subagents/researcher.md` (point its body at `WebResearcher`); Test `infra/ci/tests/test_web_research_policy.py`.

**Interfaces:**
- Produces: an egress preset listing the allowlisted hosts (FRED `api.stlouisfed.org`, SEC `www.sec.gov`/`data.sec.gov`, Fed `www.federalreserve.gov`, CME `www.cmegroup.com`) mirroring the existing `hindsight.yaml` preset shape; `researcher.md` body references `services.trader.intel.web_research.WebResearcher`. A lint asserts the preset lists the four host groups and researcher.md still declares `write: deny`, `task: deny`.

- [ ] **Step 1: Failing test** — parse the preset YAML: asserts the four host groups present; parse researcher.md: still read-only scopes.
- [ ] **Step 2: Run → fails** (preset missing).
- [ ] **Step 3: Implement** the preset (match `hindsight.yaml` format) + update researcher.md body.
- [ ] **Step 4: Run → passes;** the Layer-3 scope guard still passes.
- [ ] **Step 5: Commit** — `feat(infra): web-research egress allowlist + researcher subagent wiring`

---

### Task 13: runner + Phase-4 integration smoke

**Files:** Create `scripts/run_intel.py`, `tests/integration/phase-4/__init__.py`, `tests/integration/phase-4/test_intel_pipeline.py`; Modify `pyproject.toml` if the N999 per-file-ignore doesn't already cover `tests/integration/phase-4/**`.

**Interfaces:**
- Consumes: everything above.
- Produces: `run_intel.py` with subcommands `ingest` (Alpaca news → classify → aggregate → World Facts), `brief` (weekly macro brief), `sentiment` (compute the sentiment feature for a ticker over a date range and print it) — all graceful-offline (no key/DSN → skip with a clear message). The integration test wires `AlpacaNewsClient(None)` (disabled) + fixture news through classifier→aggregator→SentimentFeature→MicroLens end-to-end offline, asserting a `CompositeRegime.micro` label is produced and the shock protocol trips on a planted CRITICAL item.

- [ ] **Step 1: Failing integration test** — feed fixture news through the full chain offline → a `MicroLens.classify` result is produced from the derived features; a planted CRITICAL item trips an isolated `HaltControl`. Assert no network, no DSN needed.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Wire `run_intel.py` + the test.**
- [ ] **Step 4: Run → passes.** Add to CI integration-smoke. Live smoke (optional, with key): `uv run python scripts/run_intel.py ingest --symbols SPY --start 2024-01-01` prints classified counts.
- [ ] **Step 5: Commit** — `feat(intel): run_intel runner + phase-4 end-to-end integration smoke`

---

## Self-Review

**Spec coverage** (Phase-4 spec §2 sub-features 1–7 + §3 exit criteria):
1. News websocket pipeline → T1 (fetch + stream + reconnect). 2. News classifier <2s → T2 (lexicon, pure-local). 3. Sentiment aggregator 15-min → T7. 4. Transition predictor (rules + learned) → T9. 5. Web-research agent + allowlist → T10 + T12. 6. Archivist L2/L3 → T11. 7. News shock protocol (10s halt) → T8. Plus the training-critical additions the spec implies: real sentiment **feature** → T5, MICRO **lens** → T6, MICRO momentum/volume features → T4, macro connectors → T3, integration → T13.
- **Exit criteria mapping:** news classified <2s (T2, pure-local) · sentiment every 15 min queryable (T7) · transition predictor live (T9) · weekly macro briefs → Hindsight (T10) · Archivist L2/L3 (T11) · news-shock end-to-end (T8 + T13 planted-CRITICAL test).
- **Pre-2020 gap** resolved per plan: `SentimentFeature` yields 0.0 (placeholder fallback) where no news exists; strategies train on price-only pre-2020, sentiment-aware 2020+.

**Placeholder scan:** mechanical connectors (T3) and the L2/L3/aggregator tasks compress steps 3–5 to a one-line note; their interface + step-1 test pin the contract. Novel/tricky tasks (T1 parse, T2 lexicon, T5 PIT+leak-canary, T6 lens, T8 shock) carry full step detail.

**Type consistency:** `NewsItem` (T1) consumed unchanged by T2/T5/T7/T13. `Classification` (T2) consumed by T7/T8. `ClassificationResult`/`CompositeRegime` are the Phase-1 types (T6 fills `micro`). `HaltControl` (Layer 3) reused by T8. `HindsightClient` (Layer 3) reused by T7/T9/T10/T11. `SentimentState`, `ShockAction`, `Transition`, `MacroBrief` each defined once in their producing task.

**Safety:** no secret ever enters a tracked file — `.env.example` documents names only; the connectors read from the environment. Every network component is graceful-offline and unit-tested without the network.
