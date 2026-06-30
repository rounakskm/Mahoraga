"""Lint for the seven Hermes subagent definitions (Phase-3 Layer-3, Task 15).

Asserts each role file exists, carries a parseable YAML frontmatter block with all
the required permission keys, and that the read-only roles declare ``write: deny``
(amendment 2026-05-03 section 3 locked scopes). Stdlib only; the frontmatter block
is parsed by a simple split on the ``---`` fences plus line parsing, so no PyYAML
dependency is required.
"""

from __future__ import annotations

from pathlib import Path

SUBAGENTS_DIR = Path(__file__).resolve().parents[2] / "nemoclaw" / "subagents"

ROLES = [
    "planner",
    "researcher",
    "reviewer",
    "hunter",
    "guardian",
    "archivist",
    "reporter",
]

# Roles that must never write the repo (amendment section 3).
READ_ONLY_ROLES = ["planner", "researcher", "reviewer", "reporter"]

REQUIRED_KEYS = ["name", "mode", "write", "edit", "bash", "task"]


def _frontmatter(path: Path) -> dict[str, str]:
    """Parse the leading ``---`` fenced YAML frontmatter into a flat str->str map.

    Manual line parsing (``key: value``) — avoids a PyYAML dependency and is
    sufficient for the simple scalar frontmatter the subagent defs use.
    """
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path.name}: missing frontmatter opening '---'"
    parts = text.split("---", 2)
    assert len(parts) >= 3, f"{path.name}: frontmatter not closed with '---'"
    block = parts[1]
    fm: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        assert ":" in line, f"{path.name}: malformed frontmatter line: {line!r}"
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    return fm


def test_all_seven_files_exist() -> None:
    for role in ROLES:
        path = SUBAGENTS_DIR / f"{role}.md"
        assert path.is_file(), f"missing subagent definition: {path}"


def test_frontmatter_has_required_keys() -> None:
    for role in ROLES:
        fm = _frontmatter(SUBAGENTS_DIR / f"{role}.md")
        for key in REQUIRED_KEYS:
            assert key in fm, f"{role}.md: frontmatter missing required key '{key}'"
        assert fm["name"] == role, f"{role}.md: name '{fm['name']}' != '{role}'"
        assert fm["mode"] == "subagent", f"{role}.md: mode must be 'subagent'"


def test_read_only_roles_declare_write_deny() -> None:
    for role in READ_ONLY_ROLES:
        fm = _frontmatter(SUBAGENTS_DIR / f"{role}.md")
        assert fm["write"] == "deny", f"{role}.md: read-only role must declare write: deny"


def test_all_roles_declare_task_deny() -> None:
    # No subagent may dispatch other subagents; only the Orchestrator (primary) can.
    for role in ROLES:
        fm = _frontmatter(SUBAGENTS_DIR / f"{role}.md")
        assert fm["task"] == "deny", f"{role}.md: subagent must declare task: deny"
