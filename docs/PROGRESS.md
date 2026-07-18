# Mahoraga — Progress

Single source of "where are we". Updated as work lands on `main`. Detail lives in
the per-phase specs + `docs/measurements/*-exit-verification.md`.

**Last updated:** 2026-06 (Phase-3 Layer-1 provenance slice)

## Phase status

| Phase | What | Status |
|---|---|---|
| 0 | Substrate bring-up (compose, Postgres, LiteLLM, sandbox) | ✅ complete |
| — | **Substrate migration** — OpenClaw → **Hermes**, NVIDIA Nemotron inference, **Hindsight memory** (Hermes proven using it) | ✅ complete |
| 1 | Data + features + regime detector + backtest harness | ✅ complete (`phase-1-complete`) |
| 2 | **Anti-overfitting fortress** — 4 walls + 3 gates, RiskLabAI, real-SPY calibration | ✅ complete (`phase-2-complete`) |
| 3 | **Autoresearch loop** — the self-improving core | ✅ **Layers 1–3 built & proven on real SPY** (fleet runs; replay walks ~5yr; exit-criteria sign-off pending: nightly-8h + DSN race test) |
| 4 | News / sentiment intelligence (MICRO lens) | ✅ **built & proven on live Alpaca news** — full-spec build; 169 real SPY items classified, real PIT sentiment feature; [plan](superpowers/specs/phase-4-intelligence-layer/plan.md) + [tasks](superpowers/specs/phase-4-intelligence-layer/tasks.md) |
| 5 | Broker integration (paper) | ✅ **code complete; connects to live paper account** — firewall-gated, dry-run default; live paper-order run is a user-gated switch (`--live-orders`); [plan](superpowers/specs/phase-5-broker-paper-trading/plan.md) + [tasks](superpowers/specs/phase-5-broker-paper-trading/tasks.md) |
| 6 | Governance + live prep (dashboard, Telegram, audit, convergence) | ✅ **code complete** — all 7 operator surfaces built; convergence report is the fail-closed real-capital gate; [plan](superpowers/specs/phase-6-governance-live-prep/plan.md) + [tasks](superpowers/specs/phase-6-governance-live-prep/tasks.md) |
| 7 | Full autonomous operation | ⚪ not started |

## Phase 3 — layer detail (the heart of the system)

Spec: [`superpowers/specs/phase-3-autoresearch-loop/spec.md`](superpowers/specs/phase-3-autoresearch-loop/spec.md).
The loop learns **two coupled things**: how to read the market **regime**, and which
**regime-conditional** strategy works + how to apply it. Goal: adapt to any market
condition, year-over-year profit.

### Layer 1 — runnable headless kernel (mechanical, no LLM)
| Piece | Status | PR |
|---|---|---|
| `strategy_template` (regime-conditional) + `eval` (wall metadata contract) + `loop` (mechanical hill-climb) + runner + live progress | ✅ | #49 #50 |
| Real Phase-1 **MESO regime detector** in the loop (ADX + realized-vol) | ✅ | #52 |
| **Vault-holdout** validation (train/vault split — the deployment gate) | ✅ | #54 |
| **Provenance** — `experiments.iterations` (Postgres) + `strategies` registry | ✅ | this slice |

**Layer-1 exit:** unattended run produces ≥N candidates on real SPY, records all of
them (kept + discarded + reason + vault verdict), promotes only fortress-passers,
and the promoted best holds on the untouched vault. Run it:
`uv run python scripts/run_autoresearch.py --iterations 50`
([runbook](runbooks/autoresearch-training.md)).

### Layer 2 — LLM mutator + learnable detector ✅
- ✅ **LLM mutator** — Nemotron proposes regime-conditional mutations (`--llm`;
  `LLMMutator` calls NVIDIA Build / LiteLLM, validates the JSON, safety-falls-back
  to the mechanical mutation on any failure).
- ✅ **Detector-as-mutation-target** — the candidate carries the MESO thresholds
  (ADX, vol-pct); `--learn-detector` makes them a mutation target so the loop learns
  *both* how to detect regimes and how to trade them. Self-corrects the Phase-1
  vol-pct mis-scaling without touching Phase-1. The LLM tunes thresholds too when
  `--llm --learn-detector` are combined (thresholds clamped, not rejected).

### Layer 3 — research fleet ✅ built & proven (PRs #60–#66)
The seven-role fleet wrapping the working kernel, built in 5 parallel waves (17 tasks,
[plan.md](superpowers/specs/phase-3-autoresearch-loop/plan.md) / [tasks.md](superpowers/specs/phase-3-autoresearch-loop/tasks.md)):
- **Orchestrator** (`orchestrator.py`) — the multi-step dispatch: Planner→Reviewer→
  (Hunter eval)→Guardian→promote→Archivist→Reporter; polls the halt flag every step.
