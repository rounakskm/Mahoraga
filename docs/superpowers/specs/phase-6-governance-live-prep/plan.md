# Phase 6 — Governance + Live Prep — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Checkbox (`- [ ]`) steps. Dependency graph in [`tasks.md`](tasks.md).

**Goal:** Operator-facing surfaces + safety hardening so a human can supervise, audit, and halt the system with confidence — kill-switch UX, extended Telegram bot, Streamlit dashboard, audit hash-chain discipline, performance attribution, and the convergence report that gates real capital.

**Architecture:** Compose what exists. `HaltControl`/`TelegramOps`/`Reporter` (Layer 3), `trades.*` + `TradeStore` (Phase 5), `audit.events` hash-chain schema (migration 003), Hindsight client, `strategies.registry`. New code is a pure data-assembly layer under `services/trader/ops/` (fully unit-testable, DSN/broker/Hindsight all injectable + graceful-offline) with two thin UI shells: the Streamlit app (`scripts/dashboard.py`) and report renderers. **Review lesson applied (gates-real-inputs-fake):** every data-layer test feeds production-shaped rows (real schema column names), and each surface has a cross-check test against the real migration DDL.

**Tech Stack:** Python 3.11+, pandas 3.0.3, psycopg, httpx, Streamlit (new dep, `ops` extra), pytest, uv, ruff.

## Global Constraints

