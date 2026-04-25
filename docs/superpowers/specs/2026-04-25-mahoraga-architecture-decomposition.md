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

- US equities (S&P 500 + Russell 1000 universe)
- Swing trades, holding period 1 day to 6 weeks
- Long positions in Phase 1–7
- Real-time news ingestion and classification
- Regime detection across three time horizons (MACRO 3–18 mo, MESO 2–8 wk, MICRO 1–5 d)
- Autonomous strategy proposal, validation, deployment, and retirement
- Hard risk limits enforced at execution boundary, not as advisory checks
- Human override via Telegram bot and a Streamlit dashboard

### Out of scope (explicitly)

- Leverage trading
- Cryptocurrency
- Fixed income, forex, derivatives (Phase 8+ at earliest)
- Short selling (Phase 8+ at earliest)
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
- **Guardian** — stress-tests every candidate strategy, detects portfolio crowding and correlation, enforces gates, can veto Hunter proposals.
- **Archivist** — weekly meta-learner; promotes Level-1 raw experiment entries to Level-2 patterns and Level-3 meta-principles; builds the prompt-context pack other agents consume.

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
- **Ollama** — local inference for Gemma 3 (or whatever local model is current), Apple Silicon Metal acceleration on the host.
- **NemoClaw internal state** — substrate-private; persisted to a dedicated host volume at `data/nemoclaw-state/` (mounted into the NemoClaw container). Cleanly separated from the vendored source tree at `vendor/nemoclaw/` so the source is read-only by default and `git subtree pull` is unaffected by runtime state.

### 3.5 Storage (Layer 5)

- **Postgres + pgvector** — single application database with logical schemas: `knowledge` (KB Levels 1/2/3 + embeddings), `trades` (trade journal), `experiments` (autoresearch loop metadata), `strategies` (registry pointers and lifecycle state).
- **Parquet on host volume** — feature store; raw OHLCV and engineered features. Filesystem layout indexed in `experiments` schema.
- **Git** — strategy registry; every promoted candidate is a commit, with tags marking active / standby / retired.

### 3.6 Observation & Control (Layer 6)

- **Streamlit dashboard** — local web UI showing positions, recent trades, regime state, agent activity.
- **Telegram bot** — phone-resident control surface; supports commands for kill switch, strategy override, daily reports.
- **Audit log** — append-only event stream of every decision, every channel message, every order. Backed by Postgres `audit` schema and shipped to local files.
- **Kill switch** — sub-10-second halt of all trading; physical button surfaced in dashboard and Telegram.

## 4. Component Inventory

### 4.1 Services (`services/`)

| Service | Layer | Phase introduced | Language | Notes |
|---|---|---|---|---|
| `data-ingest` | 3 | 1 | Python | Alpaca/Polygon connectors, parquet writer |
| `regime-detector` | 3 | 1 | Python | MACRO/MESO/MICRO lens implementations |
| `hunter` | 2 | 3 | Python | LLM-driven strategy proposer |
| `guardian` | 2 | 3 | Python | Risk vetoes, gate enforcement |
| `archivist` | 2 | 3 | Python | KB Level promotion, weekly synthesis |
| `news-classifier` | 3 | 4 | Python | FinBERT or similar; <2s classification |
| `execution` | 3 | 5 | Python | Order routing, hard-limit enforcement |
| `training` | 3 | 3 | Python | autoresearch-style loop runner |

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

All LLM calls go through LiteLLM via OpenAI-compatible API. Model identifiers are namespaced: `ollama/gemma3:27b`, `anthropic/claude-opus-4-7`, `openrouter/x-ai/grok-2`, etc. Switching providers is a config change, not a code change.

### 5.3 Data contract (Layer 3 data-ingest → Layer 5 storage)

- OHLCV: parquet files at `data/ohlcv/{symbol}/{year}.parquet`
- Engineered features: parquet at `data/features/{symbol}/{year}-{month}.parquet`
- News: JSON-line files at `data/news/{date}.jsonl` plus indexed in Postgres `knowledge.news`
- Vault embargo enforced at the data-access boundary; the last 6 months of data are not visible to the training loop. Bypass requires an explicit `vault_override` flag that emits an audit-log warning.

### 5.4 Strategy artifact contract (Layer 3 training → Layer 5 git registry)

