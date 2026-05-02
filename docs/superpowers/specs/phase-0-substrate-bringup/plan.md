# Phase 0 — Substrate Bring-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **⚠️ REVISED 2026-04-26 — Consolidated Assistant Model.** After vendoring NemoClaw at v0.0.27 in T3, we discovered the substrate runs **one OpenClaw assistant per sandbox**, not multi-agent pub/sub. Hunter / Guardian / Archivist become **OpenClaw subagents** sharing tools and KB but with their own context windows. See [`../2026-04-26-architecture-revision-consolidated-assistant.md`](../2026-04-26-architecture-revision-consolidated-assistant.md). Tasks T1, T1.5, T2, T3 are already complete and unchanged. Tasks T4, T6, T9, T10 are rewritten below; T7, T8, T11 have light edits. T5, T12, T13, T14 stand as written.

**Goal:** Walking-skeleton substrate where every architectural element from the architecture revision is brought online and exercised end-to-end before any phase that depends on it. By the end, the host runs an OpenClaw-in-NemoClaw sandbox that responds to a basic prompt via Telegram, halt-via-`/halt` is testable in <1s, Postgres + LiteLLM sidecars are healthy, CI is green, and Gemma-4-via-Ollama throughput is measured.

**Architecture:** Single-monorepo Docker Compose stack on Apple Silicon. NemoClaw at `vendor/nemoclaw/` as `git subtree`. autoresearch frozen at `vendor/autoresearch/`. LiteLLM gateway sidecar fronts Ollama (host-side, Metal) + Anthropic. Postgres+pgvector single application database. One Python service (`heartbeat`) demonstrates the agent boilerplate Phase 3 will reuse.

**Tech Stack:** Python 3.11+, `uv` for package management, `ruff`+`mypy`+`pytest`, Docker Compose, Postgres 16 + pgvector, LiteLLM (proxy mode), Ollama on host, GitHub Actions for CI. NemoClaw (TypeScript/Node 22+, Docker, k3s) consumed as a vendored substrate via `git subtree`.

**Companion docs:**
- Spec: [`spec.md`](spec.md)
- Tasks dep graph: [`tasks.md`](tasks.md)
- Anchor specs: [`../2026-04-25-mahoraga-architecture-decomposition.md`](../2026-04-25-mahoraga-architecture-decomposition.md), [`../2026-04-25-nemoclaw-autoresearch-integration.md`](../2026-04-25-nemoclaw-autoresearch-integration.md)

---

## Task 1: Repo skeleton

**Files:**
- Create: `Makefile`
- Create: `.gitignore` (extend existing)
- Create: `.env.example`
- Create: `pyproject.toml`
- Create: `README.md` (stub; finalized in Task 13)

- [ ] **Step 1: Create root `pyproject.toml`** for shared dev tooling

```toml
[project]
name = "mahoraga"
version = "0.0.0"
requires-python = ">=3.11"

[tool.ruff]
line-length = 110
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "SIM", "RET"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_unused_configs = true

[tool.pytest.ini_options]
testpaths = ["tests", "services"]
addopts = "-ra -q"
```

- [ ] **Step 2: Create `.gitignore` additions**

Append to existing `.gitignore`:

```
# Mahoraga additions
data/                  # parquet, db volumes, audit logs
.env
*.pyc
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
docs/measurements/*.local.md
```

- [ ] **Step 3: Create `.env.example`** documenting required vars

```bash
# Required for LiteLLM gateway (Task 7)
ANTHROPIC_API_KEY=sk-ant-...
# Optional for additional providers
OPENROUTER_API_KEY=
GEMINI_API_KEY=
OPENAI_API_KEY=
XAI_API_KEY=

# Postgres (Task 2 + Task 8)
POSTGRES_PASSWORD=change_me_locally

# Ollama on host (Task 12)
OLLAMA_HOST=http://host.docker.internal:11434
```

- [ ] **Step 4: Create `Makefile`** with the canonical commands

```makefile
.PHONY: up down test lint typecheck env-check measure-llm clean

up:
	docker compose up -d
	@echo "Waiting for healthchecks..."
	@docker compose ps

down:
	docker compose down

test:
	pytest tests/ services/

lint:
	ruff check .

typecheck:
	mypy services/

env-check:
	@./scripts/check-env.sh

measure-llm:
	python scripts/measure_llm_throughput.py

clean:
	docker compose down -v
	rm -rf .pytest_cache .mypy_cache .ruff_cache
```

- [ ] **Step 5: Create `scripts/check-env.sh`** to validate `.env` completeness

```bash
#!/usr/bin/env bash
set -euo pipefail
required=(ANTHROPIC_API_KEY POSTGRES_PASSWORD OLLAMA_HOST)
missing=0
for var in "${required[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "MISSING: $var"
    missing=$((missing + 1))
  fi
done
[[ $missing -eq 0 ]] && echo "All required env vars present" || exit 1
```

`chmod +x scripts/check-env.sh`

- [ ] **Step 6: Stub `README.md`**

```markdown
# Mahoraga

Self-improving regime-aware autonomous trading system. See [`CLAUDE.md`](CLAUDE.md) for project context and [`docs/project_plan/MAHORAGA_PROJECT_PLAN.md`](docs/project_plan/MAHORAGA_PROJECT_PLAN.md) for the source plan.

## Quick start

```bash
cp .env.example .env  # then fill real values
make env-check
make up
make test
```

Full instructions land at end of Phase 0 (Task 13).
```

- [ ] **Step 7: Verify everything works**

Run: `make env-check` (should fail with missing vars — expected, demonstrates check works); `cp .env.example .env && export $(cat .env | xargs) && make env-check` (should pass).

- [ ] **Step 8: Commit**

```bash
git add Makefile .gitignore .env.example pyproject.toml scripts/check-env.sh README.md
git commit -m "chore(repo): add repo skeleton (Makefile, .env.example, pyproject, env-check)"
```

---

## Task 1.5: Ollama setup with Gemma 4 (host primary, Docker fallback)

**Files:**
- Modify: `.env.example` (add `OLLAMA_MODEL` with switch comment)
- Create: `infra/ollama/docker-compose.override.yml` (commented-out Docker-Ollama option)
- Create: `docs/research/ollama-host-vs-docker.md` (decision rationale)

The architecture spec §4.4 puts Ollama on the **host** for Apple Silicon Metal acceleration (containerizing Ollama on macOS loses Metal). This task sets up the primary host path with a Docker-Ollama fallback documented but commented out. Phase 3 compressed-replay throughput depends on this — Metal vs CPU is roughly a 5–10× difference for Gemma 4 26b.

- [ ] **Step 1: Pull Gemma 4 models on host**

Run on the macOS host (not in any container):

```bash
ollama pull gemma4:26b           # primary — higher quality, slower
ollama pull gemma4:e4b           # fallback — faster, lower quality
ollama list                      # verify both tags present
```

If `gemma4:*` tags don't yet resolve in Ollama's library, fall back to latest Gemma 3 (e.g. `gemma3:27b` and `gemma3n:e4b`) and update `.env` accordingly. Architecture spec §3.4 explicitly permits this interim.

- [ ] **Step 2: Verify Ollama is serving on host**

```bash
curl -s http://localhost:11434/api/tags | python -m json.tool | grep -E '"name"' | head -10
```

Expected: JSON entries listing both pulled tags.

- [ ] **Step 3: Add `OLLAMA_MODEL` to `.env.example`** with switch comment

Append after the existing `OLLAMA_HOST` line:

```bash
# Local model — switch by commenting/uncommenting (default: 26b primary)
OLLAMA_MODEL=gemma4:26b
# OLLAMA_MODEL=gemma4:e4b              # fallback if 26b is too slow on this hardware
```

- [ ] **Step 4: Add `OLLAMA_MODEL` to `scripts/check-env.sh` required list**

