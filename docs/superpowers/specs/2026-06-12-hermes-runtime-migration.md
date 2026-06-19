# Architecture Decision Record — Migrate the in-sandbox harness from OpenClaw to Hermes

**Status:** Approved 2026-06-12
**Type:** Architecture decision record (reverses the 2026-05 "stay with OpenClaw" decision)
**Supersedes:** the `.claude/plans/` OpenClaw-vs-Hermes decision record (2026-05) — "Stay with OpenClaw"
**Anchor specs (amended by this document):**
- [`2026-04-26-architecture-revision-consolidated-assistant.md`](2026-04-26-architecture-revision-consolidated-assistant.md) — the "one assistant per sandbox" model is unchanged; only the *harness* swaps
- [`2026-05-03-phase-3-seven-role-amendment.md`](2026-05-03-phase-3-seven-role-amendment.md) — subagent decomposition unchanged
- [`2026-05-03-hindsight-memory-layer-revision.md`](2026-05-03-hindsight-memory-layer-revision.md) — Hindsight stays canonical; this ADR adds a coexistence rule

---

## 1. Decision

**Switch the in-sandbox assistant harness from OpenClaw to NousResearch Hermes Agent**, running inside the same NemoClaw + OpenShell sandbox we already operate. The substrate (NemoClaw host + OpenShell sandbox), the memory layer (Hindsight/pgvector), the transactional store (Postgres), the inference gateway (LiteLLM), and all domain code under `services/trader/` are **unchanged**.

This reverses the 2026-05 decision to stay with OpenClaw. That decision was correct on the evidence available in May; new evidence (below) changes the balance.

## 2. Why this reverses the May decision

The May decision rested on three pillars. Two have materially weakened; one remains but is now phase-gated rather than disqualifying.

