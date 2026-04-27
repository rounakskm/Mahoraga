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
