# Mahoraga — Project Context for AI Assistants

> Note: This file is the standard Claude Code project-context file. It is auto-loaded into every Claude Code session in this repo. Both Claude Code and any AI agent working in this codebase should read this first.

## What is Mahoraga?

A self-improving, regime-aware, autonomous trading system for US equities. The system continuously adapts to market conditions and compounds intelligence over time, not just capital. Concretely: it recognizes market regimes (MACRO / MESO / MICRO lenses), selects strategies from a versioned registry that grows richer each cycle, retires decaying edges proactively, and routes everything through hard infrastructure-level risk limits with human override.

The novel contribution is the training loop: 7+ years of historical market data are replayed at accelerated speed in an environment architecturally identical to the live one, so the system has "experienced" many regimes before any real capital is deployed.

Source-of-truth project plan: [`docs/project_plan/MAHORAGA_PROJECT_PLAN.md`](docs/project_plan/MAHORAGA_PROJECT_PLAN.md) (3,216 lines). Specs under `docs/superpowers/specs/` are the navigable map.

## Architecture in one paragraph

NemoClaw (vendored at `vendor/nemoclaw/`) is the substrate — agent OS providing lifecycle, hardened sandbox, state, managed channels, and routed inference. Three always-on agents (Hunter, Guardian, Archivist) plus stateless workers (regime-detector, data-ingest, execution, training) run as sibling containers under NemoClaw. LiteLLM gateway sidecar provides multi-provider LLM routing (Ollama local, OpenRouter, Gemini, Anthropic, OpenAI, Grok behind one OpenAI-compatible API). Postgres + pgvector is the single application database (knowledge base, trade journal, experiment metadata, strategy registry pointers). Strategy mutations are driven by a karpathy/autoresearch-style loop, vendored once at `vendor/autoresearch/` and adapted in `training/`. Everything dockerized; `docker compose up` brings the full local stack online on Apple Silicon.

## Key architectural decisions (locked in 2026-04-25)

| Decision | Choice | Reason |
|---|---|---|
| Agent substrate | NVIDIA/NemoClaw, vendored as `git subtree` at `vendor/nemoclaw/` | Provides agent lifecycle, sandbox, channels, routed inference; live-tracked for security updates |
| Training-loop pattern | karpathy/autoresearch, frozen copy at `vendor/autoresearch/` | Loop kernel adapted to strategy mutation; not updated upstream after copy |
| Repo layout | Single umbrella monorepo; private | Clean upstream tracking via subtree; cohesive deploy unit |
| Database | Postgres + pgvector from day one | Single service for KB vector store, trade journal, metadata; eliminates ChromaDB and SQLite |
| LLM routing | LiteLLM gateway in front of NemoClaw | Universal multi-provider support without per-provider code |
| Runtime | Docker everywhere — local dev and future cloud | Same artifact runs locally and in cloud |
| Local target | Apple Silicon MacBook via Colima or Docker Desktop | NemoClaw supports macOS Apple Silicon (no NVIDIA GPU required) |
| Cloud target | Hostinger / CloudFront / similar — deferred to later phase | Local-first; cloud spec written when needed |

## Repo topology

```
mahoraga/
├── CLAUDE.md                      ← you are here
├── docker-compose.yml             ← orchestrates the full local stack
├── docs/
│   ├── project_plan/              ← original 3216-line plan (raw material)
│   └── superpowers/specs/         ← all specs land here
├── services/                      ← our Python trading services (one per role)
├── training/                      ← Mahoraga's autoresearch loop (adapted)
├── vendor/
│   ├── nemoclaw/                  ← live subtree from NVIDIA/NemoClaw (Apache 2.0)
│   └── autoresearch/              ← frozen copy of karpathy/autoresearch (MIT)
├── infra/
│   ├── nemoclaw-config/           ← agents.yaml, channels.yaml, routes, sandboxes, connections
│   └── compose/                   ← service Dockerfiles
└── data/                          ← gitignored
    ├── parquet/                   ← feature store
    ├── postgres/                  ← Postgres volume
    ├── nemoclaw-state/            ← NemoClaw internal state (substrate-private)
    └── audit/                     ← append-only audit log files
```

## How to extend NemoClaw without merge hell

Three tiers, in order of preference. Stay in Tier 1 unless you genuinely cannot.

**Tier 1 — Configuration (90% of changes).** Add agents, channels, routes, sandbox profiles, outbound connections by editing files under `infra/nemoclaw-config/`. Never touches `vendor/nemoclaw/`. Zero merge risk.

