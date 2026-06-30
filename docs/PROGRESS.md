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
| 3 | **Autoresearch loop** — the self-improving core | 🟡 **in progress (Layer 1 ✅ complete; Layer 2 next)** |
| 4 | News / sentiment intelligence | ⚪ not started |
| 5 | Broker integration (paper) | ⚪ not started |
| 6 | Live capital + ops (dashboard, Telegram) | ⚪ not started |
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

### Layer 2 — LLM mutator
⚪ not started. Nemotron proposes mutations (replaces the mechanical hill-climb);
adds the **regime detector itself** as a mutation target. Needs Layer-1 provenance
first (so nondeterministic runs leave an auditable lineage).

### Layer 3 — agent fleet
⚪ not started. The 7-role Hermes subagent fleet (Orchestrator / Planner / Researcher
/ Reviewer / Hunter / Guardian / Archivist+Memory-Keeper / Reporter) + Hindsight
grounding + compressed-replay + Telegram ops. Wraps a loop that already works.

## Current focus

**Layer 1 is complete** (runnable, real detector, vault-gated, provenance). Next: **Layer 2** (LLM mutator). Capital is only at
risk from Phase 5 onward; Phases 1–4 are pure research with zero capital.
