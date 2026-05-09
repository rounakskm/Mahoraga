"""Yahoo Finance OHLCV connector for equities and ETFs.

Pulls daily bars via the `yfinance` library, normalizes to the Mahoraga OHLCV
schema, and applies polite rate-limiting + exponential backoff with jitter.

`yfinance` is unofficial and rate-limited by Yahoo's edge; we stay around 2
sustained requests/second per the community-observed soft limit.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd

from services.trader.data.connectors.base import (
    Connector,
    ConnectorError,
    ConnectorResult,
    HealthStatus,
    RateLimiter,
    utcnow,
)

logger = logging.getLogger(__name__)

DEFAULT_CAPACITY = 4.0
DEFAULT_REFILL_RATE_PER_SEC = 2.0
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BASE_BACKOFF_SEC = 0.5
DEFAULT_BACKOFF_CAP_SEC = 30.0


@dataclass
class _RetryConfig:
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_backoff_sec: float = DEFAULT_BASE_BACKOFF_SEC
    backoff_cap_sec: float = DEFAULT_BACKOFF_CAP_SEC


class YFinanceConnector(Connector):
    """Daily OHLCV connector backed by `yfinance.download`.

    The fetch path is split so tests can inject a fake downloader without
    monkey-patching the `yfinance` package.
    """

    name = "yfinance"

    def __init__(
        self,
        *,
        rate_limiter: RateLimiter | None = None,
        downloader: Callable[..., pd.DataFrame] | None = None,
        retry_config: _RetryConfig | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__(
            rate_limiter=rate_limiter
            or RateLimiter(
                capacity=DEFAULT_CAPACITY,
                refill_rate_per_sec=DEFAULT_REFILL_RATE_PER_SEC,
            ),
        )
        self._downloader = downloader or self._default_downloader
        self._retry = retry_config or _RetryConfig()
        self._sleep = sleep or time.sleep

    # --- public ----------------------------------------------------------

    def fetch(self, key: str, start: date, end: date) -> ConnectorResult:
        if not key or not isinstance(key, str):
            raise ConnectorError(f"invalid ticker: {key!r}")
        if start > end:
            raise ConnectorError(f"start {start} after end {end}")

        attempt = 0
        last_error: Exception | None = None
        while attempt < self._retry.max_attempts:
            attempt += 1
            self.rate_limiter.acquire()
            try:
                raw = self._downloader(
                    tickers=key,
                    start=start.isoformat(),
                    end=end.isoformat(),
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                    threads=False,
                )
            except _PermanentError as exc:
                raise ConnectorError(str(exc)) from exc
            except _TransientError as exc:
                last_error = exc
                wait = self._compute_backoff(attempt)
                logger.warning(
                    "yfinance transient error for %s (attempt %d/%d): %s; "
                    "backing off %.2fs",
                    key,
                    attempt,
                    self._retry.max_attempts,
                    exc,
                    wait,
                )
                self._sleep(wait)
                continue
            else:
                normalized = self._normalize(raw, ticker=key)
                return ConnectorResult(
                    frame=normalized,
                    source=self.name,
                    fetched_at=utcnow(),
                    rows=len(normalized),
                    metadata={"attempts": attempt},
                )

        raise ConnectorError(
            f"yfinance fetch for {key} failed after {self._retry.max_attempts} attempts: {last_error}"
        )

    def health(self) -> HealthStatus:
        try:
            today = date.today()
            yesterday = today.replace(day=max(today.day - 1, 1))
            self.fetch("SPY", yesterday, today)
        except ConnectorError as exc:
            return HealthStatus(healthy=False, detail=str(exc))
        return HealthStatus(healthy=True, detail="SPY round-trip OK")

    # --- internals -------------------------------------------------------

    @staticmethod
    def _default_downloader(**kwargs: object) -> pd.DataFrame:
        # Imported lazily so unit tests that inject a fake downloader don't
        # need yfinance installed at import time.
        try:
            import yfinance  # noqa: PLC0415  (keep lazy)
        except ImportError as exc:
            raise _PermanentError(f"yfinance not installed: {exc}") from exc
        try:
            return yfinance.download(**kwargs)
        except Exception as exc:  # noqa: BLE001  (yfinance raises ad-hoc types)
            # yfinance does not currently distinguish transient from permanent
            # errors well; treat anything other than the well-known "no data"
            # case as transient and let backoff handle it.
            if "No data" in str(exc) or "delisted" in str(exc).lower():
                raise _PermanentError(str(exc)) from exc
            raise _TransientError(str(exc)) from exc

    def _compute_backoff(self, attempt: int) -> float:
        # Exponential backoff with full jitter, capped.
        cap = self._retry.backoff_cap_sec
        base = self._retry.base_backoff_sec * (2 ** (attempt - 1))
        return random.uniform(0.0, min(cap, base))  # noqa: S311  (jitter, not crypto)

    @staticmethod
    def _normalize(raw: pd.DataFrame, *, ticker: str) -> pd.DataFrame:
        if raw is None or raw.empty:
            raise ConnectorError(f"yfinance returned no rows for {ticker}")

        df = raw.copy()
        # yfinance returns a multi-index when given a list of tickers; collapse.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        expected_cols = {"Open", "High", "Low", "Close", "Volume"}
        missing = expected_cols - set(df.columns)
        if missing:
            raise ConnectorError(
                f"yfinance response missing columns {missing} for {ticker}"
            )

        adj_close_col = "Adj Close" if "Adj Close" in df.columns else "Close"

        return pd.DataFrame(
            {
                "ticker": ticker,
                "bar_timestamp": pd.to_datetime(df.index, utc=True),
                "open": df["Open"].astype("float64"),
                "high": df["High"].astype("float64"),
                "low": df["Low"].astype("float64"),
                "close": df["Close"].astype("float64"),
                "volume": df["Volume"].astype("int64"),
                "adj_close": df[adj_close_col].astype("float64"),
                "source": "yfinance",
                "fetched_at": utcnow(),
                "revision_at": pd.NaT,
            }
        ).reset_index(drop=True)


# Internal sentinel exceptions used to thread retry semantics through the
# pluggable downloader without leaking yfinance's exception types.


class _TransientError(Exception):
    """Raised by the downloader for retryable failures."""


class _PermanentError(Exception):
    """Raised by the downloader for failures that should not be retried."""
