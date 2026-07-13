#!/usr/bin/env python3
"""Generate the convergence report — the real-capital go/no-go artifact (Phase-6 T7).

    uv run python scripts/convergence_report.py --date 2026-07-06 \
        [--paper-stats paper.json] [--hindsight http://localhost:8888] [--out PATH]

Gathers real inputs best-effort and evaluates them through
`services/trader/ops/convergence.evaluate` (fail-closed: any source that is
missing or unreachable leaves its input None, which FAILS that criterion —
readiness can never pass vacuously). The script itself always exits 0 and
prints the verdict; a failing report is a valid, honest artifact.

Input sources (each independently optional):
  * strategies.registry rows       — Postgres via MAHORAGA_DSN (note: MAHORAGA_DSN,
                                     one common typo is "MAHOAGA_DSN").
  * replay span + regime coverage  — the SPY OHLCV parquet store
                                     (data/parquet/ohlcv/SPY/*.parquet) labelled
                                     with the real Phase-1 MESO detector
                                     (`services.trader.training.regime.meso_regimes`);
                                     `undefined` warmup bars are excluded from the
                                     coverage denominator.
  * kb_facts                       — Hindsight recall-count PROXY (documented):
                                     the slim API has no count endpoint, so we
                                     issue a broad `recall` with a large k and
                                     count the results. This is a LOWER BOUND
                                     (recall returns at most its top-N matches);
                                     it can under-count a deep KB but can never
                                     over-count a thin one — which is the safe
                                     direction for a gate. Replace with a real
                                     count endpoint when upstream grows one.
  * paper stats                    — explicit `--paper-stats <json>` file with
                                     {"days": int, "sharpe": float} wins when
                                     given; otherwise auto-gathered from
                                     `trades.pnl_daily` via MAHORAGA_DSN
                                     (`services.trader.ops.paper_stats`). No
                                     file + no DSN -> unmeasured (fail-closed).

`--date` is REQUIRED and there is deliberately NO datetime.now() fallback: the
repo's replay-safe convention is that nothing on the library/report path reads
wall-clock time, so a report regenerated during replayed history (or a re-run
of today's inputs next week) is byte-identical and attributable to an explicit
as-of date chosen by the operator.

Writes `docs/convergence/<date>-report.md` (or `--out`).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.trader.ops.convergence import (  # noqa: E402
    MIN_KB_FACTS,
    ConvergenceInputs,
    evaluate,
    render_markdown,
)

# Recall ceiling for the kb_facts proxy: comfortably above MIN_KB_FACTS so the
# lower bound can still clear the threshold when the KB is deep enough.
_KB_RECALL_K = max(1000, MIN_KB_FACTS * 10)


def _gather_registry(dsn: str | None) -> list[dict] | None:
    """`strategies.registry` rows (deployment-eligible only); None when no DSN
    or the query fails — fail-closed."""
    if not dsn:
        return None
    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=5) as conn:
            rows = conn.execute(
                "SELECT candidate_hash, vault_holds, deployment_eligible, "
                "train_sharpe, vault_sharpe "
                "FROM strategies.registry WHERE deployment_eligible"
            ).fetchall()
        return [
            {
                "candidate_hash": r[0],
                "vault_holds": r[1],
                "deployment_eligible": r[2],
                "train_sharpe": r[3],
                "vault_sharpe": r[4],
            }
            for r in rows
        ]
    except Exception as exc:  # any DB failure -> unmeasured, never a crash
        print(f"registry: unavailable ({exc}); criterion will fail closed")
        return None


def _gather_replay_and_coverage() -> tuple[float | None, dict[str, float] | None]:
    """(replay_years, regime_coverage) from the SPY parquet via the real MESO
    detector; (None, None) when the store is absent or labelling fails."""
    files = sorted(glob.glob(str(ROOT / "data/parquet/ohlcv/SPY/*.parquet")))
    if not files:
        print("spy parquet: not found; replay/coverage criteria will fail closed")
        return None, None
    try:
        import pandas as pd

        from services.trader.training.regime import meso_regimes

        df = pd.concat(pd.read_parquet(f) for f in files).sort_values("bar_timestamp")
        df.index = pd.to_datetime(df["bar_timestamp"])
        years = (df.index[-1] - df.index[0]).days / 365.25
        labels = meso_regimes(df)
        defined = labels[labels != "undefined"]  # warmup bars carry no regime info
        if defined.empty:
            return round(years, 2), None
        coverage = (defined.value_counts() / len(defined)).to_dict()
        return round(years, 2), {str(k): float(v) for k, v in coverage.items()}
    except Exception as exc:
        print(f"spy parquet: labelling failed ({exc}); criteria will fail closed")
        return None, None


def _gather_kb_facts(hindsight_url: str | None) -> int | None:
    """Hindsight fact count via the recall proxy (lower bound — see module doc);
    None when disabled/unreachable or when recall returns nothing (an empty
    result is indistinguishable from an unreachable index, so it stays
    unmeasured rather than asserting an exact 0)."""
    if not hindsight_url:
        return None
    from services.trader.training.hindsight_client import HindsightClient

    client = HindsightClient(base_url=hindsight_url)
    results = client.recall("trading experience regime strategy", k=_KB_RECALL_K)
    if not results:
        print("hindsight: no recall results; kb_depth will fail closed")
        return None
    return len(results)


def _gather_paper_stats(path: str | None) -> tuple[int | None, float | None]:
    """(days, sharpe) from the optional --paper-stats JSON; (None, None) when
    absent or malformed."""
    if not path:
        return None, None
    try:
        stats = json.loads(Path(path).read_text())
        days = int(stats["days"]) if "days" in stats else None
        sharpe = float(stats["sharpe"]) if "sharpe" in stats else None
        return days, sharpe
    except Exception as exc:
        print(f"paper stats: unreadable ({exc}); criteria will fail closed")
        return None, None


def _resolve_paper_stats(path: str | None, dsn: str | None) -> tuple[int | None, float | None]:
    """(days, sharpe) with explicit precedence: an explicit --paper-stats file
    always wins; else auto-gather from trades.pnl_daily when a DSN is set;
    else (None, None) — unmeasured, fail-closed (unchanged behaviour)."""
    if path:
        print(f"paper stats: from --paper-stats file {path}")
        return _gather_paper_stats(path)
    if dsn:
        from services.trader.ops.paper_stats import gather_paper_stats  # noqa: E402

        stats = gather_paper_stats(dsn)
        print(
            "paper stats: auto-gathered from trades.pnl_daily via MAHORAGA_DSN "
            f"(days={stats.days}, sharpe={stats.sharpe})"
        )
        return stats.days, stats.sharpe
    print("paper stats: no --paper-stats file and no MAHORAGA_DSN; criteria will fail closed")
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--date",
        required=True,
        help="as-of date (YYYY-MM-DD) stamped on the report; required — no "
        "datetime.now fallback (replay-safe convention)",
    )
    parser.add_argument(
        "--paper-stats",
        help='JSON file with {"days": int, "sharpe": float}; wins over auto-gathering '
        "from trades.pnl_daily (which needs MAHORAGA_DSN)",
    )
    parser.add_argument(
        "--hindsight",
        default=os.environ.get("HINDSIGHT_URL"),
        help="Hindsight base URL (default: $HINDSIGHT_URL; unset -> kb_depth fails closed)",
    )
    parser.add_argument("--out", help="output path (default docs/convergence/<date>-report.md)")
    args = parser.parse_args()

    dsn = os.environ.get("MAHORAGA_DSN")
    replay_years, regime_coverage = _gather_replay_and_coverage()
    paper_days, paper_sharpe = _resolve_paper_stats(args.paper_stats, dsn)
    inputs = ConvergenceInputs(
        deployment_eligible=_gather_registry(dsn),
        replay_years=replay_years,
        regime_coverage=regime_coverage,
        kb_facts=_gather_kb_facts(args.hindsight),
        paper_days=paper_days,
        paper_sharpe=paper_sharpe,
    )

    report = evaluate(inputs, generated=args.date)
    out = Path(args.out) if args.out else ROOT / "docs/convergence" / f"{args.date}-report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(report))

    print(f"\nwrote {out}")
    for c in report.criteria:
        print(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name}: {c.measured} (need {c.threshold})")
    print(f"\nVERDICT: {'READY' if report.ready else 'NOT READY'} for real capital")
    print("(a passing report is necessary but NOT sufficient — human sign-off required)")
    return 0  # always: a failing report is a valid artifact


if __name__ == "__main__":
    raise SystemExit(main())