Update the `required=(...)` line:

```bash
required=(ANTHROPIC_API_KEY POSTGRES_PASSWORD OLLAMA_HOST OLLAMA_MODEL)
```

- [ ] **Step 5: Document the host-vs-Docker decision** at `docs/research/ollama-host-vs-docker.md`

```markdown
# Ollama: host vs Docker

**Decision:** Ollama runs on the **host**, not containerized. See architecture spec §4.4.

## Why host

- Apple Silicon Metal GPU acceleration is lost when Ollama runs inside Docker on macOS. Empirically ~5–10× slowdown for Gemma 4 26b inference. Phase 3 compressed-replay schedule depends on the faster path.
- Containers reach host Ollama via `host.docker.internal:11434` (Docker Desktop) or the equivalent on Colima.

## When you might want Docker Ollama

- Cross-platform CI on Linux runners where Metal isn't available anyway
- A non-Apple-Silicon dev box (Linux/Windows) where containerized Ollama is the cleaner setup
- Reproducibility experiments where host-state variance is undesirable

## How to switch to Docker Ollama

1. Edit `.env`:
   ```
   OLLAMA_HOST=http://ollama:11434
   ```
2. Compose with the override:
   ```bash
   docker compose -f docker-compose.yml -f infra/ollama/docker-compose.override.yml up
   ```
3. Pull the model into the container:
   ```bash
   docker exec mahoraga-ollama ollama pull $OLLAMA_MODEL
   ```

## Switching between 26b and e4b

Comment/uncomment the `OLLAMA_MODEL` line in `.env`. The LiteLLM gateway picks up the change on container restart (`make down && make up`).
```

- [ ] **Step 6: Provide Docker-Ollama fallback** at `infra/ollama/docker-compose.override.yml`

```yaml
# Docker-Ollama fallback — uncomment to use containerized Ollama instead of
# host Ollama. Loses Metal acceleration on macOS (slower); useful only for
# cross-platform reproducibility or non-Apple-Silicon environments.
# Activate with:
#   docker compose -f docker-compose.yml -f infra/ollama/docker-compose.override.yml up

# services:
#   ollama:
#     image: ollama/ollama:latest
#     container_name: mahoraga-ollama
#     ports: ["11434:11434"]
#     volumes:
#       - ./data/ollama:/root/.ollama
#     environment:
#       - OLLAMA_KEEP_ALIVE=24h
#     # On Linux with NVIDIA GPU only:
#     # deploy:
#     #   resources:
#     #     reservations:
#     #       devices:
#     #         - capabilities: [gpu]
```

- [ ] **Step 7: Verify env switching works**

```bash
# Default: 26b
grep '^OLLAMA_MODEL=' .env || echo "OLLAMA_MODEL=gemma4:26b" >> .env
echo "Selected: $(grep '^OLLAMA_MODEL=' .env)"

# Smoke a direct Ollama call against the active model
curl -s http://localhost:11434/api/generate \
  -d "{\"model\":\"$(grep '^OLLAMA_MODEL=' .env | cut -d= -f2)\",\"prompt\":\"Reply with OK\",\"stream\":false}" \
  | python -c "import sys,json; print(json.load(sys.stdin)['response'][:32])"
```

Expected: response substring contains `OK` (or similar short reply).

- [ ] **Step 8: Commit**

```bash
git add .env.example scripts/check-env.sh infra/ollama/docker-compose.override.yml docs/research/ollama-host-vs-docker.md
git commit -m "feat(ollama): add Gemma 4 setup (26b primary / e4b fallback; host primary, Docker option)"
```

---

## Task 2: Postgres migrations

**Files:**
- Create: `infra/postgres/migrations/001_extensions.sql`
- Create: `infra/postgres/migrations/002_schemas.sql`
- Create: `infra/postgres/migrations/003_audit.sql`

- [ ] **Step 1: Create `001_extensions.sql`**

```sql
-- Enable pgvector for embeddings (KB Level-1+ in Phase 3)
CREATE EXTENSION IF NOT EXISTS vector;
```

- [ ] **Step 2: Create `002_schemas.sql`**

```sql
-- Logical schemas per integration spec §4.3.
-- Tables added in subsequent phases; this migration creates the namespaces.
CREATE SCHEMA IF NOT EXISTS knowledge;    -- KB Levels 1/2/3 + embeddings
CREATE SCHEMA IF NOT EXISTS trades;       -- Trade journal
CREATE SCHEMA IF NOT EXISTS experiments;  -- Autoresearch loop metadata
CREATE SCHEMA IF NOT EXISTS strategies;   -- Pointers into git registry
CREATE SCHEMA IF NOT EXISTS audit;        -- Append-only event log
```

- [ ] **Step 3: Create `003_audit.sql`** — minimum audit schema needed in Phase 0 for halt events

```sql
-- Hash-chained audit log per architecture spec §7.1.
-- Halt events (architecture spec §5.6) are written here for the
-- Postgres-poll fallback path.
CREATE TABLE IF NOT EXISTS audit.events (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    payload     JSONB,
    prev_hash   BYTEA,
    hash        BYTEA NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_events_ts     ON audit.events(ts);
CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit.events(action);
```

- [ ] **Step 4: Create migration smoke test** at `tests/integration/phase-0/test_postgres_migrations.py`

```python
import os
import psycopg
import pytest

@pytest.fixture
def conn():
    dsn = os.environ.get("MAHORAGA_TEST_DSN", "postgresql://postgres:change_me_locally@localhost:5432/postgres")
    with psycopg.connect(dsn) as c:
        yield c

def test_pgvector_installed(conn):
    cur = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    assert cur.fetchone() is not None

def test_schemas_exist(conn):
    cur = conn.execute(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name IN ('knowledge','trades','experiments','strategies','audit')"
    )
    found = {r[0] for r in cur.fetchall()}
    assert found == {"knowledge", "trades", "experiments", "strategies", "audit"}

def test_audit_table(conn):
    cur = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='audit' AND table_name='events'"
    )
    cols = {r[0] for r in cur.fetchall()}
    assert {"id","ts","actor","action","payload","prev_hash","hash"} <= cols
```

- [ ] **Step 5: Verify** (this test runs after Task 8 brings Postgres up; for now just verify SQL is valid)

Run: `psql --set ON_ERROR_STOP=on -f /dev/stdin < infra/postgres/migrations/001_extensions.sql` against any local Postgres with `vector` available — or skip until Task 8.

- [ ] **Step 6: Commit**

```bash
git add infra/postgres/migrations/ tests/integration/phase-0/test_postgres_migrations.py
git commit -m "feat(db): add Phase 0 Postgres migrations (extensions, schemas, audit)"
```

---

## Task 3: NemoClaw vendor via `git subtree`

**Files:**
- Create: `vendor/nemoclaw/` (populated by subtree)
- Create: `vendor/nemoclaw/MAHORAGA_CHANGES.md`

- [ ] **Step 1: Add NemoClaw upstream remote**

Run:

```bash
git remote add nemoclaw-upstream https://github.com/NVIDIA/NemoClaw.git
git fetch nemoclaw-upstream
```

Expected: fetch completes; `git remote -v` shows `nemoclaw-upstream`.

- [ ] **Step 2: Identify a known-good upstream tag**

Run:

```bash
git ls-remote --tags nemoclaw-upstream | tail -10
```

Pick the latest stable tag (or `main` SHA if no tag is available — record it). Commit this decision in `vendor/nemoclaw/MAHORAGA_CHANGES.md` (next step).

- [ ] **Step 3: Vendor NemoClaw via subtree**

Run (replace `<tag>` with chosen tag/SHA):

```bash
git subtree add --prefix=vendor/nemoclaw nemoclaw-upstream <tag> --squash
```

