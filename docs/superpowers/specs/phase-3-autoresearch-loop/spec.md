# Phase 3 — Autoresearch Loop Spec

**Status:** Approved 2026-04-26; **revised 2026-06-22** (re-grounded on Hermes + Hindsight + the real Phase-2 fortress; delivery re-layered kernel-first — see §0)
**Type:** Phase-level spec
**Anchor specs:** [`../2026-04-25-mahoraga-architecture-decomposition.md`](../2026-04-25-mahoraga-architecture-decomposition.md), [`../2026-04-25-nemoclaw-autoresearch-integration.md`](../2026-04-25-nemoclaw-autoresearch-integration.md)
**Predecessor:** Phases 1 + 2 (complete)
**Seven-role detail:** [`../2026-05-03-phase-3-seven-role-amendment.md`](../2026-05-03-phase-3-seven-role-amendment.md) — the agent fleet (Layer 3 below); its OpenClaw / vectorbt / pgvector-KB references are re-grounded per §0.

---

## 0. The end goal (do not lose sight of it)

**This phase is the heart of Mahoraga.** Everything before it — data, features, regime, the anti-overfitting fortress — exists to serve *this*: a **self-improving loop that learns trading strategies, validates them ruthlessly, keeps what survives, and compounds what it learns over time**. The novel contribution of the whole system is this loop. Phase 1–2 are the substrate; Phase 3 is the point.

The full vision is unchanged:
- An **LLM-driven research fleet** (the seven roles) that *proposes* strategy mutations grounded in accumulated knowledge,
- a **kernel** that mutates → backtests → evaluates each candidate through the **Phase-2 fortress**,
- a **knowledge layer (Hindsight)** that accumulates Experience/World/Observation/Mental-Model facts so the system gets smarter every iteration (compounds *intelligence*, not just capital),
- **compressed-history replay** so it "experiences" 7+ years of regimes before any live capital,
- a **git strategy registry** of only-promoted strategies with full provenance,
- **vault-holdout validation** before anything is deployment-eligible.

**What the 2026-06-22 revision changes is sequencing, not scope.** The original spec built all seven LLM agents + KB synthesis + replay + registry (13 weeks, 17 sub-features) *before* a single candidate could be produced. That front-loads the hardest, least-certain parts. We re-layer so a **runnable, headless training loop exists first** — then the LLM fleet and knowledge grounding layer onto a loop that already works. Every end-goal capability above still ships; it ships in an order where each layer is independently runnable and de-risks the next.

### Re-groundings (the spec predated these; all four apply throughout, incl. the seven-role amendment)