- **Planner / Reviewer / Guardian** (`roles.py`) — injectable-LLM, Hindsight-grounded,
  deterministic offline. Guardian passes the **fortress verdict** through (veto a
  non-promoted candidate); the catastrophic-loss kill-switch is a *live* concern
  (Phase 5+ on realized P&L), **not** a backtest-drawdown trip.
- **Tools** — `promote_pipeline` (SERIALIZABLE race-free atomic promote vs
  `strategies.master`), `refresh_master`, `parse_metric`, `worker` (git-worktree
  isolation), `replay` (PIT-clamped compressed-history clock + leak canary),
  `notebook` (regenerable markdown ledger), `hindsight_client` (retain/recall/reflect),
  `VaultValidator` (in-sample-vs-vault tolerance).
- **Ops** — `HaltControl` file-flag kill-switch, `Reporter` fleet status, `TelegramOps`
  `/halt`-`/resume`-`/status`.
- **Substrate** — 7 Hermes subagent defs (`infra/nemoclaw/subagents/`) + a CI
  permission-scope guard. Domain code never imports Hermes (CLAUDE.md rule 7).

**Proven end-to-end on real SPY (2,882 bars, 2015→2026):** a nightly cadence ran
8 iterations through the full fleet; a **replay cadence walked 42 steps across ~5 years**
(2020→2025), PIT-clamped. The Guardian veto-rate tracks market stress — heavy vetoes in
the 2020 COVID crash and 2022 bear, near-zero in the 2023–25 bull — i.e. the fleet is
demonstrably **regime-sensitive**, exactly the thesis. Run it:
`uv run python scripts/run_autoresearch.py --fleet --cadence replay --iterations 3`.

**Remaining for the formal Layer-3 exit sign-off** (amendment §7), not blockers to
Phase 4: an unattended nightly-8h run (≥50 iters), the DSN-backed race-on-promote test
in CI's integration-smoke (already wired, runs on the fresh CI DB), and Hindsight-recall
latency under a live bank.

## Phase 4 — intelligence layer ✅ built & proven (PRs #67–#72)

The MICRO lens + real-time intelligence, built in 5 waves (13 tasks,
[plan.md](superpowers/specs/phase-4-intelligence-layer/plan.md) / [tasks.md](superpowers/specs/phase-4-intelligence-layer/tasks.md)):
- **News pipeline** — `AlpacaNewsClient` (real archive fetch + live-stream stub),
  `NewsClassifier` (fast local lexicon → CRITICAL/MATERIAL/BACKGROUND + sentiment ∈
  [-1,1]; FinBERT optional), macro connectors (SEC EDGAR, Fed RSS, CME FedWatch).
- **Real sentiment** — `SentimentFeature` replaces the Phase-1 placeholder with a PIT
  sentiment series (leak-canary-tested); `SentimentAggregator` (15-min rolling +
  Hindsight World Facts).
- **MICRO lens** — `MicroLens` (momentum/reversal/shock) fills `CompositeRegime.micro`
  from sentiment + roc_3/roc_5 + volume_surge + realized_vol.
- **Intelligence** — `TransitionPredictor` (rules + Hindsight-learned overlay),
  `WebResearcher` (weekly macro brief → Hindsight Mental Model, egress-allowlisted),
  `ArchivistSynthesis` (Hindsight L2 weekly / L3 monthly).
- **News-shock protocol** — a CRITICAL item trips the Layer-3 kill-switch (`HaltControl`)
  + tightened stops + 10-min hold, within seconds.

**Proven on LIVE Alpaca news:** `run_intel.py ingest` classified **169 real SPY items**
(18 CRITICAL / 35 MATERIAL / 116 BACKGROUND) and the real `SentimentFeature` produced a
genuine PIT score series varying across [-1,1] over the news flow — the MICRO lens now
reads real sentiment. Run it: `uv run python scripts/run_intel.py ingest --symbols SPY --start 2024-03-01`.

**Remaining for the formal Phase-4 exit sign-off** (spec §3), not Phase-5 blockers: live
news-websocket reconnect under load, the 15-min aggregation cadence on a running clock,
and Hindsight L2/L3 entries accumulating under a live bank.

## Phase 5 — broker + paper trading ✅ code complete (PRs #74–#79)

Firewall-first, built in 5 waves (12 tasks,
[plan.md](superpowers/specs/phase-5-broker-paper-trading/plan.md) / [tasks.md](superpowers/specs/phase-5-broker-paper-trading/tasks.md)):
- **Domain model** — `Order`/`Position`/`Portfolio`/`OrderIntent` (`execution/model.py`);
  `trades.orders/fills/positions/pnl_daily` (Postgres, migration 007).
