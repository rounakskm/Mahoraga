"""Per-key completeness reporting for ingest runs.

Coverage is the data-foundation's fail-loud signal: a fresh ingest that
returns less than 99% of the expected bars on any symbol indicates a real
problem (rate-limited, ticker delisted, source outage). The orchestrator
either raises (fresh) or warns (backfill) on the report.

See `docs/superpowers/specs/phase-1-foundation/data-foundation-spec.md` §9.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal

import pandas as pd

from services.trader.data.storage.parquet_adapter import ParquetAdapter

logger = logging.getLogger(__name__)


class CoverageError(Exception):
    """Raised when a fresh ingest fails the per-key coverage threshold."""


@dataclass
class CoverageReport:
    key: str
    kind: Literal["ohlcv", "macro"]
    expected_count: int
    present_count: int
    missing_count: int
    coverage_pct: float
    threshold_pct: float
    passed: bool
    missing_sample: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (
            f"{self.kind}/{self.key}: {self.present_count}/{self.expected_count} "
            f"({self.coverage_pct:.1f}%, threshold {self.threshold_pct:.1f}%) "
            f"-> {'PASS' if self.passed else 'FAIL'}"
        )


def nyse_trading_days(start: date, end: date) -> pd.DatetimeIndex:
    """Return UTC-normalized NYSE trading days in `[start, end]`.

    Wraps `pandas_market_calendars` so callers don't have to know about it
    directly. NYSE because the Phase 1 universe is US equities + ETFs.
    """
    import pandas_market_calendars as mcal  # noqa: PLC0415  (lazy: heavy import)

    cal = mcal.get_calendar("NYSE")
    schedule = cal.schedule(start_date=start.isoformat(), end_date=end.isoformat())
    return pd.DatetimeIndex(schedule.index, tz="UTC").normalize()


def report_ohlcv(
    adapter: ParquetAdapter,
    *,
    ticker: str,
    start: date,
    end: date,
    threshold_pct: float = 99.0,
    asof: datetime | None = None,
    expected: pd.DatetimeIndex | None = None,
) -> CoverageReport:
    """Check OHLCV coverage for `ticker` against the NYSE trading calendar.

    Pass `expected` to override the trading-calendar default (used by tests
    that don't want the heavyweight `pandas_market_calendars` import).
    """
    if expected is None:
        expected = nyse_trading_days(start, end)
    asof_dt = asof or datetime.combine(end, datetime.min.time(), tzinfo=UTC)
    df = adapter.read(
        kind="ohlcv",
        keys=[ticker],
        start=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        end=datetime.combine(end, datetime.max.time(), tzinfo=UTC),
        asof=asof_dt,
    )
    expected_norm = (
        expected.tz_convert("UTC").normalize()
        if expected.tz
        else expected.tz_localize("UTC").normalize()
    )

    if df.empty:
        present_norm: pd.DatetimeIndex = pd.DatetimeIndex([], tz="UTC")
    else:
        present_norm = pd.DatetimeIndex(pd.to_datetime(df["bar_timestamp"], utc=True)).normalize()

    missing_idx = expected_norm.difference(present_norm)
    return _build_report(
        key=ticker,
        kind="ohlcv",
        expected_count=len(expected_norm),
        present_count=len(expected_norm) - len(missing_idx),
        missing=[ts.date().isoformat() for ts in missing_idx],
        threshold_pct=threshold_pct,
    )


def report_macro(
    adapter: ParquetAdapter,
    *,
    indicator: str,
    expected_reference_dates: pd.DatetimeIndex,
    threshold_pct: float = 99.0,
    asof: datetime | None = None,
) -> CoverageReport:
    """Check macro coverage for `indicator` against an expected release schedule.

    The caller passes the expected reference dates (e.g. monthly first-of-month
    for CPI). We then check how many of those reference dates have at least one
    row in storage that was public at `asof`.
    """
    if expected_reference_dates.empty:
        return _build_report(
            key=indicator,
            kind="macro",
            expected_count=0,
            present_count=0,
            missing=[],
            threshold_pct=threshold_pct,
        )

    expected_norm = pd.DatetimeIndex(expected_reference_dates).normalize()
    span_start = expected_norm.min().date()
    span_end = expected_norm.max().date()
    asof_dt = asof or datetime.combine(span_end, datetime.min.time(), tzinfo=UTC)

    df = adapter.read(
        kind="macro",
        keys=[indicator],
        start=datetime.combine(span_start, datetime.min.time(), tzinfo=UTC),
        end=datetime.combine(span_end, datetime.max.time(), tzinfo=UTC),
        asof=asof_dt,
    )

    if df.empty:
        present_dates: pd.DatetimeIndex = pd.DatetimeIndex([])
    else:
        present_dates = pd.DatetimeIndex(pd.to_datetime(df["reference_date"]))

    expected_set = {ts.date() for ts in expected_norm}
    present_set = {ts.date() for ts in present_dates}
    missing = sorted(expected_set - present_set)
    return _build_report(
        key=indicator,
        kind="macro",
        expected_count=len(expected_set),
        present_count=len(expected_set) - len(missing),
        missing=[d.isoformat() for d in missing],
        threshold_pct=threshold_pct,
    )


def _build_report(
    *,
    key: str,
    kind: Literal["ohlcv", "macro"],
    expected_count: int,
    present_count: int,
    missing: list[str],
    threshold_pct: float,
) -> CoverageReport:
    coverage_pct = 100.0 if expected_count == 0 else 100.0 * present_count / expected_count
    passed = coverage_pct >= threshold_pct
    return CoverageReport(
        key=key,
        kind=kind,
        expected_count=expected_count,
        present_count=present_count,
        missing_count=len(missing),
        coverage_pct=coverage_pct,
        threshold_pct=threshold_pct,
        passed=passed,
        missing_sample=missing[:25],
    )


# ---------------------------------------------------------------------------
# Feature-pipeline coverage (P1.4 F5)
# ---------------------------------------------------------------------------


@dataclass
class FeatureCoverageReport:
    """Per-feature-column null-rate report for a feature frame.

    A row exists for every feature column the pipeline emitted. The
    pipeline's coverage gate warns when any column's `null_rate_pct`
    exceeds 1% beyond the placeholder columns (placeholders are 100%
    "non-null but 0.0" and are exempt from null-rate checks by design).
    """

    feature: str
    placeholder: bool
    bars_total: int
    bars_non_null: int
    null_rate_pct: float
    passed: bool

    @property
    def summary(self) -> str:
        flag = " [PLACEHOLDER]" if self.placeholder else ""
        return (
            f"{self.feature}: {self.bars_non_null}/{self.bars_total} "
            f"({self.null_rate_pct:.1f}% null){flag}"
        )


def report_features(
    frame: pd.DataFrame,
    *,
    feature_columns: list[str],
    placeholder_columns: set[str] | None = None,
    null_rate_threshold_pct: float = 1.0,
) -> list[FeatureCoverageReport]:
    """Compute per-feature null-rate against the bar count of `frame`.

    `placeholder_columns` lets the caller mark features that legitimately
    return constant values (the sentiment_score placeholder) so the
    null-rate gate doesn't fire on them — they have 0% null by definition
    but the gate's `passed` flag is always True for placeholders.
    """
    placeholders = placeholder_columns or set()
    total = len(frame)
    reports: list[FeatureCoverageReport] = []
    for col in feature_columns:
        if col not in frame.columns:
            reports.append(
                FeatureCoverageReport(
                    feature=col,
                    placeholder=col in placeholders,
                    bars_total=total,
                    bars_non_null=0,
                    null_rate_pct=100.0,
                    passed=False,
                )
            )
            continue
        non_null = int(frame[col].notna().sum())
        null_rate = 0.0 if total == 0 else 100.0 * (total - non_null) / total
        is_placeholder = col in placeholders
        passed = is_placeholder or null_rate <= null_rate_threshold_pct
        reports.append(
            FeatureCoverageReport(
                feature=col,
                placeholder=is_placeholder,
                bars_total=total,
                bars_non_null=non_null,
                null_rate_pct=null_rate,
                passed=passed,
            )
        )
    return reports
