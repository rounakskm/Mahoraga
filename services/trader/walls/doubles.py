from __future__ import annotations

from typing import ClassVar

from services.trader.walls.base import EvaluationContext, Wall, WallReport


class AlwaysPassWall(Wall):
    """Test double — always returns passed=True. Never use in production."""

    name: ClassVar[str] = "always_pass"

    def evaluate(self, ctx: EvaluationContext) -> WallReport:
        return WallReport(
            wall_name=self.name,
            passed=True,
            score=1.0,
            reason="AlwaysPassWall — test double only",
        )


class AlwaysFailWall(Wall):
    """Test double — always returns passed=False. Never use in production."""

    name: ClassVar[str] = "always_fail"

    def evaluate(self, ctx: EvaluationContext) -> WallReport:
        return WallReport(
            wall_name=self.name,
            passed=False,
            score=0.0,
            reason="AlwaysFailWall — test double only",
        )
