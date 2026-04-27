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
# shellcheck disable=SC1091
source .env
# shellcheck disable=SC1091
source infra/nemoclaw/onboard.env
set +a

# Run onboarding (interactive by default; pass --non-interactive when supported by current NemoClaw release)
nemoclaw onboard \
  --blueprint "$NEMOCLAW_BLUEPRINT_PATH" \
  --inference-provider "$NEMOCLAW_INFERENCE_PROVIDER" \
  --inference-base-url "$NEMOCLAW_INFERENCE_BASE_URL" \
  --inference-model    "$NEMOCLAW_INFERENCE_MODEL" \
  ${NEMOCLAW_TELEGRAM_TOKEN:+--telegram-token "$NEMOCLAW_TELEGRAM_TOKEN"}

echo "Onboard complete. Use 'nemoclaw status' to verify, or run pytest -m integration for the full smoke."