- **Broker** — `AlpacaBrokerClient` (paper account/positions/orders); `submit_order`
  **defaults `dry_run=True`** (zero network on the default path); graceful no-key.
- **The architectural firewall** — `HardLimitFirewall` collects ALL violations
  (position >5%, sector >20%, daily ≤−2%, monthly ≤−10%, regime conf <40%, econ
  blackout, missing ATR stop); `size_order` (5% clamp), `ComplianceEngine` (PDT +
  wash-sale, BTC-ETF group), `EconCalendarGate` (FOMC/CPI/NFP), ATR 2× stops.
- **Executor** — the flow: halt-check → size → **firewall → compliance → (only then)
  submit**; `live_orders=False` default → every submit is dry-run. A rejected or halted
  order is architecturally incapable of reaching the broker (asserted by the invariant
  tests — the Phase-5 exit criterion).
- **Reconciliation** (local vs broker; halt on >1% notional / phantom) + `TradeStore`
  (persist to `trades.*`) + `run_paper.py` (account/positions/cycle).

**Proven (read-only) on the LIVE paper account:** `run_paper.py account` reads the real
Alpaca paper portfolio (equity $100k, buying power $400k, 0 positions). The firewall
integration smoke proves an over-limit order is rejected and **never reaches the broker**;
in-limits orders submit **dry-run** by default.

**The live-order switch is a deliberate human gate.** No paper order is submitted unless
`run_paper.py cycle --live-orders` is passed (prints a ⚠️ banner). The 30-day unattended
paper window + Sharpe>1.0 readiness gate are operational (Phase-6 monitoring), not code.

## Phase 6 — governance + live prep ✅ code complete (PRs #82–#85)

All 7 operator surfaces, built in 3 waves ([plan.md](superpowers/specs/phase-6-governance-live-prep/plan.md) / [tasks.md](superpowers/specs/phase-6-governance-live-prep/tasks.md)):
- **AuditLog** — hash-chained append + chain verification over migration-003 `audit.events`
  (sha256 prev-hash linkage, tamper detection, crash-safe autocommit rows).
- **Performance attribution** — FIFO round-trips from production `trades.orders` →
  P&L by regime / ticker / side / holding-period.
- **Telegram bot** — `/halt` `/resume` `/status` `/regime` `/strategy <hash>` `/kb`
  `/report daily|weekly`; per-chat-ID allowlist; provider errors reply, never crash.
- **Secrets audit (CI)** — `.env` gitignored, zero key-material in tracked files,
  sandbox writable scopes confined to /sandbox+/tmp. Keyring deferred to cloud deploy.
- **Streamlit dashboard** — `uv run --with streamlit streamlit run scripts/dashboard.py`:
  HALT/RESUME buttons on the shared kill-switch, halt banner, regime / positions /
  orders / P&L / fleet / KB / attribution panels, per-panel failure isolation.
