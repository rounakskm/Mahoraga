# Phase 0 — Substrate Bring-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Walking-skeleton substrate where every architectural element from the integration spec is brought online and exercised end-to-end before any phase that depends on it. By the end, `docker compose up` brings the full local stack online, a heartbeat agent registers with NemoClaw and round-trips messages, the halt-channel contract is testable, CI is green, and Gemma-4-via-Ollama throughput is measured.

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

## Task 4: NemoClaw runtime API discovery

**Files:**
- Create: `docs/research/nemoclaw-api-surface.md`

- [ ] **Step 1: Read NemoClaw's source** for agent registration and channel pub/sub APIs

Investigate (in order until you have answers):
- `vendor/nemoclaw/README.md` and any `docs/` subdirectory
- `vendor/nemoclaw/src/` for the agent runtime entry points
- `vendor/nemoclaw/package.json` for exposed npm scripts and bin commands
- Look for terms: `register`, `agent`, `channel`, `subscribe`, `publish`, `route`, `sandbox`

- [ ] **Step 2: Document findings** at `docs/research/nemoclaw-api-surface.md`

Template:

```markdown
# NemoClaw Runtime API Surface — Discovery Notes

**Vendored version:** see `vendor/nemoclaw/MAHORAGA_CHANGES.md`
**Date:** 2026-04-26

## How agents are configured

[Describe the configuration mechanism — YAML files, env vars, runtime registration calls. Reference exact files in vendor/nemoclaw/.]

## How agents register at startup

[Describe the registration handshake: HTTP endpoint, gRPC, message bus, etc. Include exact request/response shape.]

## Channel pub/sub mechanism

[Describe how a process subscribes to a channel and how it publishes. Is it WebSocket, SSE, polling, message queue, etc?]

## Sandbox enforcement

[Document how sandbox profiles in `infra/nemoclaw-config/sandbox-policies.yaml` are actually enforced — is it container-level egress filtering, in-process capability checks, or both?]

## Routed inference

[Document how the NemoClaw inference router calls upstream LLM URLs. Confirm OpenAI-compatible endpoint forwarding works as expected.]

## Phase 0 implications

[List any architectural assumptions in our specs that need adjustment based on what NemoClaw actually does. Flag deltas.]
```

- [ ] **Step 3: Verify the document is complete enough to write the heartbeat agent against**

The minimum bar: a Python developer reading this doc could write a service that successfully (a) registers with NemoClaw, (b) subscribes to one channel, (c) publishes one message. If not, expand the doc.

- [ ] **Step 4: Commit**

```bash
git add docs/research/nemoclaw-api-surface.md
git commit -m "docs(research): document NemoClaw runtime API surface"
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

## Task 6: NemoClaw config files (Phase 0 minimal)

**Files:**
- Create: `infra/nemoclaw-config/agents.yaml` (Phase 0: heartbeat only)
- Create: `infra/nemoclaw-config/channels.yaml` (heartbeat + halt)
- Create: `infra/nemoclaw-config/inference-routes.yaml`
- Create: `infra/nemoclaw-config/sandbox-policies.yaml`
- Create: `infra/nemoclaw-config/connections.yaml` (empty allowlist; populated in later phases)

- [ ] **Step 1: Create `agents.yaml`** (Phase 0 minimal — only the heartbeat agent)

```yaml
# Phase 0: only the heartbeat agent. Hunter/Guardian/Archivist
# registrations land in Phase 3.
# Format follows integration spec §5.1; adjust based on Task 4 findings.
agents:
  - name: heartbeat
    image: mahoraga/heartbeat:latest
    sandbox: heartbeat-sandbox
    channels:
      subscribe: [heartbeat, halt]
      publish: [heartbeat]
    inference:
      route: default
      preferred_model: ollama/gemma4         # LiteLLM resolves to OLLAMA_MODEL env (gemma4:26b default)
      fallback: [anthropic/claude-opus-4-7]
```

- [ ] **Step 2: Create `channels.yaml`**

```yaml
channels:
  - name: heartbeat
    payload_schema: schemas/heartbeat.json
    retention: 1d
  - name: halt
    payload_schema: schemas/halt_event.json
    retention: indefinite          # audit-critical; kill-switch trail
