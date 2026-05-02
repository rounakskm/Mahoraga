# Phase 0 — Substrate Bring-Up Spec

**Status:** Approved 2026-04-26
**Type:** Phase-level spec (broad; per-feature SDD specs to follow during implementation)
**Phase duration:** 2 weeks
**Anchor specs:** [`../2026-04-25-mahoraga-architecture-decomposition.md`](../2026-04-25-mahoraga-architecture-decomposition.md), [`../2026-04-25-nemoclaw-autoresearch-integration.md`](../2026-04-25-nemoclaw-autoresearch-integration.md)
**Predecessor:** none — this is the first phase

---

## 1. Goal

Build the **walking skeleton**: every architectural element from the integration spec is brought online and exercised end-to-end before any phase that depends on it. Derisk substrate, vendor integration, database, LLM routing, channel pub/sub. By Phase 0 exit, we know the architecture works on this hardware before we start writing trading logic.

## 2. Major Sub-Features

Each will get its own SDD feature spec when its turn comes during implementation:

1. **Vendor integration** — `git subtree add` for NemoClaw at known-good tag; one-time copy-and-freeze for autoresearch; LICENSE preservation; `MAHORAGA_CHANGES.md` initialized empty.
2. **Docker Compose stack** — `docker-compose.yml` orchestrating NemoClaw + LiteLLM + Postgres+pgvector + agent/worker stubs; healthchecks; bind mounts under `data/`. Ollama runs on **host** (not in compose) for Metal acceleration.
3. **Postgres schemas + migrations** — `knowledge`, `trades`, `experiments`, `strategies`, `audit` schemas created via init scripts; pgvector extension installed; baseline indexes.
4. **LiteLLM gateway with ≥2 providers** — primary `ollama/gemma4:latest` (or fallback variant per Phase 0 throughput measurement); plus one cloud provider (Anthropic). Verify call shape, fallback chain, cache toggle.
5. **Heartbeat agent** — minimal Python service that registers with NemoClaw, subscribes to a `heartbeat` channel, round-trips a message every 30s. Establishes the agent boilerplate so Phase 3 agents can copy it.
6. **Halt-channel smoke** — heartbeat agent additionally subscribes to `halt`; integration test publishes a halt event and asserts subscriber stops within 1s. Validates the §5.6 halt contract early.
7. **CI pipeline** — GitHub Actions: lint (`ruff`), type-check (`mypy`), unit tests (`pytest`), integration smoke (compose up → heartbeat round-trip → halt smoke → compose down). Runs on every push and PR.
8. **Bootstrap LLM throughput measurement** — measure mutations/hour Gemma-4-via-Ollama achieves on this MacBook. Output is a single number, recorded in `docs/measurements/phase-0-llm-throughput.md`. Gates Phase 3 schedule.
9. **`.env.example` + secrets discipline** — document all env vars; `.env` gitignored; no real keys committed; `make env-check` validates required vars present.

## 3. Exit Criteria

In addition to integration spec §9 acceptance items 1–7:

- All 9 sub-features above are testable; tests live in `tests/integration/phase-0/`
- `git subtree pull` exercise on a feature branch completes with no merge conflicts
- Bootstrap LLM throughput number recorded
- README at repo root documents `make up`, `make test`, `make down`, `make env-check`
- All Phase 0 work merged to `main` via reviewed PRs (no direct pushes)

## 4. Dependencies

None. Pull NemoClaw at a current known-good tag; freeze autoresearch's copy.

## 5. Timeline & Sequencing

Two weeks; single feature flow because each step depends on the prior.

| Week | Workstream |
|---|---|
| 1 | Vendor integration → Docker compose up → Postgres migrations → LiteLLM gateway connected to Ollama + Anthropic |
| 2 | Heartbeat agent → halt smoke → CI pipeline → bootstrap LLM throughput measurement → README |

## 6. Phase-Specific Risks

- **NemoClaw alpha behavior.** Mitigation: pin to known-good tag; integration tests gate every subtree pull.
- **Apple Silicon Docker quirks.** Mitigation: documented Colima or Docker Desktop setup; smoke test on actual hardware.
- **Ollama Metal acceleration not visible to containers.** Mitigation: Ollama on host; containers reach it via `host.docker.internal:11434`.
- **Bootstrap LLM throughput too low for Phase 3 schedule.** Mitigation: this phase *measures* it; if too low, Phase 3 timeline is revised before starting.

## 7. Open Questions for This Phase

- Exact NemoClaw tag/SHA to vendor — decided at first `git subtree add` against current main.
- Initial Gemma 4 quantization (q4 vs q8) — driven by host RAM measurement.
- CI runner choice: GitHub-hosted Linux (fast feedback, cheap) vs self-hosted Apple Silicon Mac (faithful smoke). Likely Linux for unit tests, manual local Mac smoke before merging compose changes.
