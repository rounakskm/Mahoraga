"""OpenClaw-in-NemoClaw sandbox bring-up smoke.

Phase 0 walking-skeleton verification: after `scripts/onboard.sh` has run,
the sandbox is up, the OpenClaw assistant responds to a basic prompt, and
inference flows through LiteLLM (verified via cost-log delta).
"""
import os
import subprocess
import time

import pytest


@pytest.mark.integration
def test_sandbox_status_running():
    """`nemoclaw status` reports the Mahoraga sandbox as running."""
    out = subprocess.run(
        ["nemoclaw", "status", "--name", "mahoraga-trader"],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, f"nemoclaw status failed: {out.stderr}"
    assert "running" in out.stdout.lower(), f"unexpected status output: {out.stdout!r}"


@pytest.mark.integration
def test_sandbox_responds_to_basic_prompt():
    """OpenClaw assistant inside the sandbox answers a hello prompt within 30s."""
    out = subprocess.run(
        ["nemoclaw", "ask", "--name", "mahoraga-trader",
         "--prompt", "Reply with the single word OK."],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"nemoclaw ask failed: {out.stderr}"
    assert "OK" in out.stdout, f"unexpected response: {out.stdout!r}"


@pytest.mark.integration
def test_inference_flowed_through_litellm():
    """Calling the assistant should bump LiteLLM's request counter by >=1."""
    pre  = _litellm_request_count()
    subprocess.run(["nemoclaw", "ask", "--name", "mahoraga-trader",
                    "--prompt", "Hello."],
                   check=True, capture_output=True, timeout=60)
    time.sleep(1)  # cost-log flush
    post = _litellm_request_count()
    assert post > pre, f"LiteLLM request count did not advance ({pre} -> {post})"


def _litellm_request_count() -> int:
    """Read the LiteLLM /metrics endpoint and return total request count, or 0 if missing."""
    import httpx
    base = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
    metrics = base.rstrip("/v1") + "/metrics"
    try:
        r = httpx.get(metrics, timeout=5)
        for line in r.text.splitlines():
            if "litellm_requests_total" in line and "{" not in line:
                return int(float(line.split()[-1]))
    except (httpx.HTTPError, ValueError):
        pass
    return 0