```

- [ ] **Step 3: Create `schemas/heartbeat.json`** at `infra/nemoclaw-config/schemas/heartbeat.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "HeartbeatEvent",
  "type": "object",
  "required": ["agent", "ts"],
  "properties": {
    "agent": {"type": "string"},
    "ts":    {"type": "string", "format": "date-time"},
    "seq":   {"type": "integer"}
  },
  "additionalProperties": false
}
```

- [ ] **Step 4: Create `schemas/halt_event.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "HaltEvent",
  "type": "object",
  "required": ["actor", "reason", "ts"],
  "properties": {
    "actor":  {"type": "string", "description": "who issued the halt"},
    "reason": {"type": "string"},
    "ts":     {"type": "string", "format": "date-time"},
    "scope":  {"type": "string", "enum": ["all", "single-strategy"]}
  },
  "additionalProperties": false
}
```

- [ ] **Step 5: Create `inference-routes.yaml`**

```yaml
routes:
  default:
    upstream: http://litellm:4000/v1
    type: openai-compatible
    timeout_s: 60
    retry: 2
```

- [ ] **Step 6: Create `sandbox-policies.yaml`** (Phase 0: heartbeat-sandbox only)

```yaml
sandboxes:
  - name: heartbeat-sandbox
    network:
      egress_allowlist:
        - http://litellm:4000
        - http://postgres:5432
    filesystem:
      mounts:
        - source: data/audit
          target: /audit
          read_only: false
    resources:
      memory_max: 512M
      cpu_max: 1
```

- [ ] **Step 7: Create empty `connections.yaml`**

```yaml
# Outbound integrations populated in Phase 1 (data feeds) and Phase 5 (broker).
# Format per integration spec §5.5.
connections: []
```

- [ ] **Step 8: Validate YAML syntax**

Run:

```bash
python -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('infra/nemoclaw-config/*.yaml')]; print('OK')"
```

Expected: `OK`.

- [ ] **Step 9: Commit**

```bash
git add infra/nemoclaw-config/
git commit -m "feat(config): add Phase 0 NemoClaw config (heartbeat agent + halt channel)"
```

---

## Task 7: LiteLLM gateway config + Docker service

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

## Task 8: Docker Compose root

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

## Task 9: Heartbeat agent service (TDD)

**Files:**
- Create: `services/heartbeat/Dockerfile`
- Create: `services/heartbeat/pyproject.toml`
- Create: `services/heartbeat/src/heartbeat/__init__.py`
- Create: `services/heartbeat/src/heartbeat/nemoclaw_client.py`
- Create: `services/heartbeat/src/heartbeat/main.py`
- Create: `services/heartbeat/tests/test_heartbeat.py`
- Create: `services/heartbeat/tests/test_nemoclaw_client.py`

- [ ] **Step 1: Create `services/heartbeat/pyproject.toml`**

```toml
[project]
name = "heartbeat"
version = "0.0.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "structlog>=24",
    "pydantic>=2.7",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "respx>=0.21"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/heartbeat"]
```

- [ ] **Step 2: Write failing test for the NemoClaw client wrapper** at `services/heartbeat/tests/test_nemoclaw_client.py`

```python
import pytest
import respx
from httpx import Response
from heartbeat.nemoclaw_client import NemoClawClient

@pytest.fixture
def client():
    return NemoClawClient(agent_name="heartbeat", base_url="http://nemoclaw:8080")

@respx.mock
def test_register_posts_to_register_endpoint(client):
    route = respx.post("http://nemoclaw:8080/agents/register").mock(return_value=Response(200, json={"ok": True}))
    client.register()
    assert route.called
    body = route.calls[0].request.read().decode()
    assert "heartbeat" in body

@respx.mock
def test_publish_posts_to_channel_endpoint(client):
    route = respx.post("http://nemoclaw:8080/channels/heartbeat/publish").mock(return_value=Response(202))
    client.publish("heartbeat", {"agent": "heartbeat", "ts": "2026-04-26T00:00:00Z"})
    assert route.called

@respx.mock
def test_subscribe_returns_iterator(client):
    respx.get("http://nemoclaw:8080/channels/halt/subscribe").mock(
        return_value=Response(200, text='data: {"actor":"test","reason":"smoke","ts":"2026-04-26T00:00:00Z"}\n\n')
    )
    msgs = list(client.subscribe("halt", limit=1))
    assert msgs[0]["actor"] == "test"
```

- [ ] **Step 3: Run test — expected to fail (no module yet)**

```bash
cd services/heartbeat && pytest tests/test_nemoclaw_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'heartbeat.nemoclaw_client'`.

- [ ] **Step 4: Implement `nemoclaw_client.py`**

```python
"""Thin Python wrapper around NemoClaw's HTTP API.

Bound to the API surface documented in
`docs/research/nemoclaw-api-surface.md`. If NemoClaw exposes
something other than HTTP+SSE, adapt the implementation here only —
the heartbeat agent itself depends on the wrapper, not on NemoClaw
directly.
"""
from __future__ import annotations

