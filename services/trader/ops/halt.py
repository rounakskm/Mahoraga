"""HaltControl — the file-flag kill-switch primitive (Phase 3, Layer 3, Task 11).

A single flag file is the cross-process halt signal: any process (Telegram ops,
Guardian's catastrophic-drawdown veto, a human operator) can trip it, and the
orchestrator polls `is_halted()` at the top of each hypothesis so a halt takes
effect within one iteration — the <10s kill-switch the hard-risk-limits require.

The flag file's contents are the halt reason (empty allowed); its existence is
the halt state. Clearing the halt unlinks the file.

# ponytail: file flag = the simplest cross-process kill-switch; upgrade to a
# Postgres advisory channel if we ever go multi-host.
"""

from __future__ import annotations

from pathlib import Path


class HaltControl:
    def __init__(self, flag_path: str | Path = "data/control/halt.flag") -> None:
        self.flag_path = Path(flag_path)

    def halt(self, reason: str = "") -> None:
        """Trip the kill-switch; `reason` is persisted in the flag file."""
        self.flag_path.parent.mkdir(parents=True, exist_ok=True)
        self.flag_path.write_text(reason, encoding="utf-8")

    def resume(self) -> None:
        """Clear the kill-switch. Idempotent — a no-op when not halted."""
        self.flag_path.unlink(missing_ok=True)

    def is_halted(self) -> bool:
        return self.flag_path.exists()

    def reason(self) -> str | None:
        """The halt reason, or `None` when not halted."""
        if not self.flag_path.exists():
            return None
        return self.flag_path.read_text(encoding="utf-8")
