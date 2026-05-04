# Architecture Revision — Hindsight as the Memory / Knowledge Layer

**Status:** Approved 2026-05-03
**Type:** Architecture revision (supersedes parts of the original architecture decomposition + the Consolidated-Assistant revision in the storage / KB layer)
**Anchor specs (revised by this document):**
- [`2026-04-25-mahoraga-architecture-decomposition.md`](2026-04-25-mahoraga-architecture-decomposition.md) — §3.5 (Storage), §5.3 (Data contract), §6 (KB Level-1 acceptance criteria), §8 (Spec catalog) partially superseded
- [`2026-04-26-architecture-revision-consolidated-assistant.md`](2026-04-26-architecture-revision-consolidated-assistant.md) — §3 (Subagent topology) clarified; §11 (Vendor inventory) extended

**Discovery context:** While preparing Phase 1 (data foundation), we evaluated Hindsight (vectorize-io/hindsight, MIT, v0.5.6) as a potential memory layer. After deep analysis (separate notes at `vendor/hindsight/MAHORAGA_NOTES.md`), the decision was made to **adopt Hindsight as the canonical memory and knowledge layer for Mahoraga**, replacing our previously-planned hand-coded `knowledge.*` Postgres schemas and the Archivist's hand-coded L1→L2→L3 promotion logic.

This revision documents the shift, the new storage topology, and the per-phase implications.

---

## 1. What changed and why

### Original plan (architecture spec §3.5 + Phase 3 spec)

A hand-coded knowledge base in Postgres, with Mahoraga-implemented logic for:
- `knowledge.experiments` — Level-1 raw experiment outcomes (`{regime, parent_strategy_id, mutation_diff, fitness_report, kept, reason, embedding}`)
- `knowledge.patterns` — Level-2 weekly Archivist promotions
- `knowledge.principles` — Level-3 monthly meta-principle synthesis
- `knowledge.news` — News + classification + sentiment
- `knowledge.embeddings` — pgvector similarity index
- Archivist Python service implementing L1→L2 weekly extraction and L2→L3 monthly synthesis algorithms

Estimated effort: weeks of design + implementation in Phase 3, plus ongoing tuning of the consolidation algorithm.

### What Hindsight gives us out of the box

A research-backed memory system with state-of-the-art performance on the LongMemEval benchmark, four-tier semantic memory hierarchy that maps almost 1:1 onto our planned three levels:

| Mahoraga (planned hand-coded) | Hindsight (built-in) |
|---|---|
| `knowledge.experiments` (L1 raw) | **Experience Facts** — agent's actions and observations, automatically tagged with entities, time series, sparse+dense vectors |
| `knowledge.news`, regime labels | **World Facts** — objective external state |
| `knowledge.patterns` (L2 auto-extracted) | **Observations** — auto-consolidated, evidence-grounded beliefs with stable/strengthening/weakening/stale trend metadata |
| `knowledge.principles` (L3 monthly synthesis) | **Mental Models** — curated summaries; built via Hindsight `reflect()` |
| Custom embedding management | **Built-in** sparse + dense vector representations |
| Hand-coded L1→L2 consolidation | **TEMPR** auto-consolidation pipeline (Temporal + Entity + Metadata + Phrase + Relevance) |

**Net effect:** Archivist becomes a thin orchestrator that triggers Hindsight `reflect()` on cadence (weekly L2 promotion, monthly L3 synthesis) instead of implementing extraction algorithms from scratch. Phase 3 KB design + L2/L3 algorithm work largely disappears.

### Why this is the right call now

1. **State-of-the-art performance.** Independently reproduced by Virginia Tech Sanghani Center and The Washington Post on LongMemEval. The right metric for an agent that learns over years.
2. **MIT license** — least restrictive among our vendors; commercial product use unrestricted.
3. **Storage stack matches.** Hindsight runs on PostgreSQL + pgvector. No new infrastructure.
4. **First-party NemoClaw integration** ships at `vendor/hindsight/hindsight-integrations/nemoclaw/`.
5. **Production maturity.** v0.5.6, 11.8k stars, 1,220+ commits, used in production at Fortune 500 enterprises.
6. **Three operations align with our needs.** `retain()` for storing iteration outcomes, `recall()` for KB context packs, `reflect()` for Archivist-style synthesis.

