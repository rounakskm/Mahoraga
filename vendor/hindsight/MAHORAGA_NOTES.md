# Mahoraga adoption of vectorize-io/hindsight

This file is the canonical record of (a) how this vendored copy is tracked, (b) how Mahoraga uses Hindsight as the **memory / knowledge-base layer** for the entire project, and (c) every upstream pull we land.

See architecture revision [`docs/superpowers/specs/2026-05-03-hindsight-memory-layer-revision.md`](../../docs/superpowers/specs/2026-05-03-hindsight-memory-layer-revision.md) for the architectural posture (Hindsight replaces our planned hand-coded `knowledge.*` Postgres schemas; trade journal and audit hash-chain remain in our Postgres as system-of-record).

## Vendored at

- Upstream: `https://github.com/vectorize-io/hindsight`
- Tag: `v0.5.6`
- Commit SHA (peeled): `e9b187330ccd8ccf363a0acc8cf8696a8da7d828`
- Date pulled: `2026-05-03`
- License: **MIT** (Copyright 2025 Vectorize AI, Inc.)

## Why we adopted Hindsight

Mahoraga's planned three-level KB (architecture spec §3.5: L1 raw experiments / L2 patterns / L3 meta-principles) maps almost 1:1 onto Hindsight's four-tier memory model (World Facts / Experience Facts / Observations / Mental Models). Hindsight's auto-consolidation pipeline implements the L1→L2 promotion algorithm we'd otherwise hand-code in Archivist. In addition:

- **State-of-the-art on the LongMemEval benchmark** (independently reproduced by Virginia Tech Sanghani Center and The Washington Post)
- **PostgreSQL + pgvector backend** matches our existing stack
- **MIT license** — least restrictive of our vendors
- **First-party NemoClaw integration** ships in this tree at `hindsight-integrations/nemoclaw/`
- **Production-grade**: 11.8k stars, 1,220+ commits, used in production at Fortune 500 enterprises
- **MCP server, Python + Node SDK, Docker + Helm + embedded modes** — no surprises in deployment

## Vendoring discipline

This is a **live `git subtree`**, mirrored on the NemoClaw + tradingagents pattern. We pull updates monthly because Hindsight is actively maintained (52 tagged releases as of v0.5.6) and the team ships meaningful improvements each cycle.

- **Routine pulls:** monthly. Review release notes, run our integration smoke (Phase 3+ task), pull if green.
- **Pull command:**
  ```bash
  git fetch hindsight-upstream
  git subtree pull --prefix=vendor/hindsight hindsight-upstream <tag-or-sha> --squash
  ```
- **Push policy:** never automatic. Explicit `git subtree push` only if we ever upstream a fix.
- **Breaking-change watch:** the API surface (`retain` / `recall` / `reflect` + bank schema) may evolve pre-1.0. Pin to the tag our integration tests pass against; only advance after re-running smoke.

## License obligations (MIT)

- Preserve `vendor/hindsight/LICENSE` verbatim. Never delete.
- MIT requires: include the copyright notice and permission notice in all copies or substantial portions. We satisfy this by keeping the LICENSE in the subtree and propagating attribution into any direct copies of source files.
- For files we extract or adapt into `services/trader/`, include a header attribution block:
  ```python
  # Adapted for Mahoraga from vectorize-io/hindsight
  # Source: vendor/hindsight/<original/path.py>
  # Upstream commit: <SHA at time of extraction>
  # Modifications: <one-line summary>
  ```
- We do **not** plan to extract Hindsight source files. We use Hindsight as a **service** via its Python client — no source-level cherry-picks expected. If that ever changes, attribution discipline above kicks in.

## How Mahoraga uses Hindsight

### Deployment topology

Hindsight runs as a **sidecar service** in our Docker compose stack with its own Postgres+pgvector instance (separate from our trade-journal / audit Postgres for blast-radius isolation):

```
mahoraga-hindsight     ← Hindsight API (ghcr.io/vectorize-io/hindsight:v0.5.6)
mahoraga-hindsight-db  ← pgvector/pgvector:pg16 (separate volume: data/hindsight-db/)
mahoraga-postgres      ← our trade journal + audit (existing)
```

### Bank topology

A single shared memory bank, `mahoraga-trader`, with subagent role distinguished by metadata on retain calls:

| Bank | Purpose | Subagents accessing |
|---|---|---|
| `mahoraga-trader` | All knowledge: experiments, patterns, principles, news, sentiment, regime labels, web research, macro narratives | Main orchestrator (read+write), Hunter (read+write Experience Facts), Guardian (read+write Experience Facts), Archivist (read+write across all tiers + reflect), Web-Research (read+write World Facts + Mental Models) |

The bank's mission / directives / disposition (Hindsight bank-level config) is documented in the revision spec §3.

### What goes into Hindsight (the knowledge layer)

