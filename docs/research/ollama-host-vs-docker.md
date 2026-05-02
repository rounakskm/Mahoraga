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
   # Either source .env first so $OLLAMA_MODEL reflects your current selection:
   source .env && docker exec mahoraga-ollama ollama pull "$OLLAMA_MODEL"
   # Or pull the explicit tag:
   docker exec mahoraga-ollama ollama pull gemma4:26b
   ```

## Switching between 26b and e4b

Comment/uncomment the `OLLAMA_MODEL` line in `.env`. The LiteLLM gateway picks up the change on container restart (`make down && make up`).

**If `gemma4:*` tags don't resolve in Ollama's library**, use `gemma3:27b` and `gemma3n:e4b` instead and update `.env` accordingly. Architecture spec §3.4 explicitly permits this interim until Gemma 4 lands in Ollama.

## Current model availability

- Gemma 4 26b and e4b models pulled successfully on 2026-04-26.
