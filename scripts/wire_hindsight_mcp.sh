#!/usr/bin/env bash
# Wire the Hermes sandbox -> Hindsight memory layer over MCP. Idempotent.
# Run after the Hindsight stack is up (`docker compose up -d hindsight`) and the
# Hermes sandbox is onboarded (scripts/onboard.sh). Proven 2026-06-20:
# the Hermes agent stores + recalls memories through Hindsight (bank mahoraga-trader).
#
# Prereqs already baked in elsewhere:
#   - agents/hermes/Dockerfile.base: HERMES_UV_EXTRAS includes `mcp` (MAHORAGA-PATCH)
#     so Hermes has the MCP client. Apply with `nemoclaw <sb> rebuild` if missing.
#   - The mahoraga-trader bank exists in Hindsight (auto-created on first PUT).
set -euo pipefail
cd "$(dirname "$0")/.."

SANDBOX="${NEMOCLAW_SANDBOX_NAME:-mahoraga-hermes}"
GATEWAY="${OPENSHELL_GATEWAY:-nemoclaw}"
BANK="${HINDSIGHT_BANK:-mahoraga-trader}"
MCP_URL="http://host.openshell.internal:8888/mcp/${BANK}/"

echo "==> [1/3] Apply Hindsight egress preset (sandbox -> host.openshell.internal:8888)"
nemoclaw "$SANDBOX" policy-add --from-file infra/nemoclaw/policies/presets/hindsight.yaml --yes >/dev/null
echo "    egress applied"

echo "==> [2/3] Register Hindsight as an MCP server in Hermes config.yaml"
TMP="$(mktemp -d)"
openshell sandbox download -g "$GATEWAY" "$SANDBOX" /sandbox/.hermes/config.yaml "$TMP" >/dev/null
CFG="$TMP/config.yaml"
if grep -q "mcp_servers:" "$CFG" && grep -q "hindsight:" "$CFG"; then
  echo "    mcp_servers.hindsight already present — skipping"
else
  cat >> "$CFG" <<YAML
mcp_servers:
  hindsight:
    # Native HTTP MCP transport. Hindsight memory bank: ${BANK}.
    url: "${MCP_URL}"
    connect_timeout: 20
    timeout: 120
YAML
  openshell sandbox upload -g "$GATEWAY" "$SANDBOX" "$CFG" /sandbox/.hermes/config.yaml >/dev/null
  echo "    registered ${MCP_URL}"
fi
rm -rf "$TMP"

echo "==> [3/3] Test the MCP connection (lists Hindsight memory tools)"
openshell sandbox exec --tty -g "$GATEWAY" --name "$SANDBOX" -- \
  bash -lc "timeout 60 hermes mcp test hindsight 2>&1 | tail -6" 2>&1 \
  | tr -d '\000' | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g' | grep -vE "^\s*$" | tail -6

echo
echo "Done. Verify the agent uses it:"
echo "  curl :8642/v1/chat/completions  -d '{\"messages\":[{\"role\":\"user\",\"content\":\"store X in hindsight memory\"}]}'"