- Type hints everywhere; ruff clean (E,F,W,I,N,UP,B,SIM,RET); tests next to code; TDD.
- Graceful-offline: `dsn=None`/`broker` disabled/`hindsight=None` → empty-but-renderable surfaces, never raise. One-time `logging.warning` when a surface is degraded (review lesson #2).
- Kill-switch paths must keep the <10s end-to-end guarantee; the dashboard halt button and Telegram `/halt` both write the SAME `HaltControl` default flag.
- No plaintext secrets in any new file; dashboard reads env only.
- Real-capital go-live stays a human gate; the convergence report renders a documented yes/no + rationale, it does not flip anything.

---

## File Structure

- `services/trader/ops/audit.py` — `AuditLog(dsn)`: hash-chained append + chain verification over `audit.events` (migration 003 columns).
- `services/trader/ops/attribution.py` — `attribute(fills_df, regimes, ...) → AttributionReport` (P&L by regime / ticker / side / holding-period). Pure pandas.
- `services/trader/ops/telegram.py` (extend) — `/regime`, `/strategy <hash>`, `/kb`, `/report daily|weekly`; injectable providers.
- `services/trader/ops/dashboard_data.py` — `DashboardData(dsn, broker=None, hindsight=None)`: one method per dashboard panel, each returning a plain dataclass/DataFrame; the Streamlit app only renders.
- `scripts/dashboard.py` — the Streamlit app (thin; halt button → `HaltControl().halt()`).
- `services/trader/ops/convergence.py` + `scripts/convergence_report.py` — readiness gathering + markdown report with documented thresholds.
- `infra/ci/tests/test_secrets_audit.py` — sandbox secrets audit (no `.env`/key material reachable from sandbox-mounted scopes).
- `pyproject.toml` — `ops` optional dependency group (`streamlit`).

---

### Task 1: `AuditLog` — hash-chained append + verification

**Files:** Create `services/trader/ops/audit.py`, `services/trader/ops/tests/test_audit.py`. READ `infra/postgres/migrations/003_audit.sql` first and bind to its real columns.

**Interfaces:** `AuditLog(dsn: str | None)`: `.append(event_type: str, payload: dict) -> str | None` (returns the row hash; hash = sha256(prev_hash + canonical-json payload + event_type + ts-from-db is unstable → hash over prev_hash + event_type + canonical payload only, ts stored but not hashed — document why); `.verify_chain() -> ChainVerdict(ok: bool, rows: int, first_bad: int | None)`; `.is_enabled()`. dsn=None → no-op/None. Autocommit per row (crash-safe: a torn write is absent, not corrupt).

- [ ] Steps: TDD — pure hash-logic tests always run (chain of 3 dicts → deterministic hashes; tamper detection via a `_verify_rows(rows)` helper taking injected rows); DSN-gated append+verify round-trip. ruff. Commit `feat(ops): AuditLog — hash-chained append + chain verification`.

---

### Task 2: `attribution` — performance attribution

**Files:** Create `services/trader/ops/attribution.py`, `services/trader/ops/tests/test_attribution.py`.

**Interfaces:** `AttributionReport` frozen (`total_pl: float`, `by_regime: dict[str, float]`, `by_ticker: dict[str, float]`, `by_side: dict[str, float]`, `by_holding_period: dict[str, float]` buckets `intraday/1-5d/5-20d/20d+`, `n_round_trips: int`); `attribute(orders: pd.DataFrame, regimes: pd.Series | None = None) -> AttributionReport` where `orders` has the **production `trades.orders` columns** (ts, ticker, side, filled_qty, filled_avg_price, status) — pair FILLED buys/sells per ticker FIFO into round trips, compute realized P&L per trip, bucket. `regimes` (bar-indexed labels) optional → by_regime uses the entry-date label, else `{"unknown": total}`.

- [ ] Steps: TDD — a hand-built order set with known round-trip P&L (+$500 SPY 3d trip in trending_low_vol, −$200 QQQ intraday) → exact buckets; empty frame → zeroed report. Column names asserted against `007_trades.sql` DDL text (cross-check test, review lesson). ruff. Commit `feat(ops): performance attribution (regime/ticker/side/holding-period)`.

---

### Task 3: Telegram extended commands + daily/weekly report

**Files:** Modify `services/trader/ops/telegram.py`; extend `services/trader/ops/tests/test_telegram.py`.

**Interfaces:** `TelegramOps(halt, reporter, token=None, allowed_chat_ids=None, *, regime_provider=None, strategy_provider=None, kb_provider=None, report_provider=None)` — new optional callables: `regime_provider() -> str` (rendered current regime + transition prob), `strategy_provider(hash) -> str`, `kb_provider() -> str` (recent Hindsight highlights), `report_provider(kind) -> str` (daily/weekly). `.handle`: `/regime`, `/strategy <hash>`, `/kb`, `/report daily|weekly` route to providers; provider None → "not wired" reply (never raise); help text lists all commands.

- [ ] Steps: TDD — each new command with a stub provider returns its render; missing provider → graceful reply; help updated; existing tests stay green. ruff. Commit `feat(ops): telegram /regime /strategy /kb /report commands`.

---

### Task 4: secrets sandbox audit

**Files:** Create `infra/ci/tests/test_secrets_audit.py`.

**Interfaces:** A CI test asserting: (a) `.env` is git-ignored (`git check-ignore .env` exit 0 — run via subprocess with cwd=repo root; skip if no .env); (b) no tracked file under `infra/nemoclaw/` or `services/` contains an Alpaca/FRED/NVIDIA key pattern (`grep -rE "(PK[A-Z0-9]{16,}|APCA-API-SECRET)" --include=*` over tracked files via `git grep`); (c) the sandbox filesystem scopes in `infra/nemoclaw/policies/filesystem.yaml` do not include the repo root or `.env` path (parse the yaml textually; the writable scopes must be under /sandbox subpaths). Document in the test docstring that full keyring migration is deferred to cloud deploy (`# ponytail:` note).

- [ ] Steps: TDD (plant a fake key in a tmp copy → the grep helper catches it), run against the real repo → PASS. ruff. Commit `test(ci): secrets sandbox audit — no plaintext keys reachable`.

---

### Task 5: `DashboardData` — the pure data layer

**Files:** Create `services/trader/ops/dashboard_data.py`, `services/trader/ops/tests/test_dashboard_data.py`. READ `reporter.py`, `trade_store.py`, `alpaca_broker.py`, `hindsight_client.py`, `attribution.py` (T2) for real signatures.

**Interfaces:** `DashboardData(dsn=None, broker=None, hindsight=None)` with one method per panel, all graceful-offline: `.positions() -> pd.DataFrame` (broker or latest `trades.positions` snapshot), `.recent_orders(limit=50) -> pd.DataFrame` (trades.orders), `.fleet_activity(limit=100) -> pd.DataFrame` (experiments.iterations), `.regime_now() -> dict` (latest labels from parquet via the Phase-1 detector when data present, else `{}`), `.kb_recent(k=10) -> list[dict]` (Hindsight recall), `.attribution() -> AttributionReport` (T2 over recent_orders), `.pnl_series() -> pd.DataFrame` (trades.pnl_daily), `.halt_status() -> dict` (HaltControl state + reason). Every DB read takes an injectable `rows` for tests + real SQL against production column names.

- [ ] Steps: TDD — each method with injected production-shaped rows; all-None constructor → empty-but-typed returns; a DDL cross-check test asserting the SQL column lists appear in the migration files. ruff. Commit `feat(ops): DashboardData — pure panel data layer (graceful-offline)`.

---

### Task 6: Streamlit dashboard + kill-switch UX

**Files:** Create `scripts/dashboard.py`; Modify `pyproject.toml` (add `[project.optional-dependencies] ops = ["streamlit>=1.40"]`); Test `services/trader/ops/tests/test_dashboard_smoke.py` (import + panel-assembly smoke without streamlit runtime).

**Interfaces:** The app: sidebar HALT button (red) → `HaltControl().halt("dashboard operator halt")` + RESUME button; panels: halt banner (if halted), regime state, positions, recent orders, P&L chart (pnl_daily), fleet activity, KB recent, attribution tables — all from `DashboardData`, each panel wrapped so one failing panel never blanks the page. Run: `uv run --with streamlit streamlit run scripts/dashboard.py`. Structure the module so panel-builder functions are importable WITHOUT streamlit installed (lazy `import streamlit` inside `main()`); the smoke test imports the module and calls the pure builders.

- [ ] Steps: TDD — smoke test imports + builds panels offline; kill-switch timing test: `HaltControl.halt()` → `is_halted()` visible <1s (trivially true; assert to pin the contract). Manual verify: launch the app, screenshot if possible. ruff. Commit `feat(ops): Streamlit dashboard + kill-switch UX (halt button)`.

---

### Task 7: convergence report — the Phase-7 gate artifact

**Files:** Create `services/trader/ops/convergence.py`, `scripts/convergence_report.py`, `services/trader/ops/tests/test_convergence.py`.

**Interfaces:** `ConvergenceInputs` (gathered: `deployment_eligible: list[dict]` from strategies.registry, `replay_years: float` from experiments.iterations run_id span or provided, `regime_coverage: dict[str, int]` labels seen in training data, `kb_depth: dict` Hindsight counts, `paper_days: int`, `paper_sharpe: float | None`); `ConvergenceReport` (per-criterion pass/fail + rationale + overall `ready: bool`); `evaluate(inputs, thresholds=DEFAULT_THRESHOLDS) -> ConvergenceReport`. **DEFAULT_THRESHOLDS (documented rationale in-module):** ≥1 deployment-eligible strategy with vault_holds; replay ≥3 years; all 4 MESO regimes represented ≥5% of bars; paper window ≥30 days with Sharpe >1.0; KB depth ≥100 facts. `render_markdown(report) -> str`. The script gathers real inputs (DSN/Hindsight/paper stats file) and writes `docs/convergence/<date>-report.md`. Missing inputs → criterion FAILS with "not yet measured" (fail-closed — readiness can't pass vacuously; review lesson).

- [ ] Steps: TDD — all-pass inputs → ready True with rationale strings; missing paper stats → that criterion fails and overall not ready; renderer includes every criterion. ruff. Commit `feat(ops): convergence report — documented go/no-go for real capital (fail-closed)`.

---

## Self-Review

**Spec coverage:** kill-switch UX → T6 (+ existing Telegram /halt); Telegram bot commands → T3; Streamlit dashboard → T5+T6; audit-log discipline → T1; security hardening → T4 (keyring deferred, documented); convergence report → T7; performance attribution → T2 (surfaced in T5/T6). Exit criteria all mapped; the <10s kill-switch is pinned by T6's timing test + the existing end-to-end halt tests.
**Placeholder scan:** each task's step-1 test + interface block pins the contract; UI shell (T6) is deliberately thin with the logic in T5.
**Type consistency:** `AttributionReport` defined in T2, consumed by T5/T6/T7; `DashboardData` consumed by T6; `ChainVerdict` local to T1.
**Review lesson applied:** DDL cross-check tests (T2, T5), fail-closed convergence (T7), one-time degradation warnings, production-shaped fixtures throughout.
