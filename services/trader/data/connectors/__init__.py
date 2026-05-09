"""Data-source connectors for Mahoraga's data foundation.

Each module here exposes a `Connector` subclass that pulls a specific kind of
market or macro data from a free public API. See
`docs/superpowers/specs/phase-1-foundation/data-foundation-spec.md` §5.
"""

from services.trader.data.connectors.base import (
    Connector,
    ConnectorError,
    ConnectorResult,
    HealthStatus,
    RateLimiter,
    RateLimitStatus,
)

__all__ = [
    "Connector",
    "ConnectorError",
    "ConnectorResult",
    "HealthStatus",
    "RateLimiter",
    "RateLimitStatus",
]
