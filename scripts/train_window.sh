#!/usr/bin/env bash
# Mahoraga TRAINING cadence — the other half of the conductor.
#
# Runs the seven-role autoresearch fleet WITH MEMORY on real SPY, which:
#   - promotes vault-holding winners into strategies.registry (the back pocket
#     the paper cadence auto-adopts via `run_paper.py cycle --from-registry`), and
#   - accumulates Experience Facts into Hindsight (the "learns on the way" memory).
#
# Intended for a weekly launchd cadence (see infra/ops/com.mahoraga.train-window.plist).
# REQUIRES the memory stack UP: Hindsight + LiteLLM + Ollama serving (gemma4). Without
# them --hindsight degrades to a logged no-op (training still runs, memory just doesn't
# accumulate that run). ALWAYS exits 0 (launchd-friendly): diagnose from the log.
#
# Env (from .env): MAHORAGA_DSN (registry/master persistence), MAHORAGA_HINDSIGHT_URL
# (memory), NVIDIA_API_KEY (LLM mutations). Tunables: TRAIN_CADENCE (default replay),
# TRAIN_ITERS (default 12).

set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 0
mkdir -p data/logs
LOG="data/logs/train_window.log"

{
    echo "==== train_window $(date -u +%FT%TZ) ===="
    set -a
    # shellcheck disable=SC1091
    source .env 2>/dev/null
    set +a
    : "${MAHORAGA_HINDSIGHT_URL:=http://localhost:8888}"
    export MAHORAGA_HINDSIGHT_URL
    export MAHORAGA_DSN="${MAHORAGA_DSN:-postgresql://postgres:${POSTGRES_PASSWORD:-}@localhost:5432/postgres}"

    uv run python scripts/run_autoresearch.py \
        --fleet \
        --cadence "${TRAIN_CADENCE:-replay}" \
        --iterations "${TRAIN_ITERS:-12}" \
        --learn-detector \
        --hindsight

    echo "==== done (rc=$?) ===="
} >> "$LOG" 2>&1

exit 0