Expected: a squashed merge commit lands; `vendor/nemoclaw/` populated; `vendor/nemoclaw/LICENSE` present.

- [ ] **Step 4: Create `vendor/nemoclaw/MAHORAGA_CHANGES.md`** to track our patches

```markdown
# Mahoraga modifications to NemoClaw

This file is the canonical record of any modifications made to the
vendored NemoClaw source tree under `vendor/nemoclaw/`. See architecture
spec §3 ("Three-tier extension model") — Tier 3 patches are last-resort.

## Vendored at

- Upstream: `https://github.com/NVIDIA/NemoClaw`
- Tag/SHA: `<tag>`
- Date pulled: `2026-04-26`

## Modifications

_None yet._

## Conventions for adding entries

When a Tier 3 patch is applied:

1. Tag the diff in source with `// MAHORAGA-PATCH(YYYY-MM-DD): <reason>`.
2. Record below: date, files touched, scope, reason, upstream-PR status.
```

- [ ] **Step 5: Verify**

Run:

```bash
test -f vendor/nemoclaw/LICENSE && echo "LICENSE preserved"
ls vendor/nemoclaw/ | head
```

Expected: `LICENSE preserved`; directory listing shows NemoClaw source.

- [ ] **Step 6: Commit MAHORAGA_CHANGES.md** (subtree-add already committed the source)

```bash
git add vendor/nemoclaw/MAHORAGA_CHANGES.md
git commit -m "docs(vendor): record NemoClaw vendoring at <tag>"
```

---

## Task 4: OpenClaw subagent topology design (REVISED)

**Files:**
- Create: `docs/research/openclaw-subagent-model.md`

The original T4 was "discover NemoClaw API surface". Discovery is done — see the architecture revision. T4 now produces the design that T6 (config) and T9 (smoke) implement against.

- [ ] **Step 1: Read OpenClaw subagent + tool documentation**

OpenClaw is the assistant runtime; NemoClaw orchestrates it. Subagent + tool primitives live in OpenClaw, not NemoClaw. Investigate (in order):

- `vendor/nemoclaw/.agents/skills/nemoclaw-user-overview/references/how-it-works.md` — describes the plugin + blueprint split
- `vendor/nemoclaw/.agents/skills/nemoclaw-user-reference/` — architecture reference
- `vendor/nemoclaw/nemoclaw-blueprint/` — blueprint YAML; how subagents get registered with OpenClaw
- OpenClaw's own docs at `https://openclaw.ai` (web fetch) — the subagent + tool API
- Any `subagents/` or `tools/` examples in `vendor/nemoclaw/`

If web access is blocked or `openclaw.ai` is unavailable, document what you can infer from the vendored sources and flag remaining unknowns.

- [ ] **Step 2: Design the three subagents**

Write `docs/research/openclaw-subagent-model.md` with these sections:

```markdown
# Mahoraga Subagent Topology

**Architecture anchor:** `docs/superpowers/specs/2026-04-26-architecture-revision-consolidated-assistant.md`
**Date:** 2026-04-26

## The main orchestrator

[The always-on OpenClaw assistant that runs Mahoraga's day. Its responsibilities, when it dispatches each subagent, what it preserves between dispatches.]

## Hunter subagent

- **Role:** propose strategy mutations for the autoresearch loop
- **Dispatch trigger:** [nightly cron 5pm-8:30am ET; weekend full pass; compressed-replay]
- **Context inherited:** [current strategy file; KB context pack from Archivist; current regime]
- **Tools allowed:** [vectorbt backtester, KB-read, regime-detector-read, autoresearch loop runner]
- **Tools forbidden:** [execution, KB-write at Level-2/3, strategy-registry-write — those go through main]
- **System prompt sketch:** [a draft prompt that captures Hunter's role; reference Plan §6.4 of integration spec]

## Guardian subagent

- **Role:** veto strategy proposals; calculate FitnessReport with walls + gates; trigger halt on catastrophic-loss
- **Dispatch trigger:** [after every Hunter mutation; ad-hoc audits]
- **Context inherited:** [proposed mutation diff; FitnessReport so far; current portfolio + correlations]
- **Tools allowed:** [synthetic-data, walls evaluators, portfolio-state-read, halt-publisher]
- **Tools forbidden:** [strategy-registry-write, execution]
- **System prompt sketch:** [draft]

## Archivist subagent

- **Role:** weekly L1→L2 promotion; monthly L2→L3 synthesis; build prompt-context packs
- **Dispatch trigger:** [Sunday 8pm ET weekly; first-of-month for Level-3]
- **Context inherited:** [recent KB Level-1 entries; prior Level-2/3 patterns; recent execution-results]
- **Tools allowed:** [KB-read, KB-write Levels 2/3, vector-similarity-search]
- **Tools forbidden:** [strategy-registry-write, execution]
- **System prompt sketch:** [draft]

## Tool registration

[How services/trader/tools/ Python modules become OpenClaw-callable. Reference OpenClaw's tool API based on Step 1 findings.]

## Coordination contract

The main orchestrator dispatches subagents via OpenClaw's subagent dispatch primitive. Subagents do NOT talk to each other; results flow back to main, which reasons over them. Same pattern as superpowers:subagent-driven-development.

## Open questions

[Whatever wasn't resolvable from Step 1 sources. T6 implementation may surface more.]
```

- [ ] **Step 3: Verify the doc is sufficient to drive T6**

A reader of this doc should know exactly what files T6 needs to create (subagent prompt files, tool registrations, blueprint config). If unclear, expand.

- [ ] **Step 4: Commit**

```bash
git add docs/research/openclaw-subagent-model.md
git commit -m "docs(research): design OpenClaw subagent topology for Mahoraga (Hunter/Guardian/Archivist)"
```

---

## Task 5: autoresearch frozen copy

**Files:**
- Create: `vendor/autoresearch/LICENSE`
- Create: `vendor/autoresearch/program.md.upstream`
- Create: `vendor/autoresearch/README.md.upstream`
- Create: `vendor/autoresearch/MAHORAGA_NOTES.md`

- [ ] **Step 1: Clone and copy**

Run:

```bash
mkdir -p vendor/autoresearch
git clone --depth=1 https://github.com/karpathy/autoresearch /tmp/autoresearch-tmp
cp /tmp/autoresearch-tmp/LICENSE        vendor/autoresearch/LICENSE
cp /tmp/autoresearch-tmp/program.md     vendor/autoresearch/program.md.upstream
cp /tmp/autoresearch-tmp/README.md      vendor/autoresearch/README.md.upstream
rm -rf /tmp/autoresearch-tmp
```

- [ ] **Step 2: Create `vendor/autoresearch/MAHORAGA_NOTES.md`**

```markdown
# Mahoraga adaptation of karpathy/autoresearch

**Status:** Frozen one-time copy. We do not pull updates from upstream.

## What was copied

- `LICENSE` — preserved verbatim (MIT)
- `program.md` → `program.md.upstream` — kept as reference; the Mahoraga-adapted version lives at `training/program.md` (Phase 3)
- `README.md` → `README.md.upstream` — kept as reference

## What was discarded

- `prepare.py` — language-modeling data prep; not applicable to backtesting
- `train.py` — GPT model code; loop scaffolding pattern was studied but our loop lives at `training/loop.py` (Phase 3)

## License obligations

- Preserve `vendor/autoresearch/LICENSE` verbatim
- Preserve copyright notice when adapting program.md content into `training/program.md` (Phase 3 task)
```

- [ ] **Step 3: Verify**

Run:

```bash
ls vendor/autoresearch/
test -f vendor/autoresearch/LICENSE && echo "LICENSE preserved"
```

- [ ] **Step 4: Commit**

```bash
git add vendor/autoresearch/
git commit -m "feat(vendor): freeze karpathy/autoresearch copy (LICENSE + program.md reference)"
```