## 2. The storage split — knowledge vs system-of-record

This revision draws an explicit boundary:

### Knowledge layer (Hindsight)

Everything that is "what we have learned" or "what is true about the world / our experience":

- All autoresearch iteration outcomes (kept and discarded both)
- All trade decision *contexts* (the reasoning, regime, signals, expected outcome — distinct from the trade itself)
- All news events with classification + sentiment
- All regime labels (MACRO/MESO/MICRO) with confidence
- All FRED / SEC / Fed / FedWatch macro signals
- All web-research findings + macro narrative summaries
- All Archivist-promoted patterns (Observations) and meta-principles (Mental Models)
- All operator-curated Mental Models

### System-of-record layer (Postgres, existing schemas)

Everything that is "exact transactional state" or "tamper-evident audit":

| Schema | Why it stays relational |
|---|---|
| `trades.*` (orders, fills, positions, pnl_daily) | Regulatory + reconciliation needs ACID + exact tabular queries (e.g., "exact IBIT position on 2026-04-15 at 10:23"). Hindsight retrieves by meaning, not exact relational state. |
| `audit.events` (hash-chained log) | Tamper-evident immutable trail for halt events + decision provenance. Hindsight consolidates and dedupes; we need the opposite (every event preserved verbatim). |
| `strategies.*` (registry pointers, lifecycle) | Lifecycle state (active/standby/retired) into the git-versioned strategy registry. Relational state for current promotion, references git tags. |

### What gets dropped

The `knowledge` schema (Postgres migration `002_schemas.sql`) is unused under this revision. Migration `004_drop_knowledge_schema.sql` drops it cleanly.

The `experiments` schema's planned tables (`iterations`, `mutations`, `fitness_reports`) are also moot — these are Experience Facts in Hindsight. The `experiments` schema namespace is repurposed to hold thin operational state (last-cadence-run timestamps, queue depth metrics) if needed later; otherwise dropped in the same migration.

## 3. Bank topology and configuration

A **single shared memory bank** named `mahoraga-trader`. All subagents (Hunter, Guardian, Archivist, web-research, news-classifier) and the main orchestrator share access. Role-of-writer is captured in `metadata` on each `retain()` call so retrieval can filter by role when relevant.

### Bank configuration (per Hindsight's mission/directives/disposition model)

```yaml
# infra/hindsight/bank-mahoraga-trader.yaml — applied at Phase 3 setup time
name: mahoraga-trader

mission: |
  You are the long-term memory of Mahoraga, a self-improving regime-aware
  autonomous trading system for US equities, ETFs, and Bitcoin (via BTC ETFs).
  Your role is to retain every market observation, autoresearch experiment,
  trade decision context, and macro narrative, and to surface relevant memories
  when subagents reason about strategy mutation, risk veto, or knowledge
  synthesis. You are the substrate that makes year-over-year compounding
  intelligence possible.

directives:
  - Never surface memories that originated within the vault embargo window
    (last 6 months of historical data) when the requesting context is a
    training-mode call. Vault enforcement at the data-access boundary is
    primary; this is defense-in-depth.
  - Do not fabricate or hallucinate facts during reflect(). If memories
    contradict, surface the contradiction explicitly with evidence.
  - Tag every retain() call with the originating subagent role
    (hunter/guardian/archivist/main/web-research/news-classifier) and the
    cadence context (nightly/weekend/replay/live).
  - Treat hard risk limits (architecture spec §5.5) as facts about the
    execution boundary, not advisory; they are not subject to reflect()
    rationalization.

disposition:
  caution: 5            # max — bias toward surfacing contradictory evidence
  thoroughness: 5       # max — prefer completeness in recall over speed
  novelty_seeking: 3    # moderate — surface novel patterns but anchor in evidence
  conservatism: 4       # high — favor stable trends over latest data
  formality: 3          # moderate — structured outputs but readable rationale
```

The first three values are draft and will be tuned in Phase 3 once Hunter and Guardian prompts stabilize.

## 4. The three operations: how each subagent uses them

