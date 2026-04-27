# Mahoraga — Architecture & Decomposition Spec

**Status:** Approved 2026-04-25
**Type:** Architecture & decomposition map (umbrella spec; not directly implementable)
**Source plan:** [`docs/project_plan/MAHORAGA_PROJECT_PLAN.md`](../../project_plan/MAHORAGA_PROJECT_PLAN.md)
**Companion spec:** [`2026-04-25-nemoclaw-autoresearch-integration.md`](2026-04-25-nemoclaw-autoresearch-integration.md)

---

## 1. Vision & Problem Statement

Mahoraga is a self-improving, regime-aware, autonomous trading system for US equities. Most algorithmic trading systems are static — they find an edge and exploit it until it dies. Mahoraga is fundamentally adaptive: it recognizes market regimes before deploying strategies, renews decaying edges proactively, monitors via live news streams, and extracts meta-principles that compound understanding across time.

The core philosophy: a trader that has "seen enough markets to know what works" — converging on positive risk-adjusted returns year-over-year with bounded survivable drawdowns.

The novel contribution is the **convergence model**: 7+ years of historical market data are replayed at accelerated speed in a training environment that is architecturally identical to the live one. By the time real capital is deployed, the system has experienced the regimes that matter and has a populated knowledge base of strategies, patterns, and meta-principles.

**Target operator:** solo or small-team, running on a MacBook Pro initially, scaling to cloud (Hostinger, CloudFront, similar) once stable. Real capital, hard infrastructure-level risk limits, human override controls.

**Success criterion (north star):** Sharpe ratio greater than SPY's Sharpe by at least 0.3 on 24-month rolling windows, with maximum drawdown under 20% from peak. This is "outperforms passive index on a risk-adjusted basis with bounded losses" — not "never loses."

## 2. System Boundaries & Non-Goals

### In scope

- US equities (S&P 500 + Russell 1000 with point-in-time constituents)
- US-listed ETFs — broad market (SPY, QQQ, IWM), sector (XLF, XLK, XLE, XLV, etc.), commodity, and BTC ETFs (IBIT, FBTC, GBTC, BITB, ARKB)
- Bitcoin exposure **via BTC ETFs only** (in scope from Phase 1). Spot BTC and BTC options deferred to Phase 8 expansion.
- Swing trades, holding period 1 day to 6 weeks
- Long positions in Phases 1–7 (shorts in Phase 8)
- Real-time news ingestion and classification (incl. BTC-relevant news for BTC-ETF symbols)
- Regime detection across three time horizons (MACRO 3–18 mo, MESO 2–8 wk, MICRO 1–5 d)
- Autonomous strategy proposal, validation, deployment, and retirement
- Hard risk limits enforced at execution boundary, not as advisory checks
- Human override via Telegram bot and a Streamlit dashboard

### Out of scope (explicitly)

- Spot cryptocurrency, including spot BTC — Phase 8 expansion track (8c)
- Cryptocurrencies other than Bitcoin (no ETH, SOL, etc. — even via ETFs)
- Leverage trading
- Options — Phase 8 expansion (8a)
- Short selling — Phase 8 expansion (8b)
- Fixed income (bonds), forex, commodity futures
- Multi-currency or international equities
- Intraday or day trading (system targets swing trades)
- High-frequency strategies

### Non-goals about behavior

- "Never lose money" — not the target. Bounded drawdown with positive expected value over rolling windows is.
- Beating any individual benchmark on any individual day, week, or month. The target is risk-adjusted outperformance over 24-month rolling windows.

## 3. Six-Layer Architecture Overview