1. **Substrate: OpenClaw → Hermes** (PR #41). The fleet's subagent/permission model is Hermes (SKILL.md / MCP / `hermes` CLI), not OpenClaw frontmatter. The permission-scope CI guard is re-expressed against Hermes.
2. **Engine: vectorbt → pandas.** Backtests run on the Phase-1 `services/trader/backtest/` engine (pure pandas/numpy). No vectorbt.
3. **Fortress: 4 walls + 3 gates, no synthetic-data.** `eval.py` runs the real `GateSystem`. Guardian's "synthetic-data adversarial test" is replaced by the metadata-driven walls (§2).
4. **Knowledge: Hindsight, not a hand-built pgvector KB.** The KB *is* Hindsight (bank `mahoraga-trader`, proven Hermes↔Hindsight MCP). Archivist = Hindsight `retain()`/`reflect()`, not a custom index. The markdown notebook stays as the auditable canonical ledger.

## 1. Architecture — kernel + fleet

```
            ┌─────────────────────── Layer 3: LLM research fleet (Hermes subagents) ───────────────────────┐
            │  Orchestrator · Planner · Researcher · Reviewer · Hunter · Guardian · Archivist · Reporter    │
            │  proposes grounded mutations, grades, narrates, curates Hindsight knowledge                   │
            └───────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                                         │ drives
            ┌────────────────────────────────────────────▼──────────────────────────────────────────────────┐
            │  Layer 1 + 2: the KERNEL (headless Python, services/trader/training/)                           │
            │  mutate strategy → backtest on real data → eval through the FORTRESS → record → promote-if-best  │
            └────────────────────────────────────────────┬──────────────────────────────────────────────────┘
                                                         │ uses
        Phase 1 data/features/regime/backtest   ·   Phase 2 walls + gates   ·   Hindsight knowledge   ·   git registry
```

The **kernel is substrate-independent** — plain Python that runs with no LLM and no agent. The **fleet drives the kernel** with intelligence. This boundary *is* the substrate-portability surface: swap Hermes for anything and the kernel is untouched.

## 2. The critical interface — `eval.py` and the wall metadata contract

This is the one genuinely hard integration point and the kernel's core. The Phase-2 walls are **pure predicates over `EvaluationContext.metadata`** — they do not run backtests; the kernel must *populate* what they read:

| metadata key | Produced by the kernel | Consumed by |
|---|---|---|
| `trial_sharpes` | Sharpe of every mutation tried this campaign | Wall 1 DSR |
| `trial_returns_matrix` | (T × N) returns of all trials | Wall 1 PBO |
| `num_trials` | cumulative mutation count (multiple-testing) | Wall 1 DSR, Wall 4 budget |
| `perturbed_sharpes` | Sharpe under ±10/20 % parameter perturbation (re-backtests) | Wall 2 sensitivity |
| `rolling_sharpes` | per-rolling-window Sharpe | Wall 2 stability |
| `oos_sharpes` | walk-forward out-of-sample fold Sharpes | Wall 3 |
| `per_regime_sharpes` | Sharpe per Phase-1 regime label | Wall 3 |
| `num_params` | strategy parameter count | Wall 2 MDL |

`eval.py(strategy, params, campaign_state) → GateSystemReport` builds this metadata (running the Phase-1 engine for the perturbations/folds), then calls `GateSystem.evaluate(ctx)`. **The Phase-2 calibration already proves the gate side works on real SPY; the kernel's job is to feed it.**

## 3. Delivery layers (each independently runnable)

### Layer 1 — Runnable headless kernel (the minimum that "starts training")

The lean 4-piece loop. **No LLM, no agents** — mutation is *mechanical* (parameter search over a strategy template). Proves the loop + fortress integration end-to-end on real SPY with zero nondeterminism.

1. **`strategy_template.py`** — a parametrized strategy + a fixed mutation surface (constants + the body of `signal()`/`position_size()`). Seeded with the SMA/timing family we already calibrated against.
2. **`eval.py`** — §2: populate the wall metadata contract + run the `GateSystem`.
3. **`loop.py`** — mechanical mutate → eval → record; keep the best (beats-master test).
4. **results store** — every iteration (kept + discarded, with reason) to Postgres `experiments.iterations`; promoted strategies to the git registry with provenance.

**Layer-1 exit:** the loop runs unattended, produces ≥N candidates on real SPY, records all of them, and promotes only fortress-passing ones — a real (if mechanical) training run. *This is the milestone that lets the operator "start training."*

### Layer 2 — LLM-driven mutation (the system starts to *reason*)

Swap the mechanical mutator for an **LLM Hunter** (via LiteLLM → Nemotron): it proposes a single-change mutation, the kernel runs it through the *same* eval/record/promote path. Add the **strategy-template safety rails** (mutation surface constrained; bad mutations can't break the backtester). The loop now explores intelligently.

**Layer-2 exit:** LLM-proposed mutations flow through the kernel; quality (improvement rate vs mechanical baseline) measured.

### Layer 3 — The research fleet + knowledge grounding (the full vision)

The seven Hermes subagents (per the seven-role amendment, re-grounded): Orchestrator cadence + Telegram `/halt`-`/resume`-`/status`; Planner/Reviewer hypothesis queue grounded in **Hindsight** forbidden-patterns; Researcher paper/web scout; Guardian veto via the fortress; **Archivist = Hindsight `retain()`/`reflect()`** (Experience→Observation→Mental-Model synthesis) + the canonical markdown notebook; Reporter fleet observability. Plus **compressed-history replay** (2018→vault boundary, PIT-clamped) and **vault-holdout validation**.

**Layer-3 exit (= original Phase-3 exit criteria, re-grounded):** seven subagents dispatch within Hermes permission scopes (CI guard); nightly cadence runs unattended 8h (≥50 iterations, ≥80 % within budget); race-on-promote safe (Postgres serializer); replay walks ≥3 years with no look-ahead leak; vault-holdout matches in-sample within tolerance; Hindsight recall <500 ms; Reporter `/status` <2 s.

## 4. Dependencies

- Phase 1 (data + features + regime + backtest engine) ✓
- Phase 2 (4 walls + 3 gates; the metadata contract; the `mahoraga-trader` calibration) ✓
- Hermes + Hindsight live and integrated (proven) ✓
- Phase-0 LLM-throughput measurement informs Layer-2/3 cadence sizing

## 5. Sub-features by layer

**Layer 1:** `strategy_template.py` · `eval.py` (+ metadata contract) · `loop.py` (mechanical) · `experiments.iterations` schema + writer · git registry + provenance · vault-holdout check
**Layer 2:** LLM-Hunter mutator (LiteLLM) · mutation-surface safety rails · improvement-rate metric
**Layer 3:** 7 Hermes subagent defs + permission CI guard · Orchestrator cadence + Telegram ops · Planner/Reviewer (Hindsight-grounded) · Researcher · Guardian (fortress veto) · Archivist (Hindsight retain/reflect + markdown notebook) · Reporter · `promote_pipeline`/`refresh_master`/`parse_metric` tools (ported from multiautoresearch) · compressed-history replay engine

## 6. Risks

- **LLM mutation quality** (too aggressive breaks the backtester / too timid = no exploration). Mitigated by Layer-1-first (mechanical baseline to beat) + constrained mutation surface.
- **Compressed-replay look-ahead leak.** PIT enforced at storage (Phase 1) + deliberate-leak canary.
- **Over-building the fleet before the loop runs.** Mitigated by the layering itself — Layer 1 must run before Layer 3 starts.
- **Hindsight/LLM cost under replay.** Batched retains, cadenced reflects, cheap-model entity extraction (per the Hindsight revision).
- **Substrate churn.** Kernel is substrate-independent; only Layer 3 touches Hermes.

## 7. Open questions

- Strategy-template mutation surface — how much to expose (constants only vs `signal()` body). Decide in the Layer-1 `strategy-template-spec.md`.
- `promote_pipeline` Postgres isolation level (serializable vs `SELECT … FOR UPDATE`). Decide before the Layer-3 race test.
- Hermes permission-scope expression (can Hermes subagent defs express per-role write/bash/task scopes as cleanly as the OpenClaw frontmatter assumed?). Resolve at Layer-3 start — a substrate-portability checkpoint.
- Mechanical mutator scope for Layer 1 (grid vs random vs simple hill-climb). Start simplest; the LLM replaces it in Layer 2.
