# Phase 1 — Data Foundation Spec (sub-feature 1)

**Status:** Drafted 2026-05-09
**Parent:** [`spec.md`](spec.md), [`plan.md`](plan.md), [`tasks.md`](tasks.md)
**Predecessor:** Phase 0 substrate
**Owner stream:** A (data) — critical path

---

## 1. Goal

Stand up the data plumbing that every later sub-feature depends on:

- A connector layer that pulls **OHLCV (equities + ETFs)** and **macro indicators** from free public APIs.
- A parquet-backed storage adapter that writes **append-only** with point-in-time-correct read semantics.
- A PIT discipline contract enforced at the storage layer (not in strategy code) so that no Mahoraga component can read data that wouldn't have been publicly available at the simulated bar timestamp.
- A rate-limit / backoff / fail-loud policy that protects free-tier API budgets and refuses to silently drop bars.

By exit, downstream sub-features (universe, vault embargo, feature pipeline, regime detector, backtest harness) can call `read(symbol, start, end, asof=t)` and get a PIT-correct DataFrame without ever knowing how the data got there.

## 2. In scope

- **OHLCV** for the Phase 1 universe: S&P 500 + Russell 1000 equities + the ETF allowlist (broad, sector, commodity, thematic). Daily bars first; intra-day (1-min) capability added if a free source is reliable enough.
- **Macro indicators** with PIT discipline: GDP, CPI/Core CPI, PCE/Core PCE, unemployment, NFP/JOLTS, ISM PMI, retail sales, industrial production. Treasury yields at 1M / 3M / 6M / 1Y / 2Y / 5Y / 10Y / 30Y. TIPS / breakevens at 5Y / 10Y / 30Y. CBOE VIX / VIX9D / SKEW / put-call ratio.
- **Storage layout** under `data/parquet/{ohlcv,macro}/...` (bind-mounted from compose).
- **Storage-adapter API surface** that the feature pipeline / regime detector / backtest harness consume.
- **Rate-limit + backoff + coverage monitor** with audit-log integration.

## 3. Out of scope (for this sub-feature)

- **BTC-ETF + spot-BTC connectors** — deferred to `btc-data-spec.md` per Phase 1 plan.md §3.
- **Universe management** (PIT constituents, ETF allowlist YAML) — owned by `universe-spec.md`.
- **Vault embargo enforcement** — owned by `vault-embargo-spec.md`. This spec exposes the *hook* the embargo will plug into; it does not enforce.
- **Feature engineering** — owned by `feature-pipeline-spec.md`.
- **News / sentiment / reddit** — Phase 4. The connector layer's design must not preclude adding these later, but no Phase 1 work happens on them.

## 4. Architecture sketch

```
┌────────────────────────────────────────────────────────────────────────┐
│ services/trader/data/                                                  │
│                                                                        │
│   connectors/        — one module per source, sharing a Connector ABC  │
│     yfinance.py        OHLCV for equities + ETFs                       │
│     fred.py            macro indicators (GDP, CPI, unemployment, …)    │
│     bls.py             labor-data fallback / cross-check               │
│     treasury.py        Treasury yields (TreasuryDirect + FRED)         │
│     cboe.py            VIX / VIX9D / SKEW (CBOE pages or FRED proxy)   │
│                                                                        │
│   storage/                                                             │
│     parquet_adapter.py read / write / list / gaps                      │
│     pit.py             PIT-correct view logic (release_date <= asof)   │
│     schema.py          dataclasses for the row shapes                  │
│                                                                        │
│   ingest.py            orchestrator: loop over connectors → write      │
│   coverage.py          post-ingest gap + completeness reporting        │
│   audit.py             audit-log writes for every ingest run           │
│                                                                        │
│   tests/               pytest suite (unit + integration)               │
└────────────────────────────────────────────────────────────────────────┘
```

Plain Python; no NemoClaw / OpenClaw glue (substrate-portable per CLAUDE.md item 7). Runs inside the host or any container; the parquet root is a config knob.

## 5. Connector inventory + rate-limit posture

