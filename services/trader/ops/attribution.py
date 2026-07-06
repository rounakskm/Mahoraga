"""Performance attribution — realized P&L by regime / ticker / side / holding period.

Consumes order rows shaped exactly like the production ``trades.orders`` table
(``infra/postgres/migrations/007_trades.sql``): ``ts``, ``ticker``, ``side``
(BUY/SELL), ``filled_qty``, ``filled_avg_price``, ``status``. Only FILLED rows
(and PARTIAL rows with ``filled_qty > 0``) count as fills.

Fills are paired per ticker FIFO into round trips: a BUY opens or extends a
long lot queue; a SELL consumes long lots FIFO (realized P&L =
``(sell_price - buy_price) * matched_qty``, partial matches split lots). A SELL
with no open long lot opens a SHORT lot, closed by later BUYs with the same
symmetric P&L formula. Each matched lot is one round trip.

Unmatched open lots contribute nothing: unrealized P&L is out of scope here —
it lives in the ``trades.positions`` reconciliation snapshots.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import pandas as pd

# Column names of trades.orders that `attribute` consumes. The test suite
# cross-checks these against the 007_trades.sql DDL text (review lesson).
CONSUMED_COLUMNS: tuple[str, ...] = (
    "ts",
    "ticker",
    "side",
    "filled_qty",
    "filled_avg_price",
    "status",
)

# Order statuses whose fills count toward realized P&L. PARTIAL additionally
# requires filled_qty > 0 (enforced in the row filter below).
_COUNTED_STATUSES: frozenset[str] = frozenset({"FILLED", "PARTIAL"})

_EPS = 1e-9

_UNKNOWN_REGIME = "unknown"


@dataclass(frozen=True)
class AttributionReport:
    """Realized-P&L attribution over completed round trips."""

    total_pl: float = 0.0
    by_regime: dict[str, float] = field(default_factory=dict)
    by_ticker: dict[str, float] = field(default_factory=dict)
    by_side: dict[str, float] = field(default_factory=dict)
    by_holding_period: dict[str, float] = field(default_factory=dict)
    n_round_trips: int = 0


@dataclass
class _Lot:
    """An open (not yet fully matched) fill lot."""

    qty: float
    price: float
    ts: pd.Timestamp


@dataclass(frozen=True)
class _Trip:
    """One matched lot = one completed round trip."""

    ticker: str
    side: str  # "long" (buy-then-sell) or "short" (sell-then-buy)
    pl: float
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp


def _holding_bucket(entry_ts: pd.Timestamp, exit_ts: pd.Timestamp) -> str:
    """Calendar-day holding bucket: intraday / 1-5d / 5-20d / 20d+."""
    days = (exit_ts.normalize() - entry_ts.normalize()).days
    if days == 0:
        return "intraday"
    if days <= 5:
        return "1-5d"
    if days <= 20:
        return "5-20d"
    return "20d+"


def _regime_at(regimes: pd.Series | None, ts: pd.Timestamp) -> str:
    """Nearest-prior (asof) regime label at `ts`; "unknown" when unresolvable."""
    if regimes is None or regimes.empty:
        return _UNKNOWN_REGIME
    index_tz = getattr(regimes.index, "tz", None)
    lookup_ts = ts
    if index_tz is None and lookup_ts.tzinfo is not None:
        lookup_ts = lookup_ts.tz_localize(None)
    elif index_tz is not None and lookup_ts.tzinfo is None:
        lookup_ts = lookup_ts.tz_localize(index_tz)
    label = regimes.asof(lookup_ts)
    if label is None or pd.isna(label):
        return _UNKNOWN_REGIME
    return str(label)


def _fifo_round_trips(fills: pd.DataFrame) -> list[_Trip]:
    """Pair fills per ticker FIFO into completed round trips."""
    trips: list[_Trip] = []
    open_lots: dict[str, deque[_Lot]] = {}
    # Direction of the open lot queue per ticker ("long" / "short"). A fill
    # first closes opposite-direction lots FIFO; any remainder opens (or
    # extends) same-direction lots, so a queue only ever holds one direction.
    direction: dict[str, str] = {}

    for row in fills.itertuples(index=False):
        ticker = str(row.ticker)
        qty = float(row.filled_qty)
        price = float(row.filled_avg_price)
        ts = pd.Timestamp(row.ts)
        opens = "long" if row.side == "BUY" else "short"
        closes = "short" if row.side == "BUY" else "long"

        queue = open_lots.setdefault(ticker, deque())
        while qty > _EPS and queue and direction.get(ticker) == closes:
            lot = queue[0]
            matched = min(qty, lot.qty)
            # Long: buy at lot.price, sell at price. Short: symmetric.
            pl = (
                (price - lot.price) * matched
                if closes == "long"
                else (lot.price - price) * matched
            )
            trips.append(
                _Trip(ticker=ticker, side=closes, pl=pl, entry_ts=lot.ts, exit_ts=ts)
            )
            lot.qty -= matched
            qty -= matched
            if lot.qty <= _EPS:
                queue.popleft()
        if qty > _EPS:
            queue.append(_Lot(qty=qty, price=price, ts=ts))
            direction[ticker] = opens
    return trips


def attribute(
    orders: pd.DataFrame, regimes: pd.Series | None = None
) -> AttributionReport:
    """Attribute realized P&L across regime / ticker / side / holding period.

    `orders` uses the production ``trades.orders`` column names (see
    ``CONSUMED_COLUMNS``). `regimes`, when given, is a DatetimeIndex-indexed
    label Series; each round trip is labeled by the nearest-prior regime at its
    ENTRY timestamp. Empty input or no completed trips returns a zeroed report.
    """
    if orders.empty:
        return AttributionReport()

    counted = orders["status"].isin(_COUNTED_STATUSES)
    fills = orders.loc[
        counted & (orders["filled_qty"] > 0) & orders["filled_avg_price"].notna(),
        list(CONSUMED_COLUMNS),
    ].sort_values("ts", kind="stable")

    trips = _fifo_round_trips(fills)
    if not trips:
        return AttributionReport()

    sorted_regimes = regimes.sort_index() if regimes is not None else None

    total_pl = 0.0
    by_regime: dict[str, float] = {}
    by_ticker: dict[str, float] = {}
    by_side: dict[str, float] = {}
    by_holding_period: dict[str, float] = {}
    for trip in trips:
        total_pl += trip.pl
        regime = _regime_at(sorted_regimes, trip.entry_ts)
        bucket = _holding_bucket(trip.entry_ts, trip.exit_ts)
        by_regime[regime] = by_regime.get(regime, 0.0) + trip.pl
        by_ticker[trip.ticker] = by_ticker.get(trip.ticker, 0.0) + trip.pl
        by_side[trip.side] = by_side.get(trip.side, 0.0) + trip.pl
        by_holding_period[bucket] = by_holding_period.get(bucket, 0.0) + trip.pl

    return AttributionReport(
        total_pl=total_pl,
        by_regime=by_regime,
        by_ticker=by_ticker,
        by_side=by_side,
        by_holding_period=by_holding_period,
        n_round_trips=len(trips),
    )