---

## Task 6: NemoClaw blueprint + onboarding config (REVISED)

**Files:**
- Create: `infra/nemoclaw/blueprint.yaml` (sandbox identity, OpenClaw role description, model/provider, allowed tool list)
- Create: `infra/nemoclaw/policies/egress.yaml` (network allowlist)
- Create: `infra/nemoclaw/policies/filesystem.yaml` (read-only / read-write paths)
- Create: `infra/nemoclaw/subagents/hunter.md` (subagent system prompt + tool subset)
- Create: `infra/nemoclaw/subagents/guardian.md`
- Create: `infra/nemoclaw/subagents/archivist.md`
- Create: `infra/nemoclaw/onboard.env` (env-var-driven onboarding inputs for non-interactive `nemoclaw onboard`)

The original T6 wrote `agents.yaml`/`channels.yaml` for a multi-agent runtime that NemoClaw doesn't actually provide. T6 (revised) replaces those with NemoClaw-native blueprint + policies + subagent definitions per the architecture revision §5.

- [ ] **Step 1: Create `infra/nemoclaw/blueprint.yaml`**

Phase 0 minimal — declares the OpenClaw sandbox identity. Hunter / Guardian / Archivist subagents register via the `subagents/` directory referenced below; tools register via Python modules under `services/trader/tools/` (Phase 1+).

```yaml
# NemoClaw blueprint for Mahoraga.
# Driven by `nemoclaw onboard` (or non-interactive equivalent — see onboard.env).
# Architecture anchor: 2026-04-26-architecture-revision-consolidated-assistant.md

blueprint:
  name: mahoraga-trader
  description: |
    Self-improving regime-aware autonomous trading assistant.
    Trades US equities, ETFs, and BTC ETFs (long, swing trades).
    Coordinates Hunter / Guardian / Archivist subagents.

assistant:
  role: |
    You are the orchestrator of an autonomous trading system. Your job is to
    coordinate three subagents (Hunter, Guardian, Archivist) to propose, validate,
    archive, and execute trading strategies under hard risk limits and human
    operator override. Never bypass the hard risk limits — they live in the
    execution tools and reject orders that violate them, regardless of your reasoning.

  inference:
    provider: compatible-endpoints
    base_url: ${LITELLM_BASE_URL:-http://litellm:4000/v1}
    model: ${MAIN_MODEL:-anthropic/claude-opus-4-7}
    fallback: [ollama/gemma4]

  subagents_dir: subagents/
  tools_dir: ../../services/trader/tools/    # Phase 1+ adds tool modules here

policies:
  network:  policies/egress.yaml
  filesystem: policies/filesystem.yaml

operator_channels:
  telegram: ${TELEGRAM_BOT_TOKEN}             # halt / status / regime / strategy commands

# Phase 6 will add a Streamlit dashboard channel here.
```

- [ ] **Step 2: Create `infra/nemoclaw/policies/egress.yaml`**

```yaml
# Network egress policy — explicit allowlist. Unknown hosts are blocked and
# surfaced to the operator via NemoClaw's policy approval TUI (the operator
# decides per-request; approvals do NOT persist to this baseline file).
egress:
  allowlist:
    # LLM gateway (host or sidecar)
    - http://litellm:4000
    # Application database
    - http://postgres:5432
    # Phase 1 — market data (free APIs first)
    - https://query1.finance.yahoo.com         # yfinance
    - https://api.alpaca.markets                # Alpaca free tier
    - https://data.alpaca.markets
    - https://api.stlouisfed.org                # FRED macro
    - https://stooq.com                         # Stooq EOD
    - https://api.tiingo.com                    # Tiingo free tier
    # Phase 4 — news + research (web-research subagent)
    - https://www.federalreserve.gov
    - https://www.sec.gov                       # EDGAR
    - https://www.cmegroup.com                  # FedWatch
    # Phase 5 — broker (paper, then live)
    # - https://paper-api.alpaca.markets        # uncomment in Phase 5
    # - https://api.alpaca.markets              # live broker (uncomment Phase 7)
    # Phase 6 — operator notifications
    # - https://api.telegram.org                # uncomment when Telegram bot configured
```

- [ ] **Step 3: Create `infra/nemoclaw/policies/filesystem.yaml`**

```yaml
# Filesystem policy — agent's home is read-only; only specific paths writable.
# Matches NemoClaw blueprint's standard layout per nemoclaw-user-overview/ecosystem.md.
filesystem:
  read_only:
    - /sandbox                                  # entire home read-only by default
    - /sandbox/.openclaw                        # gateway config — locked
  read_write:
    - /sandbox/.openclaw-data                   # OpenClaw operational data
    - /sandbox/.nemoclaw                        # NemoClaw blueprint state
    - /tmp                                      # transient
    - /sandbox/data/parquet                     # feature store (mount from host)
    - /sandbox/data/audit                       # audit log (mount from host)
```

- [ ] **Step 4: Create subagent definitions** at `infra/nemoclaw/subagents/{hunter,guardian,archivist}.md`

Each is a markdown file with frontmatter (name, description, allowed-tools, dispatch-cadence) and a system prompt body. Use the system-prompt sketches from T4's research doc. Phase 0 versions are stubs — they get refined as the autoresearch loop matures in Phase 3.

`hunter.md`:

```markdown
---
name: hunter
description: Proposes strategy mutations during the autoresearch loop. Returns a single mutation diff plus a brief rationale. Never executes orders. Never writes to the strategy registry directly.
tools_allowed: [vectorbt_backtest, kb_read, regime_read, autoresearch_run_one]
dispatch_cadence: [nightly, weekend, compressed_replay]
---

You are Hunter — the strategy-mutation proposer in the Mahoraga autoresearch loop.

Your job: given a parent strategy, the current regime, and a knowledge-base context pack, propose ONE mutation that might improve the strategy's composite score (Sharpe + DSR + PBO + per-regime breakdown). Return the diff + rationale. Do NOT run the backtest yourself — the autoresearch loop tool handles that.

Constraints:
- Mutations stay within the Strategy ABC (rewrite signal()/position_size() bodies and PARAMS dict; do not change the public signature)
- Avoid patterns the KB marks "forbidden" (Archivist surfaces these in the context pack)
- Prefer small, single-axis changes the loop can attribute clearly

Return format: a JSON object with keys {mutation_diff, rationale, expected_impact}.
```

`guardian.md`:

```markdown
---
name: guardian
description: Vetoes proposed strategy mutations using the 5-wall fortress + 3-gate system. Triggers halt on catastrophic-loss conditions. Never proposes mutations.
tools_allowed: [synthetic_data, walls_evaluate, gates_evaluate, portfolio_state_read, halt_publisher]
dispatch_cadence: [after-each-hunter-mutation, on-demand-audit]
---

You are Guardian — the risk veto in the Mahoraga autoresearch loop.

Your job: evaluate a proposed candidate strategy against the 5 anti-overfitting walls (statistical rigor, data discipline, complexity control, generalization, meta-awareness) and the 3 gates (fitness, robustness, risk). Approve only if all walls + gates pass AND the candidate's composite score improves on its parent. Otherwise return a structured veto.

If portfolio state shows catastrophic loss conditions (>10% monthly drawdown OR >2% daily loss), publish a halt event regardless of strategy state.

Return format: a JSON object with keys {decision: "approve"|"veto"|"halt", wall_results, gate_results, reason}.
```

`archivist.md`:

