# Phase 3 — Autoresearch Loop Core Spec

**Status:** Approved 2026-04-26
**Type:** Phase-level spec
**Phase duration:** 13 weeks (largest phase — this is where the system learns to learn)
**Anchor specs:** [`2026-04-25-mahoraga-architecture-decomposition.md`](2026-04-25-mahoraga-architecture-decomposition.md), [`2026-04-25-nemoclaw-autoresearch-integration.md`](2026-04-25-nemoclaw-autoresearch-integration.md)
**Predecessor:** Phases 1 + 2

---

## 1. Goal

Bring the **two-brain autoresearch system online**: Hunter, Guardian, Archivist running as always-on agents under NemoClaw, driving the loop kernel through nightly cadence and compressed-history replay. By Phase 3 exit, the system is autonomously promoting strategies to a populated KB and a versioned registry, with vault validation passing. **This is where most of our energy goes** — it's the heart of Mahoraga.

## 2. Major Sub-Features

Each will get its own SDD feature spec:

1. **Hunter agent service** — LLM-driven mutation proposer; consumes KB context from Archivist; publishes `strategy-proposals`; subscribes to `risk-vetoes`, `execution-results`, `halt`.
2. **Guardian agent service** — vetoes proposals using `synthetic-data` and Phase 2 walls/gates; publishes `risk-vetoes`; can publish `halt` on catastrophic-loss trip.
3. **Archivist agent service** — KB Level promotion (Level-1 → Level-2 weekly; Level-2 → Level-3 monthly); builds prompt-context packs surfacing forbidden patterns and recent successes.
4. **Loop kernel** (`training/loop.py`) — implements `autoresearch_iteration()` per integration spec §6.4; supports nightly, weekend, and replay cadences.
5. **`strategy_template.py` contract** — `Strategy` Protocol per integration spec §6.2; mutation surface fixed (constants + body of `signal()` and `position_size()`).
6. **`eval.py`** — produces `FitnessReport` integrating Phase 2 walls + 3 gates.
7. **Compressed-history replay engine** — walks 2018 → vault boundary at PIT-clamped timestamps; same kernel as nightly cadence with `point_in_time` cursor.
8. **KB Level-1 storage + retrieval** — Postgres `knowledge.experiments` populated every iteration (kept and discarded both); pgvector embeddings for similarity search; <500ms query latency target.
9. **Git strategy registry** — only promoted strategies committed to `strategies/<id>/strategy.py` on `main`; each commit message includes parent strategy ID, mutation diff hash, FitnessReport hash, KB iteration ID.
10. **Vault validation framework** — strategies promoted from training data are evaluated on the 6-month vault holdout before being marked deployment-eligible.

## 3. Exit Criteria

- All 3 always-on agents register with NemoClaw and exchange channel messages
- Nightly cadence runs unattended 8h: ≥50 iterations, ≥80% within budget, no crashes
- Discarded candidates appear in `knowledge.experiments` with `kept=false` + reason
- Promoted candidates appear as commits in registry with full provenance metadata
- Compressed-replay walks ≥3 historical years end-to-end with no look-ahead-bias detection failures
- Vault validation: a strategy promoted from training is evaluated on the 6-month vault holdout and matches in-sample within tolerance
- KB pgvector similarity search returns relevant prior experiments in <500ms

## 4. Dependencies

- Phase 1 (data + features + regime detector)
- Phase 2 (walls + 3 gates + synthetic-data)
- Phase 0 bootstrap LLM throughput measurement (informs cadence sizing)

## 5. Timeline & Sequencing — 13 weeks, 3 parallel streams converging in week 13

| Weeks | Stream A (Agents) | Stream B (Loop kernel) | Stream C (Replay + KB) |
|---|---|---|---|
| 1–2 | Agent boilerplate + NemoClaw registration (extends Phase 0 heartbeat pattern) | `loop.py` skeleton; `Strategy` contract; mutator primitives | KB Level-1 schema + pgvector setup |
| 3–4 | Hunter v1 (single-shot mutation, structured prompts) | `eval.py` wiring Phase 2 walls + gates | replay clock cursor + PIT enforcement |
| 5–6 | Guardian v1 (synthetic-data + walls + vetoes) | nightly cadence skeleton | compressed-replay end-to-end on 1 year |
| 7–8 | Archivist v1 (Level-1 → Level-2 weekly) | weekend cadence | replay across 3 years |
| 9–10 | Hunter v2 (KB context retrieval, multi-step mutation chains) | end-to-end loop with 3 cadences | git registry integration |
| 11 | full agent integration | unattended 8h test | vault validation framework |
| 12 | failure-mode testing (agent crash, LLM timeout, network drop) | budget tuning | vault-holdout pass |
| 13 | exit-criteria sign-off | exit-criteria sign-off | exit-criteria sign-off |

## 6. Phase-Specific Risks

- **Bootstrap LLM throughput insufficient.** Phase 0 measured it. If too low: cloud-tier upgrade, reduce experiments_per_day, or extend bootstrap wall-clock.
- **Compressed-replay look-ahead leak.** Mitigation: PIT enforced at storage layer (Phase 1); future-data-injection tests; deliberate-leak canary.
- **pgvector scaling.** Unlikely to hit limits in Phase 3 (~100K iterations). Monitor; revisit at ~50M entries.
- **LLM mutation quality.** Mutations may be too aggressive (break backtester) or too timid (no exploration). Mitigation: structured mutator primitives constrain surface; iterate on prompt design; track exploration-vs-exploitation metric.
- **Agent reasoning consistency under fallback.** Hunter's behavior may shift when LiteLLM falls back from Anthropic to OpenAI to local. Mitigation: prompts written provider-neutral; fallback paths tested in CI.
- **Strategy registry pollution.** Even with "only promoted" rule, ~50 commits/month is meaningful volume. Mitigation: commits go to a dedicated `strategy/<id>` branch namespace; only major version bumps go to main.

## 7. Open Questions for This Phase

- Hunter mutation rate (mutations/min) — empirical; tunable via cadence config.
- Guardian veto threshold severity — calibrated against Phase 2 known-good/known-bad; expect adjustment.
- Strategy registry tagging convention (`strategy/<id>/active` git tags vs branches). Decided early Phase 3.
- KB embedding model choice (local vs cloud) — affects retrieval cost. Decided in `kb-storage-spec.md` (a feature-level spec under Phase 3).
- Multi-step mutation chains in Hunter v2 — how many steps before we cut off? Empirical.