```
                     ┌─────────────────────────────────┐
                     │   mahoraga-trader (bank)        │
                     │                                  │
                     │  World Facts ─── Observations    │
                     │  Experience Facts ── Mental      │
                     │                       Models     │
                     └──┬───────────────┬──────────┬───┘
                        │ retain()      │ recall() │ reflect()
                        ▼               ▼          ▼
        ┌───────────────┴────┬──────────┴────┬─────┴──────┐
        Hunter (mutate)      Guardian (veto)  Archivist    Main
        retain on iter       recall failures  reflect L1→L2  recall
        recall context pack  retain veto      retain L3       on ops
                                              recall context  query
```

### Hunter (mutation proposer)

- **`retain()`**: at the END of each iteration (kept and discarded both) — Experience Fact `{regime, parent_strategy_id, mutation_diff, fitness_report, kept, reason, ts, role: "hunter", cadence: "nightly|weekend|replay"}`
- **`recall()`**: at the START of each iteration — query the bank for the KB context pack: recent successes / failures / forbidden patterns in the current regime
- **`reflect()`**: never (Hunter proposes; reflection is Archivist's job)

### Guardian (risk veto)

- **`retain()`**: after every veto decision — Experience Fact `{candidate_strategy, walls_results, gates_results, decision, reason, portfolio_state_snapshot, ts, role: "guardian"}`
- **`recall()`**: when evaluating a new candidate — query for similar past failures, regime crowding history, historical correlation patterns
- **`reflect()`**: rarely (only on demand if Archivist hasn't yet promoted a needed pattern)

### Archivist (KB consolidation orchestrator)

- **`retain()`**: occasionally — when the operator manually surfaces a curated insight
- **`recall()`**: when building prompt-context packs for Hunter
- **`reflect()`**: weekly (Sunday 8pm — promotes Experience Facts to Observations) and monthly (first business day — promotes Observations to Mental Models). Archivist becomes a thin scheduler around `reflect()`.

### Main orchestrator

- **`retain()`**: every halt event, every operator command, every escalation event
- **`recall()`**: when answering operator queries via Telegram (`/regime`, `/strategy <id>`, `/why-did-we-trade-X`)
- **`reflect()`**: rarely; mostly delegated to Archivist

### Web-research (Phase 4)

- **`retain()`**: every Sunday — World Facts (FRED data, SEC filings, Fed statements, FedWatch) + Mental Model (synthesized macro narrative)
- **`recall()`**: when building briefings — surface prior macro narratives and their accuracy

### News-classifier (Phase 4)

- **`retain()`**: every classified news event — World Fact `{ticker, classification, sentiment, source, ts, role: "news-classifier"}`
- **`recall()`**: rarely (sentiment-aggregator queries by ticker/window)

## 5. Cost discipline during compressed-replay

Hindsight uses LLM calls during `retain()` (entity extraction) and `reflect()` (synthesis). During Phase 1–3 compressed-replay, this is meaningful cost. Mitigations baked into Phase 3 spec amendment:

1. **Batched retains** — queue iteration outcomes; flush in batches (default `BATCH_SIZE=50`) to amortize entity extraction
2. **Cadenced reflect** — `reflect()` only at end-of-day cadence boundaries during compressed-replay, not per-iteration
3. **Cheap-model entity extraction** — point Hindsight's extraction-model config at `ollama/gemma4` (local, free, Metal-accelerated). Reserve cloud LLMs for `reflect()` only.
4. **Daily LLM budget cap** — fail-open with logged warning + skip non-essential retains if exceeded
5. **Phase 0 LLM throughput measurement** (T12 — already done) gives the empirical upper bound; Phase 3 cadence sizing flows from that

## 6. Deployment topology

Hindsight runs as a **sidecar service** in our existing Docker compose stack:

```yaml
services:
  hindsight:
    image: ghcr.io/vectorize-io/hindsight-api:v0.5.6
    container_name: mahoraga-hindsight
    ports: ["8080:8080"]
    depends_on:
      hindsight-db:
        condition: service_healthy
      litellm:
        condition: service_started
    environment:
      HINDSIGHT_DB_URL: postgres://hindsight:${HINDSIGHT_DB_PASSWORD}@hindsight-db:5432/hindsight
      HINDSIGHT_API_LLM_API_KEY: ${LITELLM_MASTER_KEY}
      HINDSIGHT_API_LLM_BASE_URL: http://litellm:4000/v1
      HINDSIGHT_API_LLM_MODEL: ollama/gemma4   # cheap model for entity extraction
      HINDSIGHT_API_REFLECT_MODEL: anthropic/claude-opus-4-7   # quality model for reflection

  hindsight-db:
    image: pgvector/pgvector:pg16
    container_name: mahoraga-hindsight-db
    volumes:
      - ./data/hindsight-db:/var/lib/postgresql/data
    environment:
      POSTGRES_PASSWORD: ${HINDSIGHT_DB_PASSWORD}
      POSTGRES_DB: hindsight
      POSTGRES_USER: hindsight
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U hindsight"]
      interval: 5s
```

Notes:

- **Separate Postgres** (`hindsight-db`) from our `postgres` (trades + audit). Blast-radius isolation: Hindsight outage cannot kill audit chain or trading state.
- **LLM calls flow through LiteLLM** — preserves multi-provider routing and cost tracking
- **Two-model split:** cheap model (`ollama/gemma4`) for high-frequency entity extraction during retain; quality model (Anthropic) for low-frequency reflect synthesis

## 7. What changes in existing specs

### Architecture decomposition spec (`2026-04-25-mahoraga-architecture-decomposition.md`)

| Section | Status |
|---|---|
| §3.5 Storage | **Partially superseded.** `knowledge.*` schema removed; replaced by Hindsight bank `mahoraga-trader`. `trades.*`, `audit.events`, `strategies.*` unchanged. |
| §4.3 Infrastructure sidecars | Add Hindsight + hindsight-db rows |
| §5.3 Data contract | Update KB references to point at Hindsight bank `mahoraga-trader` |
| §6 Phase 3 exit criteria | Reword "KB Level-1 populated" → "Hindsight `mahoraga-trader` bank populated with Experience Facts; Archivist `reflect()` cadence running" |
| §8 Spec catalog | This revision is added |

### Consolidated-Assistant revision (`2026-04-26-architecture-revision-consolidated-assistant.md`)

| Section | Status |
|---|---|
| §11 Vendor inventory | Extended with Hindsight row |
| §3 Subagent topology — KB references | Clarified: subagents share access to a single shared `mahoraga-trader` bank |

### Phase-level specs (amendment banners pointing here; full rewrites at phase entry)

- **Phase 1** — no change beyond data-ingest knowing it can write World Facts to Hindsight if the regime detector wants to memoize
- **Phase 3 (autoresearch loop core)** — meaningful amendment: KB Level-1 implementation drops; Archivist becomes Hindsight orchestrator. New work: `services/trader/tools/memory.py` wrapper around `hindsight_client`; cadenced `reflect()` driver. Saved work: full L1→L2 promotion algorithm.
- **Phase 4 (intelligence layer)** — news-classifier writes World Facts to Hindsight; web-research writes Mental Models. Sentiment aggregation queries Hindsight directly.
- **Phase 5 (paper trading)** — every order's *context* (reasoning, signals, regime) retained as Experience Fact. The order *itself* (transactional state) stays in `trades.*`.
- **Phase 6 (governance)** — operator can curate Mental Models manually via dashboard; convergence-report leverages Hindsight `reflect()` over months of trading history.
- **Phase 7 (live trading)** — same as Phase 5 with live broker; all operator queries (`/why-did-we-trade-X`, `/regime`) flow through Hindsight `recall()`.

## 8. Effort summary

| Bucket | Without Hindsight (hand-coded) | With Hindsight | Net savings |
|---|---|---|---|
| Phase 3 KB design + L1/L2/L3 schemas | 5–7 days | 0.5 day (Hindsight bank config + wrapper) | ~5 days |
| L1→L2 weekly promotion algorithm | 4–6 days | 0 (Hindsight auto-consolidation) | ~5 days |
| L2→L3 monthly synthesis algorithm | 3–5 days | 0.5 day (Archivist scheduler + prompt) | ~3 days |
| pgvector tuning + retrieval ranking | 3–4 days | 0 (TEMPR built-in) | ~3 days |
| Vendoring + revision (this work) | — | 1 day | -1 day |
| **Total** | **~17 days** | **~2 days** | **~15 days net** |

Plus the harder-to-quantify upside: **state-of-the-art retrieval for free**, **temporal reasoning out of the box**, **graph-based entity resolution we wouldn't have built**, and the **NemoClaw integration that ships first-party**.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Vendor risk — Vectorize.io is a startup | MIT license + 1,200+ commits + active community = forkable if needed; also they're a funded company with paying customers |
| LLM cost during compressed-replay | Batched retains, cadenced reflects, cheap-model extraction (see §5) |
| API breaking changes pre-1.0 | Pin to v0.5.6; advance only after smoke passes; quarterly subtree-pull review |
| Hindsight outage in production | Separate DB instance + service; trading still works via `trades.*` and hard-limit firewall (memory-recall failures degrade gracefully — agents fall back to "no prior memory") |
| Vault embargo not enforced inside Hindsight | Embargo enforced at the data-access boundary BEFORE retain calls (Phase 1 spec); Hindsight is downstream of vault checks |
| Cross-tenant memory leak (if we ever multi-tenant) | Single bank for now; Phase 8 multi-account would split banks. Out of scope until then. |
| Hindsight mission/directives drift | Bank config is YAML, version-controlled; changes go through PR review like any code change |

## 10. Verification — how we know each piece succeeds

| Step | Acceptance test |
|---|---|
| Vendoring complete | `vendor/hindsight/LICENSE` MIT preserved; `MAHORAGA_NOTES.md` cites pinned SHA + bank config + cherry-pick policy; CLAUDE.md updated |
| Hindsight service up | `docker compose up hindsight hindsight-db` succeeds; `curl http://localhost:8080/health` returns 200 |
| Bank initialized | `mahoraga-trader` bank exists with mission/directives/disposition applied; verified via Hindsight admin CLI |
| Smoke retain/recall | A test Experience Fact `retain()`-ed and successfully `recall()`-ed via the Python client |
| LLM routing through LiteLLM | Hindsight retain triggers a LiteLLM request log entry; reflect uses the Anthropic-tier model |
| `knowledge` schema dropped | Migration `004` applies cleanly; `\dn` in Postgres no longer lists `knowledge` |
| Phase 3 readiness | `services/trader/tools/memory.py` wrapper passes unit tests; Archivist scheduler test fires `reflect()` on cadence |
| Vault embargo defense in depth | Test injects future-dated content into a `retain()` call → blocked at the vault-check decorator before reaching Hindsight |
| Cost cap | A test bursting 1000 retain calls in 60s respects the configured per-day LLM budget cap |

## 11. Path forward (sequenced)

1. **Now (this PR):** Vendor + revision spec + CLAUDE.md updates + compose service stub + migration to drop `knowledge` schema. **No `services/trader/tools/memory.py` yet** (that lands in Phase 3 implementation).
2. **Phase 3 entry:** Detailed sub-feature spec for the memory wrapper + bank initialization + Archivist scheduler. Full integration tests against a live Hindsight container.
3. **Phase 4 entry:** News + sentiment + web-research write paths. Operator queries.
4. **Phase 6:** Operator dashboard surfaces recent Observations + Mental Models. Convergence-report uses Hindsight `reflect()`.
5. **Phase 7:** Live trade decisions retained; full memory-driven reasoning in production.
6. **Standing rule:** Any code that writes to Hindsight goes through `services/trader/tools/memory.py` (Phase 3+); no direct `hindsight_client` imports outside that wrapper. Substrate-portability practice applies.

## 12. Open questions resolved by this revision

- **KB Level-1 storage backend** → Hindsight Experience Facts (not `knowledge.experiments` Postgres table)
- **L1→L2 promotion algorithm** → Hindsight auto-consolidation (TEMPR pipeline)
- **L2→L3 synthesis algorithm** → Hindsight `reflect()` invoked by Archivist scheduler
- **News + sentiment storage** → Hindsight World Facts (not `knowledge.news` Postgres table)
- **Vector similarity search** → Hindsight TEMPR (not raw pgvector queries)

## 13. Open questions remaining (resolved during Phase 3 implementation)

1. **Per-role banks vs single shared bank.** Default: single shared. Revisit if cross-role retrieval contention appears.
2. **Mission/directives wording final tuning** once Hunter/Guardian/Archivist prompts stabilize
3. **Cost cap empirical value** — set after Phase 3 first compressed-replay test
4. **Embedded vs API-service mode** — default API service for blast-radius isolation; revisit if cost/latency dictate embedded