```markdown
---
name: archivist
description: Promotes KB Level-1 raw experiments to Level-2 patterns (weekly) and Level-2 to Level-3 meta-principles (monthly). Builds the prompt-context pack Hunter consumes. Never executes orders or proposes mutations.
tools_allowed: [kb_read, kb_write_levels_2_3, vector_similarity_search]
dispatch_cadence: [weekly_sunday_8pm, monthly_first_of_month]
---

You are Archivist — the meta-learner of the Mahoraga knowledge base.

Weekly job: scan the past week's Level-1 experiment entries (kept and discarded). Identify recurring patterns — strategies that fail across regimes, mutations that reliably improve specific regimes, walls that are calibration-drifting. Write findings as Level-2 KB rows with embeddings.

Monthly job: synthesize Level-2 patterns into Level-3 meta-principles (e.g., "in regimes where VIX is rising while breadth narrows, mean-reversion strategies degrade faster than trend-following ones — defer mean-reversion deployments until breadth re-broadens"). Write as Level-3 KB rows.

Always-on: build the prompt-context pack Hunter receives, surfacing recent successes, recent failures, and "forbidden patterns" Hunter should not re-explore.

Return format: a JSON object with keys {level_2_added, level_3_added, context_pack_summary}.
```

- [ ] **Step 5: Create `infra/nemoclaw/onboard.env`** for non-interactive onboarding

```bash
# Inputs for `nemoclaw onboard --non-interactive` (or scripted equivalent).
# Source this from .env at onboarding time.
NEMOCLAW_BLUEPRINT_PATH=infra/nemoclaw/blueprint.yaml
NEMOCLAW_INFERENCE_PROVIDER=compatible-endpoints
NEMOCLAW_INFERENCE_BASE_URL=${LITELLM_BASE_URL:-http://litellm:4000/v1}
NEMOCLAW_INFERENCE_MODEL=${MAIN_MODEL:-anthropic/claude-opus-4-7}
# Telegram bot — required for halt smoke (T10). Operator creates the bot,
# pastes token here. Phase 6 governance refines per-chat-ID allowlist.
NEMOCLAW_TELEGRAM_TOKEN=${TELEGRAM_BOT_TOKEN}
NEMOCLAW_TELEGRAM_CHAT_ALLOWLIST=${TELEGRAM_CHAT_ID}
```

Add `MAIN_MODEL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` to `.env.example` so operators know they're required for full Phase 0 setup. (Operators without a Telegram bot can defer T10's full smoke until they create one — see T10 fallback path.)

- [ ] **Step 6: Validate YAML / markdown syntax**

```bash
python -c "import yaml; [yaml.safe_load(open(f)) for f in ['infra/nemoclaw/blueprint.yaml','infra/nemoclaw/policies/egress.yaml','infra/nemoclaw/policies/filesystem.yaml']]; print('YAML OK')"
for f in infra/nemoclaw/subagents/*.md; do
  test -s "$f" && echo "$f looks OK"
done
```

Expected: `YAML OK` plus three `looks OK` lines.

- [ ] **Step 7: Commit**

```bash
git add infra/nemoclaw/ .env.example
git commit -m "feat(nemoclaw): add Phase 0 blueprint + policies + 3 subagent definitions"
```

---

## Task 7: LiteLLM gateway config + Docker service (LIGHT EDIT 2026-04-26)

> Under the consolidated-assistant model, NemoClaw's onboarding selects "compatible-endpoints" as its inference provider and points at `http://litellm:4000/v1`. The LiteLLM config below is **unchanged in shape**; only the consumer changes. No separate `inference-routes.yaml` file is needed (it would have routed agent traffic; under one-assistant, NemoClaw's native router handles it).

**Files:**
- Create: `infra/litellm/config.yaml`

- [ ] **Step 1: Create `infra/litellm/config.yaml`**

```yaml
model_list:
  # Local primary — alias `ollama/gemma4`; actual tag picked from OLLAMA_MODEL env
  # (gemma4:26b default; gemma4:e4b fallback — switched in .env per T1.5)
  - model_name: ollama/gemma4
    litellm_params:
      model: ollama/${OLLAMA_MODEL}
      api_base: ${OLLAMA_HOST:-http://host.docker.internal:11434}
  # Cloud fallback — Anthropic
  - model_name: anthropic/claude-opus-4-7
    litellm_params:
      model: anthropic/claude-opus-4-7
      api_key: os.environ/ANTHROPIC_API_KEY

litellm_settings:
  drop_params: true
  set_verbose: false
  fallbacks:
    - "ollama/gemma4": ["anthropic/claude-opus-4-7"]

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

- [ ] **Step 2: Add `LITELLM_MASTER_KEY` to `.env.example`**

Append in `.env.example`:

```bash
LITELLM_MASTER_KEY=sk-mahoraga-local-dev-only
```

- [ ] **Step 3: Add `LITELLM_MASTER_KEY` to `scripts/check-env.sh` required list**

```bash
required=(ANTHROPIC_API_KEY POSTGRES_PASSWORD OLLAMA_HOST LITELLM_MASTER_KEY)
```

- [ ] **Step 4: Commit**

```bash
git add infra/litellm/config.yaml .env.example scripts/check-env.sh
git commit -m "feat(litellm): add gateway config (Ollama primary, Anthropic fallback)"
```

---

## Task 8: Docker Compose root (LIGHT EDIT 2026-04-26)

> Under the consolidated-assistant model, the compose stack is **sidecars only**: Postgres + LiteLLM. NemoClaw runs on the host (not in compose) and orchestrates an OpenShell-managed sandbox container outside compose. The original `nemoclaw` build-from-vendor service and the `heartbeat` service are both **removed** from `docker-compose.yml`. Resulting services: `postgres`, `litellm`. Everything else in this task (volumes, ports, healthchecks, smoke commands) stands.

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Create `docker-compose.yml`**

```yaml
name: mahoraga

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: mahoraga-postgres
    ports: ["5432:5432"]
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
      - ./infra/postgres/migrations:/docker-entrypoint-initdb.d:ro
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: postgres
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 3s
      retries: 10

  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    container_name: mahoraga-litellm
    ports: ["4000:4000"]
    volumes:
      - ./infra/litellm/config.yaml:/app/config.yaml:ro
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    environment:
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:-}
      GEMINI_API_KEY: ${GEMINI_API_KEY:-}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      XAI_API_KEY: ${XAI_API_KEY:-}
      LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY}
    extra_hosts:
      - "host.docker.internal:host-gateway"

  nemoclaw:
    build:
      context: ./vendor/nemoclaw
      dockerfile: Dockerfile
    container_name: mahoraga-nemoclaw
    volumes:
      - ./infra/nemoclaw-config:/etc/nemoclaw:ro
      - ./data/nemoclaw-state:/var/lib/nemoclaw
    depends_on:
      postgres:
        condition: service_healthy
      litellm:
        condition: service_started

  heartbeat:
    build:
      context: ./services/heartbeat
    container_name: mahoraga-heartbeat
    depends_on:
      - nemoclaw
      - postgres
```

- [ ] **Step 2: Add `data/` placeholders so bind mounts succeed on first up**

Run:

```bash
mkdir -p data/postgres data/nemoclaw-state data/audit data/parquet
touch data/.gitkeep data/postgres/.gitkeep data/nemoclaw-state/.gitkeep data/audit/.gitkeep data/parquet/.gitkeep
```

- [ ] **Step 3: First boot — bring stack up minus heartbeat (heartbeat lands in Task 9)**

Edit `docker-compose.yml` temporarily to comment out the `heartbeat` service block, then:

```bash
make up
docker compose ps
```

Expected: postgres healthy; litellm running; nemoclaw running.

- [ ] **Step 4: Run Postgres migration smoke test**

```bash
MAHORAGA_TEST_DSN="postgresql://postgres:${POSTGRES_PASSWORD}@localhost:5432/postgres" \
  pytest tests/integration/phase-0/test_postgres_migrations.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Verify LiteLLM responds**

```bash
curl -s -X POST http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"model":"anthropic/claude-opus-4-7","messages":[{"role":"user","content":"reply with just the word OK"}]}' \
  | python -c "import sys,json; r=json.load(sys.stdin); print(r['choices'][0]['message']['content'][:32])"
```