The system is organized as six layers, deployed under a single substrate.

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 6 — Observation & Control                                 │
│  Streamlit dashboard │ Telegram bot │ Audit logs │ Kill switch   │
├──────────────────────────────────────────────────────────────────┤
│  Layer 5 — Storage                                               │
│  Postgres + pgvector │ Parquet feature store │ Git registry      │
├──────────────────────────────────────────────────────────────────┤
│  Layer 4 — Shared Infrastructure (sidecars)                      │
│  LiteLLM gateway │ Ollama │ NemoClaw internal state              │
├──────────────────────────────────────────────────────────────────┤
│  Layer 3 — Stateless Workers                                     │
│  regime-detector │ data-ingest │ execution │ training │ news-cls │
├──────────────────────────────────────────────────────────────────┤
│  Layer 2 — Always-on Agents                                      │
│  Hunter (profit) │ Guardian (risk) │ Archivist (memory)          │
├──────────────────────────────────────────────────────────────────┤
│  Layer 1 — Substrate                                             │
│  NemoClaw (vendored) — lifecycle, sandbox, channels, routing     │
└──────────────────────────────────────────────────────────────────┘
```

### 3.1 Substrate (Layer 1)

NemoClaw, vendored at `vendor/nemoclaw/` as a `git subtree`. Provides agent lifecycle management, hardened sandbox per agent, persistent state for substrate concerns (not application data), managed channel messaging between agents, and a routed inference layer. Mahoraga services run as containerized workloads NemoClaw orchestrates.

### 3.2 Always-on Agents (Layer 2)

Three roles, each a long-running containerized Python service:

- **Hunter** — generates strategy hypotheses, proposes mutations to existing strategies, monitors edge decay, drives the autoresearch loop overnight.
- **Guardian** — stress-tests every candidate strategy (using `synthetic-data` for adversarial scenarios), detects portfolio crowding and correlation, enforces gates, can veto Hunter proposals.
- **Archivist** — weekly meta-learner; promotes Level-1 raw experiment entries to Level-2 patterns and Level-3 meta-principles; builds the prompt-context pack other agents consume.
- **Web-research** (Phase 4+) — runs Sunday weekly macro-narrative synthesis. Has a *distinct* sandbox profile with outbound web egress to a fixed allowlist; unlike the other three agents which have no general web egress. Output is published to the `kb-updates` channel as Level-2 / Level-3 KB entries.

Inter-agent communication is exclusively through NemoClaw channels. No direct service-to-service HTTP calls between agents.

### 3.3 Stateless Workers (Layer 3)

Called by agents on demand; do not maintain conversation state:

- **regime-detector** — MACRO/MESO/MICRO lens computation
- **data-ingest** — Alpaca, Polygon, news websocket connectors; writes parquet
- **execution** — signal-to-order routing, paper or live, with hard-limit enforcement
- **training** — autoresearch-style loop runner, called by Hunter on cadence
- **news-classifier** (Phase 4+) — fast NLP path, CRITICAL/MATERIAL/BACKGROUND in <2s

### 3.4 Shared Infrastructure (Layer 4)

- **LiteLLM gateway** — single OpenAI-compatible endpoint translating to Ollama, OpenRouter, Gemini, Anthropic, OpenAI, Grok. All agent inference flows through here.
- **Ollama** — local inference for Gemma 4 (per project plan), Apple Silicon Metal acceleration on the host. If Gemma 4 is not yet available in Ollama at Phase 0, use the latest Gemma release as interim and upgrade when Gemma 4 lands.
- **NemoClaw internal state** — substrate-private; persisted to a dedicated host volume at `data/nemoclaw-state/` (mounted into the NemoClaw container). Cleanly separated from the vendored source tree at `vendor/nemoclaw/` so the source is read-only by default and `git subtree pull` is unaffected by runtime state. (NemoClaw may use SQLite internally; that is its private concern, not part of the application data model.)

> **Divergence from project plan:** the plan named ChromaDB for the KB vector store and SQLite for the trade journal. These are consolidated into Postgres + pgvector for operational simplicity (one database to back up, one connection pool, one migration system). SQLite is *only* present if NemoClaw's substrate uses it internally; we do not introduce SQLite for application concerns.

### 3.5 Storage (Layer 5)

- **Postgres + pgvector** — single application database with logical schemas: `knowledge` (KB Levels 1/2/3 + embeddings), `trades` (trade journal), `experiments` (autoresearch loop metadata), `strategies` (registry pointers and lifecycle state).
- **Parquet on host volume** — feature store; raw OHLCV and engineered features. Filesystem layout indexed in `experiments` schema.
- **Git (monorepo)** — strategy registry lives at `strategies/<strategy_id>/strategy.py` in this same repo. **Only promoted strategies** (passed all 5 walls + 3 gates AND improved composite score) are committed; the thousands of nightly experiments are tracked exclusively in Postgres `experiments.iterations` (with mutation diffs stored as columns). This keeps `main` from being polluted by experiment churn while preserving the "git registry with active/standby/retired tags" contract from the project plan. Lifecycle states are git tags (e.g., `strategy/<id>/active`, `strategy/<id>/retired`).

### 3.6 Observation & Control (Layer 6)

- **Streamlit dashboard** — local web UI showing positions, recent trades, regime state, agent activity.
- **Telegram bot** — phone-resident control surface; supports commands for kill switch, strategy override, daily reports.
- **Audit log** — append-only event stream of every decision, every channel message, every order. Backed by Postgres `audit` schema and shipped to local files.
- **Kill switch** — sub-10-second halt of all trading; prominent button in dashboard and Telegram command. Halt-contract details in §5.6.

## 4. Component Inventory

### 4.1 Services (`services/`)

| Service | Layer | Phase introduced | Language | Notes |
|---|---|---|---|---|
| `data-ingest` | 3 | 1 | Python | Free-API-first (yfinance, Alpaca free tier, FRED, Stooq); paid tier (Polygon, Alpaca paid) only if free tier insufficient. 1-minute granularity is acceptable; per-tick is not required. |
| `regime-detector` | 3 | 1 | Python | MACRO/MESO/MICRO lens implementations |
| `synthetic-data` | 3 | 2 | Python | Library (not standalone container) called by Guardian and training. Generates GBM with regime switching, jump-diffusion crash scenarios, historical analogue paths. Used for Wall 4 ensemble perturbation, Guardian adversarial tests, weekly scenario simulation. |
| `hunter` | 2 | 3 | Python | LLM-driven strategy proposer |
| `guardian` | 2 | 3 | Python | Risk vetoes, gate enforcement, adversarial stress testing via `synthetic-data` |
| `archivist` | 2 | 3 | Python | KB Level promotion, weekly synthesis |
| `web-research` | 2 | 4 | Python | Sunday weekly macro narrative synthesis (Plan §6, §8). Outbound web egress to a fixed allowlist (FRED, SEC EDGAR, Federal Reserve RSS, CME FedWatch, news syndication). Distinct sandbox profile from Hunter/Guardian/Archivist (which have *no* general web egress). |
| `news-classifier` | 3 | 4 | Python | FinBERT or similar; <2s classification SLA for live shock protocol |
| `execution` | 3 | 5 | Python | Order routing, hard-limit enforcement, compliance predicates (PDT, wash-sale, SSR) |
| `training` | 3 | 3 | Python | autoresearch-style loop runner; calls `synthetic-data` for Wall 4 perturbations |

### 4.2 Vendor dependencies

| Dependency | Path | License | Update model |
|---|---|---|---|
| NVIDIA/NemoClaw | `vendor/nemoclaw/` | Apache 2.0 | Live `git subtree`; monthly + 72h security |
| karpathy/autoresearch | `vendor/autoresearch/` | MIT | Frozen; one-time copy |

### 4.3 Infrastructure sidecars

| Sidecar | Purpose | Runs as |
|---|---|---|
| LiteLLM gateway | Universal LLM provider routing | Container in `docker-compose.yml` |
| Ollama | Local inference | Host process; exposed to containers via host network |
| Postgres + pgvector | Single application database | Container with persisted volume |

## 5. Component Contracts

The boundaries between layers are durable; the implementations behind them can change. These are the contracts that define interoperability.

### 5.1 Channel contract (Layer 1 ↔ Layer 2)

Agents communicate over named NemoClaw channels. Each message is a JSON payload with required envelope fields: `id`, `timestamp`, `from_agent`, `channel`, `correlation_id`, `payload`. All channel traffic is logged to the audit log; replay is supported.

Standard channels (defined in `infra/nemoclaw-config/channels.yaml`):

- `market-state` — regime-detector publishes; Hunter, Guardian subscribe
- `strategy-proposals` — Hunter publishes; Guardian subscribes
- `risk-vetoes` — Guardian publishes; Hunter subscribes
- `kb-updates` — Archivist publishes; Hunter, Guardian subscribe
- `execution-orders` — Hunter (after Guardian approval) publishes; execution subscribes
- `execution-results` — execution publishes; Hunter, Guardian, Archivist subscribe

### 5.2 Inference contract (any layer → Layer 4 LiteLLM)

All LLM calls go through LiteLLM via OpenAI-compatible API. Model identifiers are namespaced: `ollama/gemma4:latest`, `anthropic/claude-opus-4-7`, `openrouter/x-ai/grok-2`, etc. Switching providers is a config change, not a code change.

### 5.3 Data contract (Layer 3 data-ingest → Layer 5 storage)

- OHLCV: parquet files at `data/ohlcv/{symbol}/{year}.parquet`
- Engineered features: parquet at `data/features/{symbol}/{year}-{month}.parquet`
- News: JSON-line files at `data/news/{date}.jsonl` plus indexed in Postgres `knowledge.news`
- Vault embargo enforced at the data-access boundary; the last 6 months of data are not visible to the training loop. Bypass requires an explicit `vault_override` flag that emits an audit-log warning.

> **Wall 2 (data discipline) is an architectural contract**, enforced here at the storage layer. The other four anti-overfitting walls (statistical rigor, complexity control, generalization, meta-awareness) are evaluation predicates run at the training boundary; their internals are specified in `five-wall-fortress-spec.md`.

### 5.4 Strategy artifact contract (Layer 3 training → Layer 5 git registry)

A strategy is a single `strategy.py` file conforming to the `Strategy` ABC defined in the integration spec. Promotion to the registry is a git commit; the commit message includes parent strategy ID, mutation diff summary, and the FitnessReport hash. Lifecycle states (active / standby / retired) are git tags.

### 5.5 Risk-limit & compliance contract (Layer 3 execution boundary)

Hard limits and regulatory compliance predicates are enforced in the execution service, not as advisory checks consulted by agents. An order that violates any hard limit *or* compliance rule is rejected at the execution boundary regardless of which agent submitted it. This is the architectural firewall between the research stack and real capital.

Compliance predicates (Plan §23, FR-4.4) live alongside hard limits and run on every order: PDT pattern-day-trader rule, wash-sale detection (cross-account, 30-day window), short-sale restriction (SSR) flag handling. Detail deferred to `paper-trading-spec.md` (Phase 5); the contract is fixed here: compliance rejection has the same architectural status as hard-limit rejection.

### 5.6 Halt contract (kill switch)

Sub-10-second halt of all trading is a contract every order-emitting service must honor from day one. The mechanism:

- **Primary:** dedicated NemoClaw channel `halt`. Any service can publish a halt event (Telegram bot, dashboard button, Guardian on catastrophic-loss trip, manual operator command). All order-emitting services (`execution`, and any agent that can place orders) subscribe and stop submitting orders within 1 second of receipt.
- **Fallback:** the execution service additionally polls Postgres `audit.events` for the most recent halt marker every 2 seconds, providing a path independent of channel availability.
- **Recovery:** halts require explicit human resume via Telegram or dashboard; no automatic recovery. Resume emits a `halt_clear` event on the same channel.

The halt mechanism is testable end-to-end in Phase 0 (substrate bring-up) using a stub order-emitter; full kill-switch UX (Telegram command, dashboard button) is deferred to `governance-spec.md` (Phase 6) but the channel contract is locked here.

## 6. Phase Milestone Gates

The 9 gates below anchor the project's sequencing. Each phase gets a dedicated executable spec at the start of its work. Gates are sequential; a phase cannot start until the prior phase's exit criteria are demonstrably met.

| # | Phase | Est. duration | Exit criteria (all must be true) |
|---|---|---|---|
| **0** | Substrate bring-up | 2 weeks | `docker compose up` brings NemoClaw + LiteLLM + Postgres + Ollama up; one trivial agent registers and round-trips a message; CI passes; vendor subtree pull tested. |
| **1** | Foundation | 8 weeks | 8+ years OHLCV ingested to parquet; 70+ features computed; vault (last 6 months) embargoed at data layer; regime detector ≥75% accuracy on labeled historical; vectorbt backtest harness runs <30s/strategy. |
| **2** | Five-Wall Fortress | 6 weeks | All 5 anti-overfitting walls implemented as testable predicates; deliberate-overfit canary strategy is rejected by Wall 1; 3-gate system implemented; calibration on known good and bad historical strategies. |
| **3** | Autoresearch Loop Core | 13 weeks | Hunter, Guardian, Archivist agents register with NemoClaw and exchange messages; loop kernel runs nightly cadence unattended for 8h; ≥50 experiments per night; KB Level-1 populated; git strategy registry committing winners; vault validation passes. |
| **4** | Intelligence Layer | 9 weeks | News websocket live; classifier <2s; sentiment state aggregated every 15 min; transition predictor live; web research agent producing weekend macro briefs; Archivist Level-2 patterns being extracted. |
| **5** | Broker + Paper Trading | 8 weeks | Alpaca paper integration live; position sizing + hard limits enforced at execution boundary; 30 consecutive days of paper trading on live data; Sharpe > 1.0 on paper-only window. |
| **6** | Governance + Live Prep | 5 weeks | Kill switch tested (<10s halt); Telegram bot operational with override commands; Streamlit dashboard live; security hardening (secrets in vault, audit logging); convergence report passes vault holdout. |
| **7** | Live Trading Stage 1 | 10 weeks | Real capital $5K–$15K deployed; positive returns OR controlled-loss learning; 90 consecutive days without infrastructure incident; weekly Archivist syntheses producing meaningful Level-3 entries. |
| **8** | Expansion | ongoing | Options, shorts, multi-agent distributed research, capital scaling — each as its own future spec. |

**Sequencing rule (non-negotiable):** Phases 1–4 are pure research with zero capital at risk. Phase 5 broker integration does not begin until Phase 3 and Phase 4 have both passed exit criteria. The convergence report must pass vault holdout validation before any real capital deploys in Phase 7.

## 7. Cross-Cutting Concerns

### 7.1 Observability

Every channel message, every LLM call, every order, every agent decision is logged to the audit log. Postgres `audit` schema is the index; raw payloads are appended to local files at `data/audit/{date}.jsonl`. Streamlit dashboard surfaces real-time agent activity. Metrics export is OpenTelemetry-compatible; backend deferred to cloud phase.

### 7.2 Security

- Secrets in `.env`, never committed. `.env.example` documents required keys. Production: secrets manager (deferred to cloud phase).
- Per-agent sandbox policies in `infra/nemoclaw-config/sandbox-policies.yaml` — outbound network allowlists, filesystem mount restrictions, resource limits.
- All inter-agent communication is mediated by NemoClaw and logged. No agent can call another agent without going through a managed channel.
- Audit log is append-only and tamper-evident (hash-chained entries). Verified during weekly Archivist runs.

### 7.3 IP & licensing posture

- Repo is private. May become a commercial product.
- NemoClaw Apache 2.0 — preserve `vendor/nemoclaw/LICENSE`, document modifications in `vendor/nemoclaw/MAHORAGA_CHANGES.md`, do not use NVIDIA trademarks in product branding.
- autoresearch MIT — preserve `vendor/autoresearch/LICENSE` and copyright notice.
- No vendor LICENSE file is ever deleted. No copyright header is ever stripped from vendored code.

### 7.4 Hardware budget

**Local (initial):** Apple Silicon MacBook Pro. NemoClaw minimum is 8 GB RAM, 4 vCPU, 20 GB disk. Mahoraga's full stack on top (Postgres + Ollama + agents + LiteLLM) targets 16 GB RAM, 8 vCPU, 100 GB disk for comfortable operation. Ollama Metal acceleration on host (not containerized) for inference speed.

**Cloud (deferred):** Hostinger, CloudFront, or similar. Spec written when needed; Docker Compose translates straightforwardly to a single-VM deployment, with Kubernetes/k3s an option for multi-node scaling.

### 7.5 Deployment posture (two environments)

Two deployment targets, not three. The plan's DEV/STAGING/PROD distinction is collapsed into:

- **DEV (local)** — Apple Silicon MacBook Pro running the full Docker Compose stack. Used for all of Phases 0–4 (substrate bring-up through intelligence layer). Phase 5 paper trading also runs in DEV against Alpaca's *paper* API; the "30 consecutive days of paper trading" Phase 5 exit criterion is satisfied here, not in a separate STAGING environment.
- **PROD (cloud, deferred)** — Hostinger / CloudFront / similar. Brought online before Phase 7 live trading. Configuration switching via `MAHORAGA_ENV=prod`: connects to Alpaca *live* API, vault-access policy stays read-only-for-training, audit logs ship to durable cloud storage. The actual cloud deployment spec is written when we get to Phase 7 prep, since service composition may evolve during Phases 1–4.

A single environment variable (`MAHORAGA_ENV` ∈ {`dev`, `prod`}) selects broker connection, data-feed flag, audit-log destination, and any other environment-keyed behavior. Same image, different config — no separate codebases.

### 7.6 Bootstrap LLM economics

Compressed-history replay (Phase 1–3) projects 4–6 weeks of wall-clock to walk 2018 → vault boundary at thousands of mutations. At one LLM call per mutation, this exceeds tier-1 cloud-provider RPM quotas under any reasonable iteration budget.

**Plan:** primary bootstrap LLM is **local Gemma 4 via Ollama** on the host's Metal GPU. This is free and rate-limited only by hardware throughput (~30–60 mutations/hour empirically expected on M-series silicon for the model size at hand; verify in Phase 0). Cloud LLMs (Anthropic, Gemini, OpenRouter) are reserved for:
- Hard mutations Hunter can't make headway on locally (escalation triggered by Archivist when KB indicates "we've been stuck on this regime for N attempts")
- Weekend Archivist Level-2/Level-3 synthesis (long-context reasoning, Gemini)
- Web research (long-document fundamental analysis, Gemini)

**Implication:** Phase 0 must verify Gemma-4-via-Ollama throughput meets the bootstrap schedule before Phase 1 begins. If it doesn't, options are: extend bootstrap wall-clock; budget cloud-tier upgrade (real cost — link to Plan §27); or reduce `experiments_per_day` in compressed-replay. The integration spec §6.5 cadence is adjustable.

## 8. Spec Catalog

Specs live at `docs/superpowers/specs/`. Naming convention: `YYYY-MM-DD-<topic>-spec.md`.

Per-phase specs each live in their own folder under `docs/superpowers/specs/phase-N-<topic>/`. The folder holds `spec.md` (the broad phase spec), `plan.md` and `tasks.md` (implementation plan + dep graph) when the phase is being implemented, and any sub-feature specs created during that phase under SDD.

### Currently written

| Spec | Purpose | Phases unblocked |
|---|---|---|
| [`2026-04-25-mahoraga-architecture-decomposition.md`](2026-04-25-mahoraga-architecture-decomposition.md) (this document) | Map of the whole project | Anchors all future specs |
| [`2026-04-25-nemoclaw-autoresearch-integration.md`](2026-04-25-nemoclaw-autoresearch-integration.md) | NemoClaw substrate + autoresearch loop integration | 0, 1, 2, 3 |
| [`phase-0-substrate-bringup/spec.md`](phase-0-substrate-bringup/spec.md) | Phase 0 (walking skeleton) | 0 |
| [`phase-1-foundation/spec.md`](phase-1-foundation/spec.md) | Phase 1 (data + features + regime) | 1 |
| [`phase-2-five-wall-fortress/spec.md`](phase-2-five-wall-fortress/spec.md) | Phase 2 (walls + gates + synthetic-data) | 2 |
| [`phase-3-autoresearch-loop/spec.md`](phase-3-autoresearch-loop/spec.md) | Phase 3 (Hunter/Guardian/Archivist + loop kernel) | 3 |
| [`phase-4-intelligence-layer/spec.md`](phase-4-intelligence-layer/spec.md) | Phase 4 (news + sentiment + transition predictor) | 4 |
| [`phase-5-broker-paper-trading/spec.md`](phase-5-broker-paper-trading/spec.md) | Phase 5 (Alpaca paper + compliance) | 5 |
| [`phase-6-governance-live-prep/spec.md`](phase-6-governance-live-prep/spec.md) | Phase 6 (kill switch + dashboard + convergence report) | 6 |
| [`phase-7-live-trading-stage-1/spec.md`](phase-7-live-trading-stage-1/spec.md) | Phase 7 (live capital Stage 1) | 7 |
| [`phase-8-expansion/spec.md`](phase-8-expansion/spec.md) | Phase 8 (expansion framework) | 8 |

### Anticipated sub-feature specs (each lives inside its phase folder)

| Sub-feature spec | Phase folder | Purpose |
|---|---|---|
| `data-foundation-spec.md` | `phase-1-foundation/` | Data ingestion (free APIs first), feature engineering details, vault embargo |
| `regime-detector-spec.md` | `phase-1-foundation/` | MACRO/MESO/MICRO lens algorithms |
| `synthetic-data-spec.md` | `phase-2-five-wall-fortress/` | GBM+regime switching, jump-diffusion (BTC-aware), historical analogue generation |
| `five-wall-fortress-spec.md` | `phase-2-five-wall-fortress/` | Anti-overfitting predicates and 3-gate system |
| `intelligence-layer-spec.md` | `phase-4-intelligence-layer/` | News classifier, transition predictor, web-research service |
| `paper-trading-spec.md` | `phase-5-broker-paper-trading/` | Alpaca integration, position sizing, hard limits, regulatory compliance |
| `governance-spec.md` | `phase-6-governance-live-prep/` | Kill switch UX, Telegram bot, Streamlit dashboard, audit discipline |
| `performance-attribution-spec.md` | `phase-6-governance-live-prep/` | Regime/strategy/sector/holding-period/signal-source attribution (Plan §25) |
| `convergence-report-spec.md` | `phase-6-governance-live-prep/` | Vault holdout validation; threshold for live-capital readiness |
| `cloud-deployment-spec.md` | `phase-7-live-trading-stage-1/` | Hostinger / CloudFront / equivalent; PROD environment activation |
| `live-trading-stage-1-spec.md` | `phase-7-live-trading-stage-1/` | Capital allocation per Plan §27, monitoring, escalation |

Plans (executable task lists) follow specs and live at `docs/superpowers/plans/`.

## 9. Open Questions

These are flagged from the source project plan; they do not block Phase 0–3 work but need resolution before later phases:

1. **NemoClaw plugin/extension API maturity & abandonment risk.** NemoClaw is alpha software (released March 2026). Its extension surface may shift between minor versions; NVIDIA could pause or deprecate the project. Mitigation has two layers:
   - **Routine instability:** stay in Tier 1 (configuration) extensions; pin to known-good releases; review release notes before each pull; integration test gate before merging any subtree pull.
   - **Abandonment contingency:** keep our use of NemoClaw confined to a minimum substrate API surface — channel pub/sub, sandbox enforcement, agent lifecycle — that any reasonable agent-orchestration substrate could provide. *Do not* depend on NemoClaw-specific features such as its native routed-inference layer (LiteLLM in front of it already protects this). Acceptable replacements if NemoClaw is abandoned: LangGraph, raw Docker + nats.io for channels, or a custom orchestrator. Verify quarterly that our agents would port to a replacement substrate within reasonable effort (target: <2 person-weeks).
2. **Pre-2020 news archive coverage.** Alpaca's news archive starts ~2020. For 2018–2019 backtests, choices are price-action proxies, alternate news source (cost), or truncating training history. Decision deferred to Phase 1 spec.
3. **Capital scaling thresholds.** Plan §27 proposes $5K–$15K (Stage 1) → $15K–$50K (Stage 2) → $50K–$200K (Stage 3) with Sharpe > 1.0 plus 6–12-month track record as Stage 1→2 trigger. Confirm or revise during Phase 7 (`live-trading-stage-1-spec.md`).
4. **Regime label taxonomy.** MACRO regimes are conceptually clear but boundary edge cases are not (e.g., "early bull with narrowing breadth" — bull or rotation?). Calibration deferred to Phase 1 regime-detector spec.
5. **Earnings-season special handling.** Project plan acknowledges earnings drive volatility but no dedicated module is specified. Decision deferred to Phase 4 spec.
6. **LLM provider fallback priority.** If primary provider fails or hits rate limits, what is the fallback order? Cost-vs-capability tradeoff. Decision deferred to integration spec implementation; LiteLLM supports fallback chains natively.
7. **Forbidden-pattern KB structure.** How are negative-learning entries (failed mutations) indexed for efficient retrieval? Embedding-based or rule-based? Decision deferred to Phase 3 spec.
8. **Multi-agent distributed research.** Phase 8 envisions multiple research agents coordinating on KB without conflicts. Architectural decision deferred to Phase 8 spec.
9. **Compressed-replay clock-skew handling.** During bootstrap, simulated clock advances faster than wall clock. How are wall-clock-dependent operations (LLM rate limits, API quotas) reconciled? Decision deferred to integration spec.
10. **Convergence-report acceptance threshold.** Vault holdout validation produces a number; what is the threshold below which we refuse to deploy live capital? Quantitative threshold deferred to Phase 6 spec.
