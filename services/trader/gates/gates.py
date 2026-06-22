"""Three-gate system — the promotion decision over the four walls.

A gate aggregates wall verdicts (and, for the risk gate, the return series) into
a pass/fail. All three must pass to promote a strategy:

- Fitness   ← Wall 1 (statistical_rigor): is the edge statistically real?
- Robustness← Wall 2 (complexity_control) AND Wall 3 (generalization): robust + general?
- Risk      ← Wall 4 (meta_awareness) AND max-drawdown within limit.

`GateSystem.evaluate(ctx)` runs the walls, then the gates, then AND-aggregates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

import pandas as pd

from services.trader.walls.base import EvaluationContext, Wall, WallReport
from services.trader.walls.wall_1_statistical import StatisticalRigorWall
from services.trader.walls.wall_2_complexity import ComplexityControlWall
from services.trader.walls.wall_3_generalization import GeneralizationWall
from services.trader.walls.wall_4_meta import MetaAwarenessWall


@dataclass(frozen=True)
class GateReport:
    gate_name: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class GateSystemReport:
    promoted: bool
    wall_reports: dict[str, WallReport]
    gate_reports: list[GateReport]
    reason: str = ""


def max_drawdown(returns) -> float:
    eq = (1.0 + pd.Series(returns).fillna(0.0)).cumprod()
    return float((eq / eq.cummax() - 1.0).min())


def _w(walls: dict[str, WallReport], name: str) -> bool:
    r = walls.get(name)
    return bool(r is not None and r.passed)


class Gate(ABC):
    name: ClassVar[str]

    @abstractmethod
    def evaluate(self, walls: dict[str, WallReport], ctx: EvaluationContext) -> GateReport: ...


class FitnessGate(Gate):
    name: ClassVar[str] = "fitness"

    def evaluate(self, walls, ctx) -> GateReport:
        ok = _w(walls, "statistical_rigor")
        return GateReport(self.name, ok, f"statistical_rigor passed={ok}")


class RobustnessGate(Gate):
    name: ClassVar[str] = "robustness"

    def evaluate(self, walls, ctx) -> GateReport:
        cx, gn = _w(walls, "complexity_control"), _w(walls, "generalization")
        return GateReport(self.name, cx and gn, f"complexity={cx} generalization={gn}")


class RiskGate(Gate):
    name: ClassVar[str] = "risk"

    def __init__(self, *, max_drawdown_limit: float = 0.25) -> None:
        self.max_drawdown_limit = max_drawdown_limit

    def evaluate(self, walls, ctx) -> GateReport:
        meta = _w(walls, "meta_awareness")
        dd = max_drawdown(ctx.returns)
        dd_ok = dd >= -self.max_drawdown_limit
        return GateReport(self.name, meta and dd_ok, f"meta={meta} max_dd={dd:.2%} (ok={dd_ok})")


class GateSystem:
    def __init__(self, *, walls: list[Wall] | None = None, gates: list[Gate] | None = None) -> None:
        self.walls = walls or [
            StatisticalRigorWall(),
            ComplexityControlWall(),
            GeneralizationWall(),
            MetaAwarenessWall(),
        ]
        self.gates = gates or [FitnessGate(), RobustnessGate(), RiskGate()]

    def evaluate(self, ctx: EvaluationContext) -> GateSystemReport:
        wall_reports = {w.name: w.evaluate(ctx) for w in self.walls}
        gate_reports = [g.evaluate(wall_reports, ctx) for g in self.gates]
        promoted = all(g.passed for g in gate_reports)
        failed = [g.gate_name for g in gate_reports if not g.passed]
        reason = "promoted" if promoted else f"rejected by gates: {', '.join(failed)}"
        return GateSystemReport(promoted, wall_reports, gate_reports, reason)
