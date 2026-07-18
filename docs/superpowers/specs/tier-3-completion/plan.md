# Tier 3 — Completion Plan (feature-complete before the convergence gate)

> **For agentic workers:** subagent-driven, TDD, checkbox steps. Dependency graph in [`tasks.md`](tasks.md).

**Goal:** Close the remaining deferred implementation so the app is *feature-complete* — a real multi-symbol portfolio system with live intelligence cadences — leaving only the two uncompressible gates: ~30 elapsed paper-trading days (convergence) and the human real-capital sign-off.

**Scope decision (ponytail):** build the items that complete the *core system* and the two named Phase-4 exit gaps; **defer FinBERT** (the fast local lexicon classifier meets the <2s SLA and adds no measured accuracy need — a heavy torch/transformers dep for marginal gain; revisit only if sentiment quality is ever shown lacking). Live news uses a **periodic REST refresh** cadence, not a long-lived websocket (same effect for a local operator; websocket is a cloud-phase optimization — documented `# ponytail`).

**Tech stack:** unchanged — Python 3.11+, pandas 3.0.3, httpx, psycopg, pytest, uv, ruff. Reuses the executor (already multi-intent), firewall (already portfolio-wide sector/position), signal, aggregator, connectors, Hindsight.

## Global constraints
- Full type hints; ruff clean (E,F,W,I,N,UP,B,SIM,RET). Graceful-offline everywhere (no key/DSN → safe no-op + one warning). Tests next to code, TDD. No look-ahead. Nothing under `services/` imports streamlit/Hermes. Conventional commits, PR + CI green before merge.
- **Multi-symbol live safety:** the firewall's sector + position + daily/monthly limits already aggregate over `portfolio` — multi-symbol just passes N intents to the existing `Executor.run_cycle`. The reconciler already diffs the full positions dict. No safety path is weakened; a per-symbol sector map is the one new input.

---

### Task 1: watchlist + sector map + multi-symbol signals

**Files:** `services/trader/execution/watchlist.py`, `services/trader/execution/tests/test_watchlist.py`

**Interfaces:**
- `DEFAULT_WATCHLIST: tuple[str, ...]` = `("SPY","QQQ","IWM","XLK","XLE","XLF","XLV")` (broad indices + 4 sector ETFs to exercise the 20% sector cap).
- `SECTOR_BY_TICKER: dict[str,str]` — SPY/QQQ/IWM→"BROAD", XLK→"TECH", XLE→"ENERGY", XLF→"FINANCIALS", XLV→"HEALTHCARE"; `sector_for(ticker) -> str` (default "UNKNOWN").
- `signals_for(artifact: dict, bars_by_symbol: dict[str, pd.DataFrame]) -> dict[str, DailySignal]` — per symbol run `signal.compute_signal(artifact, bars)`; skip symbols with None (undefined regime / warmup); log a one-line summary.
- `intents_for(signals, portfolio, prices, atr_by_symbol, *, weight=0.03) -> list[OrderIntent]` — per symbol `signal.intent_from_signal(...)`; drop None; the list is what `Executor.run_cycle` consumes.

- [ ] Write failing tests: `sector_for("XLE")=="ENERGY"`, default "UNKNOWN"; `signals_for` over a 2-symbol synthetic bars dict returns a signal per symbol with a valid regime, skips a warmup-only symbol; `intents_for` builds one intent per actionable signal, and each intent round-trips through `size_order` to a valid `Order` (production-input check). Reuse `compute_signal`/`intent_from_signal` from `execution/signal.py` (read it for exact signatures).
- [ ] Implement; run `pytest services/trader/execution/tests/test_watchlist.py -q` → pass; ruff.
- [ ] Commit `feat(execution): watchlist + sector map + multi-symbol signal/intent builders`.

---

### Task 2: multi-symbol `cycle` in run_paper

**Files:** modify `scripts/run_paper.py`; `tests/integration/phase-5/test_multi_symbol.py`

**Interfaces:**
- `cycle` gains `--watchlist` (flag): fetch ~450 daily bars per `DEFAULT_WATCHLIST` symbol (reuse `_daily_bars`), compute `signals_for` + `atr` per symbol, build `intents_for`, one `prices` dict (latest trade per symbol), and a `ctx_for(intent, order)` that sets `sector=sector_for(intent.ticker)` and `order_notional` from the un-clamped target weight. Run ONE `Executor.run_cycle(intents, portfolio, prices, ctx_for)`. Without `--watchlist`, the existing single-SPY `--signal` path is unchanged.
- Safety unchanged: dry-run default, `--live-orders` + quote required, halt-first, reconcile+snapshot, per-intent firewall/compliance.

- [ ] Failing integration test (offline, stub broker recording submits): a 3-symbol watchlist where one signals long (in-limits), one is undefined (skipped), one would breach the sector cap given a seeded portfolio → exactly the in-limits one submits (dry-run), the cap-breach one is rejected and never reaches the broker, and the executor saw one shared portfolio. Assert no network.
- [ ] Implement; `pytest tests/integration/phase-5/test_multi_symbol.py -q` → pass; `run_paper.py cycle --help` shows `--watchlist`; ruff.
- [ ] Commit `feat(execution): multi-symbol paper cycle (portfolio-wide firewall over a watchlist)`.

---

### Task 3: Researcher pipeline (closes the deferred Phase-4 stub)

**Files:** `services/trader/intel/researcher.py`, `services/trader/intel/tests/test_researcher.py`

