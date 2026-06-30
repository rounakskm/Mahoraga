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
from services.trader.training.vault import validate_on_vault, vault_cutoff

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests/integration/phase-2/calibration/fixtures/spy_daily.csv"


def load_spy() -> tuple[pd.Series, pd.Series | None, pd.DataFrame | None]:
    """Return (adj_close price, regimes, ohlcv). From the real OHLCV parquet we use
    the actual Phase-1 MESO detector + return the frame (for --learn-detector); from
    the adj-close-only fixture, regimes/ohlcv are None (loop uses the inline proxy)."""
    files = sorted(glob.glob(str(ROOT / "data/parquet/ohlcv/SPY/*.parquet")))
    if files:
        from services.trader.training.regime import meso_regimes

        df = pd.concat(pd.read_parquet(f) for f in files).sort_values("bar_timestamp")
        df.index = pd.to_datetime(df["bar_timestamp"])
        price = df["adj_close"].astype(float)
        return price, meso_regimes(df), df
    df = pd.read_csv(FIXTURE, parse_dates=["date"]).set_index("date")
    return df["adj_close"].astype(float), None, None


def main() -> int:
    ap = argparse.ArgumentParser(description="Layer-1 autoresearch training run (SPY)")
    ap.add_argument("--iterations", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--vault-days", type=int, default=180, help="held-out vault window")
    ap.add_argument("--llm", action="store_true", help="use the Nemotron LLM mutator (Layer 2)")
    ap.add_argument("--llm-model", default=None, help="override the LLM model id")
    ap.add_argument("--learn-detector", action="store_true",
                    help="make the regime detector thresholds a mutation target (Layer 2)")
    args = ap.parse_args()

    mutator = None
    if args.llm:
        from services.trader.training.llm import LLMMutator

        mutator = LLMMutator(model=args.llm_model)

    run_id = f"seed{args.seed}-{int(time.time())}"
    prov = ProvenanceWriter(os.environ.get("MAHORAGA_DSN"))

    price, regimes, ohlcv = load_spy()
    real_detector = regimes is not None
    if regimes is None:  # fixture fallback: derive the proxy so we can still split
        from services.trader.training.strategy_template import label_regimes

        regimes = label_regimes(price)
    detector = "real Phase-1 MESO detector" if real_detector else "inline trend×vol proxy"

    learn_detector = args.learn_detector and ohlcv is not None
    cutoff = vault_cutoff(price, args.vault_days)
    train_price = price[price.index <= cutoff]
    if learn_detector:  # the detector is a mutation target: search on TRAIN features
        from services.trader.training.regime import detector_features

        adx, vol = detector_features(ohlcv)
        train_feats = (adx[adx.index <= cutoff], vol[vol.index <= cutoff])
        detector = "LEARNABLE (thresholds mutated)"
        loop_kwargs = {"detector_features": train_feats}
    else:  # fixed detector: search on the train regime slice
        train_regimes = regimes[regimes.index <= cutoff]
        loop_kwargs = {"regimes": train_regimes}

    print(f"SPY: {len(price)} bars {price.index[0].date()} -> {price.index[-1].date()}")
    print(f"regimes: {detector}")
    mut_label = f"LLM ({mutator.model})" if mutator else "mechanical hill-climb"
    print(f"train: <= {cutoff.date()} ({len(train_price)} bars) | vault (held out): > {cutoff.date()}")
    print(f"running {args.iterations} iterations on TRAIN through the fortress | mutator: {mut_label}\n")

    out_dir = ROOT / "data/autoresearch"
    out_dir.mkdir(parents=True, exist_ok=True)
    live = out_dir / f"run_seed{args.seed}_{len(price)}bars.csv"
    live.write_text("index,sharpe,fitness,quarterly_win_rate,max_drawdown,promoted,is_best,windows,reason\n")

    # Live progress: print each iteration AND append it to the CSV as it completes,
    # so training is watchable in real time (`tail -f` the CSV from another terminal).
    def on_iter(it):
        flag = "BEST" if it.is_best else ("ok " if it.promoted else "   ")
        print(
            f"  iter {it.index:3d}  Sharpe {it.sharpe:+.4f}  Qwin {it.quarterly_win_rate:.0%}  "
            f"dd {it.max_drawdown:+.0%}  [{flag}]  {it.reason[:48]}", flush=True)
        with live.open("a") as fh:
            fh.write(f'{it.index},{it.sharpe:.6f},{it.fitness:.6f},{it.quarterly_win_rate:.4f},'
                     f'{it.max_drawdown:.4f},{it.promoted},{it.is_best},"{it.windows}","{it.reason}"\n')
        prov.write_iteration(
            run_id=run_id, iteration=it.index, params=it.windows,
            train_sharpe=it.sharpe, promoted=it.promoted, is_best=it.is_best, reason=it.reason,
        )

    res = run_loop(
        train_price, iterations=args.iterations, seed=args.seed,
        mutator=mutator, on_iteration=on_iter, **loop_kwargs,
    )

    print(f"\npromoted {res.num_promoted}/{args.iterations} | best TRAIN Sharpe {res.best_sharpe:.4f}"
          f" | quarterly-win {res.best_quarterly_win_rate:.0%} | fitness {res.best_fitness:.4f}")
    print(f"best regime->window: {res.best.windows if res.best else None}")

    # The non-negotiable gate: validate the promoted best on the untouched vault.
    if res.best is not None:
        # learnable detector: re-derive vault regimes from the best's learned thresholds
        full_regimes = res.best.regimes_for(adx, vol) if learn_detector else regimes
        vr = validate_on_vault(res.best, price, full_regimes, cutoff, res.best_sharpe)
        verdict = "✅ HOLDS — deployment-eligible" if vr.holds else "❌ FAILS vault — NOT deployment-eligible"
        print(f"\nvault-holdout: {verdict}\n  {vr.reason}")
        if vr.holds:  # register the deployment-eligible survivor (incl learned detector)
            strat_dir = ROOT / "strategies"
            strat_dir.mkdir(exist_ok=True)
            best_params = {
                "windows": res.best.windows,
                "adx_threshold": res.best.adx_threshold,
                "vol_threshold": res.best.vol_threshold,
            }
            artifact = strat_dir / f"{run_id}.json"
            artifact.write_text(json.dumps({
                "run_id": run_id, "candidate_hash": candidate_hash(best_params),
                **best_params, "train_sharpe": res.best_sharpe,
                "vault_sharpe": vr.vault_sharpe, "vault_holds": vr.holds,
            }, indent=2))
            prov.register_strategy(
                run_id=run_id, params=best_params, train_sharpe=res.best_sharpe,
                vault_sharpe=vr.vault_sharpe, vault_holds=vr.holds,
                artifact_path=str(artifact.relative_to(ROOT)),
            )
            print(f"  registered -> {artifact.relative_to(ROOT)} "
                  f"(detector: adx≥{res.best.adx_threshold:.0f}, vol>{res.best.vol_threshold:.1f})")
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
