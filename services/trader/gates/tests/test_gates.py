"""Gate-system aggregation: all gates must pass to promote."""
from __future__ import annotations

import pandas as pd

from services.trader.gates import GateSystem
from services.trader.walls import EvaluationContext
from services.trader.walls.doubles import AlwaysFailWall, AlwaysPassWall


def _ctx(returns):
    return EvaluationContext(
        strategy=None, backtest_result=None, returns=returns,
        universe=["SPY"], metadata={"num_trials": 1},
    )


def test_all_walls_pass_low_drawdown_promotes():
    # AlwaysPassWall under every wall name the gates look up -> all gates pass
    walls = [type("W", (AlwaysPassWall,), {"name": n})() for n in
             ("statistical_rigor", "complexity_control", "generalization", "meta_awareness")]
    rep = GateSystem(walls=walls).evaluate(_ctx(pd.Series([0.001, -0.0005] * 100)))
    assert rep.promoted, rep.reason


def test_one_failing_wall_rejects():
    walls = [type("W", (AlwaysPassWall,), {"name": n})() for n in
             ("complexity_control", "generalization", "meta_awareness")]
    walls.append(type("F", (AlwaysFailWall,), {"name": "statistical_rigor"})())
    rep = GateSystem(walls=walls).evaluate(_ctx(pd.Series([0.001, -0.0005] * 100)))
    assert not rep.promoted and "fitness" in rep.reason


def test_catastrophic_drawdown_fails_risk_gate():
    walls = [type("W", (AlwaysPassWall,), {"name": n})() for n in
             ("statistical_rigor", "complexity_control", "generalization", "meta_awareness")]
    crash = pd.Series([-0.05] * 40)  # ~-87% drawdown
    rep = GateSystem(walls=walls).evaluate(_ctx(crash))
    assert not rep.promoted and "risk" in rep.reason