| May rationale | Status in June 2026 |
|---|---|
| **Hermes-in-NemoClaw is experimental; OpenClaw is the blessed path** | **Weakened.** NVIDIA published an official deployment guide — ["Deploy Self-Evolving Agents for Faster, More Secure Research with a Hermes Agent and NVIDIA NemoClaw"](https://developer.nvidia.com/blog/deploy-self-evolving-agents-for-faster-more-secure-research-with-a-hermes-agent-and-nvidia-nemoclaw/) — describing exactly our topology: Hermes as harness, OpenShell as sandbox, Nemotron/compatible-endpoints for inference. Hermes is at v0.16 ("Surface Release", native desktop app, ~100 PRs in one week). It is now a first-class, NVIDIA-documented path. |
| **No agent-level self-improvement worth the risk** | **Reversed — this is now the decisive *pro*.** Hermes auto-writes a `SKILL.md` after any task with ≥5 tool calls (YAML frontmatter + learned procedure), grades and prunes skills on a schedule, and persists them across sessions. This is agent-level self-improvement we would otherwise have to hand-build. It is *orthogonal* to our strategy-level autoresearch loop (Phase 3) — the two compound. OpenClaw has none of this. |
| **Hermes gateway can't restart after stop (#2426); kill-switch risk** | **Still open, now phase-gated.** [NemoClaw #2426](https://github.com/NVIDIA/NemoClaw/issues/2426) remains open (PR #2438 fixed only the error message, not recovery). This is a *Phase 6 live-capital* blocker, not a *Phase 2–5 research* blocker. We are in Phase 2 with zero capital at risk. Mitigation 1 (watchdog) neutralizes it for Phases 2–5; a real upstream fix or production restart mechanism is a Phase 6 entry gate. |

### What did NOT change

- **Memory drift risk.** Hermes ships its own SQLite (`~/.hermes/state.db`) + `MEMORY.md`. This is real and is addressed by Mitigation 3 (Hindsight stays canonical; Hermes memory is ephemeral session cache only).
- **No public trading deployment on Hermes.** Still true. We accept this for research phases; Phase 6 entry is independently gated on the hard-limit firewall, which lives *outside* the harness regardless.
- **`network_mode: host` in the upstream Hermes compose.** Irrelevant to us — we do **not** use the Hermes standalone compose. Hermes runs inside the OpenShell sandbox, whose egress allowlist + filesystem policy + L7 proxy provide isolation independent of the harness. See §5.

## 3. What changes in the repo (substrate layer only)

Per CLAUDE.md §"Substrate-portable application code", the harness is substrate; domain code is not. This migration touches **only** substrate-adapter files:

| File | Change |
|---|---|
| `infra/nemoclaw/blueprint.yaml` | OpenClaw `A:` role block → Hermes agent block (`agent: hermes`, gateway + API-server config, skills dir) |
| `infra/nemoclaw/onboard.env` | `nemoclaw onboard` → `nemoclaw onboard --agent hermes`; add `API_SERVER_KEY`, Hermes phone-home |
| `infra/nemoclaw/policies/filesystem.yaml` | `/sandbox/.openclaw*` paths → `/sandbox/.hermes*`; add skills read-write paths |
| `infra/nemoclaw/policies/egress.yaml` | add Hermes phone-home hosts (`*.nousresearch.com`) behind an explicit, commented allowlist |
| `infra/nemoclaw/skills/` (new) | `agent_created/` + `stable/` dirs + promotion policy (Mitigation 2) |
| `scripts/hermes_gateway_watchdog.py` (new) | gateway health-check + auto-restart (Mitigation 1) |
| `CLAUDE.md` | architecture paragraph, decisions table, vendor notes |
| `docker-compose.dev.yml` (new) | lightweight Postgres-only dev stack (independent of this migration; bundled for convenience) |

**Unchanged:** everything under `services/trader/` (data, universe, features, regime, backtest, walls), all Postgres migrations, Hindsight, LiteLLM, the autoresearch kernel. The subagent system prompts in `infra/nemoclaw/subagents/*.md` are portable as-is — Hermes dispatches subagents the same conceptual way (system prompt + tool subset), so their content carries over; only the dispatch mechanism (a Hermes skill/subagent registration) differs, and that is wired at onboarding.

## 4. The four mitigations (entry conditions for the switch)

### Mitigation 1 — Kill-switch watchdog for #2426

`scripts/hermes_gateway_watchdog.py`: a host-side loop that polls the Hermes gateway health endpoint every 30 s and re-launches it (`nemoclaw` gateway start path) if it stops responding. ~50 lines, zero deps beyond stdlib + the NemoClaw CLI. Fully neutralizes #2426 for Phases 2–5. **Phase 6 entry gate:** either #2426 is closed upstream with a pinned stable release, *or* this watchdog is hardened to production grade (systemd/launchd supervision + alerting) and load-tested against the halt/resume cycle.

### Mitigation 2 — Audited skill-promotion pipeline

Hermes writes auto-generated skills to `infra/nemoclaw/skills/agent_created/`. **No auto-generated skill may touch the trading path until promoted to `infra/nemoclaw/skills/stable/` by explicit operator review.** Skills affecting data reads, signal generation, risk checks, or order routing require review before promotion. Enforced by:
- directory convention (`agent_created/` is never on the trading tool path; only `stable/` is mounted to the live assistant's skills dir),
- a promotion checklist in `infra/nemoclaw/skills/README.md`,
- a CI lint (Phase 3) that fails if any skill under `agent_created/` references a trading-execution tool.

This preserves the auditability the hard-limit compliance posture requires: the agent's behavior cannot silently change in a way the operator can't see or correct.

### Mitigation 3 — Hindsight stays canonical

Hermes' `~/.hermes/state.db` (SQLite) + `MEMORY.md` are treated as **ephemeral operational cache only** — session continuity and skill scaffolding. All durable knowledge (Experience Facts, World Facts, Observations, Mental Models) continues to flow into **Hindsight/pgvector** (bank `mahoraga-trader`) as the single source of truth. The two layers serve different purposes and do not compete: Hermes caches *how to do things* (skills); Hindsight stores *what we learned* (knowledge). Nothing in the trading or audit path reads from Hermes SQLite.

### Mitigation 4 — Version pin + integration smoke gate

Pin NemoClaw at its current vendored tag and pin the Hermes agent version at onboarding. After every NemoClaw subtree pull, run the Hermes sandbox bring-up smoke (the T9/T10 equivalents from the consolidated-assistant spec §7) before merging. Advance the pin only after smoke passes.

## 5. Security posture (unchanged or improved)

The isolation boundary is **OpenShell**, not the harness. Per the NVIDIA deployment guide, the security model is identical regardless of harness:
- **Credential isolation:** the assistant never sees real tokens — auth happens as requests exit the sandbox proxy (egress allowlist in `policies/egress.yaml`).
- **Network policy is code, not prompt:** explicit allowlists for destinations, ports, verbs.
- **Filesystem compartmentalization:** read-only home; specific read-write paths (`policies/filesystem.yaml`).
- **Hard risk limits** (max position 5 %, daily-loss halt 2 %, etc.) are enforced at the execution-tool boundary in Python, *outside* the harness's reasoning — prompt injection cannot bypass them. This is unchanged from the consolidated-assistant spec §8.

The upstream Hermes standalone-compose weaknesses surfaced in research (`network_mode: host`, no seccomp baked into the Dockerfile) **do not apply** — we never run that compose. Hermes runs inside the OpenShell sandbox.

## 6. Risks of this decision

| Risk | Mitigation |
|---|---|
| #2426 not fixed by Phase 6 | Mitigation 1 watchdog + Phase 6 entry gate; if neither holds, Phase 6 does not start until resolved (sequencing rule, CLAUDE.md) |
| Auto-skill introduces a silent behavior change on the trading path | Mitigation 2 promotion gate + CI lint; `agent_created/` never on the live tool path |
| Hermes SQLite drifts from Hindsight | Mitigation 3 — Hermes memory is non-authoritative; nothing trading/audit reads it |
| Hermes breaking changes (2-week cadence) | Mitigation 4 — version pin + smoke gate before advancing |
| We discover Hermes can't dispatch our 7-role subagents cleanly | Subagent prompts are portable; if dispatch is worse than OpenClaw's, the roles-as-tools fallback (Python tools spinning sub-conversations against the OpenAI-compat endpoint) works under either harness — this was already an architectural cost we pay regardless (per the May decision record) |

## 7. Re-evaluation

This decision is revisited only if, before Phase 6:
1. #2426 is *still* open AND the watchdog proves insufficient under halt/resume load testing, **or**
2. NVIDIA downgrades or abandons the Hermes-in-NemoClaw path, **or**
3. The auto-skill mechanism produces a trading-path incident that the promotion gate failed to catch.

Otherwise the switch stands through the research phases and into Phase 6 entry review.

## 8. What stays the same (explicit)

- One assistant per OpenShell sandbox (consolidated-assistant model)
- Hunter / Guardian / Archivist as subagents, coordinated by the main assistant
- Hindsight as canonical memory; Postgres for trades/audit/registry
- LiteLLM multi-provider gateway
- All hard risk limits + kill-switch semantics (Telegram `/halt` + `nemoclaw stop` fallback + `audit.events` poll)
- The five-wall fortress + three-gate system (Phase 2), autoresearch kernel (Phase 3), all phase gates
- Substrate-portability: domain code under `services/trader/` is harness-agnostic and transfers unchanged
