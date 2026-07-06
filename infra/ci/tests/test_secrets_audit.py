"""Secrets sandbox audit (Phase-6 governance, Task 4).

Asserts the local secrets posture holds:

1. ``.env`` (the only place broker/LLM keys live) is git-ignored.
2. No tracked file contains key material (Alpaca ``PK...`` key IDs, pasted
   ``APCA-API-SECRET-KEY`` headers, ``sk-...`` / ``nvapi-...`` provider keys).
3. The Hermes sandbox filesystem scopes cannot reach the repo or ``.env`` —
   every writable path is under ``/sandbox`` or ``/tmp``.

Stdlib only (subprocess + textual YAML scan; no PyYAML), matching the other
infra CI tests.

# ponytail: .env + gitignore + sandbox isolation is the local posture; keyring/vault when cloud lands
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_FILE = REPO_ROOT / "infra" / "nemoclaw" / "policies" / "filesystem.yaml"

# Alpaca key IDs, pasted secret-key headers, OpenAI-style and NVIDIA keys.
SECRET_PATTERN = r"(PK[A-Z0-9]{16,}|APCA-API-SECRET-KEY:\s*\w|sk-[A-Za-z0-9]{20,}|nvapi-[A-Za-z0-9]{20,})"

# Vendored upstreams have their own hygiene; this file names the patterns themselves.
GREP_EXCLUDES = [":!vendor", ":!infra/ci/tests/test_secrets_audit.py"]


def _find_tracked_secrets(repo: Path) -> list[str]:
    """Return tracked files in ``repo`` whose content matches SECRET_PATTERN."""
    result = subprocess.run(
        ["git", "grep", "-lE", SECRET_PATTERN, "--", *GREP_EXCLUDES],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.splitlines()
    if result.returncode == 1:  # git grep: no matches
        return []
    raise RuntimeError(f"git grep failed (rc={result.returncode}): {result.stderr}")


def _writable_paths(policy_text: str) -> list[str]:
    """Extract the path tokens listed under the ``read_write:`` section, textually."""
    paths: list[str] = []
    in_section = False
    for raw in policy_text.splitlines():
        line = raw.split("#", 1)[0].rstrip()  # strip trailing comments
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "read_write:":
            in_section = True
            continue
        if in_section:
            if stripped.startswith("- "):
                paths.append(stripped[2:].strip())
            else:  # next YAML key — section over
                in_section = False
    return paths


def test_env_is_gitignored() -> None:
    if not (REPO_ROOT / ".env").exists():
        pytest.skip("no .env file present in this checkout")
    result = subprocess.run(
        ["git", "check-ignore", ".env"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, ".env exists but is NOT git-ignored — key material at risk of commit"


def test_helper_catches_planted_key(tmp_path: Path) -> None:
    """TDD self-check: a planted fake key in a fresh git repo is detected.

    The fake key is built by concatenation so this test file itself never
    contains a matching literal.
    """
    fake_key = "PK" + "ABCDEFGHIJKLMNOP12"
    (tmp_path / "leaked.py").write_text(f'API_KEY = "{fake_key}"\n', encoding="utf-8")
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "ci@test.local"],
        ["git", "config", "user.name", "ci"],
        ["git", "add", "leaked.py"],
        ["git", "commit", "-q", "-m", "plant fake key"],
    ):
        subprocess.run(cmd, cwd=tmp_path, check=True, capture_output=True)
    assert _find_tracked_secrets(tmp_path) == ["leaked.py"]


def test_no_tracked_file_contains_key_material() -> None:
    hits = _find_tracked_secrets(REPO_ROOT)
    assert hits == [], f"tracked files contain key material: {hits}"


def test_sandbox_writable_scopes_cannot_reach_repo_or_env() -> None:
    text = POLICY_FILE.read_text(encoding="utf-8")
    paths = _writable_paths(text)
    assert paths, f"no read_write paths found in {POLICY_FILE} — parse failure or empty policy"
    for path in paths:
        assert path.startswith(("/sandbox", "/tmp")), (
            f"writable sandbox scope escapes isolation: {path!r} (must be under /sandbox or /tmp)"
        )
    assert ".env" not in text, f".env must never appear as a mounted/readable path in {POLICY_FILE}"
