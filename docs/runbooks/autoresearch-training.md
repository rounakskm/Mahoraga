# Runbook — Start an Autoresearch Training Run

How to run Mahoraga's autoresearch loop (Phase 3, Layer 1) from a clean checkout,
and how to watch results **live while it trains**. The loop is self-contained:
no Postgres, no Hermes, no LLM, no network — pure Python on real SPY data.

## What it does (one paragraph)

The loop mutates a **regime-conditional** strategy (in each market regime —
trending/ranging × low/high vol — it holds SPY when price is above that regime's
SMA), backtests each candidate on ~10 years of real SPY, runs it through the
**Phase-2 anti-overfitting fortress** (4 walls + 3 gates), and keeps the best
*promoted* candidate. It hill-climbs toward a better regime→behaviour map, and the
fortress filters out fragile / overfit / high-drawdown candidates. The search runs
**only on training data**; the promoted best is then validated on the held-out
**vault** (the last `--vault-days`, default 180, that the search never saw) — it is
deployment-eligible only if its edge survives there.

---

## Prerequisites (once)

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) installed.
- This repo checked out.

```bash
cd Mahoraga
uv sync                 # installs deps incl. RiskLabAI (numba). First run is slow (~1-2 min, native build).
```

## Step 1 — Data (optional)

The loop loads SPY from the Phase-1 parquet store if present, otherwise it falls
back to the committed real-SPY fixture (2,882 bars, 2015-2026) — so **a first run
needs no data setup**. To pull fresh / full SPY daily yourself (needs network):

```bash
uv run python scripts/pull_spy_daily.py        # -> data/parquet/ohlcv/SPY/
```

## Step 2 — Start training

```bash
uv run python scripts/run_autoresearch.py --iterations 50
# add --llm to use the Nemotron mutator (Layer 2; needs NVIDIA_API_KEY) --seed 0
```

Flags: `--iterations N` (default 50; ~1 s/iteration), `--seed S` (reproducible run).

You'll see a live per-iteration stream:

```
SPY: 2882 bars 2015-01-02 -> 2026-06-18
running 50 mechanical iterations through the fortress...

  iter   0  Sharpe +0.0644  [BEST]  promoted
  iter   1  Sharpe +0.0541  [ok ]  promoted
  iter   3  Sharpe +0.0634  [   ]  rejected by gates: fitness
  ...
promoted 41/50 | best daily Sharpe 0.0704
best regime->window: {'trending_low_vol': 240, 'trending_high_vol': 230, 'ranging_low_vol': 30, 'ranging_high_vol': 30}
live results -> data/autoresearch/run_seed0_2882bars.csv
```

`[BEST]` = a new best promoted candidate · `[ok ]` = promoted · `[   ]` = rejected
(the `reason` column says which gate).

## Step 3 — Watch / visualize live (from a second terminal)

The run appends every iteration to a CSV **as it happens**, so you can watch or
plot mid-run without stopping it.

**Tail it:**
```bash
tail -f data/autoresearch/run_seed0_2882bars.csv
```

**Live summary (re-run any time during training):**
```bash
uv run python - <<'PY'
import pandas as pd, glob
f = sorted(glob.glob("data/autoresearch/run_*.csv"))[-1]
d = pd.read_csv(f)
print(f"{len(d)} iterations | promoted {d.promoted.sum()} | best Sharpe {d[d.is_best].sharpe.max():.4f}")
print(d.tail(10)[["index","sharpe","promoted","is_best","reason"]].to_string(index=False))
PY
```

**Quick plot of the Sharpe trajectory (optional):**
```bash
uv run --with matplotlib python - <<'PY'
import pandas as pd, glob, matplotlib.pyplot as plt
d = pd.read_csv(sorted(glob.glob("data/autoresearch/run_*.csv"))[-1])
plt.plot(d["index"], d["sharpe"], ".-"); plt.scatter(d[d.is_best]["index"], d[d.is_best]["sharpe"], c="r", label="best")
plt.xlabel("iteration"); plt.ylabel("daily Sharpe"); plt.legend(); plt.savefig("data/autoresearch/trajectory.png")
print("saved data/autoresearch/trajectory.png")
PY
```

## Step 4 — Read the results

`data/autoresearch/run_*.csv` columns:

| column | meaning |
|---|---|
| `index` | iteration number |
| `sharpe` | candidate's daily Sharpe over the full SPY history |
| `promoted` | did it clear all 3 gates (fitness/robustness/risk)? |
| `is_best` | promoted **and** a new high-water Sharpe (the loop adopted it) |
| `windows` | the regime→SMA-window map (the strategy itself) |
| `reason` | gate verdict — e.g. `rejected by gates: fitness, risk` |

The **best** strategy is the highest-Sharpe `is_best=True` row's `windows`.

## What to expect (and why)

- **Most micro-tweaks promote.** On a coherent strategy family over a bull-market
  decade, the candidates are genuinely *valid* variations — the fortress isn't
  meant to reject good strategies. Its **rejection teeth** show on genuinely overfit
  candidates: see the calibration proof (`tests/integration/phase-2/calibration/`)
  where an overfit 16-config grid is rejected with PBO=0.84.
- **PBO is skipped inside the loop on purpose.** PBO (CSCV) needs a *diverse* set of
  hypotheses; a hill-climb of near-identical SMA tweaks is ~0.97 correlated, where
  PBO is pure noise. The loop relies on DSR + the complexity/generalization/risk
  gates instead. PBO re-engages at Layer 2 when the LLM proposes distinct strategies.
- **This is in-sample optimisation.** Walk-forward + per-regime checks guard
  robustness, but the *true* out-of-sample guard is the **vault holdout** (last 6
  months embargoed) — that's the next Layer-1 slice; until it lands, treat the best
  Sharpe as in-sample.
- **Runtime:** ~1 s/iteration (dominated by the perturbation backtests + numba JIT
  warmup on iteration 0).

## Troubleshooting

- *First run hangs ~1 min at iter 0* — numba is JIT-compiling RiskLabAI; normal, once.
- *`No module named ...`* — run via `uv run` (not bare `python`) so the project env is used.
- *Want a fresh seed each time* — pass a different `--seed`.