A strategy is a single `strategy.py` file conforming to the `Strategy` ABC defined in the integration spec. Promotion to the registry is a git commit; the commit message includes parent strategy ID, mutation diff summary, and the FitnessReport hash. Lifecycle states (active / standby / retired) are git tags.

### 5.5 Risk-limit contract (Layer 3 execution boundary)

Hard limits are enforced as predicates in the execution service, not as advisory checks consulted by agents. An order that violates any hard limit is rejected at the execution boundary regardless of which agent submitted it. This is the architectural firewall between the research stack and real capital.

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

## 8. Spec Catalog

Specs live at `docs/superpowers/specs/`. Naming convention: `YYYY-MM-DD-<topic>-spec.md`.

### Currently written

| Spec | Purpose | Phases unblocked |
|---|---|---|
| `2026-04-25-mahoraga-architecture-decomposition.md` (this document) | Map of the whole project | Anchors all future specs |
| `2026-04-25-nemoclaw-autoresearch-integration.md` | NemoClaw substrate + autoresearch loop integration | 0, 1, 2, 3 |

### Expected to be written before each phase begins

| Spec (planned) | Drafted before | Purpose |
|---|---|---|
| `data-foundation-spec.md` | Phase 1 | Data ingestion, feature engineering, vault embargo |
| `regime-detector-spec.md` | Phase 1 | MACRO/MESO/MICRO lens algorithms |
| `five-wall-fortress-spec.md` | Phase 2 | Anti-overfitting predicates and 3-gate system |
| `intelligence-layer-spec.md` | Phase 4 | News classifier, transition predictor, web research |
| `paper-trading-spec.md` | Phase 5 | Alpaca integration, position sizing, hard limits |
| `governance-spec.md` | Phase 6 | Kill switch, Telegram bot, dashboard, audit |
| `live-trading-stage-1-spec.md` | Phase 7 | Capital allocation, monitoring, escalation |
| `cloud-deployment-spec.md` | When ready to leave local | Hostinger / CloudFront / equivalent |

Plans (executable task lists) follow specs and live at `docs/superpowers/plans/`.

## 9. Open Questions

These are flagged from the source project plan; they do not block Phase 0–3 work but need resolution before later phases:

1. **NemoClaw plugin/extension API maturity.** NemoClaw is alpha software (released March 2026). Its extension surface may shift. Mitigation: stay in Tier 1 (configuration) extensions; pin to known-good releases; review release notes before each pull.
2. **Pre-2020 news archive coverage.** Alpaca's news archive starts ~2020. For 2018–2019 backtests, choices are price-action proxies, alternate news source (cost), or truncating training history. Decision deferred to Phase 1 spec.
3. **Capital scaling thresholds.** When does Stage 1 ($5K–$15K) promote to Stage 2 ($50K+)? Performance and stability targets undefined. Decision deferred to Phase 7 spec.
4. **Regime label taxonomy.** MACRO regimes are conceptually clear but boundary edge cases are not (e.g., "early bull with narrowing breadth" — bull or rotation?). Calibration deferred to Phase 1 regime-detector spec.
5. **Earnings-season special handling.** Project plan acknowledges earnings drive volatility but no dedicated module is specified. Decision deferred to Phase 4 spec.
6. **LLM provider fallback priority.** If primary provider fails or hits rate limits, what is the fallback order? Cost-vs-capability tradeoff. Decision deferred to integration spec implementation; LiteLLM supports fallback chains natively.
7. **Forbidden-pattern KB structure.** How are negative-learning entries (failed mutations) indexed for efficient retrieval? Embedding-based or rule-based? Decision deferred to Phase 3 spec.
8. **Multi-agent distributed research.** Phase 8 envisions multiple research agents coordinating on KB without conflicts. Architectural decision deferred to Phase 8 spec.
9. **Compressed-replay clock-skew handling.** During bootstrap, simulated clock advances faster than wall clock. How are wall-clock-dependent operations (LLM rate limits, API quotas) reconciled? Decision deferred to integration spec.
10. **Convergence-report acceptance threshold.** Vault holdout validation produces a number; what is the threshold below which we refuse to deploy live capital? Quantitative threshold deferred to Phase 6 spec.