**Interfaces:** reuse the T3-Phase-4 connectors (`edgar`, `fed_rss`, `fedwatch`) + `hindsight_client`.
- `Hypothesis` frozen: `source: str`, `text: str`, `signal_kind: str` (∈ {"macro_risk","rate_path","sector_rotation","event"}), `confidence: float`.
- `Researcher(connectors: dict, hindsight=None).scan(asof) -> list[Hypothesis]` — pull the macro connectors (best-effort, each in try/except → skip on error), map notable items to structured single-change hypotheses (e.g. a Fed hawkish RSS title → rate_path; an 8-K with material items → event; a FedWatch >60% hike prob → rate_path high-conf); dedup; when `hindsight` enabled, `retain` each as a World Fact and `recall` the do-not-repeat set to drop stale ones. Never raises offline → `[]`.
- `to_planner_queue(hyps) -> list[dict]` — the shape the fleet Planner reads (so the researcher's output can seed hypotheses; the Planner already grounds on Hindsight).

- [ ] Failing tests with stub connectors (fixture records): a hawkish Fed item → a rate_path hypothesis; a high FedWatch prob → high-confidence rate_path; empty/erroring connectors → `[]`; a fake Hindsight records one retain per hypothesis and drops a do-not-repeat hash. No network.
- [ ] Implement; `pytest services/trader/intel/tests/test_researcher.py -q` → pass; ruff.
- [ ] Commit `feat(intel): Researcher pipeline — macro sources → structured hypotheses (Hindsight-grounded)`.

---

### Task 4: live news refresh cadence

**Files:** modify `scripts/run_intel.py` (add `refresh` subcommand); `services/trader/news/tests/test_refresh.py` (pure helper)

**Interfaces:**
- Extract a pure `refresh_once(client, classifier, aggregator, symbols, since) -> dict` in `services/trader/news/refresh.py` — fetch news since `since`, ingest through the aggregator (writes World Facts for MATERIAL/CRITICAL), return `{symbol: SentimentState}` + counts; write the latest per-symbol sentiment to `data/sentiment/<symbol>.json` (a snapshot the MICRO lens / a future live firewall can read). Graceful: disabled client → `{}` + message.
- `run_intel.py refresh --symbols SPY QQQ --since-min 20` — one live pass; intended for periodic invocation (the launchd cadence), which IS the "15-min live sentiment" exit criterion via periodic REST rather than a held-open websocket (`# ponytail:` documented).

- [ ] Failing test for `refresh_once` with an injected fake client (fixture items) + real classifier + aggregator → returns per-symbol SentimentState, writes the snapshot JSON, counts by level; disabled client → empty + no write. No network.
- [ ] Implement; `pytest services/trader/news/tests/test_refresh.py -q` → pass; `run_intel.py refresh --help` exits 0; ruff.
- [ ] Commit `feat(intel): live news refresh cadence (periodic ingest → World Facts + sentiment snapshot)`.

---

### Task 5: FedWatch real endpoint + small robustness

**Files:** modify `services/trader/data/connectors/fedwatch.py`; extend its test.

**Interfaces:** keep the current `_get`-injectable shape; point the default `_get` at a real best-effort source (CME FedWatch has no clean public JSON — use the CME published-probabilities JSON if reachable, else the current fixture-shaped fallback, else `{}`). Add a `source: str` note in the returned mapping via a companion `probabilities_with_source(asof) -> tuple[dict, str]`. Document the best-effort nature and that a paid feed is the upgrade path (`# ponytail:`).

- [ ] Failing test: injected `_get` returns the real-shaped payload → normalized dict; network error → `{}` (unchanged graceful contract); `probabilities_with_source` returns the source label.
- [ ] Implement; test pass; ruff.
- [ ] Commit `feat(data): FedWatch best-effort real endpoint + source label`.

---

### Task 6: cadence wrapper + docs

**Files:** modify `scripts/paper_window.sh`, `docs/runbooks/paper-window.md`, `docs/PROGRESS.md`

- [ ] `paper_window.sh`: the morning branch runs `run_intel.py refresh --symbols SPY QQQ IWM` before the `cycle` (so sentiment is fresh), and `cycle` uses `--watchlist` (multi-symbol). Keep the weekday guard + logging. Runbook updated with the multi-symbol + refresh notes. PROGRESS gets a "Tier-3 completion" section.
- [ ] `bash -n scripts/paper_window.sh` parses; commit `feat(ops): cadence runs news refresh + multi-symbol cycle; docs`.

---

## Self-review
- **Coverage:** multi-symbol (T1+T2) makes it a real portfolio system — the biggest completeness gap; Researcher (T3) closes the one explicitly-deferred Phase-4 stub; live news refresh (T4) satisfies the Phase-4 "sentiment every 15 min" exit via periodic REST; FedWatch (T5) removes the last stub transport; cadence (T6) wires it together.
- **Deliberately deferred (documented):** FinBERT (lexicon meets SLA), held-open websocket (periodic REST suffices locally), multi-symbol *training* (the strategy is symbol-agnostic; per-symbol application at execution is the value — retraining per-symbol is a research extension, not a completeness gap). These are noted so "complete" is honest, not silent.
- **Safety:** no change to the firewall/executor/reconciler contracts; multi-symbol exercises paths already built and tested. Every new network path is graceful-offline + unit-tested without the network.
- **The two uncompressible gates remain:** ≥30 elapsed paper days (convergence) and the human capital sign-off. Feature-complete ≠ cleared-to-trade-real-money — by design.
