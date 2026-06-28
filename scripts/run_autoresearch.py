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


def load_spy() -> pd.Series:
    files = sorted(glob.glob(str(ROOT / "data/parquet/ohlcv/SPY/*.parquet")))
    if files:
        df = pd.concat(pd.read_parquet(f) for f in files).sort_values("bar_timestamp")
        return pd.Series(
            df["adj_close"].to_numpy(float),
            index=pd.to_datetime(df["bar_timestamp"]),
        )
    df = pd.read_csv(FIXTURE, parse_dates=["date"]).set_index("date")
    return df["adj_close"].astype(float)


def main() -> int:
    ap = argparse.ArgumentParser(description="Layer-1 autoresearch training run (SPY)")
    ap.add_argument("--iterations", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    price = load_spy()
    print(f"SPY: {len(price)} bars {price.index[0].date()} -> {price.index[-1].date()}")
    print(f"running {args.iterations} mechanical iterations through the fortress...\n")

    res = run_loop(price, iterations=args.iterations, seed=args.seed)

    rows = pd.DataFrame(
        {
            "index": i.index, "sharpe": i.sharpe, "promoted": i.promoted,
            "is_best": i.is_best, "windows": str(i.windows), "reason": i.reason,
        }
        for i in res.iterations
    )
    out_dir = ROOT / "data/autoresearch"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"run_seed{args.seed}_{len(price)}bars.parquet"
    rows.to_parquet(out)

    print(f"promoted {res.num_promoted}/{args.iterations} | best daily Sharpe {res.best_sharpe:.4f}")
    print(f"best regime->window: {res.best.windows if res.best else None}")
    print(f"results -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
