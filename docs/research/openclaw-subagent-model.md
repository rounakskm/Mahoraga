# Mahoraga Subagent Topology

**Architecture anchor:** [`../superpowers/specs/2026-04-26-architecture-revision-consolidated-assistant.md`](../superpowers/specs/2026-04-26-architecture-revision-consolidated-assistant.md)
**Date:** 2026-04-26
**Source material consulted:**
- `vendor/nemoclaw/.agents/skills/nemoclaw-user-overview/references/{overview,ecosystem,how-it-works}.md`
- `vendor/nemoclaw/CLAUDE.md`
- `vendor/nemoclaw/.agents/skills/nemoclaw-user-configure-inference/SKILL.md`
- `vendor/nemoclaw/nemoclaw-blueprint/` (blueprint YAML + policies)
- `vendor/nemoclaw/nemoclaw/src/blueprint/` (TypeScript runner)

This document describes how Hunter / Guardian / Archivist (the conceptual three brains of Mahoraga) are realized as **OpenClaw subagents** sharing tools, knowledge base, and execution boundary, but with their own context windows. T6 implements the configuration this designs; T9/T10 verify it.

---

## 1. The main orchestrator

**Identity:** the always-on OpenClaw assistant configured by `infra/nemoclaw/blueprint.yaml`, running inside a single OpenShell sandbox provisioned by NemoClaw.

**Responsibilities:**
- Reasons about the trading day at the macro level (regime context, risk posture, calendar of upcoming releases).
- Dispatches Hunter, Guardian, Archivist on the right cadences.
- Owns the operator-interaction surface: receives `/halt`, `/status`, `/regime`, `/strategy <id>` commands via Telegram.
- Holds the audit log writer; every subagent dispatch produces an `audit.events` row keyed by the subagent name and the dispatch reason.
- Coordinates between subagent results — Hunter proposes, Guardian vetoes, Archivist promotes — but no subagent talks to another directly.

**What it preserves between dispatches:**
- The current strategy registry pointer (which strategies are active, standby, retired).
- The current regime label (MACRO / MESO / MICRO from the regime-detector tool).
- A short rolling memory of the last N orchestrator decisions for self-explanation.
- The Telegram session.

**What it does NOT preserve:**
- Subagent inner reasoning — each subagent dispatch is fresh context. Only the subagent's structured return value flows back.

## 2. Hunter subagent

| Field | Value |
|---|---|
| **Role** | Propose strategy mutations for the autoresearch loop |
| **Dispatch trigger** | Nightly cron 5pm–8:30am ET (Phase 3); weekend full pass (Sun 6pm–9pm); compressed-history replay (Phase 1–3 bootstrap) |
| **Context inherited** | Parent strategy file; current regime; KB context pack from Archivist (recent successes, recent failures, forbidden patterns) |
| **Tools allowed** | `vectorbt_backtest`, `kb_read`, `regime_read`, `autoresearch_run_one` |
| **Tools forbidden** | `execution_*` (would let it place real trades), `kb_write_levels_2_3` (only Archivist promotes), `strategy_registry_write` (only main commits promotions), `outbound_web` (no internet egress; pre-vetted KB context only) |
| **Returns to main** | `{mutation_diff, rationale, expected_impact, regime_affinity}` |

**System prompt sketch:**

> You are Hunter — the strategy-mutation proposer in the Mahoraga autoresearch loop.
>
> Your job: given a parent strategy, the current regime, and a knowledge-base context pack, propose ONE mutation that might improve the strategy's composite score (Sharpe + DSR + PBO + per-regime breakdown). Return the diff + rationale. Do NOT run the backtest yourself — the autoresearch loop tool handles that.
>
> Constraints:
> - Mutations stay within the Strategy ABC (rewrite signal()/position_size() bodies and PARAMS dict; do not change the public signature)
> - Avoid patterns the KB marks "forbidden" (Archivist surfaces these in the context pack)
> - Prefer small, single-axis changes the loop can attribute clearly
> - You do NOT execute orders. You do NOT promote strategies to the registry. You return a proposal.

## 3. Guardian subagent

| Field | Value |
|---|---|
| **Role** | Veto strategy proposals using the 5-wall fortress + 3-gate system; trigger halt on catastrophic-loss conditions |
| **Dispatch trigger** | After every Hunter mutation; ad-hoc audits requested by main; periodic portfolio-wide stress checks |
| **Context inherited** | Proposed mutation diff; FitnessReport so far; current portfolio state + correlations; current regime |
| **Tools allowed** | `synthetic_data` (GBM, jump-diffusion, BTC-aware jumps), `walls_evaluate` (Walls 1/3/4/5), `gates_evaluate`, `portfolio_state_read`, `halt_publisher` |
| **Tools forbidden** | `strategy_registry_write`, `execution_*`, `kb_write_levels_2_3` |
| **Returns to main** | `{decision: "approve" \| "veto" \| "halt", wall_results, gate_results, reason}` |

**System prompt sketch:**

> You are Guardian — the risk veto in the Mahoraga autoresearch loop.
>
> Your job: evaluate a proposed candidate strategy against the 5 anti-overfitting walls (statistical rigor, data discipline, complexity control, generalization, meta-awareness) and the 3 gates (fitness, robustness, risk). Approve only if all walls + gates pass AND the candidate's composite score improves on its parent. Otherwise return a structured veto.
>
> If portfolio state shows catastrophic loss conditions (>10% monthly drawdown OR >2% daily loss), publish a halt event regardless of strategy state.
>
> You do NOT propose mutations. You do NOT execute orders. You return an approve/veto decision with reasons.

