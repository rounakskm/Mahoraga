#!/usr/bin/env python3
"""Start a (Layer-1, mechanical) autoresearch training run on real SPY.

    uv run python scripts/run_autoresearch.py --iterations 50

Loads SPY daily from the Phase-1 parquet store (falls back to the committed
calibration fixture), runs the regime-conditional hill-climb through the Phase-2
fortress, prints a summary, and writes every iteration to
data/autoresearch/<timestamp>.parquet (kept + discarded, with the gate reason).

ponytail: results -> parquet for now. Postgres experiments.iterations + git
strategy registry (full provenance) is the next Layer-1 slice; the loop already
returns everything they need.
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

import pandas as pd

from services.trader.training.loop import run_loop

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests/integration/phase-2/calibration/fixtures/spy_daily.csv"


def load_spy() -> tuple[pd.Series, pd.Series | None]:
    """Return (adj_close price, regimes). From the real OHLCV parquet we use the
    actual Phase-1 MESO detector; from the adj-close-only fixture, regimes is None
    (the loop falls back to its inline proxy)."""
    files = sorted(glob.glob(str(ROOT / "data/parquet/ohlcv/SPY/*.parquet")))
    if files:
        from services.trader.training.regime import meso_regimes

        df = pd.concat(pd.read_parquet(f) for f in files).sort_values("bar_timestamp")
        df.index = pd.to_datetime(df["bar_timestamp"])
        price = df["adj_close"].astype(float)
        return price, meso_regimes(df)
    df = pd.read_csv(FIXTURE, parse_dates=["date"]).set_index("date")
    return df["adj_close"].astype(float), None


def main() -> int:
    ap = argparse.ArgumentParser(description="Layer-1 autoresearch training run (SPY)")
    ap.add_argument("--iterations", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    price, regimes = load_spy()
    detector = "real Phase-1 MESO detector" if regimes is not None else "inline trend×vol proxy"
    print(f"SPY: {len(price)} bars {price.index[0].date()} -> {price.index[-1].date()}")
    print(f"regimes: {detector}")
    print(f"running {args.iterations} mechanical iterations through the fortress...\n")

    out_dir = ROOT / "data/autoresearch"
    out_dir.mkdir(parents=True, exist_ok=True)
    live = out_dir / f"run_seed{args.seed}_{len(price)}bars.csv"
    live.write_text("index,sharpe,promoted,is_best,windows,reason\n")

    # Live progress: print each iteration AND append it to the CSV as it completes,
    # so training is watchable in real time (`tail -f` the CSV from another terminal).
    def on_iter(it):
        flag = "BEST" if it.is_best else ("ok " if it.promoted else "   ")
        print(f"  iter {it.index:3d}  Sharpe {it.sharpe:+.4f}  [{flag}]  {it.reason[:70]}", flush=True)
        with live.open("a") as fh:
            fh.write(f'{it.index},{it.sharpe:.6f},{it.promoted},{it.is_best},"{it.windows}","{it.reason}"\n')

    res = run_loop(
        price, iterations=args.iterations, seed=args.seed,
        regimes=regimes, on_iteration=on_iter,
    )

    print(f"\npromoted {res.num_promoted}/{args.iterations} | best daily Sharpe {res.best_sharpe:.4f}")
    print(f"best regime->window: {res.best.windows if res.best else None}")
    print(f"live results -> {live.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
