"""Parquet-backed storage with point-in-time-correct read semantics.

See `docs/superpowers/specs/phase-1-foundation/data-foundation-spec.md` §6, §7.
"""

from services.trader.data.storage.parquet_adapter import ParquetAdapter
from services.trader.data.storage.pit import pit_view_macro, pit_view_ohlcv
from services.trader.data.storage.schema import (
    MACRO_ARROW_SCHEMA,
    OHLCV_ARROW_SCHEMA,
    MacroRow,
    OhlcvRow,
)
from services.trader.data.storage.vault import VaultEmbargoError, assess_vault

__all__ = [
    "MACRO_ARROW_SCHEMA",
    "OHLCV_ARROW_SCHEMA",
    "MacroRow",
    "OhlcvRow",
    "ParquetAdapter",
    "VaultEmbargoError",
    "assess_vault",
    "pit_view_macro",
    "pit_view_ohlcv",
]
