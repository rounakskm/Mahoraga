"""Lint for the Phase-4 web-research egress allowlist + researcher wiring (Task 12).

Asserts that:
  (a) ``infra/nemoclaw/policies/presets/web-research.yaml`` exists and its text
      declares the four allowlisted host groups (FRED, SEC EDGAR, Federal Reserve,
      CME); and
  (b) ``infra/nemoclaw/subagents/researcher.md`` still declares the locked
      read-only scopes ``write: deny`` and ``task: deny`` in its frontmatter.

Stdlib only — the preset is checked by simple substring containment and the
frontmatter is parsed by splitting on the ``---`` fences (mirrors
``test_subagent_defs.py``), so no PyYAML dependency is required.
"""

from __future__ import annotations

from pathlib import Path

INFRA_DIR = Path(__file__).resolve().parents[2]
PRESET = INFRA_DIR / "nemoclaw" / "policies" / "presets" / "web-research.yaml"
RESEARCHER = INFRA_DIR / "nemoclaw" / "subagents" / "researcher.md"

# The four allowlisted host groups for web research.
REQUIRED_HOSTS = [
    "api.stlouisfed.org",  # FRED
    "www.sec.gov",  # SEC EDGAR
    "www.federalreserve.gov",  # Federal Reserve
    "www.cmegroup.com",  # CME
]


def _frontmatter(path: Path) -> dict[str, str]:
    """Parse the leading ``---`` fenced YAML frontmatter into a flat str->str map."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path.name}: missing frontmatter opening '---'"
    parts = text.split("---", 2)
    assert len(parts) >= 3, f"{path.name}: frontmatter not closed with '---'"
    fm: dict[str, str] = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        assert ":" in line, f"{path.name}: malformed frontmatter line: {line!r}"
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    return fm


def test_preset_exists() -> None:
    assert PRESET.is_file(), f"missing web-research egress preset: {PRESET}"


def test_preset_lists_the_four_host_groups() -> None:
    text = PRESET.read_text(encoding="utf-8")
    for host in REQUIRED_HOSTS:
        assert host in text, f"web-research.yaml: missing allowlisted host {host!r}"


def test_researcher_still_read_only() -> None:
    fm = _frontmatter(RESEARCHER)
    assert fm["write"] == "deny", "researcher.md: must still declare write: deny"
    assert fm["task"] == "deny", "researcher.md: must still declare task: deny"
