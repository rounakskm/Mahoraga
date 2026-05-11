"""Tests for `RegimeStore` (P1.5 R3).

Round-trip + vault embargo + idempotent re-write semantics. No
Postgres dependency — the audit-events path is exercised in
test_detector_audit.py via a fake writer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from services.trader.data.storage.vault import VaultEmbargoError
from services.trader.regime.store import (
    RegimeStore,
    decode_inputs,
    encode_inputs,
    regime_frame_schema,
)


def _frame(
    scope: str,
    bars: list[str],
    *,
    meso_label: str = "trending_low_vol",
    macro_label: str = "bull",
    meso_conf: float = 0.9,
    macro_conf: float = 0.8,
    composite_conf: float = 0.8,
    fetched_at: datetime | None = None,
) -> pd.DataFrame:
    fetched = fetched_at or datetime.now(UTC)
    return pd.DataFrame(
        {
            "scope": [scope] * len(bars),
            "asof": pd.to_datetime(bars, utc=True),
            "meso_label": [meso_label] * len(bars),
            "meso_conf": [meso_conf] * len(bars),
            "macro_label": [macro_label] * len(bars),
            "macro_conf": [macro_conf] * len(bars),
            "composite_conf": [composite_conf] * len(bars),
            "inputs": [encode_inputs({"x": 1.0})] * len(bars),
            "source": ["regime-detector"] * len(bars),
            "fetched_at": [pd.Timestamp(fetched)] * len(bars),
        }
    )


_LENS_NAMES = ["meso", "macro"]


class TestRegimeStoreSchema:
    def test_schema_lists_lens_columns(self) -> None:
        schema = regime_frame_schema(_LENS_NAMES)
        names = schema.names
        for col in [
            "scope", "asof",
            "meso_label", "meso_conf",
            "macro_label", "macro_conf",
            "composite_conf", "inputs", "source", "fetched_at",
        ]:
            assert col in names

    def test_extra_lenses_extend_schema(self) -> None:
        schema = regime_frame_schema(["meso", "macro", "micro"])
        assert "micro_label" in schema.names
        assert "micro_conf" in schema.names


class TestRegimeStoreRoundtrip:
    def test_write_then_read_basic(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=None)
        written = store.write(
            _frame("universe", ["2026-01-05", "2026-01-06", "2026-01-07"]),
            lens_names=_LENS_NAMES,
        )
        assert written == 3
        assert (tmp_path / "regime" / "universe" / "2026.parquet").exists()

        out = store.read(
            scopes=["universe"],
            start=datetime(2026, 1, 5, tzinfo=UTC),
            end=datetime(2026, 1, 7, 23, 59, tzinfo=UTC),
            lens_names=_LENS_NAMES,
        )
        assert len(out) == 3
        assert (out["scope"] == "universe").all()
        # JSON-encoded inputs round-trip
        decoded = decode_inputs(out["inputs"].iloc[0])
        assert decoded == {"x": 1.0}

    def test_read_missing_scope_returns_empty(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=None)
        out = store.read(
            scopes=["doesnotexist"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
            lens_names=_LENS_NAMES,
        )
        assert out.empty

    def test_idempotent_rewrite_dedupes_on_scope_asof(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=None)
        store.write(
            _frame("universe", ["2026-01-05", "2026-01-06"]),
            lens_names=_LENS_NAMES,
        )
        # Re-write same (scope, asof) keys with a later fetched_at — should
        # win on dedupe but produce 0 new rows.
        later = datetime(2030, 1, 1, tzinfo=UTC)
        second = store.write(
            _frame(
                "universe",
                ["2026-01-05", "2026-01-06"],
                meso_label="ranging_low_vol",
                fetched_at=later,
            ),
            lens_names=_LENS_NAMES,
        )
        assert second == 0

        out = store.read(
            scopes=["universe"],
            start=datetime(2026, 1, 5, tzinfo=UTC),
            end=datetime(2026, 1, 6, 23, 59, tzinfo=UTC),
            lens_names=_LENS_NAMES,
        )
        assert (out["meso_label"] == "ranging_low_vol").all()

    def test_multiple_years_use_multiple_partitions(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=None)
        store.write(
            _frame("universe", ["2025-12-31", "2026-01-01"]),
            lens_names=_LENS_NAMES,
        )
        assert (tmp_path / "regime" / "universe" / "2025.parquet").exists()
        assert (tmp_path / "regime" / "universe" / "2026.parquet").exists()


class TestRegimeStorePIT:
    def test_asof_filters_future_writes(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=None)
        store.write(
            _frame(
                "universe",
                ["2026-01-05"],
                fetched_at=datetime(2026, 5, 1, tzinfo=UTC),
            ),
            lens_names=_LENS_NAMES,
        )
        # Reading at an asof earlier than fetched_at should exclude the row.
        empty = store.read(
            scopes=["universe"],
            start=datetime(2026, 1, 5, tzinfo=UTC),
            end=datetime(2026, 1, 6, tzinfo=UTC),
            asof=datetime(2026, 4, 30, tzinfo=UTC),
            lens_names=_LENS_NAMES,
        )
        assert empty.empty


class TestRegimeStoreVault:
    def test_recent_window_blocked(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=180)
        store.write(
            _frame("universe", ["2026-04-01"]), lens_names=_LENS_NAMES
        )
        with pytest.raises(VaultEmbargoError):
            store.read(
                scopes=["universe"],
                start=datetime(2026, 4, 1, tzinfo=UTC),
                end=datetime(2026, 4, 2, tzinfo=UTC),
                lens_names=_LENS_NAMES,
            )

    def test_override_requires_reason(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=180)
        store.write(
            _frame("universe", ["2026-04-01"]), lens_names=_LENS_NAMES
        )
        with pytest.raises(ValueError):
            store.read(
                scopes=["universe"],
                start=datetime(2026, 4, 1, tzinfo=UTC),
                end=datetime(2026, 4, 2, tzinfo=UTC),
                lens_names=_LENS_NAMES,
                vault_override=True,
                vault_override_reason="",  # empty reason
            )

    def test_override_with_reason_succeeds(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=180)
        store.write(
            _frame("universe", ["2026-04-01"]), lens_names=_LENS_NAMES
        )
        out = store.read(
            scopes=["universe"],
            start=datetime(2026, 4, 1, tzinfo=UTC),
            end=datetime(2026, 4, 2, tzinfo=UTC),
            lens_names=_LENS_NAMES,
            vault_override=True,
            vault_override_reason="integration test exercises vault override",
        )
        assert len(out) == 1


class TestRegimeStoreErrorPaths:
    def test_negative_cutoff_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            RegimeStore(tmp_path, vault_cutoff_days=-1)

    def test_missing_required_column_raises(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=None)
        bad = pd.DataFrame({"scope": ["x"], "asof": pd.to_datetime(["2026-01-01"])})
        with pytest.raises(ValueError):
            store.write(bad, lens_names=_LENS_NAMES)


class TestSchemaCompat:
    def test_written_parquet_uses_declared_schema(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=None)
        store.write(_frame("universe", ["2026-01-05"]), lens_names=_LENS_NAMES)
        table = pq.read_table(
            tmp_path / "regime" / "universe" / "2026.parquet"
        )
        names = table.schema.names
        assert "meso_label" in names
        assert "macro_label" in names
        assert "composite_conf" in names