- **Convergence report** — `scripts/convergence_report.py`: the **fail-closed**
  real-capital go/no-go (unmeasured criterion = FAIL). Thresholds: ≥1 vault-holding
  deployment-eligible strategy · replay ≥3yr · all 4 regimes ≥5% · KB ≥100 facts ·
  paper ≥30 days · paper Sharpe >1.0. First snapshot committed: **NOT READY** (honest —
  the paper window hasn't run). A passing report is necessary; the flip stays human.

Prior to Phase 6, a **three-reviewer adversarial audit** of Phases 3–5 found and fixed
7 Critical + ~15 Important findings (PR #81) — theme: gates were sound, production
inputs were fake/miswired. Lesson recorded in memory + applied to all Phase-6 code.

## Paper window — STARTED 2026-07-06 (live paper orders, zero real capital)

The first live paper order is in: **BUY 3 SPY (market/OTO)** from the real signal
(`seed4` artifact: regime `ranging_high_vol`, close 751.28 > SMA30 744.85), accepted by
Alpaca with the protective 2×ATR stop leg resting at the venue; persisted to
`trades.orders`; day-0 `trades.pnl_daily` baseline recorded ($100k). Live-run fixes
landed en route (each caught by a safety layer doing its job): Alpaca bars need an
explicit `start` + tail-slice; whole-share sizing for OTO orders; penny-rounded stop
prices; broker 4xx bodies now logged; reconciler accepts divergences EXPLAINED by
post-snapshot orders (no false halt when the overnight entry fills at the open).
Daily cadence: `scripts/paper_window.sh` + `infra/ops/com.mahoraga.paper-window.plist`
([runbook](runbooks/paper-window.md)) — the launchd install is the operator's step.

## Paper-window ops follow-ups ✅ (Tier 1, 2026-07-13)

Three gaps found in the post-Phase-6 review of "what still can't happen":
- **Paper-stats bridge** (`ops/paper_stats.py`) — `trades.pnl_daily` → days + annualized
  Sharpe; the convergence report now **auto-gathers** from the DSN when `--paper-stats`
  isn't given (explicit file still wins; no source → fail-closed unmeasured).
- **Telegram bot runner** (`scripts/run_telegram_bot.py` + `ops/bot_providers.py`) —
  all 7 commands wired to real providers (regime + transition risk, registry lookup,
  Hindsight KB, daily/weekly reports). Polling REFUSES to start without a
  `TELEGRAM_CHAT_ID` allowlist (an open bot could `/resume` the kill-switch).
  Local smoke: `uv run python scripts/run_telegram_bot.py --once /status`.
- **Monthly P&L armed** (`TradeStore.monthly_pl_pct`) — trailing-30d baseline from
  `pnl_daily` vs live account equity feeds the firewall; the CLAUDE.md **10% monthly
  catastrophic halt can now actually trip** (was 0.0 + warning). Verified live against
  the local Postgres (159/159 with DSN).
  Bonus: a test fixture that could have deleted a REAL paper-window pnl row was
  defused (synthetic sentinel dates + snapshot/restore).

## Retrain under the fixed vol scale ✅ (2026-07-13)

The paper window now trades **seed11** (`strategies/seed11-1783928660.json`), retrained
after the vol-scale unification: train Sharpe **0.0713** / vault **0.0695** (holds; vs
seed4's 0.0535/0.0664), 70% quarterly win, and a **balanced learned detector**
(adx≥27, vol>40.0 on the 0–100 scale — a real regime split instead of the old
everything-is-high-vol labeling). Swap verified with a dry-run: the account's existing
3-SPY long matched seed11's signal — book aligned, zero churn. `MAHORAGA_PAPER_STRATEGY`
updated in `.env`.

## Tier 3 — feature-complete ✅ (2026-07-18)

The deferred implementation is done — the app is now a real multi-symbol portfolio
system with live intelligence cadences ([plan](superpowers/specs/tier-3-completion/plan.md)):
- **Multi-symbol trading** — `run_paper.py cycle --watchlist` runs the strategy across
  SPY/QQQ/IWM + XLK/XLE/XLF/XLV through ONE portfolio-aware `Executor.run_cycle` (the
  executor was already multi-intent). Live-data proof: 7 symbols, distinct regimes, 4
  dry-submits, XLF auto-rejected (regime confidence 35% < 40% floor). Sector cap enforced
  portfolio-wide.
- **Researcher pipeline** — macro sources → structured hypotheses (rate_path/event/…),
  Hindsight-grounded, `to_planner_queue` seeds the fleet. Closes the last Phase-4 stub.
- **Live news refresh** — `run_intel.py refresh` = periodic ingest → World Facts +
  per-symbol sentiment snapshot (the Phase-4 15-min cadence via periodic REST).
- **FedWatch endpoint** — best-effort real source + honest source label (degrades to {},
  never fabricates).
- **Cadence** — `paper_window.sh` now runs a news refresh then the multi-symbol cycle.

**Deliberately deferred** (documented, not silent): FinBERT (lexicon meets the <2s SLA),
held-open websocket (periodic REST suffices locally), per-symbol retraining (the strategy
is symbol-agnostic). See the plan self-review.

**Tier-2 soak:** a 42-step fleet replay across 2021→2026 recorded 161 iterations; the
Guardian veto rate is textbook regime-sensitive — heavy in the 2022 bear, ~zero in the
2024–25 bull. That provenance feeds the convergence report's replay-depth + regime
coverage.

## The only remaining gates (uncompressible by design)

1. **~30 elapsed paper-trading days** — the convergence report needs the window to
   accumulate; this is calendar time, not code. Install the launchd cadence to advance it.
2. **Human real-capital sign-off** — a passing convergence report is necessary but never
   sufficient; the flip to real money is always yours.

Everything buildable is built. The app is feature-complete and usable today.

## Current focus

**Phases 1–6 code-complete; the 30-day paper window is live.** Trains on ~5yr real SPY regimes, reads real news
sentiment, firewall-gated paper execution wired to the live Alpaca paper account, full
operator surfaces (dashboard / Telegram / audit / attribution / convergence gate).
**Next: the 30-day live paper window** (`run_paper.py cycle --live-orders`, operator's
switch) — its results feed the convergence report, which is the fail-closed gate for
Phase 7 / real capital. **Real-capital go-live remains a human sign-off**, per CLAUDE.md.