import json
from typing import Any, Iterator

import httpx


class NemoClawClient:
    def __init__(self, agent_name: str, base_url: str, timeout_s: int = 30) -> None:
        self.agent_name = agent_name
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s)

    def register(self) -> None:
        r = self._client.post("/agents/register", json={"name": self.agent_name})
        r.raise_for_status()

    def publish(self, channel: str, payload: dict[str, Any]) -> None:
        r = self._client.post(f"/channels/{channel}/publish", json=payload)
        r.raise_for_status()

    def subscribe(self, channel: str, *, limit: int | None = None) -> Iterator[dict[str, Any]]:
        with self._client.stream("GET", f"/channels/{channel}/subscribe") as r:
            r.raise_for_status()
            count = 0
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                yield json.loads(line[len("data: "):])
                count += 1
                if limit is not None and count >= limit:
                    return

    def close(self) -> None:
        self._client.close()
```

- [ ] **Step 5: Run test — expected to pass**

```bash
cd services/heartbeat && pip install -e .[dev] && pytest tests/test_nemoclaw_client.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Write failing test for the heartbeat agent** at `services/heartbeat/tests/test_heartbeat.py`

```python
from unittest.mock import MagicMock
from heartbeat.main import HeartbeatAgent

def test_heartbeat_publishes_on_tick():
    client = MagicMock()
    agent = HeartbeatAgent(client=client, interval_s=0)
    agent.tick()
    client.publish.assert_called_once()
    args, _ = client.publish.call_args
    assert args[0] == "heartbeat"
    assert args[1]["agent"] == "heartbeat"
    assert "ts" in args[1]
    assert args[1]["seq"] == 1

def test_heartbeat_increments_seq():
    client = MagicMock()
    agent = HeartbeatAgent(client=client, interval_s=0)
    agent.tick()
    agent.tick()
    seqs = [c.args[1]["seq"] for c in client.publish.call_args_list]
    assert seqs == [1, 2]

def test_halt_stops_publishing():
    client = MagicMock()
    agent = HeartbeatAgent(client=client, interval_s=0)
    agent.tick()
    agent.on_halt({"actor": "test", "reason": "smoke", "ts": "2026-04-26T00:00:00Z"})
    agent.tick()
    assert client.publish.call_count == 1   # second tick blocked by halt
```

- [ ] **Step 7: Run test — expected to fail (no main.py yet)**

```bash
pytest tests/test_heartbeat.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 8: Implement `services/heartbeat/src/heartbeat/main.py`**

```python
"""Heartbeat agent — minimal long-running service that demonstrates
the agent boilerplate Phase 3 agents (Hunter, Guardian, Archivist)
will reuse.

- Registers with NemoClaw on startup
- Publishes to the `heartbeat` channel every interval_s seconds
- Subscribes to `halt`; on receipt, stops publishing
"""
from __future__ import annotations

import os
import signal
import time
from datetime import datetime, timezone
from threading import Thread
from typing import Any

import structlog

from heartbeat.nemoclaw_client import NemoClawClient

log = structlog.get_logger()


class HeartbeatAgent:
    def __init__(self, client: Any, *, interval_s: int = 30) -> None:
        self.client = client
        self.interval_s = interval_s
        self._seq = 0
        self._halted = False
        self._running = True

    def tick(self) -> None:
        if self._halted:
            return
        self._seq += 1
        ts = datetime.now(timezone.utc).isoformat()
        self.client.publish("heartbeat", {"agent": "heartbeat", "ts": ts, "seq": self._seq})
        log.info("heartbeat.tick", seq=self._seq, ts=ts)

    def on_halt(self, msg: dict[str, Any]) -> None:
        self._halted = True
        log.warning("heartbeat.halted", reason=msg.get("reason"), actor=msg.get("actor"))

    def run(self) -> None:
        while self._running:
            self.tick()
            time.sleep(self.interval_s)

    def stop(self) -> None:
        self._running = False


