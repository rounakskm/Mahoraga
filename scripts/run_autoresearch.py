#!/usr/bin/env python3
"""Start a (Layer-1, mechanical) autoresearch training run on real SPY.

    uv run python scripts/run_autoresearch.py --iterations 50

Loads SPY daily from the Phase-1 parquet store (falls back to the committed
calibration fixture), searches on TRAIN through the Phase-2 fortress, validates the
promoted best on the held-out vault, and records provenance.

Provenance: every iteration streams to a live CSV (always) and, when MAHORAGA_DSN
is set, to Postgres `experiments.iterations`; a deployment-eligible best (promoted
AND vault holds) is written to the tracked `strategies/<run>.json` registry and
`strategies.registry`. No DSN -> Postgres writes are skipped, the run still works.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import time
from pathlib import Path

import pandas as pd

from services.trader.training.loop import run_loop
from services.trader.training.provenance import ProvenanceWriter, candidate_hash
from services.trader.training.vault import split_train, validate_on_vault

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
    ap.add_argument("--vault-days", type=int, default=180, help="held-out vault window")
    args = ap.parse_args()

    run_id = f"seed{args.seed}-{int(time.time())}"
    prov = ProvenanceWriter(os.environ.get("MAHORAGA_DSN"))

    price, regimes = load_spy()
    real_detector = regimes is not None
    if regimes is None:  # fixture fallback: derive the proxy so we can still split
        from services.trader.training.strategy_template import label_regimes

        regimes = label_regimes(price)
    detector = "real Phase-1 MESO detector" if real_detector else "inline trend×vol proxy"

    # The search may ONLY see training data; the last --vault-days are held out.
    train_price, train_regimes, cutoff = split_train(price, regimes, args.vault_days)
    print(f"SPY: {len(price)} bars {price.index[0].date()} -> {price.index[-1].date()}")
    print(f"regimes: {detector}")
    print(f"train: <= {cutoff.date()} ({len(train_price)} bars) | vault (held out): > {cutoff.date()}")
    print(f"running {args.iterations} mechanical iterations on TRAIN through the fortress...\n")

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
        prov.write_iteration(
            run_id=run_id, iteration=it.index, params=it.windows,
            train_sharpe=it.sharpe, promoted=it.promoted, is_best=it.is_best, reason=it.reason,
        )

    res = run_loop(
        train_price, iterations=args.iterations, seed=args.seed,
        regimes=train_regimes, on_iteration=on_iter,
    )

    print(f"\npromoted {res.num_promoted}/{args.iterations} | best TRAIN Sharpe {res.best_sharpe:.4f}")
    print(f"best regime->window: {res.best.windows if res.best else None}")

    # The non-negotiable gate: validate the promoted best on the untouched vault.
    if res.best is not None:
        vr = validate_on_vault(res.best, price, regimes, cutoff, res.best_sharpe)
        verdict = "✅ HOLDS — deployment-eligible" if vr.holds else "❌ FAILS vault — NOT deployment-eligible"
        print(f"\nvault-holdout: {verdict}\n  {vr.reason}")
        if vr.holds:  # register the deployment-eligible survivor
            strat_dir = ROOT / "strategies"
            strat_dir.mkdir(exist_ok=True)
            artifact = strat_dir / f"{run_id}.json"
            artifact.write_text(json.dumps({
                "run_id": run_id, "candidate_hash": candidate_hash(res.best.windows),
                "params": res.best.windows, "train_sharpe": res.best_sharpe,
                "vault_sharpe": vr.vault_sharpe, "vault_holds": vr.holds,
            }, indent=2))
            prov.register_strategy(
                run_id=run_id, params=res.best.windows, train_sharpe=res.best_sharpe,
                vault_sharpe=vr.vault_sharpe, vault_holds=vr.holds,
                artifact_path=str(artifact.relative_to(ROOT)),
            )
            print(f"  registered -> {artifact.relative_to(ROOT)}")
    else:
        print("\nvault-holdout: no promoted candidate to validate")

    prov.close()
    pg = (
        "Postgres experiments.iterations + strategies.registry"
        if prov.is_enabled() else "skipped (set MAHORAGA_DSN to enable)"
    )
    print(f"\nprovenance: {pg}")
    print(f"live results -> {live.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
