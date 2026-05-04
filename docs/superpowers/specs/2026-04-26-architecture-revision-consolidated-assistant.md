# Architecture Revision — Consolidated Assistant Model

**Status:** Approved 2026-04-26
**Type:** Architecture revision (supersedes parts of the original architecture decomposition + NemoClaw integration specs)
**Anchor specs (revised by this document):**
- [`2026-04-25-mahoraga-architecture-decomposition.md`](2026-04-25-mahoraga-architecture-decomposition.md) — §3.2, §3.3, §5.1, §5.6 partially superseded
- [`2026-04-25-nemoclaw-autoresearch-integration.md`](2026-04-25-nemoclaw-autoresearch-integration.md) — §4.5, §4.6, §5.1, §5.2, §5.4 partially superseded

**Discovery context:** During Phase 0 Task 3, we vendored NemoClaw at `v0.0.27`. Reading its shipped documentation revealed that NemoClaw + OpenClaw + OpenShell is built around running **one always-on OpenClaw assistant per sandbox**, not the multi-agent pub/sub runtime our original specs assumed. This revision aligns the architecture with that reality.

---

## 1. What changed and why

### Original assumption (incorrect)

Our original specs treated NemoClaw as an "agent OS" providing channel pub/sub between Hunter, Guardian, and Archivist as separate always-on agent containers. The integration spec defined `agents.yaml`, `channels.yaml`, an HTTP-based agent registration handshake, and a halt channel for inter-agent kill-switch propagation.

### What NemoClaw actually is

Per the vendored `nemoclaw-user-overview` skill (verbatim):

> "OpenClaw is the assistant: runtime, tools, memory, and behavior inside the container. It does not define the sandbox or the host gateway."
> "OpenShell is the execution environment: sandbox lifecycle, network, filesystem, and process policy, inference routing."
> "NemoClaw is the NVIDIA reference stack that implements the definition above on the host: `nemoclaw` CLI and plugin, versioned blueprint, channel messaging configured for OpenShell-managed delivery."

NemoClaw runs **one OpenClaw assistant inside one OpenShell sandbox**. The "channel messaging" it provides is human↔assistant (Telegram/Discord/Slack), not agent↔agent. There is no built-in pub/sub between multiple assistants.

### The consolidated model (this revision)

Mahoraga is **one OpenClaw assistant** running inside **one NemoClaw-hardened sandbox**, with Hunter / Guardian / Archivist implemented as **OpenClaw subagents** dispatched from the main assistant. Each subagent runs in its own context window but shares the surrounding tools, the knowledge base, the strategy registry, and the audit log. The autoresearch loop is a tool the main assistant invokes, not a separate runtime.

This matches NemoClaw's design intent ("always-on assistant") and is dramatically simpler than the multi-process model in the original specs.

## 2. The new architectural picture

