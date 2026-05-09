<!--
Adapted from anthropics/financial-services @ 1c2ece3467c3434ddd01e655970e35b773940a29
Source: plugins/vertical-plugins/financial-analysis/skills/audit-xls/SKILL.md (top-of-file
through Section 3g; full source is ~250 lines of Excel/financial-model audit guidance)
License: Apache 2.0 (preserved below)
Adapted: 2026-05-09 for Mahoraga Reviewer role — the upstream skill audits Excel financial
models (3-statement, DCF, LBO, merger). We don't build those. We DO produce backtest reports
and strategy-mark sheets, and the same audit discipline applies: every derived value must
be reproducible, no hardcoded numbers in formulas, sanity-check ranges, flag suspect logic.
The port keeps the QC philosophy + sanity-test patterns and replaces the model-specific
checks (BS balance, CF tie-out, DCF discount-rate, LBO cash sweep) with backtest-output
analogs (PnL reconstruction, Sharpe sanity, regime-coverage, look-ahead-bias trace).
-->

<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (c) 2026 Anthropic PBC. Adapted by Mahoraga maintainers.
-->

# Audit (Reviewer role)

QC pass on a backtest report or a strategy-mark spreadsheet before the autoresearch loop accepts the output. Three scopes:
- **range** — a single cell range or table
- **report** — one full backtest output (PnL, equity curve, trade log, scorecard)
- **batch** — a multi-strategy autoresearch run before promotion

## Step 1: Determine scope

If the caller provided scope, use it. Otherwise the orchestrator picks based on context:
- Hunter handing off a screen → `range`
- A new mutation candidate finishing backtest → `report`
- An autoresearch sweep finishing → `batch`

The `batch` scope is the deepest — required before any strategy version is promoted from candidate to production-eligible.

## Step 2: Universal checks (all scopes)

| Check | What to look for |
|---|---|
| Numeric errors | NaN, inf, division-by-zero in any output column |
| Hardcoded constants in formulas | A computed metric should be a formula referencing inputs, never a pasted number |
| Off-by-one ranges | Sums or averages that miss the first or last period |
| Time-period consistency | Daily / weekly / monthly bars should not be mixed within one calculation |
| Unit mismatches | Returns expressed as both decimals and percentages in the same table |
| Missing data without explanation | Gaps in a time series must be flagged + reason captured |
| Stale data | Inputs older than expected for the as-of date |
| Look-ahead bias | Any feature that depends on data not yet available at the bar timestamp — **fatal, abort** |

The look-ahead-bias check runs first and gates everything else. A backtest with look-ahead is rejected outright; the strategy version is flagged and excluded from promotion.

## Step 3: Backtest-report integrity (REPORT scope)

### 3a. Structural review

| Check | Test |
|---|---|
| Input/computation separation | Raw price/feature inputs separated from derived signals/positions |
| Period coverage | Backtest covers every regime represented in the universe (bull/bear/sideways/crisis) |
| Vault embargo | Last 6 months of data is excluded from any in-sample step (Phase 7 hard rule) |
| Reproducibility | Backtest seed + data snapshot SHA recorded; rerun produces bit-identical output |

### 3b. PnL reconstruction

| Check | Test |
|---|---|
| Trade log → PnL | Sum of trade-level PnL = aggregate PnL (every period) |
| Cash + position value tie-out | Equity curve = cash + positions marked-to-market every bar |
| Slippage and cost model | Realistic vs. unrealistic — e.g., assuming midpoint fills on illiquid names is a bug |
| Borrow cost on shorts | Modeled or excluded? Excluded must be flagged. |
| Dividend handling | Long positions accrue dividends; shorts pay them — both modeled? |

If equity curve does not reconcile with the trade log, **quantify the gap per period and trace where it breaks** — nothing else matters until reconciled.

### 3c. Statistics

| Check | Test |
|---|---|
| Sharpe sanity | Sharpe > 3 on a public-equity strategy is suspicious — likely look-ahead, in-sample over-fit, or cost model too lenient |
| Drawdown coverage | Max drawdown is computed peak-to-trough across the full sample, not just per regime |
| Trade count sufficiency | <30 trades over the sample → statistics are not statistically meaningful |
| Hit rate vs. avg win / avg loss | Plausible combination — 90% hit rate with 2:1 reward:risk is implausible |

### 3d. Logic and reasonableness

| Check | Flag if |
|---|---|
| Position sizing | Any single position > 5% of portfolio (firewall hard limit — must be enforced upstream, audited downstream) |
| Sector exposure | Any sector > 20% of portfolio |
| Daily loss simulation | Every backtest day exceeds 2% loss → strategy violates daily-halt rule |
| Catastrophic month | Any month worse than -10% → strategy violates catastrophic-suspension rule |
| Regime confidence floor | Any entry taken with regime-detector confidence <40% → strategy violates regime-gate rule |
| Event window respect | Any entry within ±30 min of FOMC/CPI/NFP/earnings → strategy violates firewall blackout |

The hard-limit checks are mandatory. A strategy that simulated trades violating any of them is **rejected from promotion regardless of returns**.

## Step 4: Batch integrity (BATCH scope only)

Run on every autoresearch sweep before any candidate is promoted:

| Check | Test |
|---|---|
| In-sample vs. out-of-sample gap | OOS Sharpe should be within ~30% of in-sample; >50% drop is over-fit |
| Multiple-comparison correction | If N candidates were tested, the threshold for "good" Sharpe rises with N |
| Survivorship bias | Universe must include delisted tickers active during the sample |
| Walk-forward coverage | Every walk-forward step covers ≥30 trades; rebalance-only-on-month-end fails this for thin universes |
| Promotion eligibility | Candidate passes ALL universal checks + ALL hard-limit checks + survives walk-forward |

## Step 5: Output

```json
{
  "audit_id": "uuid",
  "subject": "backtest_id | strategy_version | range_id",
  "scope": "range|report|batch",
  "ran_at": "2026-MM-DD HH:MM TZ",
  "verdict": "pass|warn|fail",
  "warnings": ["array of strings — non-blocking issues"],
  "failures": ["array of strings — blocking issues, each a hard rule violated"],
  "promotion_recommendation": "promote|hold|reject"
}
```

## Important notes

- The audit is independent of the producer. Reviewer never reads the strategy code or the autoresearch loop's mutation reasoning before running checks — that prevents anchoring.
- A `fail` verdict is final; a strategy is not retried with adjusted hyperparameters in the same sweep. Retire and let the next mutation explore differently.
- A `warn` verdict surfaces in the operator's morning note; the operator decides whether to override.
- Audit records persist in `audit.events` and Hindsight; over time the failure-mode catalog feeds back into the autoresearch loop's prior probabilities for known-bad mutation classes.
