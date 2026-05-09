<!-- SPDX-License-Identifier: Apache-2.0 -->

# `services/trader/universe` — Universe Management

Phase 1 sub-feature 2. Provides point-in-time-correct membership for the
trading universe so backtests don't bake in survivorship bias.

Design docs (read these first):

- [`docs/superpowers/specs/phase-1-foundation/universe-spec.md`](../../../docs/superpowers/specs/phase-1-foundation/universe-spec.md)
- [`docs/superpowers/specs/phase-1-foundation/universe-and-vault-plan.md`](../../../docs/superpowers/specs/phase-1-foundation/universe-and-vault-plan.md)
- [`docs/superpowers/specs/phase-1-foundation/universe-and-vault-tasks.md`](../../../docs/superpowers/specs/phase-1-foundation/universe-and-vault-tasks.md)

## Layout

```
services/trader/universe/
├── models.py        UniverseEvent / UniverseEntry / UniverseSeed dataclasses
├── loader.py        Universe.load(root) + members / is_member / history / etf_allowlist
├── tests/           pytest fixtures
└── README.md        this file

data/universe/
├── sp500/{seed.yaml, events.yaml}
├── russell1000/{seed.yaml, events.yaml}
└── etfs.yaml
```

## Usage

```python
from datetime import date
from services.trader.universe import Universe

u = Universe.load("data/universe")

# Point-in-time membership
members = u.members(name="sp500", asof=date(2018, 6, 25))
assert "GE" in members  # GE was still in S&P 500 the day before its removal

# ETF allowlist filtered by listing/delisting date
sectors = u.etf_allowlist(asof=date(2026, 5, 1))
print([e.ticker for e in sectors if e.category.startswith("sector")])
```

## YAML schema

Each named universe lives in `data/universe/<name>/` with two files:

- `seed.yaml` — the initial membership on `seed_date`
- `events.yaml` — sorted list of `{date, ticker, action: add|remove, note}`

Membership on date Y is `seed_members ∪ {add events ≤ Y} ∖ {remove events ≤ Y}`.

The loader rejects malformed YAML at startup:

| Violation | Error |
|---|---|
| Seed name disagrees with parent directory | `UniverseSchemaError: name field disagrees` |
| Event predates `seed_date` | `predates seed_date` |
| Events not sorted by date | `precedes prior event` |
| Double-add of an existing member | `already a member` |
| Remove of a non-member | `not a member` |
| Duplicate ticker in `etfs.yaml` | `duplicate ticker` |

## Status

| Chunk | Branch | Status |
|---|---|---|
| U1. YAML schema + loader | `phase-1-universe-yaml-and-loader` | Merged |
| U2. Bootstrap scripts (Wikipedia) | `phase-1-universe-bootstrap-scripts` | Merged |
| U3. Index-reproduction audit | `phase-1-universe-index-reproduction` | **In review (this PR)** |

## Operator runbook (chunk U2)

Regenerate the S&P 500 YAML files from the latest Wikipedia snapshot:

```bash
python scripts/build_sp500_universe.py \
    --root data/universe \
    --seed-date 2014-01-01
```

Optional environment variables:

- `MAHORAGA_AUDIT_DSN` (or `MAHORAGA_TEST_DSN`) — Postgres DSN. When set, a
  hash-chained `audit.events` row with `action='universe_rebuild'` is
  written, mirroring the data-foundation manifest pattern.

After the script runs:

- `data/universe/sp500/seed.yaml` — back-derived membership at `seed_date`
- `data/universe/sp500/events.yaml` — adds/removes from `seed_date` to today
- `data/universe/manifests/universe-rebuilds.parquet` — new row per run with
  `run_id`, `seed_size`, `events_count`, error list

Re-running the script is idempotent: same Wikipedia state → same YAML
output (the back-derivation is deterministic). Any divergence between two
consecutive builds reflects real Wikipedia edits.

### Russell 1000 — deferred to a follow-up

FTSE Russell publishes annual reconstitution PRs in June each year, but
the Wikipedia Russell 1000 article doesn't carry a clean changes table.
For Phase 1, Russell 1000 stays on the small hand-curated YAML committed
in U1; a future sub-feature will scrape FTSE Russell directly.

## Index-reproduction audit (chunk U3)

**The load-bearing acceptance test for P1.2.** The mechanism: pull
`Universe.members(name="sp500", asof=last_day_of_month)` for a target
month, look up OHLCV for those tickers via the Phase 1 `ParquetAdapter`,
and compute the equal-weighted price return. A green audit means the
universe + OHLCV layers are aligned — the most common backtest failure
mode (silent survivorship bias) is caught by the comparison.

Two tests exercise this:

1. **`services/trader/universe/tests/test_index_replay.py`** — runs in CI.
   Synthetic 3-ticker universe with hand-computed +10%/+5%/-5% monthly
   moves; asserts the equal-weighted return is exactly `(0.10+0.05-0.05)/3
   = +3.33%`. Catches mechanism bugs without needing live HTTP.

2. **`tests/integration/phase-1/universe/test_index_reproduction.py`** —
   operator-run, **opt-in via `MAHORAGA_LIVE_AUDIT=1`**. Reads the
   operator-populated S&P 500 YAML + the operator-populated `data/parquet/
   ohlcv/` files for July 2018. Asserts the equal-weighted return lands
   inside a generous sanity range (currently `[-5%, +10%]`) and that
   ≥100 of the ~500 constituents have OHLCV — gross misses indicate
   the operator hasn't fully run the ingest.

Operator runbook for the live audit:

```bash
# 1. Populate the full S&P 500 history
python scripts/build_sp500_universe.py

# 2. Ingest yfinance OHLCV for the audited month (the Phase 1 ingest
#    orchestrator handles this; this is a placeholder until the trader
#    service ships an end-to-end CLI)
python -m services.trader.data.ingest \
    --start 2018-07-01 --end 2018-07-31 \
    --tickers $(yq '.members | join(" ")' data/universe/sp500/seed.yaml)

# 3. Run the live audit
MAHORAGA_LIVE_AUDIT=1 pytest tests/integration/phase-1/universe -v
```

The reference number for July 2018 is loose by design — the goal is
"did we reconstruct the index correctly?" not "match a vendor's number
exactly". If the audit fails, the fastest debugging step is comparing
the per-ticker `report.constituent_returns` dict against an external
data source for a handful of names.

## What U1 ships vs U2

The YAML files committed with U1 cover only a small bootstrap subset (~20
S&P 500 tickers + 3 add/remove events spanning 2014–2018). The loader works
the same way on the full ≥10 y history; chunk U2 adds the bootstrap scripts
that fetch Wikipedia + FTSE Russell PRs and write the full seed + events
files.
