#!/usr/bin/env bash
set -euo pipefail
required=(ANTHROPIC_API_KEY POSTGRES_PASSWORD OLLAMA_HOST OLLAMA_MODEL)
missing=0
for var in "${required[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "MISSING: $var"
    missing=$((missing + 1))
  fi
done
if [[ $missing -eq 0 ]]; then
  echo "All required env vars present"
else
  exit 1
fi
