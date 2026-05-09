"""OpenClaw-in-NemoClaw sandbox bring-up smoke.

Phase 0 walking-skeleton verification: after `scripts/onboard.sh` has run,
the sandbox is up, can execute a shell command via the OpenShell gateway,
and inference flows through LiteLLM (verified by direct gateway call).

NemoClaw v0.1.0 does NOT expose a scriptable `nemoclaw ask` / `nemoclaw stop`.
The sandbox-internal OpenClaw assistant speaks over its own gateway-token
authenticated HTTP API (see `nemoclaw <name> gateway-token`), but that surface
is deferred to Phase 1 once we have the trader bridge. For Phase 0, "alive"
is asserted via `openshell sandbox exec` and the inference route registration.
"""
import os
import subprocess

import pytest

SANDBOX = os.environ.get("MAHORAGA_SANDBOX_NAME", "mahoraga-trader")


@pytest.mark.integration
def test_sandbox_status_running():
    """`nemoclaw <name> status` reports the Mahoraga sandbox as running."""
    out = subprocess.run(
        ["nemoclaw", SANDBOX, "status"],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, f"nemoclaw status failed: {out.stderr}"
    text = (out.stdout + out.stderr).lower()
    assert "running" in text, f"unexpected status output: {out.stdout!r}"


@pytest.mark.integration
def test_sandbox_exec_responds():
    """`openshell sandbox exec` runs a no-op command inside the sandbox within 30s."""
    out = subprocess.run(
        ["openshell", "sandbox", "exec", SANDBOX, "--", "echo", "phase0-ok"],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, f"sandbox exec failed: {out.stderr}"
    assert "phase0-ok" in out.stdout, f"unexpected exec output: {out.stdout!r}"


@pytest.mark.integration
def test_inference_route_registered():
    """The gateway has the LiteLLM-backed inference route bound to ollama/gemma4."""
    out = subprocess.run(
        ["openshell", "inference", "get"],
        capture_output=True, text=True, timeout=15,
    )
    assert out.returncode == 0, f"openshell inference get failed: {out.stderr}"
    assert "compatible-endpoint" in out.stdout, f"provider not registered: {out.stdout!r}"
    assert "ollama/gemma4" in out.stdout, f"model not registered: {out.stdout!r}"


@pytest.mark.integration
def test_litellm_serves_chat_completion():
    """LiteLLM gateway answers an ollama/gemma4 chat-completion via the host port."""
    import httpx

    base = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
    key = os.environ.get("LITELLM_MASTER_KEY", "")
    r = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": "ollama/gemma4",
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "max_tokens": 15,
        },
        timeout=120,
    )
    r.raise_for_status()
    body = r.json()
    content = body["choices"][0]["message"]["content"]
    assert content.strip().startswith("OK"), f"unexpected completion: {content!r}"
