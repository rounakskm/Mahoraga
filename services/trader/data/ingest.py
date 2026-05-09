"""Ingest orchestrator.

Wires Connector + ParquetAdapter + Coverage + AuditLogger into a single
`run()` entry point. The orchestrator is the only piece of code that knows
about all four; everything below is reusable in isolation.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Literal

import pandas as pd

from services.trader.data.audit import AuditLogger
from services.trader.data.connectors.base import Connector, ConnectorError
from services.trader.data.coverage import (
    CoverageError,
    CoverageReport,
    nyse_trading_days,
    report_macro,
    report_ohlcv,
)
from services.trader.data.storage.parquet_adapter import ParquetAdapter

logger = logging.getLogger(__name__)


class IngestMode(StrEnum):
    """Coverage gate selection.

    - `FRESH`: 99% per-key coverage required; below threshold raises CoverageError.
    - `BACKFILL`: 95% per-key coverage required; below threshold logs warning,
      writes the gap details to the manifest, and continues.
    """

    FRESH = "fresh"
    BACKFILL = "backfill"


THRESHOLDS = {
    IngestMode.FRESH: 99.0,
    IngestMode.BACKFILL: 95.0,
}


@dataclass
class IngestResult:
    rows_written: int
    coverage_reports: list[CoverageReport]
    failures: list[str] = field(default_factory=list)


class Ingest:
    """End-to-end ingest of a connector against a key set."""

    def __init__(
        self,
        *,
        adapter: ParquetAdapter,
        audit: AuditLogger,
    ) -> None:
        self.adapter = adapter
        self.audit = audit

    def run_ohlcv(
        self,
        connector: Connector,
        *,
        tickers: Iterable[str],
        start: date,
        end: date,
        mode: IngestMode = IngestMode.FRESH,
        expected_calendar: pd.DatetimeIndex | None = None,
    ) -> IngestResult:
        """Ingest OHLCV for `tickers`. Per-symbol coverage gated by mode."""
        threshold = THRESHOLDS[mode]
        if expected_calendar is None:
            expected_calendar = nyse_trading_days(start, end)
        with self.audit.run(source=connector.name) as run:
            rows_written = 0
            reports: list[CoverageReport] = []
            failures: list[str] = []
            for ticker in tickers:
                try:
                    result = connector.fetch(ticker, start, end)
                except ConnectorError as exc:
                    failures.append(f"{ticker}: {exc}")
                    logger.error("connector failure for %s: %s", ticker, exc)
                    continue
                rows_written += self.adapter.write(result, kind="ohlcv")
                report = report_ohlcv(
                    self.adapter,
                    ticker=ticker,
                    start=start,
                    end=end,
                    threshold_pct=threshold,
                    expected=expected_calendar,
                )
                reports.append(report)
                if not report.passed:
                    msg = report.summary
                    failures.append(msg)
                    logger.warning("coverage gate failed: %s", msg)

            run.rows_written = rows_written
            run.coverage_pct = _avg_coverage(reports)
            run.errors = failures

            if mode == IngestMode.FRESH and any(not r.passed for r in reports):
                # Errors recorded; raising here propagates through the audit
                # context manager which finalizes the run with errors attached.
                raise CoverageError(
                    f"fresh ingest below {threshold:.1f}% threshold for "
                    f"{sum(1 for r in reports if not r.passed)} of {len(reports)} keys"
                )

            return IngestResult(
                rows_written=rows_written,
                coverage_reports=reports,
                failures=failures,
            )

    def run_macro(
        self,
        connector: Connector,
        *,
        indicators: Iterable[str],
        start: date,
        end: date,
        expected_reference_dates: dict[str, pd.DatetimeIndex],
        mode: IngestMode = IngestMode.FRESH,
    ) -> IngestResult:
        """Ingest macro indicators. Per-indicator coverage gated by mode."""
        threshold = THRESHOLDS[mode]
        with self.audit.run(source=connector.name) as run:
            rows_written = 0
            reports: list[CoverageReport] = []
            failures: list[str] = []

            for indicator in indicators:
                expected = expected_reference_dates.get(indicator)
                if expected is None:
                    failures.append(
                        f"{indicator}: no expected_reference_dates provided"
                    )
                    continue
                try:
                    result = connector.fetch(indicator, start, end)
                except ConnectorError as exc:
                    failures.append(f"{indicator}: {exc}")
                    logger.error("connector failure for %s: %s", indicator, exc)
                    continue
                rows_written += self.adapter.write(result, kind="macro")
                report = report_macro(
                    self.adapter,
                    indicator=indicator,
                    expected_reference_dates=expected,
                    threshold_pct=threshold,
                )
                reports.append(report)
                if not report.passed:
                    failures.append(report.summary)
                    logger.warning("coverage gate failed: %s", report.summary)

            run.rows_written = rows_written
            run.coverage_pct = _avg_coverage(reports)
            run.errors = failures

            if mode == IngestMode.FRESH and any(not r.passed for r in reports):
                raise CoverageError(
                    f"fresh ingest below {threshold:.1f}% threshold for "
                    f"{sum(1 for r in reports if not r.passed)} of {len(reports)} indicators"
                )

            return IngestResult(
                rows_written=rows_written,
                coverage_reports=reports,
                failures=failures,
            )


def _avg_coverage(reports: list[CoverageReport]) -> float | None:
    if not reports:
        return None
    return sum(r.coverage_pct for r in reports) / len(reports)


# Type alias for callers that want to be explicit
Kind = Literal["ohlcv", "macro"]
