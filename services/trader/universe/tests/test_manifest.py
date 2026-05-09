"""Tests for the universe-rebuild manifest writer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from services.trader.universe.manifest import RebuildManifestWriter, RebuildRun


def _run(idx: int = 0) -> RebuildRun:
    return RebuildRun(
        run_id=f"r{idx}",
        source="sp500-wikipedia",
        started_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 9, 12, 1, tzinfo=UTC),
        seed_size=503,
        events_count=42,
        errors=[],
    )


class TestRebuildManifestWriter:
    def test_first_run_creates_file(self, tmp_path: Path) -> None:
        writer = RebuildManifestWriter(tmp_path)
        writer.append(_run())
        assert writer.path.exists()
        df = pq.read_table(writer.path).to_pandas()
        assert len(df) == 1
        assert df["source"].iloc[0] == "sp500-wikipedia"

    def test_appends_rather_than_overwrites(self, tmp_path: Path) -> None:
        writer = RebuildManifestWriter(tmp_path)
        for i in range(3):
            writer.append(_run(i))
        df = pq.read_table(writer.path).to_pandas()
        assert len(df) == 3
        assert list(df["run_id"]) == ["r0", "r1", "r2"]

    def test_unfinished_run_raises(self, tmp_path: Path) -> None:
        writer = RebuildManifestWriter(tmp_path)
        run = RebuildRun(
            run_id="r1",
            source="sp500-wikipedia",
            started_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
        )
        with pytest.raises(ValueError, match="finished_at"):
            writer.append(run)

    def test_records_errors_list(self, tmp_path: Path) -> None:
        writer = RebuildManifestWriter(tmp_path)
        run = _run()
        run.errors = ["RuntimeError: bad table"]
        writer.append(run)
        df = pq.read_table(writer.path).to_pandas()
        assert list(df["errors"].iloc[0]) == ["RuntimeError: bad table"]
