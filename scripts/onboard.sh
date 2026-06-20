#!/usr/bin/env bash
# Onboard the Mahoraga Hermes sandbox via NemoClaw (v0.1.0), reproducibly.
# Harness migrated OpenClaw -> Hermes 2026-06-12; see
# docs/superpowers/specs/2026-06-12-hermes-runtime-migration.md.
#
# This encodes the exact non-interactive flow validated during the 2026-06-12
# Rung-C bring-up: Hermes routes through our LiteLLM gateway (compatible-endpoint)
# to nvidia/nemotron-ultra, with Ollama available as a LiteLLM fallback.
#
# IMPORTANT — the localhost vs host.docker.internal gotcha:
#   NemoClaw validates the inference endpoint HOST-SIDE during onboarding, where
#   `localhost:4000` reaches LiteLLM. But the OpenShell gateway forwards inference
#   from INSIDE its own bridge-network container, where `localhost:4000` is the
#   container itself (nothing there) -> runtime 503 "inference service unavailable".
#   Fix: onboard with localhost:4000 (validation passes), then repoint the provider
#   to host.docker.internal:4000 (reachable from the gateway container). This script
#   does both.
set -euo pipefail

cd "$(dirname "$0")/.."

# ── Prerequisites ────────────────────────────────────────────────
command -v nemoclaw >/dev/null 2>&1 || { echo "FATAL: nemoclaw CLI not on PATH"; \
  echo "   Run: cd vendor/nemoclaw && npm install && npm link"; exit 2; }
command -v openshell >/dev/null 2>&1 || { echo "FATAL: openshell CLI not on PATH"; exit 2; }
test -f .env || { echo "FATAL: .env missing — copy .env.example and fill in"; exit 2; }

set -a
# shellcheck disable=SC1091
source .env
# shellcheck disable=SC1091
source infra/nemoclaw/onboard.env
set +a

: "${LITELLM_MASTER_KEY:?LITELLM_MASTER_KEY must be set in .env}"

SANDBOX="${NEMOCLAW_SANDBOX_NAME:-mahoraga-hermes}"
GATEWAY="${OPENSHELL_GATEWAY:-nemoclaw}"
MODEL="${NEMOCLAW_MODEL:-nvidia/nemotron-ultra}"
RUNTIME_ENDPOINT="${MAHORAGA_RUNTIME_ENDPOINT:-http://host.docker.internal:4000}"

# onboard.env exports NEMOCLAW_ENDPOINT_URL=http://localhost:4000 (host-side
# validation) + NEMOCLAW_PROVIDER=custom + COMPATIBLE_API_KEY=$LITELLM_MASTER_KEY.
echo "==> [1/4] nemoclaw onboard --agent hermes (sandbox=$SANDBOX model=$MODEL)"
nemoclaw onboard --agent "${NEMOCLAW_AGENT:-hermes}" --non-interactive --no-gpu --yes \
  --yes-i-accept-third-party-software --name "$SANDBOX" "$@"

echo "==> [2/4] Repoint inference endpoint to $RUNTIME_ENDPOINT (gateway-container reachable)"
openshell provider update compatible-endpoint -g "$GATEWAY" \
  --config "OPENAI_BASE_URL=$RUNTIME_ENDPOINT"

echo "==> [3/4] Ensure port-forward 8642 is up"
openshell forward start --background 8642 "$SANDBOX" 2>/dev/null \
  || echo "    (forward already active)"

echo "==> [4/4] Smoke test: health + a real prompt through Nemotron Ultra"
sleep 2
curl -sf -m 10 http://127.0.0.1:8642/health && echo "  <- gateway healthy"
code=$(curl -s -m 120 http://127.0.0.1:8642/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Reply with exactly: MAHORAGA HERMES LIVE"}],"stream":false}' \
  -o /tmp/onboard_smoke.json -w "%{http_code}")
echo "  chat http=$code -> $(python3 -c "import json;print(json.load(open('/tmp/onboard_smoke.json'))['choices'][0]['message']['content'][:80])" 2>/dev/null)"

echo
echo "Done. Manage with:"
echo "  nemoclaw list"
echo "  nemohermes $SANDBOX status | logs --follow | connect"
echo "  python scripts/hermes_gateway_watchdog.py   # kill-switch watchdog (bug #2426)"