| Memory tier | Mahoraga content | When it lands |
|---|---|---|
| **World Facts** | Regime labels (MACRO/MESO/MICRO + confidence), news classifications (CRITICAL/MATERIAL/BACKGROUND), sentiment scores, FRED macro releases, SEC filings, Federal Reserve statements, CME FedWatch probabilities | Phase 1+ (regime detector); Phase 4 (news + macro) |
| **Experience Facts** | Every autoresearch iteration outcome (kept and discarded both): `{regime, parent_strategy_id, mutation_diff, fitness_report, kept, reason_if_discarded, ts}`. Every trade decision context. Reconciliation events. | Phase 3 (autoresearch loop); Phase 5 (trade decisions) |
| **Observations** (auto) | Auto-consolidated patterns Hindsight derives from Experience Facts — replaces our planned L2 schema | Phase 3+ (continuous; consolidated by Hindsight) |
| **Mental Models** | Curated meta-principles (e.g., "in regimes where VIX is rising while breadth narrows, mean-reversion strategies degrade faster"); macro narrative summaries (web-research output); operator-curated concerns | Phase 3 (Archivist L3 promotion); Phase 4 (web research); Phase 6 (operator curation) |

### What stays in our existing Postgres (system-of-record, not knowledge)

| Schema | Why it stays relational |
|---|---|
| `trades.*` | Regulatory + reconciliation needs ACID + exact tabular queries (e.g., "exact IBIT position on date X at time Y"). Hindsight retrieves by meaning, not exact relational state. |
| `audit.events` | Hash-chained immutable log for halt events + decision provenance. Hindsight consolidates and dedupes; we need the opposite (no consolidation, every event preserved verbatim). |
| `strategies.*` | Lifecycle pointers (active/standby/retired) into the git-versioned strategy registry. Relational state for current promotion, with provenance metadata referencing git tags. |

The previously-planned `knowledge` schema (Postgres migration `002_schemas.sql`) is **dropped** in migration `004_drop_knowledge_schema.sql`. Hindsight owns it.

### The three Hindsight operations and how each agent uses them

| Operation | Caller | When |
|---|---|---|
| `retain(bank, content, kind, metadata)` | data-ingest, Hunter, Guardian, news-classifier, web-research | After every iteration, news event, scenario test, web-research finding |
| `recall(bank, query, strategy)` | Hunter (KB context pack assembly), Guardian (failure-pattern lookup), main orchestrator (operator query routing) | Before any reasoning step that benefits from prior memory |
| `reflect(bank, query, mission, directives, disposition)` | Archivist (weekly L1→L2, monthly L2→L3), main orchestrator (deep questions like "what makes our strategies fail in rising-vol regimes?") | Cadenced or on-demand |

### NemoClaw integration ships first-party in this tree

`vendor/hindsight/hindsight-integrations/nemoclaw/` contains a documented integration we should follow. `vendor/hindsight/hindsight-docs/docs-integrations/nemoclaw.md` documents the recipe. Phase 3 implementation should start there, not from scratch.

## Cost discipline (compressed-replay LLM calls)

Hindsight uses LLM calls for entity extraction during `retain()` and for `reflect()`. During Phase 1–3 compressed-replay (thousands of iterations), this is real cost. **Mitigation, baked into Phase 3 spec:**

- Batch retain operations: queue iteration outcomes, flush in batches of N (configurable; default 50)
- Run `reflect()` only at end-of-day cadence boundaries during compressed-replay (not after every iteration)
- Use a cheap local model (Gemma 4 via LiteLLM) for entity extraction; reserve cloud LLMs for `reflect()` only
- Set per-day LLM budget cap; fail-open with logged warning if exceeded

## Subtree-pull log

| Date | Prior SHA | New SHA | Tag | Upstream summary | Mahoraga integration impact |
|---|---|---|---|---|---|
| 2026-05-03 | (initial) | `e9b18733` | v0.5.6 | Initial subtree-add | Adopting as memory layer for entire project |

## Modifications log (Tier-3 patches inside `vendor/hindsight/`)

We do not plan to modify the vendored tree; we use Hindsight as a service. If we ever need to patch (rare, same posture as NemoClaw §3 three-tier extension model):

1. Tag the diff with `// MAHORAGA-PATCH(YYYY-MM-DD): <reason>`.
2. Record below: date, files touched, scope, reason, upstream-PR status.

_No Tier-3 patches yet._

## Open questions (resolved at integration time, not blocking)

1. **Hindsight `embedded` mode vs API service.** v0.5.6 ships both `hindsight-embed` (in-process) and `hindsight-api` (service). Phase 3 implementation chooses. Default plan: API service for clean blast-radius isolation; revisit if cost/latency dictate embedded.
2. **Single bank vs per-role banks.** Default plan: single shared `mahoraga-trader` bank with role metadata. Revisit if cross-role contention or noisy retrieval pushes us to per-role banks.
3. **Mission / directives / disposition wording for the bank.** First draft in the revision spec §3; iterate during Phase 3 implementation as Hunter/Guardian/Archivist prompts are tuned.
4. **Cost cap during compressed-replay.** Set empirically once Phase 3 starts; LLM throughput measurement (Phase 0 T12) gives the upper bound.