```
┌─────────────────────────────────────────────────────────────────┐
│  HOST (Apple Silicon Mac, dev / cloud VM, prod)                 │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  NemoClaw blueprint → OpenShell sandbox                   │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  OpenClaw assistant (always-on)                     │  │  │
│  │  │                                                       │  │  │
│  │  │  Main orchestrator                                   │  │  │
│  │  │  │                                                    │  │  │
│  │  │  ├─→ Hunter subagent (mutate strategy)              │  │  │
│  │  │  ├─→ Guardian subagent (validate / veto)            │  │  │
│  │  │  ├─→ Archivist subagent (KB synthesis)              │  │  │
│  │  │  └─→ (future) Web-Research subagent                 │  │  │
│  │  │                                                       │  │  │
│  │  │  Shared tools: vectorbt, postgres+pgvector KB,       │  │  │
│  │  │  strategy-registry git, news-classifier, exec API   │  │  │
│  │  │                                                       │  │  │
│  │  │  Inference: → inference.local (OpenShell route) →   │  │  │
│  │  │  → LiteLLM gateway sidecar → upstream providers     │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  │                                                             │  │
│  │  OpenShell layers: filesystem isolation, network egress    │  │
│  │  policy (Alpaca, Polygon, FRED, news, LiteLLM only),       │  │
│  │  process limits, credential placeholders.                  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Sidecars (Docker compose, outside the sandbox):                 │
│  • LiteLLM gateway (multi-provider routing)                     │
│  • Postgres + pgvector (KB, trades, experiments, audit)          │
│  • Ollama (host process; Metal acceleration)                    │
│                                                                  │
│  Operator surface:                                               │
│  • Telegram bot (NemoClaw built-in; halt / status / regime)     │
│  • Streamlit dashboard (Phase 6)                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 3. Hunter / Guardian / Archivist as OpenClaw subagents

Each is a **subagent definition** (system prompt + allowed tool subset + dispatch policy) under `services/trader/subagents/`. The main assistant dispatches them on the right cadence with the right context. They run in fresh per-invocation context windows but write back to the shared KB, registry, and audit log.

| Subagent | Runs when | Inherits | Dispatches result back via |
|---|---|---|---|
| Hunter | Nightly + compressed-replay; on-demand from main | KB context pack from Archivist; current regime; parent strategy | Mutation diff → main → Guardian |
| Guardian | After every Hunter mutation; on Guardian-initiated audits | Mutation diff; FitnessReport; portfolio state; synthetic-data tools | Approve / veto + reason → main |
| Archivist | Weekly (L1→L2); monthly (L2→L3); on-demand | Recent KB Level-1 entries; prior Level-2/3 patterns | New KB rows + prompt-context pack → main |

Subagents don't talk to each other directly. Coordination is the main assistant's job (just like the brainstorming skill's controller pattern). This **is** the same subagent-driven-development pattern the user codified in CLAUDE.md "Practices to follow" — applied internally to the trader.

## 4. What this changes in the existing specs

### Architecture decomposition spec

| Section | Status |
|---|---|
| §1 Vision, §2 Scope | Unchanged |
| §3.1 Substrate (NemoClaw) | Stands; just remember NemoClaw runs ONE OpenClaw, not many |
| **§3.2 Always-on Agents** | **Superseded.** Hunter/Guardian/Archivist are subagents inside one OpenClaw, not separate containers |
| §3.3 Stateless Workers | Mostly stands. They become **tools** the OpenClaw assistant calls, not RPC endpoints called by separate agents |
| §3.4 Shared Infrastructure (LiteLLM, Postgres, Ollama) | Unchanged |
| §3.5 Storage | Unchanged |
| §3.6 Observation & Control | Unchanged (Telegram bot is a NemoClaw built-in; dashboard still planned) |
| §4.1 Service inventory | Hunter/Guardian/Archivist/Web-Research entries change from "Layer-2 agent containers" to "subagent definitions inside services/trader/" |
| **§5.1 Channel contract** | **Superseded.** No NemoClaw channels. Coordination is in-process within OpenClaw. |
| §5.2–5.5 Inference, Data, Strategy, Risk-limit & compliance | Unchanged |
| **§5.6 Halt contract** | **Revised** (see §6 below) |
| §6 Phase milestone gates | Mostly unchanged; Phase 3 exit criteria reword from "agents register" to "subagents dispatch" |
| §7–9 | Unchanged |

### Integration spec

| Section | Status |
|---|---|
| §1–3 | Unchanged |
| §4.1 NemoClaw substrate | Reframe: the substrate hosts ONE assistant, not three |
| §4.2 LiteLLM | Unchanged in concept; LiteLLM is reached via NemoClaw's "compatible endpoints" inference option |
| §4.3 Postgres+pgvector | Unchanged |
| §4.4 Ollama | Unchanged |
| **§4.5 Agent containers** | **Superseded.** Replaced by §3 of this revision. |
| §4.6 Stateless workers | Reframe as **tools** rather than separate services |
| **§5.1 agents.yaml**, **§5.2 channels.yaml** | **Superseded — both files dropped.** Replaced by NemoClaw onboarding config (see §5 below) |
| §5.3 inference-routes.yaml | Replaced by NemoClaw's native inference routing |
| §5.4 sandbox-policies.yaml | Replaced by NemoClaw blueprint network-policy YAML (`nemoclaw-blueprint/policies/`) — same intent, different file location |
| §5.5 connections.yaml | Replaced by NemoClaw onboarding (Telegram token, Alpaca keys, etc. become OpenShell credential providers) |
| §6 autoresearch loop | Conceptually unchanged; `autoresearch_iteration()` becomes a tool the OpenClaw main orchestrator invokes |
| §7 Docker compose | Simpler — no per-agent containers, just sandbox + sidecars |
| §8 Upstream tracking | Unchanged |
| §9 Acceptance criteria | Phase 0–3 exits reworded against this model |
| §10 Open questions | Several resolved by this revision (e.g., channel-payload mechanism) |

## 5. Configuration topology under the new model

### NemoClaw blueprint (replaces our `agents.yaml` / `channels.yaml`)

Phase 0 config lives at `infra/nemoclaw/`:

- `blueprint.yaml` — sandbox identity, OpenClaw role description, allowed tool list, model + provider selection
- `policies/egress.yaml` — declarative network allowlist (Alpaca, Polygon, FRED, SEC EDGAR, news websockets, LiteLLM gateway, Postgres)
- `policies/filesystem.yaml` — read-write paths inside the sandbox (`/sandbox/.openclaw-data`, `/sandbox/.nemoclaw`, parquet mount), everything else read-only
- `subagents/hunter.md`, `subagents/guardian.md`, `subagents/archivist.md` — subagent definitions (system prompt + tool subset + cadence)
- `tools/` — Python modules registered as OpenClaw tools (vectorbt wrapper, KB read/write, strategy registry, regime detector, etc.)

We provision the sandbox via `nemoclaw onboard` once at Phase 0 setup. Future phases add tools and refine subagent definitions.

### LiteLLM still plugs in

LiteLLM remains a Docker sidecar on host (Apple-Silicon Metal Ollama still on host directly). NemoClaw's onboarding wizard offers "compatible endpoints" as a provider option — point it at `http://litellm:4000/v1` and inference flows: OpenClaw → `inference.local` (OpenShell route) → LiteLLM → Ollama / Anthropic / OpenRouter / Gemini / OpenAI / Grok.