| Source | Coverage | Free-tier limit | Posture |
|---|---|---|---|
| **yfinance** (Yahoo Finance) | OHLCV daily + intra-day for equities + ETFs; some adjustments | unofficial, soft-rate-limited; documented ~2 req/s sustained | Primary OHLCV connector. Token-bucket throttle. Single-symbol backoff on transient errors; per-symbol partial-failure tolerance. |
| **FRED** (St. Louis Fed) | Macro indicators + Treasury yields + breakevens + some CBOE indices | 120 req/min with API key; lower without | Primary macro connector. Get a key in `.env`; fail loud if missing. Per-series fetch is one HTTP call; cache locally to avoid re-fetching. |
| **BLS** (Bureau of Labor Stats) | CPI components, NFP detail, unemployment | 25 req/day unauthenticated; 500 req/day with key | Cross-check/fallback for FRED CPI/unemployment when release dates disagree. Rarely used directly. Get a key. |
| **TreasuryDirect** | Treasury yield curves (constant-maturity) | unauthenticated public CSV/XML; no documented limit | Fallback for FRED yield series; useful for cross-validation. |
| **CBOE** (vix.com / cboe.com pages) | VIX / VIX9D / SKEW / put-call | unauthenticated public; rate-limited by HTML scraping politeness | Last-resort. Prefer FRED's `VIXCLS` series. |

A `Connector` ABC defines:

```python
class Connector(ABC):
    name: str
    rate_limiter: RateLimiter

    def fetch(self, key: str, start: date, end: date) -> ConnectorResult: ...
    def health(self) -> HealthStatus: ...
    def rate_limit_status(self) -> RateLimitStatus: ...
```

`ConnectorResult` is a normalized DataFrame plus per-row provenance: `source`, `fetched_at`, `as_of_release_date` (for macro), `revision_at` (for OHLCV restatements when applicable).

## 6. Storage layout

```
data/parquet/
  ohlcv/
    {SYMBOL}/
      {YEAR}.parquet              — daily bars; partition key = year
      {YEAR}-{MM}.parquet         — intra-day bars when sourced; partition key = month
  macro/
    {INDICATOR}/
      {YEAR}.parquet              — partition key = release_year (NOT reference_year)
  manifests/
    ingest-runs.parquet           — one row per ingest run (run_id, source, started_at, finished_at, rows_written, coverage_pct, errors)
```

OHLCV row schema (PyArrow):

```
ticker:               string
bar_timestamp:        timestamp[us, tz=UTC]
open / high / low / close: float64
volume:               int64
adj_close:            float64
source:               string
fetched_at:           timestamp[us, tz=UTC]
revision_at:          timestamp[us, tz=UTC] | null
```

Macro row schema:

```
indicator:            string
reference_date:       date            — the period the value covers (e.g. 2026-01)
as_of_release_date:   date            — when this value first became public (e.g. 2026-02-13)
value:                float64
unit:                 string
source:               string
fetched_at:           timestamp[us, tz=UTC]
```

Append-only. **Rewrites are forbidden**; corrections / restatements land as a new row with a later `revision_at` or `as_of_release_date`, and the PIT reader picks the row whose `as_of_release_date <= asof` (or `revision_at <= asof` for OHLCV) most recent.

## 7. PIT discipline contract

The storage adapter exposes exactly one read primitive for time-series data:

```python
def read(
    self,
    kind: Literal["ohlcv", "macro"],
    keys: list[str],            # ticker(s) or indicator name(s)
    start: datetime,
    end: datetime,
    asof: datetime | None = None,   # default = now (UTC)
) -> pd.DataFrame
```

Contract:

1. **Reference window** is `[start, end]` (the bars the caller wants).
2. **As-of cutoff** is `asof` (the simulated "today"). If `None`, use real-time now.
3. The reader returns only rows where:
   - For OHLCV: `bar_timestamp ∈ [start, end]` AND `(revision_at IS NULL OR revision_at <= asof)`.
   - For macro: `reference_date ∈ [start, end]` AND `as_of_release_date <= asof`.
4. When multiple rows exist for the same `(key, reference_date)` differing only in revision/release time, the reader returns the **latest version that was public at `asof`** — never a value that wasn't yet public.
5. **No silent omission.** If a key has zero rows in the window, the reader returns an empty DataFrame for that key; the caller's coverage check decides if that's an error. We never quietly substitute or interpolate.

This contract is the single chokepoint that prevents look-ahead bias. The `audit-xls` reviewer prompt (already merged at `services/trader/prompts/reviewer/audit-xls.md`) treats any backtest output not produced via this read primitive as a fatal failure.

## 8. Multi-source PIT consistency

When two sources cover the same indicator (FRED CPI vs BLS CPI, FRED yields vs TreasuryDirect):

