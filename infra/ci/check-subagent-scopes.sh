#!/usr/bin/env bash
#
# Subagent permission-scope guard (Hermes frontmatter).
#
# Enforces the locked permission scoping from amendment §6
# (docs/superpowers/specs/2026-05-03-phase-3-seven-role-amendment.md, re-grounded
# to the Hermes `.md` frontmatter the subagent defs actually use):
#
#   - read-only roles (planner, researcher, reviewer, reporter) MUST declare
#     `write: deny` in their frontmatter.
#   - ALL seven roles MUST declare `task: deny`.
#
# Any violation prints a FAIL line and exits 1, failing CI. Scope creep is a
# substrate-portability red flag, not a convenience.
#
# Usage: check-subagent-scopes.sh [SUBAGENTS_DIR]
#   SUBAGENTS_DIR defaults to infra/nemoclaw/subagents
set -euo pipefail

SUBAGENTS_DIR="${1:-infra/nemoclaw/subagents}"

READONLY_ROLES=(planner researcher reviewer reporter)
ALL_ROLES=(planner researcher reviewer reporter hunter guardian archivist)

# A frontmatter line "<key>: <value>" resolving to deny, tolerant of surrounding
# whitespace and optional quotes: e.g. `write: deny`, `  write:  "deny" `.
deny_re() {
  # $1 = key
  printf '^[[:space:]]*%s[[:space:]]*:[[:space:]]*["'\''"]?deny["'\''"]?[[:space:]]*$' "$1"
}

failures=0

assert_deny() {
  # $1 = role, $2 = key
  local role="$1" key="$2" file="$SUBAGENTS_DIR/$1.md"
  if [[ ! -f "$file" ]]; then
    echo "FAIL: $role — missing def file ($file)"
    failures=$((failures + 1))
    return
  fi
  if grep -Eq "$(deny_re "$key")" "$file"; then
    echo "PASS: $role — $key: deny"
  else
    echo "FAIL: $role — $key must resolve to deny in $file"
    failures=$((failures + 1))
  fi
}

echo "Checking subagent permission scopes in: $SUBAGENTS_DIR"

echo "[write: deny] read-only roles"
for role in "${READONLY_ROLES[@]}"; do
  assert_deny "$role" write
done

echo "[task: deny] all roles"
for role in "${ALL_ROLES[@]}"; do
  assert_deny "$role" task
done

if [[ "$failures" -ne 0 ]]; then
  echo "RESULT: FAIL — $failures permission-scope violation(s)"
  exit 1
fi

echo "RESULT: PASS — all subagent permission scopes within bounds"
