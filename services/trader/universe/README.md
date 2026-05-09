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
| U2. Bootstrap scripts (Wikipedia) | `phase-1-universe-bootstrap-scripts` | **In review (this PR)** |
| U3. Index-reproduction audit test | `phase-1-universe-index-reproduction` | Planned |

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

## What U1 ships vs U2

The YAML files committed with U1 cover only a small bootstrap subset (~20
S&P 500 tickers + 3 add/remove events spanning 2014–2018). The loader works
the same way on the full ≥10 y history; chunk U2 adds the bootstrap scripts
that fetch Wikipedia + FTSE Russell PRs and write the full seed + events
files.