## 6. Halt contract (revised)

Original §5.6 specified a `halt` channel + Postgres-poll fallback because we assumed multiple agent processes had to be stopped independently. With one OpenClaw process inside one sandbox, the contract simplifies to:

- **Primary:** operator types `/halt` in Telegram (or clicks the dashboard button when Phase 6 lands). NemoClaw's Telegram channel routes to OpenClaw, which suspends tool use within 1 s. The new state is recorded in `audit.events` with `action='halt'`.
- **Fallback (preserved):** if Telegram is unreachable, operator can `nemoclaw stop` from the host CLI, which sends SIGTERM to the OpenClaw process. Trade-execution tools poll `audit.events` for the most recent halt record every 2 s as a defense-in-depth (in case the process is wedged but tools still execute).
- **Recovery:** explicit `/resume` from operator after manual review.

The Postgres `audit.events` schema from Phase 0 T2 already supports this — `actor`, `action`, `payload` columns are sufficient to record the halt.

## 7. Phase 0 plan changes

Tasks already completed and unchanged:
- T1 (repo skeleton) ✅
- T1.5 (Ollama setup) ✅
- T2 (Postgres migrations) ✅
- T3 (NemoClaw subtree vendored) ✅

Tasks revised:
- **T4** — NemoClaw API discovery → renamed to **"OpenClaw subagent topology design"**: document the main-assistant + 3-subagent split, list the tools each subagent can call, write the system prompts as draft markdown files
- **T6** — NemoClaw config files → **"NemoClaw blueprint + onboarding config"**: write `blueprint.yaml`, `policies/egress.yaml`, `policies/filesystem.yaml`, draft subagent definition files. No `agents.yaml`/`channels.yaml`.
- **T9** — Heartbeat agent → **"OpenClaw sandbox bring-up smoke"**: run `nemoclaw onboard` (or its scripted equivalent), verify the assistant boots, sends a hello message via Telegram, and responds to a basic prompt
- **T10** — Halt-channel smoke → **"Halt smoke via Telegram + audit-log"**: operator sends `/halt`; assistant suspends tool use within 1s; halt event lands in `audit.events`

Tasks unchanged:
- T5 (autoresearch frozen)
- T7 (LiteLLM gateway)
- T8 (Docker compose) — except the `heartbeat` service is removed; replaced by the NemoClaw-managed sandbox
- T11 (CI pipeline) — removes heartbeat unit tests; adds the new T9/T10 smoke
- T12 (LLM throughput)
- T13 (README finalization)
- T14 (Phase 0 exit verification)

## 8. Trade-off acknowledged

**Loss of structural isolation between brains.** Hunter and Guardian no longer run in separate processes; they share the same OpenClaw context, tools, and credentials. A prompt-injection attack reaching the orchestrator could in theory subvert Guardian's veto.