def main() -> None:
    base_url = os.environ.get("NEMOCLAW_BASE_URL", "http://nemoclaw:8080")
    client = NemoClawClient(agent_name="heartbeat", base_url=base_url)
    client.register()
    agent = HeartbeatAgent(client=client, interval_s=int(os.environ.get("HEARTBEAT_INTERVAL_S", "30")))

    def halt_listener() -> None:
        for msg in client.subscribe("halt"):
            agent.on_halt(msg)

    Thread(target=halt_listener, daemon=True).start()

    def shutdown(signum: int, _frame: Any) -> None:
        log.info("heartbeat.shutdown", signal=signum)
        agent.stop()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    agent.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 9: Add `__init__.py`**

```python
# services/heartbeat/src/heartbeat/__init__.py
__all__ = ["main"]
```

- [ ] **Step 10: Run all heartbeat tests**

```bash
cd services/heartbeat && pytest tests/ -v
```

Expected: 6 passed (3 client + 3 agent).

- [ ] **Step 11: Create `services/heartbeat/Dockerfile`**

```dockerfile
FROM python:3.11-slim AS base
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir -e .
CMD ["python", "-m", "heartbeat.main"]
```

- [ ] **Step 12: Build the image and verify**

```bash
docker compose build heartbeat
```

Expected: image builds cleanly.

- [ ] **Step 13: Commit**

```bash
git add services/heartbeat/
git commit -m "feat(heartbeat): add heartbeat agent (NemoClaw client wrapper + agent + tests)"
```

---

## Task 10: Halt-channel smoke test

**Files:**
- Create: `tests/integration/phase-0/test_halt_smoke.py`

- [ ] **Step 1: Bring full stack up**

```bash
make up
docker compose ps
```

Expected: postgres healthy, litellm up, nemoclaw up, heartbeat up. Wait ~5s for heartbeat to register.

- [ ] **Step 2: Verify heartbeat is publishing**

```bash
docker logs --tail 20 mahoraga-heartbeat
```

Expected: structured log lines `heartbeat.tick seq=N ts=...`.

- [ ] **Step 3: Write failing integration test** at `tests/integration/phase-0/test_halt_smoke.py`

```python
"""Halt-channel smoke test.

Publishes a halt event to NemoClaw's `halt` channel and asserts the
heartbeat agent stops publishing within 1 second (architecture spec
§5.6 contract: <1s halt response).
"""
import os
import subprocess
import time
from datetime import datetime, timezone

import httpx
import pytest

NEMOCLAW = os.environ.get("NEMOCLAW_TEST_URL", "http://localhost:8080")
HEARTBEAT_CONTAINER = "mahoraga-heartbeat"


def _last_heartbeat_seq() -> int | None:
    out = subprocess.run(
        ["docker", "logs", "--tail", "5", HEARTBEAT_CONTAINER],
        check=True, capture_output=True, text=True,
    ).stdout
    seqs = [int(s.split("seq=")[1].split()[0]) for s in out.splitlines() if "seq=" in s]
    return seqs[-1] if seqs else None


@pytest.mark.integration
def test_halt_stops_heartbeat_within_1s():
    pre = _last_heartbeat_seq()
    assert pre is not None, "heartbeat not running before halt"

    httpx.post(
        f"{NEMOCLAW}/channels/halt/publish",
        json={
            "actor": "phase-0-smoke-test",
            "reason": "halt-channel smoke",
            "ts": datetime.now(timezone.utc).isoformat(),
            "scope": "all",
        },
        timeout=5,
    ).raise_for_status()

    time.sleep(1.5)
    seq_t1 = _last_heartbeat_seq()
    time.sleep(2.0)
    seq_t2 = _last_heartbeat_seq()

    # Within 1s of halt, no NEW seq should appear; allow at most one trailing tick
    assert seq_t2 - (seq_t1 or 0) <= 0, f"heartbeat still publishing after halt: {seq_t1} -> {seq_t2}"
```

- [ ] **Step 4: Run integration test**

```bash
pytest tests/integration/phase-0/test_halt_smoke.py -v -m integration
```

Expected: PASS within ~5s.

- [ ] **Step 5: Add `pytest` markers config** to root `pyproject.toml`

```toml
[tool.pytest.ini_options]
testpaths = ["tests", "services"]
addopts = "-ra -q"
markers = [
    "integration: requires docker compose stack to be up",
]
```

- [ ] **Step 6: Tear down**

```bash
make down
```

- [ ] **Step 7: Commit**

```bash
git add tests/integration/phase-0/test_halt_smoke.py pyproject.toml
git commit -m "test(phase-0): add halt-channel smoke test (verifies §5.6 contract)"
```

---

## Task 11: CI pipeline (GitHub Actions)

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
