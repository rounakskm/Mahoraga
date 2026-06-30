"""Self-check for the subagent permission-scope guard.

Verifies the guard (infra/ci/check-subagent-scopes.sh) enforces amendment §6
(re-grounded to Hermes frontmatter):
  - read-only roles (planner, researcher, reviewer, reporter) must declare write: deny
  - all 7 roles must declare task: deny
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GUARD = REPO_ROOT / "infra" / "ci" / "check-subagent-scopes.sh"
REAL_SUBAGENTS = REPO_ROOT / "infra" / "nemoclaw" / "subagents"


def _run(target_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(GUARD), str(target_dir)],
        capture_output=True,
        text=True,
    )


def test_guard_passes_on_real_subagent_defs():
    result = _run(REAL_SUBAGENTS)
    assert result.returncode == 0, (
        f"guard should pass on real defs, got rc={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_guard_fails_on_planted_write_allow_planner(tmp_path):
    # Copy real defs into a temp dir, then plant a bad planner.
    for src in REAL_SUBAGENTS.glob("*.md"):
        (tmp_path / src.name).write_text(src.read_text())
    (tmp_path / "planner.md").write_text(
        "---\n"
        "name: planner\n"
        "mode: subagent\n"
        "write: allow\n"
        "edit: deny\n"
        "bash: deny\n"
        "task: deny\n"
        "---\n\n"
        "# Planner\n"
    )
    result = _run(tmp_path)
    assert result.returncode != 0, (
        f"guard should fail on planted write: allow planner, got rc=0\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
