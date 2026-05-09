"""Connector base classes for the data foundation.

Defines the `Connector` ABC that every data-source adapter implements, plus the
shared `RateLimiter`, error types, and result envelope.

See `data-foundation-spec.md` §5 for the design rationale.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd


class ConnectorError(Exception):
    """Raised by a connector for unrecoverable errors.

    Permanent HTTP errors (4xx other than 429), schema mismatches, or missing
    credentials must raise this. Transient failures (429, 5xx, connection
    errors) are retried internally with exponential backoff before this is
    raised.
    """


@dataclass
class HealthStatus:
    healthy: bool
    detail: str = ""


@dataclass
class RateLimitStatus:
    capacity: float
    available: float
    refill_rate_per_sec: float


@dataclass
class ConnectorResult:
    """Normalized result from a `Connector.fetch` call.

    Every connector returns its data as a pandas DataFrame plus per-row
    provenance metadata. Storage adapters consume this without needing to know
    which connector produced it.
    """

    frame: pd.DataFrame
    source: str
    fetched_at: datetime
    rows: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.rows == 0:
            self.rows = len(self.frame)


class RateLimiter:
    """Thread-safe token-bucket rate limiter.

    Tokens refill continuously at `refill_rate_per_sec`. `acquire(n)` blocks
    until `n` tokens are available, then consumes them. Designed for
    polite throttling against free-tier APIs.
    """

    def __init__(self, capacity: float, refill_rate_per_sec: float) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_rate_per_sec <= 0:
            raise ValueError("refill_rate_per_sec must be positive")
        self._capacity = float(capacity)
        self._refill_rate = float(refill_rate_per_sec)
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0, *, timeout: float | None = None) -> None:
        """Block until `tokens` are available, then consume them.

        Raises `TimeoutError` if `timeout` is set and elapses before tokens
        become available.
        """
        if tokens <= 0:
            raise ValueError("tokens must be positive")
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill_locked()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                missing = tokens - self._tokens
                wait = missing / self._refill_rate
            if deadline is not None and time.monotonic() + wait > deadline:
                raise TimeoutError(
                    f"timed out waiting for {tokens} tokens (need {missing:.3f} more)"
                )
            time.sleep(wait)

    def status(self) -> RateLimitStatus:
        with self._lock:
            self._refill_locked()
            return RateLimitStatus(
                capacity=self._capacity,
                available=self._tokens,
                refill_rate_per_sec=self._refill_rate,
            )

    # --- internal ---------------------------------------------------------

    def _refill_locked(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
            self._last_refill = now


class Connector(ABC):
    """Base class for all data-source connectors."""

    name: str

    def __init__(self, *, rate_limiter: RateLimiter) -> None:
        self.rate_limiter = rate_limiter

    @abstractmethod
    def fetch(self, key: str, start: date, end: date) -> ConnectorResult:
        """Fetch data for `key` over `[start, end]`.

        `key` interpretation depends on the connector — for OHLCV it's a
        ticker symbol; for macro it's a series ID (e.g. FRED's "CPIAUCSL").
        """

    @abstractmethod
    def health(self) -> HealthStatus:
        """Return a health probe result for this connector."""

    def rate_limit_status(self) -> RateLimitStatus:
        return self.rate_limiter.status()


def utcnow() -> datetime:
    """Timezone-aware UTC `now`. Centralized so tests can monkey-patch one place."""
    return datetime.now(UTC)
