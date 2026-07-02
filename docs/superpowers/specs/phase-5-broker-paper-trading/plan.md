# Phase 5 — Broker + Paper Trading — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Dependency graph + parallel waves live in [`tasks.md`](tasks.md).

**Goal:** Route a promoted strategy's signal into a real Alpaca **paper** order through an architectural hard-limit + compliance firewall, with reconciliation and the <10s kill-switch — proving the system trades responsibly before any real capital. **No real capital**: paper endpoint only, and every actual order submission is gated behind a dry-run-default switch.

**Architecture:** A new substrate-independent `services/trader/execution/` package. A domain model (Order/Position/Portfolio/OrderIntent) bridges strategy signals and broker fills. The **firewall is architectural** — an order that fails any hard limit or compliance check is logged and *never reaches the broker* (the executor calls the firewall before the broker, and the broker's `submit_order` defaults to `dry_run=True`). Reuses Layer-3 `HaltControl` (kill-switch), Phase-4 `NewsShockProtocol` (already trips halt), Phase-1 `backtest/risk.py` limit logic, `ReleaseCalendar` (FOMC/CPI/NFP), and the `AlpacaNewsClient` auth pattern. Transactional state → Postgres `trades.*` (ACID for reconciliation/tax); decision *context* → Hindsight Experience Facts.

**Tech Stack:** Python 3.11+, pandas/numpy, httpx (Alpaca trading REST), psycopg (trades.*), pytest, uv, ruff. Alpaca paper trading API (`https://paper-api.alpaca.markets/v2`): `/account`, `/positions`, `/orders`. Auth = `APCA-API-KEY-ID`/`APCA-API-SECRET-KEY` (same as `alpaca_news.py`).

## Global Constraints

- Python 3.11+; full type hints in `services/`. Pydantic/dataclasses at boundaries; no untyped dicts. ruff clean (E401 one-import-per-line, E702 no-compound, I001 sorted).
- **SAFETY — the firewall is architectural, not advisory.** The executor MUST call `HardLimitFirewall.check` (and compliance) and only submit orders it returns `allowed=True` for. A rejected order is logged with reason and never submitted. This is the Phase-5 exit criterion and the most important invariant — test it directly.
- **SAFETY — dry-run by default.** `AlpacaBrokerClient.submit_order(order, dry_run=True)` defaults to NOT POSTing (returns a simulated ack, logs the intent). The executor's `live_orders: bool = False` must be explicitly set to submit real paper orders. No task enables live submission by default. `/account` and `/positions` are read-only GETs and always safe.
- **SAFETY — paper endpoint only.** The broker client reads `ALPACA_PAPER_ENDPOINT`; a live endpoint is out of scope for this phase. Real-capital go-live is a human gate (CLAUDE.md) — not in this plan.
- **Kill-switch <10s:** the executor checks `HaltControl.is_halted()` at the top of every cycle AND before every submit; a halt stops all new orders immediately. Reuse the Layer-3 `HaltControl`; do not invent a new mechanism.
- **Graceful-offline / no-key:** no `ALPACA_API_KEY` → broker `is_enabled()` False, reads return empty, submits are no-ops. No DSN → trades persistence skipped. Unit tests never hit the network (injected transports + fixtures).
- **No look-ahead in the firewall's market inputs;** regime confidence + ATR come from PIT features.
- Tests next to code (`services/trader/execution/tests/`). TDD. Conventional commits, branch per task, PR + CI green before merge, never `--no-verify`.

---

## File Structure

**`services/trader/execution/`:**
- `model.py` — `Side`/`OrderType`/`OrderStatus` enums; `OrderIntent`, `Order`, `Position`, `Portfolio` dataclasses; helpers (`Portfolio.position_pct`, `.sector_exposure`).
- `alpaca_broker.py` — `AlpacaBrokerClient(key,secret,endpoint)`: `.account()`, `.positions()`, `.submit_order(order, dry_run=True)`, `.cancel_order(id)`, `.get_order(id)`. Graceful no-key; dry-run default.
- `sizing.py` — `size_order(intent, portfolio, price, *, max_position_pct=0.05) → Order` (weight→shares, fractional, min-notional guard).
- `stops.py` — `atr(ohlcv, window=14) → pd.Series`; `atr_stop(entry, atr_value, side, mult=2.0) → float`.
- `calendar_gate.py` — `EconCalendarGate(release_calendar=None).is_blackout(now, tickers) → bool` (±30 min / release-day around FOMC/CPI/NFP; graceful no-key).
- `firewall.py` — `HardLimitFirewall(...).check(intent, order, portfolio, ctx) → FirewallVerdict(allowed, rejections)`. The architectural gate.
- `compliance.py` — `ComplianceEngine(...).check(intent, portfolio, history) → ComplianceVerdict` (PDT, wash-sale, SSR-ready).
- `reconcile.py` — `Reconciler(broker, halt).reconcile(local: Portfolio) → ReconResult` (halt on >1% notional / phantom).
- `executor.py` — `Executor(broker, firewall, compliance, halt, *, live_orders=False).run_cycle(strategy, regime, portfolio, market) → CycleReport`. The order flow.
- `trade_store.py` — `TradeStore(dsn=None)`: persist orders/fills/positions to `trades.*`; graceful no-DSN.

**Config + integration:**
- `infra/postgres/migrations/007_trades.sql` — `trades.orders`, `trades.fills`, `trades.positions`, `trades.pnl_daily`.
- `scripts/run_paper.py` — CLI: `account`/`positions` (read smokes), `cycle` (dry-run one execution cycle on a registry strategy). Graceful-offline.
- `tests/integration/phase-5/test_execution_firewall.py` — the architectural firewall test + a dry-run cycle end-to-end.

---

### Task 1: execution domain model

**Files:** Create `services/trader/execution/__init__.py`, `model.py`, `tests/__init__.py`, `tests/test_model.py`.

**Interfaces:**
- Produces:
  - `Side(str, Enum)` = BUY/SELL; `OrderType` = MARKET/LIMIT; `OrderStatus` = NEW/SUBMITTED/FILLED/PARTIAL/CANCELED/REJECTED.
  - `OrderIntent` frozen: `ticker`, `side: Side`, `target_weight: float` ([-1,1]), `reason: str`, `regime_confidence: float`, `stop_price: float | None`.
  - `Order` frozen: `id: str|None`, `ticker`, `side`, `qty: float`, `order_type: OrderType`, `limit_price: float|None`, `stop_price: float|None`, `status: OrderStatus`, `filled_qty: float=0`, `filled_avg_price: float|None`.
  - `Position` frozen: `ticker`, `qty: float`, `avg_entry: float`, `market_value: float`, `unrealized_pl: float`, `sector: str="UNKNOWN"`.
  - `Portfolio` frozen: `equity: float`, `cash: float`, `buying_power: float`, `positions: dict[str, Position]`, `day_trade_count: int=0`. Methods: `position_pct(ticker) → float` (`|market_value|/equity`), `sector_exposure(sector) → float`, `notional() → float`.

- [ ] **Step 1: Write the failing test** — build a `Portfolio` with two positions; assert `position_pct` and `sector_exposure` compute the right fractions; `OrderIntent`/`Order` construct with the right defaults; enums round-trip their string values.
- [ ] **Step 2: Run → fails** (module missing).
- [ ] **Step 3: Implement** the enums + frozen dataclasses + the three Portfolio helpers (pure arithmetic; guard equity==0 → 0.0).
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `feat(execution): order/position/portfolio domain model`

---

### Task 2: `AlpacaBrokerClient` — paper trading API (dry-run default)

**Files:** Create `services/trader/execution/alpaca_broker.py`, `tests/test_alpaca_broker.py`, fixtures `tests/fixtures/{account,positions,order}.json`.

**Interfaces:**
- Consumes: `model.Order`, `model.Position`, `model.Portfolio`.
- Produces: `AlpacaBrokerClient(key=None, secret=None, endpoint="https://paper-api.alpaca.markets/v2")`:
  - `.is_enabled() → bool`; `.account() → Portfolio` (GET `/account` + `/positions`); `.positions() → dict[str,Position]`;
  - `.submit_order(order, *, dry_run=True) → Order` — **dry_run=True (default) does NOT POST**; returns the order with `status=SUBMITTED` and a simulated id, logging the intent. `dry_run=False` POSTs to `/orders` (`APCA` headers) and maps the response to `Order`.
  - `.cancel_order(id) → bool`; `.get_order(id) → Order | None`.
  - No key → `is_enabled()` False, `.account()` returns an empty `Portfolio`, `.submit_order` is a logged no-op. Transport `_get`/`_post`/`_delete` overridable for tests.

- [ ] **Step 1: Failing test** — parse the committed `account.json`+`positions.json` fixtures via the client's mappers → a `Portfolio` with the right equity + positions; `AlpacaBrokerClient(None,None)` is disabled and `.account()` is empty; **`submit_order(order)` with default dry_run makes NO `_post` call** (inject a `_post` that raises; submit still returns a SUBMITTED order) — the dry-run safety invariant.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** — httpx via overridable transports; `_map_account`/`_map_position`/`_map_order`; dry-run short-circuits before `_post`. Mirror `alpaca_news.py` auth + disabled idiom.
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `feat(execution): AlpacaBrokerClient — paper account/positions/orders (dry-run default, graceful no-key)`

---

### Task 3: `trades.*` migration

**Files:** Create `infra/postgres/migrations/007_trades.sql`, `tests/test_trades_schema.py` (DSN-gated).

**Interfaces:**
- Produces: `trades.orders` (id, ts, ticker, side, qty, order_type, limit_price, stop_price, status, broker_order_id, reason, filled_qty, filled_avg_price), `trades.fills` (order_id FK, ts, qty, price), `trades.positions` (snapshot: ts, ticker, qty, avg_entry, market_value, unrealized_pl), `trades.pnl_daily` (date, equity, realized_pl, unrealized_pl). `IF NOT EXISTS` throughout (the `trades` schema exists from `002_schemas.sql`).

- [ ] **Step 1: Failing test** (DSN-gated) — the four tables exist and accept a sample insert/round-trip.
- [ ] **Step 2: Run → fails** (no tables).
- [ ] **Step 3: Implement** the SQL (mirror `005_experiments.sql` style; FKs; indexes on ticker+ts).
- [ ] **Step 4: Recreate dev DB + run test → passes** (CI integration-smoke applies it on a fresh DB).
- [ ] **Step 5: Commit** — `feat(db): trades.orders/fills/positions/pnl_daily schema`

---

### Task 4: ATR + stop-loss util

**Files:** Create `services/trader/execution/stops.py`, `tests/test_stops.py`. (Check `services/trader/features/volatility.py` first — reuse an existing ATR if present.)

**Interfaces:**
- Produces: `atr(ohlcv: pd.DataFrame, window=14) → pd.Series` (Wilder true-range ATR; PIT — only past bars); `atr_stop(entry: float, atr_value: float, side: Side, mult=2.0) → float` (BUY → `entry - mult*atr`, SELL → `entry + mult*atr`). If `features/volatility.py` already computes ATR, import + wrap it rather than re-derive.

- [ ] **Step 1: Failing test** — `atr` on a known small OHLCV equals the hand-computed Wilder ATR; `atr_stop` places the stop `2*atr` below entry for BUY, above for SELL; PIT (future bars don't change a past ATR value).
- [ ] **Step 2–5:** implement (reuse volatility.py ATR if it exists), test passes, ruff, commit `feat(execution): ATR + 2xATR stop-loss util`.

---

### Task 5: economic-calendar entry gate

**Files:** Create `services/trader/execution/calendar_gate.py`, `tests/test_calendar_gate.py`.

**Interfaces:**
- Consumes: `data/connectors/release_calendar.ReleaseCalendar` (FRED release dates for CPI/NFP; FOMC dates).
- Produces: `EconCalendarGate(release_calendar=None, blackout_minutes=30).is_blackout(now: pd.Timestamp, series=("CPIAUCSL","PAYEMS")) → bool` — True if `now` is within ±`blackout_minutes` of a scheduled release (or, at daily granularity, on a release day within the window). `release_calendar=None` → never blackout (graceful; logged). FOMC dates via a small committed constant list (Fed doesn't have a FRED series) + CPI/NFP via the calendar. `# ponytail: daily-granularity blackout (release day) since FRED gives dates not times; tighten to ±30min when an intraday time source is wired.`

- [ ] **Step 1: Failing test** — with a stub calendar returning a known release date, `is_blackout` is True on that date and False the day after; `release_calendar=None` → always False. FOMC constant dates are honored.
- [ ] **Step 2–5:** implement, test passes, ruff, commit `feat(execution): economic-calendar entry blackout gate (FOMC/CPI/NFP)`.

---

### Task 6: position sizing

**Files:** Create `services/trader/execution/sizing.py`, `tests/test_sizing.py`.

**Interfaces:**
- Consumes: `model.{OrderIntent,Portfolio,Order,Side,OrderType}`.
- Produces: `size_order(intent, portfolio, price, *, max_position_pct=0.05, allow_fractional=True, min_notional=1.0) → Order | None` — target notional = `intent.target_weight * portfolio.equity`, clamped to `max_position_pct * equity`; qty = notional/price (rounded to whole shares unless `allow_fractional`); returns `None` if notional < `min_notional` (skip sub-share-cost orders). Sets `stop_price` from the intent.

- [ ] **Step 1: Failing test** — a 0.10 target weight on $100k equity at $50 → clamped to 5% ($5k) → 100 shares; a tiny weight below min_notional → `None`; fractional off → integer qty. Stop carried through.
- [ ] **Step 2–5:** implement, test passes, ruff, commit `feat(execution): position sizing (weight→shares, 5% clamp, min-notional)`.

---

### Task 7: hard-limit firewall (the architectural gate)

**Files:** Create `services/trader/execution/firewall.py`, `tests/test_firewall.py`.

**Interfaces:**
- Consumes: `model.*`, `stops` (T4), `calendar_gate` (T5), and the Phase-1 `backtest/risk.py` limit logic (reuse where shaped right).
- Produces:
  - `FirewallContext` frozen: `now: pd.Timestamp`, `regime_confidence: float`, `daily_pl_pct: float`, `monthly_pl_pct: float`, `has_stop: bool`, `sector: str`.
  - `FirewallVerdict` frozen: `allowed: bool`, `rejections: list[str]`.
  - `HardLimitFirewall(max_position_pct=0.05, max_sector_pct=0.20, daily_loss_halt=0.02, monthly_catastrophic=0.10, min_regime_conf=0.40, calendar_gate=None).check(intent, order, portfolio, ctx) → FirewallVerdict` — collect ALL violations (don't short-circuit): position >5%, resulting sector >20%, `daily_pl_pct <= -2%`, `monthly_pl_pct <= -10%`, `regime_confidence < 0.40`, econ blackout, missing ATR stop (`ctx.has_stop` False and side is an entry). `allowed = not rejections`.

- [ ] **Step 1: Write the failing test** — an in-limits entry with a stop and high confidence → `allowed`; then one test per limit forcing exactly that rejection (position>5%, sector>20%, daily<=-2%, monthly<=-10%, conf<40%, blackout via a stub gate, missing stop) → `allowed False` with that reason present; a multi-violation order lists all reasons.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** — pure predicate collection; reuse `backtest/risk.py` thresholds; `calendar_gate.is_blackout` for the release window. No I/O.
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `feat(execution): hard-limit firewall — architectural entry gate (position/sector/loss/regime/calendar/stop)`

---

### Task 8: compliance engine

**Files:** Create `services/trader/execution/compliance.py`, `tests/test_compliance.py`.

**Interfaces:**
- Consumes: `model.*`.
- Produces: `ComplianceVerdict` frozen (`allowed`, `rejections`); `ComplianceEngine(pdt_equity_floor=25_000, wash_window_days=30, btc_etf_group=frozenset({"IBIT","FBTC","GBTC","BITB","ARKB"})).check(intent, portfolio, recent_trades: list) → ComplianceVerdict`:
  - **PDT:** if `portfolio.equity < 25_000` and this order would be the 4th day-trade in a rolling 5-business-day window → reject.
  - **Wash-sale:** if a loss-closing sale of `intent.ticker` (or a BTC-ETF-group sibling) occurred within 30 days → reject a re-buy.
  - **SSR:** stub predicate returning allowed (activates Phase 8b).

- [ ] **Step 1: Failing test** — a 4th day-trade under $25k → PDT reject; ≥$25k → allowed; a re-buy within 30 days of a BTC-ETF sibling loss sale → wash-sale reject; outside 30 days → allowed.
- [ ] **Step 2–5:** implement, test passes, ruff, commit `feat(execution): compliance — PDT + wash-sale (BTC-ETF group) + SSR-ready`.

---

### Task 9: reconciliation

**Files:** Create `services/trader/execution/reconcile.py`, `tests/test_reconcile.py`.

**Interfaces:**
- Consumes: `AlpacaBrokerClient` (T2), `HaltControl`, `model.Portfolio`.
- Produces: `ReconResult` frozen (`matched: bool`, `mismatches: list[str]`, `halted: bool`); `Reconciler(broker, halt, notional_tolerance=0.01).reconcile(local: Portfolio) → ReconResult` — compares `local.positions` to `broker.positions()`; a per-ticker notional diff > 1% of equity OR a phantom position (in one but not the other) → record mismatch and `halt.halt("reconciliation: ...")` (halted True). Benign sub-tolerance diffs → matched.

- [ ] **Step 1: Failing test** — identical local/broker → matched, no halt; a phantom broker position → mismatch + `halt.is_halted()` True (isolated HaltControl); a >1% notional drift → halt; a <1% drift → matched.
- [ ] **Step 2–5:** implement, test passes, ruff, commit `feat(execution): reconciliation — local vs broker, halt on material discrepancy`.

---

### Task 10: executor — the order flow (dry-run gated)

**Files:** Create `services/trader/execution/executor.py`, `tests/test_executor.py`.

**Interfaces:**
- Consumes: `AlpacaBrokerClient`, `HardLimitFirewall`, `ComplianceEngine`, `sizing.size_order`, `HaltControl`, `model.*`, `hindsight_client` (retain the decision context).
- Produces:
  - `CycleReport` frozen: `intents: int`, `submitted: int`, `rejected: int`, `halted: bool`, `rejections: list[str]`.
  - `Executor(broker, firewall, compliance, halt, *, hindsight=None, live_orders=False).run_cycle(intents: list[OrderIntent], portfolio, prices: dict, ctx_for) → CycleReport` — for each intent: **check `halt.is_halted()` first** (halted → stop, report halted); `size_order`; build `FirewallContext` via `ctx_for(intent)`; `firewall.check` → if not allowed, log+count rejected, continue (NEVER submit); `compliance.check` → same; else `broker.submit_order(order, dry_run=not live_orders)` and count submitted; retain an Experience Fact when hindsight enabled. **`live_orders=False` (default) → every submit is dry-run.**

- [ ] **Step 1: Write the failing test (the architectural invariant)** — with a stub broker whose `submit_order` records calls: an over-5%-position intent is **rejected and `submit_order` is NEVER called**; an in-limits intent is submitted as **dry-run** (default) — assert the broker saw `dry_run=True`; a pre-halted `HaltControl` yields `halted=True, submitted=0`; a compliance-failing intent is rejected pre-submit. This test IS the Phase-5 firewall exit criterion.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** the flow; firewall+compliance strictly before submit; halt checked first; `dry_run=not live_orders`.
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `feat(execution): executor — firewall-gated order flow, dry-run default, halt-first`

---

### Task 11: trades persistence

**Files:** Create `services/trader/execution/trade_store.py`, `tests/test_trade_store.py` (DSN-gated + a no-DSN no-op test).

**Interfaces:**
- Consumes: `model.{Order,Position}`, Task-3 `trades.*`.
- Produces: `TradeStore(dsn=None)`: `.record_order(order, reason)`, `.record_fill(order_id, qty, price)`, `.snapshot_positions(portfolio)`, `.record_daily_pnl(date, equity, realized, unrealized)`; `.is_enabled()`. `dsn=None` → every call a safe no-op (the `ProvenanceWriter(None)` pattern).

- [ ] **Step 1: Failing test** — `TradeStore(None)` is disabled and every method is a no-op (no raise); DSN-gated: `record_order` then a query returns the row.
- [ ] **Step 2–5:** implement (lazy psycopg), test passes, ruff, commit `feat(execution): TradeStore — persist orders/fills/positions to trades.* (graceful no-DSN)`.

---

### Task 12: runner + Phase-5 integration smoke

**Files:** Create `scripts/run_paper.py`, `tests/integration/phase-5/__init__.py`, `tests/integration/phase-5/test_execution_firewall.py`; add `tests/integration/phase-5/**` to the pyproject N999 ignore if absent.

**Interfaces:**
- Consumes: everything above.
- Produces: `run_paper.py` subcommands: `account` (print the paper Portfolio — read-only GET), `positions` (print open positions), `cycle --strategy <artifact>` (run ONE dry-run execution cycle from a registry strategy's current signal; prints the CycleReport; **never submits live unless `--live-orders` is passed**, which prints a bold confirmation and is off by default). All graceful-offline.
- The integration test: end-to-end OFFLINE (stub broker, no network) — an over-limit intent is rejected and never submitted; an in-limits intent is dry-run submitted; a halted control stops the cycle. Asserts the firewall invariant + the dry-run default.

- [ ] **Step 1: Failing integration test** — `Executor(...).run_cycle([...])` with a mix of in-limits and over-limit intents → `submitted` counts only the dry-run in-limits ones, `rejected` counts the rest, the stub broker never saw a `dry_run=False` call.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Wire `run_paper.py` + the test.** `--live-orders` defaults False and prints a confirmation banner.
- [ ] **Step 4: Run → passes** (offline). Add to CI integration-smoke. Live read-only smoke (with key): `run_paper.py account` prints the real paper equity.
- [ ] **Step 5: Commit** — `feat(execution): run_paper runner + phase-5 firewall integration smoke`

---

## Self-Review

**Spec coverage** (Phase-5 spec §2 sub-features + §3 exit criteria):
1. Alpaca paper integration → T2 (+T9 reconciliation query). 2. Position sizing → T6. 3. Compliance (PDT/wash-sale/SSR) → T8. 4. Hard-limit enforcement at the execution boundary → T7 (+T4 ATR stop, +T5 calendar). 5. Reconciliation → T9. 6. 30-day paper window → the *operation* of `run_paper.py` (T12) under Phase-6 monitoring — the code path ships here; the 30-day run is an operational exit-gate, not a code task.
- **Exit criteria:** submit/cancel/query orders (T2) · rejected order logged + never reaches broker (T10 executor test — the architectural invariant + T12) · reconciliation catches injected discrepancy (T9) · 30-day live run (operational, post-merge) · Sharpe>1.0 (operational metric on the paper window).
- **Model blocker** the scout flagged → T1 (built first, everything depends on it).
- **trades.* persistence** (spec memory-revision: transactional state in Postgres) → T3 + T11.

**Deferred/flagged (deliberate, paper-appropriate):** econ-calendar blackout is daily-granularity (FRED gives dates not times) — tightened to ±30min when an intraday time source lands (ponytail comment in T5). SSR is a stub (activates Phase 8b per spec). The 30-day unattended window + Sharpe>1.0 are operational gates run after merge under Phase-6 monitoring, not unit tasks. **Live order submission is never enabled by default** — `live_orders=False` / `dry_run=True` throughout; flipping it is an explicit, surfaced human decision (aligns with the CLAUDE.md real-capital gate and the outward-facing-action rule).

**Placeholder scan:** safety-critical/novel tasks (T1 model, T2 broker dry-run, T7 firewall, T10 executor) carry full step detail + the invariant tests; mechanical tasks (T3–T6, T8, T9, T11) compress steps 3–5 with the interface + step-1 test pinning the contract.

**Type consistency:** `OrderIntent`/`Order`/`Position`/`Portfolio` (T1) are consumed unchanged by T2/T6/T7/T8/T9/T10/T11. `FirewallVerdict`/`ComplianceVerdict`/`ReconResult`/`CycleReport` each defined once in their producing task. `HaltControl` (Layer 3) reused by T9/T10. `AlpacaBrokerClient` (T2) consumed by T9/T10/T12. `size_order`/`firewall.check`/`compliance.check` signatures match between definition and the executor (T10).

**Safety invariant, restated:** the executor calls firewall+compliance BEFORE the broker, submits only `allowed` orders, and the broker defaults to dry-run — so a limit-violating or non-approved order is architecturally incapable of reaching Alpaca. T10's test asserts `submit_order` is never called for a rejected intent and only ever with `dry_run=True` by default.
