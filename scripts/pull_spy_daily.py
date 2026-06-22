"""Throwaway: pull ~10y of SPY daily OHLCV via the existing Phase-1 data foundation.

Reuses YFinanceConnector + ParquetAdapter + Ingest (BACKFILL mode). Does NOT
reimplement any fetch/storage logic. `data/` is gitignored so this writes local
data only.

Run:
    uv run python scripts/pull_spy_daily.py
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from services.trader.data.audit import make_audit_logger_from_env
from services.trader.data.connectors.yfinance import YFinanceConnector
from services.trader.data.coverage import nyse_trading_days
from services.trader.data.ingest import Ingest, IngestMode
from services.trader.data.storage import ParquetAdapter

ROOT = "data/parquet"
TICKER = "SPY"
START = date(2015, 1, 1)
END = date.today()


def main() -> None:
    # Backfill job: vault_cutoff_days=None is the documented opt-out so the
    # orchestrator's internal coverage read-back can see the recent (vault-window)
    # rows it just wrote. Writes are never gated by the vault; only reads are.
    adapter = ParquetAdapter(ROOT, vault_cutoff_days=None)
    audit = make_audit_logger_from_env(parquet_root=ROOT)
    ingest = Ingest(adapter=adapter, audit=audit)

    print(f"Fetching {TICKER} daily bars {START} -> {END} (yfinance, real network pull)...")
    result = ingest.run_ohlcv(
        YFinanceConnector(),
        tickers=[TICKER],
        start=START,
        end=END,
        mode=IngestMode.BACKFILL,
    )
    print(f"rows_written (new, post-dedupe): {result.rows_written}")
    for r in result.coverage_reports:
        print("coverage:", r.summary)
        if r.missing_sample:
            print("  missing sample:", r.missing_sample)
    if result.failures:
        print("failures:", result.failures)

    # ---- VERIFY: round-trip read back through the adapter ----
    df = adapter.read(
        kind="ohlcv",
        keys=[TICKER],
        start=datetime.combine(START, datetime.min.time(), tzinfo=UTC),
        end=datetime.combine(END, datetime.max.time(), tzinfo=UTC),
        asof=datetime.combine(END, datetime.max.time(), tzinfo=UTC),
    )
    ts = pd.DatetimeIndex(pd.to_datetime(df["bar_timestamp"], utc=True)).normalize()
    distinct_days = ts.normalize().nunique()
    print("\n=== VERIFY (round-trip read) ===")
    print(f"row count:            {len(df)}")
    print(f"distinct trading days:{distinct_days}")
    print(f"first date:           {ts.min().date()}")
    print(f"last date:            {ts.max().date()}")
    print(f"adj_close == close?   {bool((df['close'] == df['adj_close']).all())} "
          f"(False => yfinance returned split/div-adjusted Adj Close)")

    # Gaps vs NYSE calendar over the realized span.
    expected = nyse_trading_days(ts.min().date(), ts.max().date())
    gaps = adapter.gaps(kind="ohlcv", key=TICKER, expected=expected)
    print(f"NYSE expected days:   {len(expected)}")
    print(f"gaps vs NYSE:         {len(gaps)}")
    if gaps:
        print("  gap dates:", [g.date().isoformat() for g in sorted(gaps)][:50])

    print("\nstored partition files:")
    for p in adapter.list_partitions(kind="ohlcv", key=TICKER):
        print(f"  {p}  ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