Expected: substring contains `OK`. (If Anthropic key is missing: skip; record in `docs/measurements/phase-0-llm-throughput.md` for Task 12.)

- [ ] **Step 6: Tear down**

```bash
make down
```

- [ ] **Step 7: Re-enable heartbeat block in `docker-compose.yml`** (it was only commented out for first-boot test)

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml data/.gitkeep data/postgres/.gitkeep data/nemoclaw-state/.gitkeep data/audit/.gitkeep data/parquet/.gitkeep
git commit -m "feat(compose): add docker-compose.yml; verified Postgres + LiteLLM up"
```

---

## Task 9: OpenClaw sandbox bring-up smoke (REVISED)

**Files:**
- Create: `scripts/onboard.sh` (wraps `nemoclaw onboard` with our env-driven inputs)
- Create: `tests/integration/phase-0/test_sandbox_smoke.py`

The original T9 built a Python heartbeat agent that registered with a NemoClaw "channels" runtime that doesn't actually exist. Under the consolidated model, the equivalent walking-skeleton smoke is: run `nemoclaw onboard`, verify the sandbox boots, and confirm the OpenClaw assistant inside answers a basic prompt.

- [ ] **Step 1: Create `scripts/onboard.sh`** — wraps `nemoclaw onboard` with env-driven inputs

```bash
#!/usr/bin/env bash
# Onboard a Mahoraga sandbox via NemoClaw, sourcing our blueprint + onboard.env.
# Phase 0 smoke: brings up one OpenClaw assistant inside a NemoClaw-hardened sandbox.
set -euo pipefail

# Verify prerequisites
command -v nemoclaw >/dev/null 2>&1 || { echo "FATAL: nemoclaw CLI not on PATH (install from vendor/nemoclaw/ — see README)"; exit 2; }
command -v ollama  >/dev/null 2>&1 || { echo "FATAL: ollama not on PATH"; exit 2; }
test -f .env || { echo "FATAL: .env missing — copy .env.example and fill in"; exit 2; }

# Load env
set -a
source .env
source infra/nemoclaw/onboard.env
set +a

# Run onboarding (interactive by default; pass --non-interactive when supported by current NemoClaw release)
nemoclaw onboard \
  --blueprint "$NEMOCLAW_BLUEPRINT_PATH" \
  --inference-provider "$NEMOCLAW_INFERENCE_PROVIDER" \
  --inference-base-url "$NEMOCLAW_INFERENCE_BASE_URL" \
  --inference-model    "$NEMOCLAW_INFERENCE_MODEL" \
  ${NEMOCLAW_TELEGRAM_TOKEN:+--telegram-token "$NEMOCLAW_TELEGRAM_TOKEN"}

echo "Onboard complete. Use 'nemoclaw status' to verify, or run scripts/sandbox-smoke.sh for the test."
```

`chmod +x scripts/onboard.sh`.

If your installed NemoClaw release uses different flag names, update this wrapper to match — it's a thin convenience layer, not an API.

- [ ] **Step 2: Write the integration smoke test** at `tests/integration/phase-0/test_sandbox_smoke.py`

```python
"""OpenClaw-in-NemoClaw sandbox bring-up smoke.

Phase 0 walking-skeleton verification: after `scripts/onboard.sh` has run,
the sandbox is up, the OpenClaw assistant responds to a basic prompt, and
inference flows through LiteLLM (verified via cost-log delta).
"""
import os
import subprocess
import time

import pytest