**Tier 2 — Sibling services (new logic).** New agents and connectors are new containers under `services/<role>/`, registered with NemoClaw via Tier 1 config. NemoClaw is language-agnostic at the channel boundary; sibling services can be Python, Node, Rust, anything.

**Tier 3 — Patches to `vendor/nemoclaw/` (last resort).** If you genuinely need to modify NemoClaw substrate code: tag the diff with `// MAHORAGA-PATCH(YYYY-MM-DD): <reason>`, log it in `vendor/nemoclaw/MAHORAGA_CHANGES.md`, attempt to upstream it via PR to NVIDIA when reasonable. Run integration tests against patched substrate before every `git subtree pull`.

## Upstream tracking

- **NemoClaw**: pulled via `git subtree pull --prefix=vendor/nemoclaw <upstream> <tag> --squash`. Routine pulls monthly; security advisories pulled within 72h. Never push back upstream by accident — `git subtree push` is explicit and never run automatically.
- **autoresearch**: frozen. We copy `program.md` and loop scaffolding into `training/` once; we do not pull updates. License preserved at `vendor/autoresearch/LICENSE`.

## IP & licensing posture

- This repo is **private** and may become a commercial product.
- NemoClaw is **Apache 2.0** — permits private fork, modification, commercial use. Obligations: preserve `vendor/nemoclaw/LICENSE`, document modifications in `vendor/nemoclaw/MAHORAGA_CHANGES.md`, preserve any upstream `NOTICE` file, do not use NVIDIA trademarks in product branding.
- autoresearch is **MIT** — preserve `vendor/autoresearch/LICENSE` and copyright notice. Otherwise unrestricted.
- Never delete vendor `LICENSE` files. Never strip copyright headers from vendored code.

## Critical sequencing rule (do not violate)

Phases 1–4 are pure research with **zero capital at risk**. Broker integration (Phase 5) does not begin until Phase 3 (autoresearch loop core) and Phase 4 (intelligence layer) have passed their exit criteria. The convergence report (vault holdout validation) must pass before any live capital. This is in the project plan and is non-negotiable.

## Hard risk limits (architectural — must exist in code, not policy)

These come from the project plan and must be enforced at the execution boundary, not as advisory checks:

- Max single position: 5% of portfolio
- Max sector exposure: 20%
- Daily loss halt: 2% (no new entries that day)
- Catastrophic loss suspension: 10% monthly drawdown → human review required
- No new entries within ±30 min of FOMC, CPI, NFP releases
- No new entries if regime confidence < 40%
- Stop-loss on every trade: max 2× ATR from entry
- Kill switch: < 10 seconds to halt all trading

## Coding & contribution conventions

- Python 3.11+. Type-hint everything in `services/` and `training/`.
- Pydantic + YAML for config. No untyped dicts at config boundaries.
- Each service in `services/` has its own `Dockerfile`, `pyproject.toml`, and is independently deployable.
- Inter-agent communication only through NemoClaw channels — no direct service-to-service HTTP calls between Hunter/Guardian/Archivist.
- Tests live next to code (`services/hunter/tests/`). Integration tests at the repo root under `tests/integration/`.
- No look-ahead bias, ever. Vault embargo (last 6 months of historical data) is checked at the data-access boundary, not by convention.

## Where to look for what

| Question | Read |
|---|---|
| What is the system supposed to do? | `docs/project_plan/MAHORAGA_PROJECT_PLAN.md` |
| What's the architectural map? | `docs/superpowers/specs/2026-04-25-mahoraga-architecture-decomposition.md` |
| How are NemoClaw and autoresearch wired in? | `docs/superpowers/specs/2026-04-25-nemoclaw-autoresearch-integration.md` |
| What phase are we in? | The most recent commit on `main` plus the spec catalog in the architecture spec |
| What's allowed to change in `vendor/`? | The "How to extend NemoClaw" section above |

## Open questions to resolve as we go

These are flagged in the architecture spec; they don't block Phase 0–3 work but need resolution before later phases:

1. NemoClaw plugin/extension API maturity (alpha software, may shift)
2. Pre-2020 news archive coverage strategy
3. Capital scaling thresholds (Stage 1 → Stage 2)
4. Regime label taxonomy (boundaries between MACRO regimes)
5. Earnings-season special handling
6. LLM provider fallback priority order under cost or rate-limit pressure

