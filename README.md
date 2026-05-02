# Mahoraga

Self-improving regime-aware autonomous trading system. See [`CLAUDE.md`](CLAUDE.md) for project context and architectural decisions, [`docs/superpowers/specs/`](docs/superpowers/specs/) for the navigable spec map.

## Prerequisites

- Apple Silicon Mac with macOS 14+ (also runs on Linux/WSL2 with caveats)
- Docker Desktop or Colima
- Python 3.11+ with `pip`
- Node.js 22.16+ (for NemoClaw CLI)
- [Ollama](https://ollama.ai) installed on host (Metal acceleration; not containerized)
- Git 2.40+ (for `git subtree`)

## Quick start

```bash
# 1. Configure environment
cp .env.example .env
# Fill in ANTHROPIC_API_KEY, POSTGRES_PASSWORD, LITELLM_MASTER_KEY, OLLAMA_MODEL,
# and (when ready) TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
make env-check

# 2. Pull a local Gemma 4 model on host (Metal acceleration)
ollama pull gemma4:26b
ollama pull gemma4:e4b      # fallback

# 3. Bring up the sidecars (Postgres + LiteLLM)
make up

# 4. Install NemoClaw CLI from the vendored tree
cd vendor/nemoclaw
npm install && npm link
cd ../..

# 5. Onboard the OpenClaw-in-NemoClaw sandbox
./scripts/onboard.sh

# 6. Run tests
make test                                                 # unit tests
pytest tests/integration/phase-0 -m integration -v        # integration smoke (requires sandbox up)

# 7. Measure local LLM throughput (records a row in docs/measurements/)
make measure-llm

# 8. Tear down
make down
```

## Project layout

See [`CLAUDE.md`](CLAUDE.md) "Repo topology" for the canonical map. Brief overview:

- `services/` — Python services (Phase 1+); per-role with own `Dockerfile` and `pyproject.toml`
- `vendor/nemoclaw/` — NVIDIA NemoClaw substrate, vendored as `git subtree` (currently `v0.0.27`)
- `vendor/autoresearch/` — karpathy/autoresearch, frozen one-time copy
- `infra/nemoclaw/` — blueprint + policies + subagent definitions (Hunter / Guardian / Archivist)
- `infra/litellm/` — LiteLLM gateway config
- `infra/postgres/migrations/` — Postgres + pgvector schemas (knowledge / trades / experiments / strategies / audit)
- `docs/` — project plan, specs, measurements, research notes

## Architecture in one paragraph

One always-on OpenClaw assistant runs inside one NemoClaw-hardened OpenShell sandbox. Hunter, Guardian, and Archivist are OpenClaw subagents — each in its own context window but sharing tools (vectorbt, Postgres KB, regime detector, LiteLLM gateway) and the audit log. The autoresearch loop is a tool the main assistant invokes nightly. LiteLLM provides multi-provider routing (Ollama-local Gemma 4 primary, plus Anthropic / Gemini / OpenRouter / OpenAI / Grok cloud). See [`docs/superpowers/specs/2026-04-26-architecture-revision-consolidated-assistant.md`](docs/superpowers/specs/2026-04-26-architecture-revision-consolidated-assistant.md) for the full picture.

## Updating NemoClaw upstream

```bash
git fetch nemoclaw-upstream
git subtree pull --prefix=vendor/nemoclaw nemoclaw-upstream <new-tag> --squash
make test                                                 # full smoke
git push                                                  # PR for review
```

Routine pulls monthly; security advisories within 72h. See [`vendor/nemoclaw/MAHORAGA_CHANGES.md`](vendor/nemoclaw/MAHORAGA_CHANGES.md) for vendoring history and [architecture spec §9 OQ 1](docs/superpowers/specs/2026-04-25-mahoraga-architecture-decomposition.md) for the abandonment-contingency plan.