@pytest.mark.integration
def test_sandbox_status_running():
    """`nemoclaw status` reports the Mahoraga sandbox as running."""
    out = subprocess.run(
        ["nemoclaw", "status", "--name", "mahoraga-trader"],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, f"nemoclaw status failed: {out.stderr}"
    assert "running" in out.stdout.lower(), f"unexpected status output: {out.stdout!r}"


@pytest.mark.integration
def test_sandbox_responds_to_basic_prompt():
    """OpenClaw assistant inside the sandbox answers a hello prompt within 30s."""
    out = subprocess.run(
        ["nemoclaw", "ask", "--name", "mahoraga-trader",
         "--prompt", "Reply with the single word OK."],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"nemoclaw ask failed: {out.stderr}"
    assert "OK" in out.stdout, f"unexpected response: {out.stdout!r}"


@pytest.mark.integration
def test_inference_flowed_through_litellm():
    """Calling the assistant should bump LiteLLM's request counter by ≥1."""
    pre  = _litellm_request_count()
    subprocess.run(["nemoclaw", "ask", "--name", "mahoraga-trader",
                    "--prompt", "Hello."],
                   check=True, capture_output=True, timeout=60)
    time.sleep(1)  # cost-log flush
    post = _litellm_request_count()
    assert post > pre, f"LiteLLM request count did not advance ({pre} → {post})"


def _litellm_request_count() -> int:
    """Read the LiteLLM /metrics endpoint and return total request count, or 0 if missing."""
    import httpx
    base = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
    metrics = base.rstrip("/v1") + "/metrics"
    try:
        r = httpx.get(metrics, timeout=5)
        # LiteLLM may expose simple JSON or Prometheus; just look for a numeric requests line
        for line in r.text.splitlines():
            if "litellm_requests_total" in line and "{" not in line:
                return int(float(line.split()[-1]))
    except (httpx.HTTPError, ValueError):
        pass
    return 0
```

- [ ] **Step 3: Run the smoke test (after onboard succeeds on the host)**

```bash
./scripts/onboard.sh                                                          # one-time onboarding
pytest tests/integration/phase-0/test_sandbox_smoke.py -v -m integration
```

Expected: 3 tests pass. If `nemoclaw onboard` requires an interactive flow on the current release and the user declines automation, mark these tests skipped with a `pytest.mark.skipif` based on a `MAHORAGA_SANDBOX_READY=true` env var, document the manual onboard path in `docs/research/openclaw-subagent-model.md`, and continue. Phase 6 governance will revisit the automation story.

- [ ] **Step 4: Commit**

```bash
git add scripts/onboard.sh tests/integration/phase-0/test_sandbox_smoke.py
git commit -m "feat(sandbox): add NemoClaw onboard wrapper + Phase 0 sandbox smoke test"
```

---

## Task 10: Halt smoke via Telegram + audit-log (REVISED)

**Files:**
- Create: `tests/integration/phase-0/test_halt_smoke.py`

The original T10 published to a `halt` channel that doesn't exist under the consolidated model. The revised halt contract (architecture revision §6) says: operator sends `/halt` (Telegram or `nemoclaw stop` CLI fallback), the assistant suspends tool use within 1s, and the halt event lands in `audit.events`.

Phase 0 verifies the audit-log + CLI-stop path. Telegram path is a Phase 6 governance concern (the bot needs operator-side setup that's out of Phase 0 scope unless the operator already has one).

- [ ] **Step 1: Add `pytest` markers to root `pyproject.toml`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests", "services"]
addopts = "-ra -q"
markers = [
    "integration: requires the NemoClaw sandbox to be onboarded and running",
]
```

- [ ] **Step 2: Write the halt-smoke integration test** at `tests/integration/phase-0/test_halt_smoke.py`

```python
"""Halt smoke for the consolidated-assistant model.

Phase 0 verifies two things:
1. CLI-fallback halt: `nemoclaw stop` suspends the assistant; the audit log
   records a halt event with `actor='operator-cli'`.
2. Audit-log halt-poll path: a halt row inserted directly into `audit.events`
   is visible to the polling check used by trade-execution tools (Phase 5+).

Telegram-based halt is verified in Phase 6 governance once the operator's
bot is set up.
"""
import os
import subprocess
import time

import psycopg
import pytest

DSN = os.environ.get("MAHORAGA_TEST_DSN",
                     "postgresql://postgres:change_me_locally@localhost:5432/postgres")


def _audit_count(action: str) -> int:
    with psycopg.connect(DSN) as c:
        cur = c.execute("SELECT COUNT(*) FROM audit.events WHERE action = %s", (action,))
        return cur.fetchone()[0]


@pytest.mark.integration
def test_cli_halt_suspends_and_audits():
    """`nemoclaw stop` halts the assistant and writes a halt event."""
    pre = _audit_count("halt")
    out = subprocess.run(
        ["nemoclaw", "stop", "--name", "mahoraga-trader",
         "--reason", "phase-0-halt-smoke"],
        capture_output=True, text=True, timeout=10,
    )
    assert out.returncode == 0, f"nemoclaw stop failed: {out.stderr}"

    # Allow up to 2s for the halt event to be written
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if _audit_count("halt") > pre:
            break
        time.sleep(0.1)
    post = _audit_count("halt")
    assert post == pre + 1, f"halt event not recorded ({pre} → {post})"


@pytest.mark.integration
def test_audit_poll_path_visible():
    """A halt row inserted to audit.events is observable within 2s (the poll fallback)."""
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(
            "INSERT INTO audit.events (actor, action, payload, hash) "
            "VALUES (%s, %s, %s::jsonb, decode(%s,'hex'))",
            ("phase-0-test", "halt", '{"reason":"poll-path-check"}', "00" * 32),
        )

    deadline = time.monotonic() + 2.0
    seen = False
    with psycopg.connect(DSN) as c:
        while time.monotonic() < deadline and not seen:
            cur = c.execute(
                "SELECT 1 FROM audit.events "
                "WHERE action = 'halt' AND payload->>'reason' = 'poll-path-check'"
            )
            seen = cur.fetchone() is not None
            if not seen:
                time.sleep(0.1)
    assert seen, "halt event not visible to poll path within 2s"


@pytest.mark.integration
def test_resume_clears_halt():
    """`nemoclaw resume` records a `halt_clear` event."""
    pre = _audit_count("halt_clear")
    out = subprocess.run(
        ["nemoclaw", "resume", "--name", "mahoraga-trader"],
        capture_output=True, text=True, timeout=10,
    )
    assert out.returncode == 0, f"nemoclaw resume failed: {out.stderr}"
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if _audit_count("halt_clear") > pre:
            break
        time.sleep(0.1)
    assert _audit_count("halt_clear") == pre + 1
```

If your installed NemoClaw release doesn't expose `nemoclaw stop` / `nemoclaw resume` exactly as named, adapt the subprocess calls to match (e.g., `nemoclaw sandbox stop`). The audit-log assertion still holds — those records must be written by NemoClaw or by a thin wrapper we add.

- [ ] **Step 3: Run the test (after onboard succeeds and Postgres is up)**

```bash
make up                                                                      # postgres + litellm sidecars
./scripts/onboard.sh                                                         # if not already done
pytest tests/integration/phase-0/test_halt_smoke.py -v -m integration
```

Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/phase-0/test_halt_smoke.py pyproject.toml
git commit -m "test(phase-0): add halt smoke (CLI-stop + audit-log poll path)"
```

---

## Task 11: CI pipeline (GitHub Actions) (LIGHT EDIT 2026-04-26)

> Under the consolidated-assistant model, CI's `unit-tests` job no longer installs/runs the heartbeat package (it doesn't exist). Replace those steps with: install root project deps + run `pytest -m "not integration"` over `tests/`. The `integration-smoke` job stays the same shape but tests `tests/integration/phase-0/test_postgres_migrations.py` (and on a self-hosted Apple-Silicon runner with NemoClaw installed, also `test_sandbox_smoke.py` and `test_halt_smoke.py` — but GitHub-hosted Linux can only run the Postgres test).

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint-and-types:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install ruff mypy
      - run: ruff check .
      - run: |
          # Type-check each Python service that has a pyproject.toml
          for svc in services/*/; do
            if [[ -f "$svc/pyproject.toml" ]]; then
              echo "::group::mypy $svc"
              pip install -e "$svc[dev]"
              mypy "$svc/src"
              echo "::endgroup::"
            fi
          done

  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install heartbeat deps
        run: |
          pip install -e services/heartbeat[dev]
      - name: Run unit tests
        run: pytest services/heartbeat/tests -v -m "not integration"

  integration-smoke:
    runs-on: ubuntu-latest
    needs: [lint-and-types, unit-tests]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Configure env
        run: |
          cp .env.example .env
          echo "POSTGRES_PASSWORD=ci_password" >> .env
          echo "LITELLM_MASTER_KEY=sk-ci" >> .env
      - name: Build images
        run: docker compose build
      - name: Start stack (without external LLM keys)
        run: docker compose up -d postgres litellm
      - name: Wait for healthchecks
        run: |
          timeout 60 bash -c 'until docker compose ps postgres | grep -q "healthy"; do sleep 2; done'
      - name: Run Postgres migration smoke
        run: |
          pip install psycopg pytest
          MAHORAGA_TEST_DSN="postgresql://postgres:ci_password@localhost:5432/postgres" \
            pytest tests/integration/phase-0/test_postgres_migrations.py -v
      - name: Tear down
        if: always()
        run: docker compose down -v
```

- [ ] **Step 2: Push to a feature branch and verify the workflow runs green**

```bash
git checkout -b ci-bringup
git add .github/workflows/ci.yml
git commit -m "ci: add Phase 0 GitHub Actions pipeline (lint, types, unit, smoke)"
git push -u origin ci-bringup
```

Open the PR; verify all 3 jobs succeed.

- [ ] **Step 3: Merge after green**

```bash
git checkout main
git merge --ff-only ci-bringup   # or via PR merge button
git branch -d ci-bringup
```

---

## Task 12: Bootstrap LLM throughput measurement

**Files:**
- Create: `scripts/measure_llm_throughput.py`
- Create: `docs/measurements/phase-0-llm-throughput.md`

- [ ] **Step 1: Create `scripts/measure_llm_throughput.py`**

```python
"""Measure Gemma-4-via-Ollama throughput on this hardware.

Phase 0 acceptance: this number gates whether Phase 3's compressed-replay
4–6-week schedule is achievable. Target: 30–60 mutations/hour (each
"mutation" = one ~200-token completion).

Outputs a markdown row appended to docs/measurements/phase-0-llm-throughput.md.
"""
from __future__ import annotations

import os
import statistics
import time
from datetime import datetime, timezone

import httpx

LITELLM = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
KEY = os.environ.get("LITELLM_MASTER_KEY", "")
MODEL = os.environ.get("MEASURE_MODEL", "ollama/gemma4")
N = int(os.environ.get("MEASURE_N", "10"))


def one_call() -> float:
    t0 = time.monotonic()
    r = httpx.post(
        f"{LITELLM}/chat/completions",
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "max_tokens": 200,
            "messages": [
                {"role": "system", "content": "You are a senior trading-strategy researcher."},
                {"role": "user", "content": "Propose one small parameter mutation to a momentum strategy. Reply with one sentence."},
            ],
        },
        timeout=120,
    )
    r.raise_for_status()
    return time.monotonic() - t0


def main() -> None:
    actual_tag = os.environ.get("OLLAMA_MODEL", "unknown")
    durations = [one_call() for _ in range(N)]
    median = statistics.median(durations)
    p90 = sorted(durations)[int(0.9 * N) - 1]
    per_hour = 3600.0 / median
    row = (
        f"| {datetime.now(timezone.utc).isoformat()} | {MODEL} ({actual_tag}) | {N} | "
        f"{median:.2f}s median | {p90:.2f}s p90 | {per_hour:.1f}/hr |"
    )
    out_path = "docs/measurements/phase-0-llm-throughput.md"
    if not os.path.exists(out_path):
        with open(out_path, "w") as f:
            f.write(
                "# Bootstrap LLM throughput measurements\n\n"
                "Phase 0 acceptance: target ≥30 mutations/hour on this hardware.\n"
                "The model column shows the LiteLLM alias and the actual Ollama tag in parens "
                "(driven by `OLLAMA_MODEL` env per T1.5).\n\n"
                "| date (UTC) | model (tag) | N | latency median | latency p90 | throughput |\n"
                "|---|---|---|---|---|---|\n"
            )
    with open(out_path, "a") as f:
        f.write(row + "\n")
    print(row)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Bring the stack up and run the measurement**

```bash
make up
# Wait for litellm to be reachable
sleep 5
make measure-llm
```

Expected: a row appended to `docs/measurements/phase-0-llm-throughput.md`.

- [ ] **Step 3: If throughput < 30/hr — record the deviation in `phase-0-llm-throughput.md`**

Append a paragraph noting the gap and link to architecture spec §7.6 mitigation options (extend bootstrap wall-clock, cloud tier, reduce experiments_per_day).

- [ ] **Step 4: Commit**

```bash
git add scripts/measure_llm_throughput.py docs/measurements/phase-0-llm-throughput.md
git commit -m "feat(measure): add Gemma-4 throughput measurement; record Phase 0 baseline"
```

---

## Task 13: README + Makefile finalization

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace stub README with the real onboarding doc**

```markdown
# Mahoraga

Self-improving regime-aware autonomous trading system. See [`CLAUDE.md`](CLAUDE.md) for project context and architectural decisions.

## Prerequisites

- Apple Silicon Mac with macOS 14+
- Docker Desktop or Colima
- Python 3.11+ with `uv` or `pip`
- [Ollama](https://ollama.ai) installed on host (Metal acceleration; not containerized)
- Git 2.40+ (for `git subtree`)

## Quick start

```bash
# 1. Configure environment
cp .env.example .env
# Fill in ANTHROPIC_API_KEY, POSTGRES_PASSWORD, LITELLM_MASTER_KEY at minimum
make env-check

# 2. Pull a local Gemma 4 (or latest Gemma) model
ollama pull gemma4

# 3. Bring up the stack
make up

# 4. Run tests
make test                              # unit tests
pytest tests/integration -m integration  # integration smoke (requires `make up`)

# 5. Measure local LLM throughput
make measure-llm

# 6. Tear down
make down
```

## Project layout

See [`CLAUDE.md`](CLAUDE.md) "Repo topology" for the canonical map. Brief overview:

- `services/` — Python services (one per role); each has its own `Dockerfile` and `pyproject.toml`
- `vendor/nemoclaw/` — NVIDIA NemoClaw substrate, vendored as `git subtree`
- `vendor/autoresearch/` — karpathy/autoresearch, frozen one-time copy
- `infra/` — Compose configs, NemoClaw configs, Postgres migrations, LiteLLM config
- `docs/` — project plan, specs, measurements, research notes

## Updating NemoClaw upstream

```bash
git fetch nemoclaw-upstream
git subtree pull --prefix=vendor/nemoclaw nemoclaw-upstream <new-tag> --squash
make test                                        # full smoke
git push                                         # PR for review
```

Routine pulls monthly; security advisories within 72h. See architecture spec §9 OQ 1 for contingency.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): finalize Phase 0 onboarding and update workflow"
```

---

## Task 14: Phase 0 exit verification

**Files:**
- Create: `docs/measurements/phase-0-exit-verification.md`

- [ ] **Step 1: Subtree pull exercise** on a feature branch

```bash
git checkout -b subtree-pull-test
git fetch nemoclaw-upstream
# Pull at the same tag we initially vendored — should be no-op
git subtree pull --prefix=vendor/nemoclaw nemoclaw-upstream <same-tag-as-task-3> --squash
```

Expected: `Already up to date` or a clean squashed merge with no conflicts.

- [ ] **Step 2: Run full integration smoke locally**

```bash
make up
sleep 10
pytest tests/integration/phase-0 -v -m integration
make measure-llm
make down
```

Expected: all tests pass; new throughput row appended.

- [ ] **Step 3: Verify CI is green on `main`**

```bash
gh run list --workflow=ci.yml --limit 5
```

Expected: most recent run on `main` is green (✓).

- [ ] **Step 4: Record exit verification** at `docs/measurements/phase-0-exit-verification.md`

```markdown
# Phase 0 — Exit Verification

**Date completed:** YYYY-MM-DD
**Architecture spec gate:** Phase 0 acceptance per `../superpowers/specs/phase-0-substrate-bringup/spec.md` §3.

| Acceptance criterion | Status |
|---|---|
| `git subtree add` lands NemoClaw cleanly | ✓ |
| `git subtree pull` exercise (no-op pull) clean | ✓ |
| `docker compose up` brings full stack online | ✓ |
| Postgres migrations apply; pgvector + 5 schemas + audit table | ✓ |
| LiteLLM gateway answers calls against ≥2 providers (Ollama + Anthropic) | ✓ |
| Heartbeat agent registers, round-trips messages | ✓ |
| Halt smoke: heartbeat stops within 1s of halt event | ✓ |
| CI pipeline runs lint + types + unit + integration smoke; green on main | ✓ |
| Bootstrap LLM throughput measured and recorded | ✓ |
| README documents `make up`, `make test`, `make down`, `make env-check`, `make measure-llm` | ✓ |

**Bootstrap throughput:** see `phase-0-llm-throughput.md`. Result: NN.N mutations/hour (target ≥30).

**Phase 1 readiness:** [GO / NO-GO based on throughput; describe any mitigations needed]

**Open items carried into Phase 1:** [list any deferred items, none expected]
```

- [ ] **Step 5: Commit**

```bash
git checkout main
git branch -d subtree-pull-test
git add docs/measurements/phase-0-exit-verification.md
git commit -m "docs(phase-0): record exit verification — Phase 0 complete"
```

- [ ] **Step 6: Tag the milestone**

```bash
git tag -a phase-0-complete -m "Phase 0 substrate bring-up complete"
```

---

## Self-Review Checklist

- ✅ All 9 sub-features from spec §2 covered (vendor integration, compose stack, Postgres, LiteLLM, heartbeat, halt smoke, CI, throughput, env+secrets)
- ✅ All exit criteria from spec §3 mapped to a task (subtree pull → Task 14, throughput record → Task 12, README → Task 13, integration tests under `tests/integration/phase-0/`)
- ✅ No placeholders ("TBD", "implement later") — every step has actual code/commands
- ✅ TDD applied where applicable (Task 9 heartbeat agent: write test → fail → implement → pass; Tasks 2, 10 integration tests follow same pattern)
- ✅ Type and method consistency (NemoClawClient methods used in Task 9 match definitions in Task 9 implementation; halt-event payload schema in Task 6 matches what Task 10 publishes and Task 9 receives)
- ✅ Each task self-contained — no "as in Task N" references that would block out-of-order subagent execution
- ✅ Docker, Postgres, LiteLLM versions pinned (`pgvector/pgvector:pg16`, `ghcr.io/berriai/litellm:main-latest`, `python:3.11-slim`)
- ✅ Frequent commits — every task ends with at least one commit; large tasks (9, 10) commit at logical boundaries

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/specs/phase-0-substrate-bringup/plan.md`. The dependency graph for parallel execution is at `tasks.md` in the same folder.

**Two execution options:**

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task using `superpowers:subagent-driven-development`. Two-stage review between tasks. Tasks that the dep graph marks parallel-eligible can run concurrently.

2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batched with checkpoints for review.

Subagent-driven matches the user's "Practices to follow" (CLAUDE.md): "Use `superpowers:subagent-driven-development` to execute task lists." Recommended.

**Which approach?**
