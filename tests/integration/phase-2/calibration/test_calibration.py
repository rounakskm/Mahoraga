"""Phase-2 exit proof — the fortress, on real SPY data, must PROMOTE a known-good
strategy (Faber 200-day SMA timing) and REJECT a deliberate-overfit canary
(best-of-many SMA-crossover grid). PBO/DSR (Wall 1) is the discriminator: the
canary's many trials deflate its Sharpe; Faber's single config does not.

Real data: tests/integration/phase-2/calibration/fixtures/spy_daily.csv
(SPY adjusted close, 2015-2026, exported from the Phase-1 parquet store).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from services.trader.gates import GateSystem
from services.trader.walls import EvaluationContext
from services.trader.walls import risklabai_wrap as rl

FIXTURE = Path(__file__).parent / "fixtures" / "spy_daily.csv"


def _spy() -> pd.Series:
    df = pd.read_csv(FIXTURE, parse_dates=["date"]).set_index("date")
    return df["adj_close"].astype(float)


def _sma_returns(price: pd.Series, fast: int, slow: int) -> pd.Series:
    """One-bar-lagged SMA-crossover daily returns (no look-ahead)."""
    ret = price.pct_change()
    if fast == 0:  # fast==0 => price-vs-SMA(slow) (Faber)
        signal = (price > price.rolling(slow).mean()).astype(float)
    else:
        signal = (price.rolling(fast).mean() > price.rolling(slow).mean()).astype(float)
    return (signal.shift(1) * ret).dropna()


def _walk_forward_sharpes(returns: pd.Series, folds: int = 5) -> list[float]:
    return [rl.sharpe(c) for c in np.array_split(returns.values, folds) if len(c) > 20]


def _ctx(returns, **metadata) -> EvaluationContext:
    return EvaluationContext(
        strategy=None, backtest_result=None, returns=returns,
        universe=["SPY"], metadata=metadata,
    )


def test_faber_promoted_canary_rejected_on_real_spy():
    price = _spy()

    # ── Known-good: Faber 200-day SMA timing (single parameter) ──────────────
    faber = _sma_returns(price, fast=0, slow=200)
    faber_ctx = _ctx(
        faber,
        num_trials=1,
        perturbed_sharpes=[rl.sharpe(_sma_returns(price, 0, w)) for w in (180, 200, 220)],
        rolling_sharpes=_walk_forward_sharpes(faber, folds=6),
        oos_sharpes=_walk_forward_sharpes(faber, folds=5),
        num_params=1,
    )

    # ── Known-bad: best-of-grid SMA crossover (overfit by selection) ─────────
    grid = [(f, s) for f in (5, 10, 20, 30) for s in (50, 100, 150, 200) if f < s]
    cols = {f"{f}_{s}": _sma_returns(price, f, s) for f, s in grid}
    matrix = pd.DataFrame(cols).dropna()
    insample = matrix.iloc[: len(matrix) // 3]  # pick the in-sample winner
    best = insample.apply(rl.sharpe).idxmax()
    canary = matrix[best]
    canary_ctx = _ctx(
        canary,
        num_trials=len(grid),
        trial_sharpes=[rl.sharpe(matrix[c]) for c in matrix.columns],
        trial_returns_matrix=matrix.values,
        perturbed_sharpes=[rl.sharpe(matrix[c]) for c in matrix.columns[:3]],  # neighbours vary
        rolling_sharpes=_walk_forward_sharpes(canary, folds=6),
        oos_sharpes=_walk_forward_sharpes(canary, folds=5),
        num_params=2,
    )

    gates = GateSystem()
    faber_rep = gates.evaluate(faber_ctx)
    canary_rep = gates.evaluate(canary_ctx)

    assert faber_rep.promoted, f"Faber should PASS: {faber_rep.reason} | " + _walls(faber_rep)
    assert not canary_rep.promoted, f"canary should be REJECTED: {canary_rep.reason} | " + _walls(canary_rep)

    # PBO is the discriminator: the canary's overfitting shows up in PBO/DSR.
    w1 = canary_rep.wall_reports["statistical_rigor"]
    assert not w1.passed, f"Wall 1 should reject the canary: {w1.reason}"


def _walls(rep) -> str:
    return " ; ".join(f"{n}:{r.passed}" for n, r in rep.wall_reports.items())
