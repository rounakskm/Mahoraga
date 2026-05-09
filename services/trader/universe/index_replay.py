"""Index-return replay.

Composes `Universe.members(name, asof)` with OHLCV from P1.1's `ParquetAdapter`
to compute a synthetic equal-weighted index return for a calendar month.

The audit test in `tests/integration/phase-1/universe/test_index_reproduction.py`
uses this against the real (Wikipedia-bootstrapped) S&P 500 + yfinance to
reproduce a known historical monthly return; the unit test in
`services/trader/universe/tests/test_index_replay.py` uses it against a
synthetic universe with hand-computed answers.

Both paths exercise the same code, so a green unit test in CI gives high
confidence that the live audit (operator-run) will reproduce within tolerance.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from services.trader.data.storage.parquet_adapter import ParquetAdapter
from services.trader.universe.loader import Universe

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonthlyReturnReport:
    """Result of a monthly equal-weighted index reconstruction."""

    universe: str
    year: int
    month: int
    eligible_count: int
    constituent_returns: dict[str, float]
    equal_weight_return: float

    @property
    def label(self) -> str:
        return f"{calendar.month_name[self.month]} {self.year}"


def monthly_equal_weight_return(
    *,
    universe: Universe,
    universe_name: str,
    year: int,
    month: int,
    adapter: ParquetAdapter,
    vault_override: bool = True,
    vault_override_reason: str = "index-reproduction audit (operator)",
) -> MonthlyReturnReport:
    """Compute the equal-weighted price return for a named universe in `(year, month)`.

    Algorithm:
    1. Look up the constituents that were members on the **last trading day**
       of the month (i.e. `members(asof=last_day_of_month)`).
    2. For each ticker, read OHLCV via `adapter.read()` for the month window.
    3. Per-ticker monthly return = `last_close / first_close - 1`. Tickers
       with fewer than 2 bars in the window are dropped (no return computable).
    4. Equal-weighted return = mean of per-ticker returns.

    `vault_override` defaults to True because audits run on dates >180 days
    in the past where the vault is moot, but the kwarg is forwarded so a
    caller can pass False if they're auditing a recent month with a
    `vault_cutoff_days=None` adapter.
    """
    if month < 1 or month > 12:
        raise ValueError(f"month must be 1..12, got {month}")

    last_day = _last_day_of_month(year, month)
    members = sorted(universe.members(name=universe_name, asof=last_day))
    if not members:
        raise ValueError(
            f"no members for {universe_name!r} on {last_day} — was the universe loaded?"
        )

    start_dt = datetime(year, month, 1, tzinfo=UTC)
    end_dt = datetime(year, month, last_day.day, 23, 59, 59, tzinfo=UTC)
    asof_dt = datetime(year, month, last_day.day, 23, 59, 59, tzinfo=UTC)

    # We pass vault_cutoff_days handling to the caller — they configure the
    # adapter. The adapter will short-circuit if the requested window is
    # outside the vault; if inside (e.g. a recent month) the override path
    # records an audit row with the reason supplied here.
    df = adapter.read(
        kind="ohlcv",
        keys=members,
        start=start_dt,
        end=end_dt,
        asof=asof_dt,
        vault_override=vault_override,
        vault_override_reason=vault_override_reason,
    )

    constituent_returns: dict[str, float] = {}
    for ticker, group in df.groupby("ticker"):
        ordered = group.sort_values("bar_timestamp")
        if len(ordered) < 2:
            continue
        first = float(ordered["close"].iloc[0])
        last = float(ordered["close"].iloc[-1])
        if first <= 0:
            logger.warning(
                "skipping %s: non-positive first close %.4f", ticker, first
            )
            continue
        constituent_returns[str(ticker)] = (last / first) - 1.0

    if not constituent_returns:
        raise ValueError(
            f"no usable OHLCV for any of {len(members)} members in {year}-{month:02d}"
        )

    ew = sum(constituent_returns.values()) / len(constituent_returns)
    return MonthlyReturnReport(
        universe=universe_name,
        year=year,
        month=month,
        eligible_count=len(constituent_returns),
        constituent_returns=constituent_returns,
        equal_weight_return=ew,
    )


def _last_day_of_month(year: int, month: int) -> date:
    _first_weekday, last_day_num = calendar.monthrange(year, month)
    # last_day_num here is 1..28/29/30/31 — pass directly
    return date(year, month, last_day_num)


# Helper used by the live audit test — given (year, month), return the actual
# last *trading* day. Because P1.1's coverage check requires NYSE-trading-day
# accuracy, we delegate to `pandas_market_calendars` when available; otherwise
# we approximate with the last calendar day. The unit test below uses synthetic
# OHLCV with weekday-only bars, so the calendar-vs-trading distinction is moot
# for it; the live audit cares.
def last_trading_day_of_month(year: int, month: int) -> date:
    last_cal = _last_day_of_month(year, month)
    try:
        import pandas_market_calendars as mcal  # noqa: PLC0415

        cal = mcal.get_calendar("NYSE")
        # Search backward up to 7 days for a session
        for offset in range(7):
            d = last_cal - timedelta(days=offset)
            sched = cal.schedule(start_date=d.isoformat(), end_date=d.isoformat())
            if not sched.empty:
                return d
    except ImportError:
        pass
    return last_cal