- The storage adapter writes **both** with their respective `source` and `as_of_release_date`. It does not merge.
- Feature-pipeline joiners that combine series across sources use the **latest** `as_of_release_date` across the joined inputs as the conservative join key. Example: joining CPI (released Feb 13) with NFP (released Feb 7) for January 2026 reference month uses `as_of = max(2026-02-13, 2026-02-07) = 2026-02-13`.
- A series with no `as_of_release_date` (i.e. OHLCV) joins on `bar_timestamp` and `revision_at`.

The conservative rule is the safe default. A future spec may relax it for use cases where partial information at the earliest release date is the load-bearing signal — but Phase 1 ships the conservative rule.

## 9. Rate-limit + backoff + fail-loud behavior

- Each connector owns a `RateLimiter` (token bucket, refill per documented free-tier rate).
- Transient failures (HTTP 429, 5xx, connection errors) → exponential backoff with jitter, max 5 attempts.
- Permanent failures (HTTP 4xx other than 429) → raise `ConnectorError` immediately; do **not** retry, do **not** silently skip.
- Coverage monitor (`coverage.py`) computes per-symbol completeness after each ingest run:
  - For OHLCV: bars present / expected bars per the trading calendar
  - For macro: rows present / expected releases for the requested window
- A **fresh** ingest run targets ≥99% per-symbol coverage; below threshold raises a `CoverageError`. A **backfill** run targets ≥95% over the requested window; below threshold logs a warning and continues, but writes the gap details to the manifests.
- Every ingest run writes a row to `manifests/ingest-runs.parquet` and an event to Postgres `audit.events` with `actor='data-ingest'`, `action='ingest'`, payload = `{run_id, source, started_at, finished_at, rows_written, coverage_pct, errors[]}`.

## 10. Acceptance / exit criteria

This sub-feature lands when:

1. ✅ `services/trader/data/` package exists with the layout in §4.
2. ✅ `yfinance` connector ingests OHLCV for a sample equity universe (≥50 names + 10 ETFs) for a 1-year window without exceeding the rate-limit budget.
3. ✅ `fred` connector ingests at least 10 macro indicators with `as_of_release_date` populated correctly (verified against FRED's release-calendar API).
4. ✅ Storage adapter passes the round-trip + PIT correctness tests:
   - Round-trip: write → read returns identical rows.
   - PIT correctness: insert row with `as_of_release_date = future_date`, read at `asof = today` → row excluded; read at `asof = future_date` → row included.
   - Multi-source consistency: insert two CPI rows for the same `reference_date` from FRED and BLS with different `as_of_release_date`; reader returns both; joiner picks the conservative one.
5. ✅ Rate-limit test: stub 429 → backoff observable in test logs; permanent 401 → `ConnectorError` raised, not retried.
6. ✅ Coverage monitor catches a deliberate gap (drop a known bar before reading) and surfaces it.
7. ✅ Audit-log integration: every ingest run produces exactly one row in `manifests/ingest-runs.parquet` and one row in Postgres `audit.events`.
8. ✅ All `tests/integration/phase-1/data-foundation/*` tests green in CI.

## 11. Open questions

| Question | Default if undecided | When to revisit |
|---|---|---|
| Free FRED API key — does the operator have one already? | Treat as missing; fail-loud on first FRED call until the key lands in `.env` | Before P1.1.code lands |
| yfinance reliability for Russell 1000 illiquid names | Accept some per-symbol coverage <99%, escalate names that fall <90% to operator review | After first full-universe ingest run |
| Intra-day bars for Phase 1 | Default daily-only; revisit if Phase 2 backtest harness needs intra-day for the FitnessReport methodology | When `backtest-harness-spec.md` is drafted |
| Restatement handling for OHLCV (yfinance occasionally re-issues split / dividend adjustments) | Append-only with `revision_at`; PIT reader picks the latest pre-`asof` revision | Once we have observed a real restatement event |

## 12. Risks specific to this sub-feature

- **yfinance unofficial API changes silently** — coverage monitor catches the symptom; mitigation is a documented escape valve to swap in Polygon (paid) without changing the storage adapter.
- **Macro release-date calendar drift** — FRED's release-calendar API is the source of truth; we cache it daily. If a release is rescheduled, the next cache pull picks it up.
- **Append-only blowup on full-history backfills** — partition by year keeps individual file sizes small; manifest tracks total row count to alert if growth exceeds expected ~0.5GB/year for the full equity universe.

## 13. What this spec hands off to its plan

`data-foundation-plan.md` (next file) breaks this spec into PR-sized chunks: connector skeleton + first connector → parquet writer → PIT view → second connector → coverage + audit → tests. Each chunk is sized for <60 minute review.
