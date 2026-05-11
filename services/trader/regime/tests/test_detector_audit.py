"""Tests for the detector's manifest + audit wiring (P1.5 R3)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from services.trader.regime.detector import RegimeDetector
from services.trader.regime.macro import MacroLens
from services.trader.regime.meso import MesoLens
from services.trader.regime.store import RegimeStore


def _feature_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bar_timestamp": pd.to_datetime(
                ["2026-01-05", "2026-01-06"], utc=True
            ),
            "adx_14": [40.0, 12.0],
            "realized_vol_pct_60": [0.0, 0.80],
        }
    )


def _macro_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bar_timestamp": pd.to_datetime(
                ["2026-01-05", "2026-01-06"], utc=True
            ),
            "yield_2s10s": [0.5, -0.10],
            "vix_level": [14.0, 35.0],
            "dxy_change_20d": [-1.0, 2.0],
        }
    )


class _FakeAuditWriter:
    """Records all writes; no Postgres needed."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def is_enabled(self) -> bool:
        return True

    def write(self, *, actor, action, payload):  # type: ignore[no-untyped-def]
        self.calls.append({"actor": actor, "action": action, "payload": dict(payload)})
        return b"\x00" * 32


class TestStorePersistence:
    def test_classify_writes_to_regime_store(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=None)
        detector = RegimeDetector(
            lenses=[MesoLens(), MacroLens()], store=store
        )
        result = detector.classify(
            scope="universe",
            feature_frame=_feature_frame(),
            macro_frame=_macro_frame(),
        )
        assert len(result.rows) == 2

        partition = tmp_path / "regime" / "universe" / "2026.parquet"
        assert partition.exists()
        df = pq.read_table(partition).to_pandas()
        assert list(df["meso_label"]) == [
            "trending_low_vol",
            "ranging_high_vol",
        ]
        assert list(df["macro_label"]) == ["bull", "bear"]

    def test_no_store_persists_nothing(self, tmp_path: Path) -> None:
        detector = RegimeDetector(lenses=[MesoLens(), MacroLens()], store=None)
        result = detector.classify(
            scope="universe",
            feature_frame=_feature_frame(),
            macro_frame=_macro_frame(),
        )
        # In-memory rows are still produced
        assert len(result.rows) == 2
        # No parquet anywhere
        assert not list(tmp_path.iterdir())


class TestManifest:
    def test_manifest_row_written_per_run(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=None)
        manifest_root = tmp_path / "manifests-root"
        detector = RegimeDetector(
            lenses=[MesoLens(), MacroLens()],
            store=store,
            manifest_root=str(manifest_root),
        )
        detector.classify(
            scope="universe",
            feature_frame=_feature_frame(),
            macro_frame=_macro_frame(),
        )
        manifest_path = manifest_root / "manifests" / "ingest-runs.parquet"
        assert manifest_path.exists()
        df = pq.read_table(manifest_path).to_pandas()
        assert len(df) == 1
        assert df["source"].iloc[0] == "regime-detector"
        assert df["rows_written"].iloc[0] == 2

    def test_no_manifest_root_skips_manifest(self, tmp_path: Path) -> None:
        # Without manifest_root, the run still succeeds; just no manifest.
        store = RegimeStore(tmp_path, vault_cutoff_days=None)
        detector = RegimeDetector(lenses=[MesoLens(), MacroLens()], store=store)
        detector.classify(
            scope="universe",
            feature_frame=_feature_frame(),
            macro_frame=_macro_frame(),
        )
        # Nothing under tmp_path/manifests
        assert not (tmp_path / "manifests").exists()


class TestAuditEvents:
    def test_audit_row_written_per_run(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=None)
        writer = _FakeAuditWriter()
        detector = RegimeDetector(
            lenses=[MesoLens(), MacroLens()],
            store=store,
            audit_writer=writer,  # type: ignore[arg-type]
            audit_actor="test-regime-detector",
        )
        detector.classify(
            scope="universe",
            feature_frame=_feature_frame(),
            macro_frame=_macro_frame(),
        )
        assert len(writer.calls) == 1
        call = writer.calls[0]
        assert call["actor"] == "test-regime-detector"
        assert call["action"] == "classify"
        payload = call["payload"]
        assert payload["source"] == "regime-detector"
        assert payload["scope"] == "universe"
        assert payload["rows_written"] == 2
        assert payload["lens_count"] == 2
        assert payload["lens_names"] == ["meso", "macro"]


class TestIdempotentRerun:
    def test_second_run_writes_zero_rows(self, tmp_path: Path) -> None:
        store = RegimeStore(tmp_path, vault_cutoff_days=None)
        manifest_root = tmp_path / "manifests-root"
        first = RegimeDetector(
            lenses=[MesoLens(), MacroLens()],
            store=store,
            manifest_root=str(manifest_root),
        )
        first.classify(
            scope="universe",
            feature_frame=_feature_frame(),
            macro_frame=_macro_frame(),
        )
        second = RegimeDetector(
            lenses=[MesoLens(), MacroLens()],
            store=store,
            manifest_root=str(manifest_root),
        )
        second.classify(
            scope="universe",
            feature_frame=_feature_frame(),
            macro_frame=_macro_frame(),
        )
        manifest_path = manifest_root / "manifests" / "ingest-runs.parquet"
        manifest = pq.read_table(manifest_path).to_pandas()
        # Both runs recorded; second.rows_written = 0
        assert len(manifest) == 2
        assert manifest["rows_written"].iloc[0] == 2
        assert manifest["rows_written"].iloc[1] == 0