**Mitigation:** OpenShell's filesystem isolation, egress allowlist, and credential placeholders prevent the obvious damage paths (the agent can't reach unapproved hosts, can't write to areas it shouldn't, can't see real broker keys). The hard risk limits enforced at the execution-tool boundary (max position 5%, daily loss halt 2%, etc. — architecture spec §5.5) are evaluated **outside** the LLM's reasoning, so prompt-injection cannot bypass them. The trade-off is acceptable for Phases 0–7. If genuine brain-isolation becomes required (e.g., for regulatory reasons), Phase 8 can revisit.

## 9. What stays the same

This revision is substrate-layer. The application doesn't change:

- The five-wall fortress + three-gate system (Phase 2)
- The autoresearch loop kernel (Phase 3) — same kernel, just dispatched as a tool from the main assistant
- The compressed-history replay (Phase 1–3 bootstrap)
- All hard risk limits, compliance predicates, kill-switch semantics
- Postgres + pgvector schemas (knowledge / trades / experiments / strategies / audit)
- LiteLLM gateway as the multi-provider routing layer
- Free-API-first data ingestion (Phase 1)
- Two-environment posture (DEV local; PROD cloud-deferred)

## 10. Open questions

1. **OpenClaw's actual subagent API.** The OpenClaw runtime is built on a Claude-Code-like substrate. Subagent dispatch shape needs to be verified during T4 by reading OpenClaw's docs (next sub-step). Likely candidates: a `Task`-style tool, or system-prompt-based role switching, or worker spawning via OpenShell. The T4 deliverable resolves this.

2. **Tool registration mechanism.** How Python modules (`services/trader/tools/`) become OpenClaw-callable tools depends on OpenClaw's plugin model. T4 also resolves this.

3. **Subagent context-window economics.** Each subagent dispatch opens a fresh context. For nightly compressed-replay that may invoke Hunter ~50 times, context-window provisioning + cost matters. T4 records observed costs; T12 verifies the bootstrap economics.

4. **Telegram halt latency.** The §6 revised halt contract claims `<1s`. NemoClaw's documented Telegram-channel latency needs measurement — defer to T10's smoke test.

5. **NemoClaw `nemoclaw onboard` automation.** Onboarding is interactive by default. For CI, we need a non-interactive path. T6 investigates and documents.

## 11. Vendor inventory (addendum 2026-04-30)

| Path | Mechanism | License | Role |
|---|---|---|---|
| `vendor/nemoclaw/` | live `git subtree` (monthly + 72h security pulls) | Apache 2.0 | Substrate (NemoClaw + OpenShell + OpenClaw) |
| `vendor/tradingagents/` | live `git subtree` (monthly pulls) | Apache 2.0 | **Reference** for data fetchers + analyst prompts; cherry-picked per phase into `services/trader/`, never integrated wholesale. Substrate-portability rule (CLAUDE.md §7) keeps LangGraph/LangChain out of `services/trader/`. See [`vendor/tradingagents/MAHORAGA_NOTES.md`](../../../vendor/tradingagents/MAHORAGA_NOTES.md) for cherry-pick targets per phase + modifications log. |
| `vendor/hindsight/` | live `git subtree` (monthly pulls) | MIT | **Memory / knowledge layer** — Experience Facts, World Facts, Observations, Mental Models. Runs as a sidecar service. Replaces planned hand-coded `knowledge.*` Postgres schemas. See [`2026-05-03-hindsight-memory-layer-revision.md`](2026-05-03-hindsight-memory-layer-revision.md) and [`vendor/hindsight/MAHORAGA_NOTES.md`](../../../vendor/hindsight/MAHORAGA_NOTES.md). |
| `vendor/autoresearch/` | frozen one-time copy | MIT | Loop pattern reference (karpathy); adapted into `training/` (Phase 3) |

The tradingagents addition (2026-04-30) does **not** change the architectural model defined in this revision — it adds a paper-validated reference repo (arXiv:2412.20138) alongside our existing vendors. Cherry-pick targets land in `services/trader/` per phase as the relevant phase begins.

---

This revision is the canonical architecture going forward. The original specs remain in the repo for historical context and to preserve their phase-gate definitions, but the substrate-layer details cited above are superseded by §3 and §5 of this document.
