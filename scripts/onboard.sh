#!/usr/bin/env bash
# Onboard a Mahoraga sandbox via NemoClaw.
# Phase 0 smoke: brings up one OpenClaw assistant inside a NemoClaw-hardened sandbox.
#
# NemoClaw v0.1.0 ships an INTERACTIVE TUI wizard for `nemoclaw onboard`. It does
# NOT take --blueprint / --inference-provider / --inference-base-url flags; the
# operator answers the wizard's questions about provider, model, credentials, and
# channels. Running this script invokes the TUI directly. To skip prompts entirely,
# pass --non-interactive (note: that flag's behavior depends on the release; current
# v0.1.0 still prompts for some inputs).
set -euo pipefail

# Verify prerequisites
command -v nemoclaw >/dev/null 2>&1 || { echo "FATAL: nemoclaw CLI not on PATH"; \
  echo "   Run: cd vendor/nemoclaw && npm install && npm link"; exit 2; }
command -v ollama   >/dev/null 2>&1 || { echo "FATAL: ollama not on PATH"; exit 2; }
test -f .env || { echo "FATAL: .env missing — copy .env.example and fill in"; exit 2; }

# Load env (so any $VAR the wizard reads from environment is available)
set -a
# shellcheck disable=SC1091
source .env
set +a

echo "Launching nemoclaw onboard (interactive TUI wizard)..."
echo "  - When prompted for provider, choose 'compatible-endpoints' (LiteLLM gateway)"
echo "  - Base URL: \${LITELLM_BASE_URL:-http://litellm:4000/v1}  =  ${LITELLM_BASE_URL:-http://litellm:4000/v1}"
echo "  - API key: paste \${LITELLM_MASTER_KEY}  (we already exported it)"
echo "  - Model: ollama/gemma4  (the LiteLLM alias)"
echo "  - Telegram: skip (Phase 6 concern) unless you have a bot ready"
echo

# Pass through any flags the operator wants (e.g., --non-interactive, --recreate-sandbox)
nemoclaw onboard --yes-i-accept-third-party-software "$@"

echo
echo "Onboard wizard exited. Verify with:"
echo "  nemoclaw list                         # see registered sandboxes"
echo "  nemoclaw <name> status                # health + NIM status"
echo "  pytest tests/integration/phase-0 -m integration -v"
