"""FRED (St. Louis Fed) macro-indicator connector.

Pulls a series' observations + the release-calendar metadata needed to populate
`as_of_release_date` on every row.

Free-tier API limit: 120 req/min with key. We throttle to ≤ 2 req/sec.

A typical fetch makes:
  - 1 call to `/fred/series` (units / metadata)
  - 1 call to `/fred/series/release` (cached after first call per series)
  - 1 call to `/fred/release/dates` (cached after first call per release)
  - 1 call to `/fred/series/observations` (the data)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

import httpx
import pandas as pd

from services.trader.data.connectors.base import (
    Connector,
    ConnectorError,
    ConnectorResult,
    HealthStatus,
    RateLimiter,
    utcnow,
)
from services.trader.data.connectors.release_calendar import (
    FRED_BASE_URL,
    HttpFetcher,
    ReleaseCalendar,
    ReleaseDateMissingError,
)

logger = logging.getLogger(__name__)

DEFAULT_CAPACITY = 60.0
DEFAULT_REFILL_RATE_PER_SEC = 2.0


class HttpxFetcher:
    """Thin `HttpFetcher` adapter around `httpx.Client`.

    Distinguishes transient (5xx, 429, network) from permanent (4xx other than
    429) errors so the connector's retry layer can react accordingly.
    """

    def __init__(self, *, timeout: float = 30.0, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    def get_json(self, url: str, params: dict[str, str]) -> dict[str, object]:
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise _TransientError(str(exc)) from exc
        if response.status_code == 429 or 500 <= response.status_code < 600:
            raise _TransientError(
                f"FRED HTTP {response.status_code}: {response.text[:200]}"
            )
        if response.status_code >= 400:
            raise _PermanentError(
                f"FRED HTTP {response.status_code}: {response.text[:200]}"
            )
        return response.json()

    def close(self) -> None:
        self._client.close()


class FredConnector(Connector):
    """Macro-indicator connector for FRED."""

    name = "fred"

    def __init__(
        self,
        *,
        api_key: str,
        rate_limiter: RateLimiter | None = None,
        fetcher: HttpFetcher | None = None,
        sleep: Callable[[float], None] | None = None,
        max_attempts: int = 5,
    ) -> None:
        if not api_key:
            raise ConnectorError(
                "FRED_API_KEY is required (https://fred.stlouisfed.org/docs/api/api_key.html)"
            )
        super().__init__(
            rate_limiter=rate_limiter
            or RateLimiter(
                capacity=DEFAULT_CAPACITY,
                refill_rate_per_sec=DEFAULT_REFILL_RATE_PER_SEC,
            ),
        )
        self._api_key = api_key
        self._fetcher = fetcher or HttpxFetcher()
        self._calendar = ReleaseCalendar(self._fetcher, api_key=api_key)
        self._sleep = sleep or _default_sleep
        self._max_attempts = max_attempts

    # --- public ----------------------------------------------------------

    def fetch(self, key: str, start: date, end: date) -> ConnectorResult:
        if not key:
            raise ConnectorError("invalid FRED series_id (empty)")
        if start > end:
            raise ConnectorError(f"start {start} after end {end}")

        units = self._fetch_units(key)
        observations = self._fetch_observations(key, start, end)

        rows: list[dict[str, object]] = []
        fetched_at = utcnow()
        for obs in observations:
            try:
                ref = date.fromisoformat(str(obs["date"]))
            except (KeyError, ValueError) as exc:
                raise ConnectorError(f"FRED observation row malformed: {obs!r}") from exc
            raw_value = obs.get("value")
            if raw_value in (None, "", "."):
                # FRED uses "." for missing values; skip them rather than fabricate.
                continue
            try:
                value = float(raw_value)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise ConnectorError(f"FRED observation has non-numeric value: {obs!r}") from exc
            try:
                release_d = self._calendar.as_of_release_date(key, ref)
            except ReleaseDateMissingError:
                # Skip observations we cannot date — never fabricate a release date.
                logger.warning(
                    "skipping FRED %s observation %s: no release_date >= reference_date",
                    key,
                    ref,
                )
                continue
            rows.append(
                {
                    "indicator": key,
                    "reference_date": ref,
                    "as_of_release_date": release_d,
                    "value": value,
                    "unit": units,
                    "source": "fred",
                    "fetched_at": fetched_at,
                }
            )

        frame = pd.DataFrame(
            rows,
            columns=[
                "indicator",
                "reference_date",
                "as_of_release_date",
                "value",
                "unit",
                "source",
                "fetched_at",
            ],
        )
        if not frame.empty:
            frame["fetched_at"] = pd.to_datetime(frame["fetched_at"], utc=True)
        return ConnectorResult(
            frame=frame,
            source=self.name,
            fetched_at=fetched_at,
            rows=len(frame),
            metadata={"series_id": key, "units": units},
        )

    def health(self) -> HealthStatus:
        try:
            # Tiny request: just the GDP series metadata. Doesn't pull observations.
            self.rate_limiter.acquire()
            self._fetcher.get_json(
                f"{FRED_BASE_URL}/series",
                {"series_id": "GDP", "api_key": self._api_key, "file_type": "json"},
            )
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(healthy=False, detail=f"{type(exc).__name__}: {exc}")
        return HealthStatus(healthy=True, detail="GDP metadata OK")

    # --- internals -------------------------------------------------------

    def _fetch_units(self, series_id: str) -> str:
        body = self._with_retries(
            self._fetcher.get_json,
            f"{FRED_BASE_URL}/series",
            {"series_id": series_id, "api_key": self._api_key, "file_type": "json"},
        )
        seriess = body.get("seriess") or []
        if not seriess:
            raise ConnectorError(f"FRED series {series_id!r} not found")
        units_raw = seriess[0].get("units_short") or seriess[0].get("units") or ""  # type: ignore[index]
        return str(units_raw)

    def _fetch_observations(
        self, series_id: str, start: date, end: date
    ) -> list[dict[str, object]]:
        body = self._with_retries(
            self._fetcher.get_json,
            f"{FRED_BASE_URL}/series/observations",
            {
                "series_id": series_id,
                "api_key": self._api_key,
                "file_type": "json",
                "observation_start": start.isoformat(),
                "observation_end": end.isoformat(),
            },
        )
        return list(body.get("observations") or [])  # type: ignore[arg-type]

    def _with_retries(
        self,
        fn: Callable[..., dict[str, object]],
        *args: object,
        **kwargs: object,
    ) -> dict[str, object]:
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            self.rate_limiter.acquire()
            try:
                return fn(*args, **kwargs)
            except _PermanentError as exc:
                raise ConnectorError(str(exc)) from exc
            except _TransientError as exc:
                last_error = exc
                wait = min(30.0, 0.5 * (2 ** (attempt - 1)))
                logger.warning(
                    "FRED transient error (attempt %d/%d): %s; backing off %.2fs",
                    attempt,
                    self._max_attempts,
                    exc,
                    wait,
                )
                self._sleep(wait)
        raise ConnectorError(
            f"FRED request failed after {self._max_attempts} attempts: {last_error}"
        )


def _default_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


# Internal sentinel exceptions threading retry semantics through the
# pluggable fetcher without leaking httpx types upward.


class _TransientError(Exception):
    """Retryable HTTP / network failure (5xx, 429, transient connection)."""


class _PermanentError(Exception):
    """Non-retryable HTTP failure (4xx other than 429, malformed response)."""
