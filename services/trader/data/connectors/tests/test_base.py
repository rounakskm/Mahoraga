"""Tests for the connector base classes."""

from __future__ import annotations

import time

import pytest

from services.trader.data.connectors.base import (
    Connector,
    ConnectorResult,
    HealthStatus,
    RateLimiter,
)


class TestRateLimiter:
    def test_initial_capacity_full(self) -> None:
        rl = RateLimiter(capacity=5.0, refill_rate_per_sec=10.0)
        status = rl.status()
        assert status.capacity == 5.0
        assert status.available == pytest.approx(5.0, abs=0.01)
        assert status.refill_rate_per_sec == 10.0

    def test_acquire_consumes_tokens(self) -> None:
        rl = RateLimiter(capacity=5.0, refill_rate_per_sec=10.0)
        rl.acquire(2.0)
        assert rl.status().available == pytest.approx(3.0, abs=0.05)

    def test_acquire_blocks_until_refill(self) -> None:
        rl = RateLimiter(capacity=2.0, refill_rate_per_sec=10.0)
        rl.acquire(2.0)
        # Bucket empty; next acquire(2.0) needs 0.2s of refill.
        start = time.monotonic()
        rl.acquire(2.0)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.15, f"expected blocking ~0.2s, got {elapsed:.3f}s"

    def test_acquire_timeout(self) -> None:
        rl = RateLimiter(capacity=1.0, refill_rate_per_sec=0.5)
        rl.acquire(1.0)
        with pytest.raises(TimeoutError):
            rl.acquire(1.0, timeout=0.1)

    def test_invalid_capacity(self) -> None:
        with pytest.raises(ValueError, match="capacity"):
            RateLimiter(capacity=0, refill_rate_per_sec=1.0)

    def test_invalid_refill_rate(self) -> None:
        with pytest.raises(ValueError, match="refill_rate"):
            RateLimiter(capacity=1.0, refill_rate_per_sec=0)

    def test_invalid_acquire_amount(self) -> None:
        rl = RateLimiter(capacity=1.0, refill_rate_per_sec=1.0)
        with pytest.raises(ValueError, match="tokens"):
            rl.acquire(0)

    def test_capacity_clamps_refill(self) -> None:
        rl = RateLimiter(capacity=2.0, refill_rate_per_sec=100.0)
        # Even after a long wait, available cannot exceed capacity.
        time.sleep(0.05)
        assert rl.status().available <= 2.0


class TestConnectorABC:
    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            Connector(rate_limiter=RateLimiter(capacity=1.0, refill_rate_per_sec=1.0))  # type: ignore[abstract]

    def test_subclass_must_implement_fetch_and_health(self) -> None:
        class Incomplete(Connector):  # missing both abstract methods
            name = "incomplete"

        with pytest.raises(TypeError):
            Incomplete(rate_limiter=RateLimiter(capacity=1.0, refill_rate_per_sec=1.0))  # type: ignore[abstract]


class TestConnectorResult:
    def test_rows_default_from_frame(self) -> None:
        import pandas as pd

        from services.trader.data.connectors.base import utcnow

        frame = pd.DataFrame({"x": [1, 2, 3]})
        result = ConnectorResult(frame=frame, source="t", fetched_at=utcnow())
        assert result.rows == 3

    def test_rows_explicit_override(self) -> None:
        import pandas as pd

        from services.trader.data.connectors.base import utcnow

        frame = pd.DataFrame({"x": [1, 2]})
        result = ConnectorResult(frame=frame, source="t", fetched_at=utcnow(), rows=99)
        assert result.rows == 99


def test_health_status_dataclass() -> None:
    h = HealthStatus(healthy=False, detail="degraded")
    assert h.healthy is False
    assert h.detail == "degraded"
