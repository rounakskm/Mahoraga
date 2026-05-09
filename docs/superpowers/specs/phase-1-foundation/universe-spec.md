# Phase 1 — Universe Management Spec (sub-feature 2)

**Status:** Drafted 2026-05-09
**Parent:** [`spec.md`](spec.md), [`plan.md`](plan.md), [`tasks.md`](tasks.md)
**Predecessor:** P1.1 data-foundation (merged 2026-05-09)
**Owner stream:** A (data) — runs alongside P1.3 vault-embargo

---

## 1. Goal

Provide a **point-in-time-correct** answer to "which tickers were members of universe X on date Y?" for the Phase 1 trading universe. Without this, every backtest silently bakes in survivorship bias — the most common look-ahead error in backtesting research.

By exit, a caller can:

```python
universe = Universe.load("data/universe")
members = universe.members(name="sp500", asof=date(2018, 1, 1))
# returns the S&P 500 constituents that day, including names
# that have since been delisted or replaced.
```

## 2. In scope

- **S&P 500 PIT membership** — historical constituents covering ≥10 years.
- **Russell 1000 PIT membership** — annual reconstitutions, plus interim adds/drops.
- **ETF allowlist** — broad-market (SPY, QQQ, IWM), sector (XLF, XLK, XLE, XLV, XLY, XLP, XLB, XLU, XLRE, XLC), commodity (GLD, USO), thematic; with `active`/`delisted` markers and listing/delisting dates.
- **Index audit** — reproduce a known historical S&P 500 month return by composing constituents from the universe with OHLCV pulled via P1.1's adapter.

## 3. Out of scope (deferred / Phase 2+)

- BTC ETFs (P1.7 sub-feature; same pattern, different YAML).
- Russell 2000 / Nasdaq 100 / sector-specific universes (Phase 2 if needed).
- Real-time membership tracking (membership advances when a new event YAML lands; no live polling).
- Cross-listings, dual-class shares, or ADR vs. ordinary mappings (out-of-scope; we treat each ticker as opaque).

## 4. Data sources (free)

The original phase-1 spec sketched "PIT constituents from SEC EDGAR", but EDGAR does not publish index membership. The actual free sources we'll use:

| Source | Coverage | Posture |
|---|---|---|
| Wikipedia "List of S&P 500 companies" + "Selected changes" tables | Full S&P 500 history with adds/drops + dates | Bootstrap source. Snapshot via Wikipedia API; scraping fallback. |
| Wikipedia "Russell 1000" article | Recent constituents + reconstitution mentions | Bootstrap. Annual reconstitutions sourced from FTSE Russell PR releases. |
| FTSE Russell reconstitution PRs (free, public) | Annual additions/removals | Manual YAML diff per year; scraped from the publication table. |
| Hand-curated YAML | The ground truth file | What we read at runtime; everything else is bootstrap input. |

**Discipline:** the runtime never hits the internet. Everything reads from `data/universe/` files; bootstrap scripts are `scripts/build_*` jobs the operator runs out-of-band.

## 5. On-disk layout

```
data/universe/
├── sp500/
│   ├── seed.yaml           — initial constituents on 2010-01-01 (or earliest reachable)
│   └── events.yaml         — list of {date, ticker, action: add|remove}
├── russell1000/
│   ├── seed.yaml
│   └── events.yaml
├── etfs.yaml               — allowlist with listing_date/delisting_date per ticker
└── manifests/
    └── universe-rebuilds.parquet   — one row per `scripts/build_*` run
```

`events.yaml` is the load-bearing file. Reconstructing membership on date Y is:

```
members(Y) = seed_set
             ∪ {add events with date ≤ Y}
             ∖ {remove events with date ≤ Y}
```

## 6. API

```python
@dataclass(frozen=True)
class UniverseEntry:
    ticker: str
    listed_at: date | None
    delisted_at: date | None

class Universe:
    @classmethod
    def load(cls, root: Path) -> "Universe": ...

    def members(self, *, name: str, asof: date) -> set[str]: ...
    def is_member(self, *, name: str, asof: date, ticker: str) -> bool: ...
    def history(self, *, name: str, ticker: str) -> list[UniverseEvent]: ...
    def known_universes(self) -> list[str]: ...
    def etf_allowlist(self, *, asof: date) -> list[UniverseEntry]: ...
```

Pure read. No HTTP. `load()` validates the YAML files (events sorted by date, no add-after-add, no remove-before-add).

## 7. Audit / acceptance

| Check | Test fixture |
|---|---|
| `members("sp500", asof=2010-12-31)` matches a known reference list | YAML reference snapshot pulled from Wikipedia |
| `members("sp500", asof=2018-06-29)` includes names known to be in the index that day (e.g. `GE` was still in mid-2018) and excludes those that left earlier | Spot-check |
| Removed tickers stay in the historical list | Don't quietly drop delisted names |
| **Reproduce a known historical index return** — compute the S&P 500 monthly return for July 2018 by composing PIT constituents with OHLCV from P1.1; compare to a published S&P 500 total-return number to within a tolerance (~10 bps for total return, larger for price-return-only since dividends matter) | This is the load-bearing acceptance test |
| ETF allowlist round-trips through YAML without losing fields | Schema validation |

## 8. Substrate-portability + Hindsight

- Pure Python at `services/trader/universe/`. No NemoClaw / OpenClaw imports.
- The universe state is an Experience-Fact-style snapshot in Hindsight (one Mental Model entry per universe, summarising "stable for ≥X days" or "high churn quarter") — Phase 3 work, not P1.2.

## 9. Open questions

| Question | Default if undecided |
|---|---|
| How far back does the Wikipedia S&P 500 history reach? | Bootstrap script fetches whatever's available; if <10 years of clean data, use 2014-01-01 as the earliest seed and accept the truncation in the audit doc. |
| Russell 1000 annual reconstitution date | June "Annual Index Reconstitution Day"; record on first Friday of July as effective date. |
| Special situation: ticker symbol changes (e.g. GOOG→GOOGL split) | Track as a separate `aliases.yaml` mapping `(historical_ticker, asof) -> canonical_ticker`. Read-side translates aliases transparently. Defer to a chunk if non-trivial. |
| ETF rebalancing inside an ETF (not within scope of the universe) | Out of scope; ETFs are tracked as opaque tickers. |

## 10. Plan — three chunks

| # | Branch | What |
|---|---|---|
| 1 | `phase-1-universe-yaml-and-loader` | YAML schema + `Universe.load()` + read API + unit tests |
| 2 | `phase-1-universe-bootstrap-scripts` | `scripts/build_sp500_universe.py` + `scripts/build_russell1000_universe.py` + manifest writes |
| 3 | `phase-1-universe-index-reproduction` | Audit test that reproduces a known monthly S&P 500 return from PIT constituents + P1.1 OHLCV |

Each lands as its own PR per the cadence in `plan.md` §7.

## 11. Acceptance criteria (rolled up)

- ✅ `services/trader/universe/` package with `Universe.load()` API
- ✅ ≥10 years of S&P 500 PIT membership encoded in `data/universe/sp500/`
- ✅ Russell 1000 annual reconstitutions encoded
- ✅ ETF allowlist file maintained
- ✅ Index-reproduction audit test passes within tolerance
- ✅ All `tests/integration/phase-1/universe/` tests green in CI