## 4. Archivist subagent

| Field | Value |
|---|---|
| **Role** | Promote KB Level-1 raw experiments to Level-2 patterns (weekly); promote Level-2 to Level-3 meta-principles (monthly); build the prompt-context pack Hunter consumes |
| **Dispatch trigger** | Weekly Sunday 8pm ET (Level-2); first business day of month (Level-3); on-demand context-pack rebuild |
| **Context inherited** | Recent KB Level-1 entries (last 7 / 30 days); prior Level-2 / Level-3 patterns; recent execution-results |
| **Tools allowed** | `kb_read`, `kb_write_levels_2_3`, `vector_similarity_search` |
| **Tools forbidden** | `strategy_registry_write`, `execution_*`, `outbound_web` |
| **Returns to main** | `{level_2_added, level_3_added, context_pack_summary, forbidden_patterns_added}` |

**System prompt sketch:**

> You are Archivist — the meta-learner of the Mahoraga knowledge base.
>
> Weekly job: scan the past week's Level-1 experiment entries (kept and discarded). Identify recurring patterns — strategies that fail across regimes, mutations that reliably improve specific regimes, walls that are calibration-drifting. Write findings as Level-2 KB rows with embeddings.
>
> Monthly job: synthesize Level-2 patterns into Level-3 meta-principles (e.g., "in regimes where VIX is rising while breadth narrows, mean-reversion strategies degrade faster than trend-following ones — defer mean-reversion deployments until breadth re-broadens"). Write as Level-3 KB rows.
>
> Always-on: build the prompt-context pack Hunter receives, surfacing recent successes, recent failures, and "forbidden patterns" Hunter should not re-explore.
>
> You do NOT propose mutations. You do NOT execute orders. You read history and write distilled lessons.

## 5. Tool registration

OpenClaw is built on the Anthropic-style assistant runtime (per `vendor/nemoclaw/`'s plugin description: "TypeScript package that registers an inference provider and the `/nemoclaw` slash command inside the sandbox"). Tools are registered via the OpenClaw blueprint and surface as callable functions inside the assistant.

For Mahoraga:

- Python tool implementations live at `services/trader/tools/<tool_name>.py`. Phase 1+ adds them. Phase 0 only registers placeholder tool stubs to satisfy the blueprint.
- Each tool exports a function with a structured signature; the OpenClaw runtime introspects it and exposes it as a callable.
- Subagent definitions reference tools by name (the `tools_allowed` list in their frontmatter); attempts to call disallowed tools are rejected by OpenClaw before reaching the tool implementation.
- The execution-boundary contract (architecture spec §5.5) is implemented in the `execution_*` tools — they reject orders that violate hard limits or compliance predicates **before** dispatching to the broker. Hunter and Guardian don't have execution access, but the main orchestrator does — and even the main can't bypass the firewall, because it lives below the LLM's reasoning surface.

## 6. Coordination contract

The main orchestrator dispatches subagents via OpenClaw's subagent dispatch primitive (analogous to the `Task` tool in Claude Code). Subagents do NOT talk to each other; results flow back to main, which reasons over them. Same pattern as `superpowers:subagent-driven-development`, applied internally to the trading system.

```
main orchestrator
   │
   ├──dispatch(Hunter, parent_strategy, kb_context) ─→ {mutation_diff, rationale}
   │                                                          │
   │                              (main reasons)              │
   │                                                          ▼
   ├──dispatch(Guardian, mutation_diff, fitness_so_far) ─→ {decision, reason}
   │                                                          │
   │                              (main reasons)              │
   │                                                          ▼
   │  (if approve and improves) ─→ commit_to_registry(candidate)
   │  (if veto) ─→ discard(candidate, log to KB Level-1 with reason)
   │  (if halt) ─→ publish halt event, suspend further dispatches
   │
   └──[on Sunday 8pm] ──dispatch(Archivist, last_7d_kb) ─→ {level_2_added, ...}
```

## 7. Open questions

- **Subagent context-window economics.** Each Hunter dispatch opens a fresh context. Compressed-replay may invoke Hunter ~50–100 times per night; per-dispatch context size needs to fit cheap enough into the bootstrap LLM (Gemma 4 26b on host) to be sustainable. T12 measures this empirically.
- **Tool call observability.** OpenClaw logs tool calls to its own state. Mahoraga also wants every tool call mirrored into Postgres `audit.events` for hash-chained auditability. The mirror mechanism (an OpenClaw plugin? A wrapping Python decorator on each tool?) needs design when Phase 1+ adds the first real tool.
- **Subagent prompt-injection isolation.** A malicious upstream news article could try to inject instructions that reach Hunter. Defense: news content is summarized/classified by the news-classifier tool **outside** the agent's reasoning surface, then surfaced as structured fields, not raw text. Phase 4's intelligence-layer spec must enforce this.
- **`nemoclaw onboard` non-interactive mode.** Currently undocumented. T6 attempts the env-driven path; T9 falls back to manual onboarding if necessary.
- **Telegram bot setup.** Operator must create a Telegram bot via BotFather, paste the token into `.env`. T10 documents the steps; full smoke deferred until that's done.
