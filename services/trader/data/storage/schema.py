"""Row schemas for the parquet-backed storage adapter.

Two row types:

- `OhlcvRow`  — daily/intraday bars for equities + ETFs.
  Natural key: `(ticker, bar_timestamp, source)`.
  Restatements add a new row with non-null `revision_at`; the original publication
  is the row with `revision_at = None`.

- `MacroRow`  — macro indicators (CPI, GDP, yields, …) with PIT discipline.
  Natural key: `(indicator, reference_date, source, as_of_release_date)`.
  A restatement of a previously published value is a new row with a later
  `as_of_release_date`.

The PyArrow schemas pin the on-disk types so files written from any future
runtime version are still readable.

See `docs/superpowers/specs/phase-1-foundation/data-foundation-spec.md` §6.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pyarrow as pa


@dataclass
class OhlcvRow:
    ticker: str
    bar_timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_close: float
    source: str
    fetched_at: datetime
    revision_at: datetime | None = None


@dataclass
class MacroRow:
    indicator: str
    reference_date: date
    as_of_release_date: date
    value: float
    unit: str
    source: str
    fetched_at: datetime


# --- PyArrow schemas -----------------------------------------------------

OHLCV_ARROW_SCHEMA = pa.schema(
    [
        pa.field("ticker", pa.string(), nullable=False),
        pa.field("bar_timestamp", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("open", pa.float64(), nullable=False),
        pa.field("high", pa.float64(), nullable=False),
        pa.field("low", pa.float64(), nullable=False),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("volume", pa.int64(), nullable=False),
        pa.field("adj_close", pa.float64(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("revision_at", pa.timestamp("us", tz="UTC"), nullable=True),
    ]
)


MACRO_ARROW_SCHEMA = pa.schema(
    [
        pa.field("indicator", pa.string(), nullable=False),
        pa.field("reference_date", pa.date32(), nullable=False),
        pa.field("as_of_release_date", pa.date32(), nullable=False),
        pa.field("value", pa.float64(), nullable=False),
        pa.field("unit", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)


OHLCV_NATURAL_KEY = ("ticker", "bar_timestamp", "source", "revision_at")
MACRO_NATURAL_KEY = ("indicator", "reference_date", "source", "as_of_release_date")


def schema_for(kind: str) -> pa.Schema:
    if kind == "ohlcv":
        return OHLCV_ARROW_SCHEMA
    if kind == "macro":
        return MACRO_ARROW_SCHEMA
    raise ValueError(f"unknown kind: {kind!r}")


def natural_key_for(kind: str) -> tuple[str, ...]:
    if kind == "ohlcv":
        return OHLCV_NATURAL_KEY
    if kind == "macro":
        return MACRO_NATURAL_KEY
    raise ValueError(f"unknown kind: {kind!r}")
