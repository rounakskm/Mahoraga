"""Measure Gemma-4-via-Ollama throughput on this hardware.

Phase 0 acceptance: this number gates whether Phase 3's compressed-replay
4-6-week schedule is achievable. Target: 30-60 mutations/hour (each
"mutation" = one ~200-token completion).

Outputs a markdown row appended to docs/measurements/phase-0-llm-throughput.md.
"""
from __future__ import annotations

import os
import statistics
import time
from datetime import datetime, timezone

import httpx

LITELLM = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
KEY = os.environ.get("LITELLM_MASTER_KEY", "")
MODEL = os.environ.get("MEASURE_MODEL", "ollama/gemma4")
N = int(os.environ.get("MEASURE_N", "10"))


def one_call() -> float:
    t0 = time.monotonic()
    r = httpx.post(
        f"{LITELLM}/chat/completions",
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "max_tokens": 200,
            "messages": [
                {"role": "system", "content": "You are a senior trading-strategy researcher."},
                {"role": "user", "content": "Propose one small parameter mutation to a momentum strategy. Reply with one sentence."},
            ],
        },
        timeout=120,
    )
    r.raise_for_status()
    return time.monotonic() - t0


def main() -> None:
    actual_tag = os.environ.get("OLLAMA_MODEL", "unknown")
    durations = [one_call() for _ in range(N)]
    median = statistics.median(durations)
    p90 = sorted(durations)[int(0.9 * N) - 1]
    per_hour = 3600.0 / median
    row = (
        f"| {datetime.now(timezone.utc).isoformat()} | {MODEL} ({actual_tag}) | {N} | "
        f"{median:.2f}s median | {p90:.2f}s p90 | {per_hour:.1f}/hr |"
    )
    out_path = "docs/measurements/phase-0-llm-throughput.md"
    if not os.path.exists(out_path):
        with open(out_path, "w") as f:
            f.write(
                "# Bootstrap LLM throughput measurements\n\n"
                "Phase 0 acceptance: target >=30 mutations/hour on this hardware.\n"
                "The model column shows the LiteLLM alias and the actual Ollama tag in parens "
                "(driven by `OLLAMA_MODEL` env per T1.5).\n\n"
                "| date (UTC) | model (tag) | N | latency median | latency p90 | throughput |\n"
                "|---|---|---|---|---|---|\n"
            )
    with open(out_path, "a") as f:
        f.write(row + "\n")
    print(row)


if __name__ == "__main__":
    main()
