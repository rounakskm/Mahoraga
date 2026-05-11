"""End-to-end Phase-1 feature-pipeline integration test (P1.4 F6).

Wires the full ingest path (yfinance fake → ParquetAdapter → AuditLogger
with a real Postgres) into the FeaturePipeline (P1.4 F1–F5), so a single
test exercises:

1. OHLCV ingest writes raw bars + 1 manifest row + 1 audit.events row.
2. FeaturePipeline reads PIT-correct OHLCV, computes features, writes
   feature parquet + 1 manifest row + 1 audit.events row.
3. Re-running the pipeline is idempotent (no duplicate feature rows).
4. PIT read at an `asof` earlier than the pipeline's `fetched_at` excludes
   the freshly written feature rows.
5. Coverage report flags SMA warmup as failing and exempts the sentiment
   placeholder.
6. FeatureStore vault embargo blocks recent windows when enforced.
7. The hash chain across (ingest, compute) rows verifies row-by-row.

CI runs this in the `integration-smoke` job. Locally, `docker compose up
-d postgres` + `MAHORAGA_TEST_DSN`.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import psycopg
import pyarrow.parquet as pq
import pytest

from services.trader.data.audit import (
    AuditLogger,
    ManifestWriter,
    PostgresAuditWriter,
)
from services.trader.data.connectors.base import RateLimiter
from services.trader.data.connectors.yfinance import (
    YFinanceConnector,
    _RetryConfig,
)
from services.trader.data.ingest import Ingest, IngestMode
from services.trader.data.storage import ParquetAdapter
from services.trader.data.storage.vault import VaultEmbargoError
from services.trader.features import FeaturePipeline
from services.trader.features.sentiment import PlaceholderFeature
from services.trader.features.store import FeatureStore
from services.trader.features.trend import SMA

_ACTOR = "test-phase1-feature-e2e"
# 30 NYSE trading days starting 2026-01-05 (Mon) — enough warmup to give
# SMA(window=20) ~10 non-null bars and ~67% null rate.
_BAR_DATES = pd.bdate_range(start="2026-01-05", periods=30, tz="UTC")
_START = date(2026, 1, 5)
_END = _BAR_DATES[-1].date()


# --- fixtures -----------------------------------------------------------


@pytest.fixture(autouse=True)
def _require_dsn() -> None:
    if not os.environ.get("MAHORAGA_TEST_DSN"):
        pytest.skip("MAHORAGA_TEST_DSN not set; integration tests require Postgres")


@pytest.fixture
def parquet_root(tmp_path: Path) -> Path:
    return tmp_path / "parquet"


@pytest.fixture
def features_root(tmp_path: Path) -> Path:
    return tmp_path / "features-root"


@pytest.fixture
def audit_logger(parquet_root: Path) -> AuditLogger:
    dsn = os.environ["MAHORAGA_TEST_DSN"]
    return AuditLogger(
        manifest=ManifestWriter(parquet_root),
        postgres=PostgresAuditWriter(dsn=dsn),
        actor=_ACTOR,
    )


# --- yfinance fakery ----------------------------------------------------


def _yf_frame(ticker: str, dates: list[pd.Timestamp]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open":      [100.0 + i for i in range(len(dates))],
            "High":      [101.0 + i for i in range(len(dates))],
            "Low":       [99.0 + i for i in range(len(dates))],
            "Close":     [100.5 + i * 0.5 for i in range(len(dates))],
            "Adj Close": [100.4 + i * 0.5 for i in range(len(dates))],
            "Volume":    [1_000_000 + i for i in range(len(dates))],
        },
        index=pd.DatetimeIndex(dates, tz="UTC"),
    )


def _make_yf_connector() -> YFinanceConnector:
    return YFinanceConnector(
        rate_limiter=RateLimiter(capacity=100.0, refill_rate_per_sec=1000.0),
        downloader=lambda **_kw: _yf_frame("SPY", list(_BAR_DATES)),
        retry_config=_RetryConfig(
            max_attempts=2, base_backoff_sec=0.001, backoff_cap_sec=0.01
        ),
        sleep=lambda _s: None,
    )


# --- helpers ------------------------------------------------------------


def _ingest_ohlcv(adapter: ParquetAdapter, audit: AuditLogger) -> None:
    Ingest(adapter=adapter, audit=audit).run_ohlcv(
        _make_yf_connector(),
        tickers=["SPY"],
        start=_START,
        end=_END,
        mode=IngestMode.FRESH,
        expected_calendar=_BAR_DATES,
    )


def _query_audit_rows(dsn: str, *, since_id: int) -> list[tuple]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, ts, actor, action, payload, prev_hash, hash "
            "FROM audit.events "
            "WHERE id > %s AND actor = %s "
            "ORDER BY id ASC",
            (since_id, _ACTOR),
        )
        return list(cur.fetchall())


def _snapshot_audit_head(dsn: str) -> int:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM audit.events ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else 0


# --- tests --------------------------------------------------------------


class TestFeaturePipelineEndToEnd:
    def test_full_path_writes_features_manifest_and_audit(
        self,
        parquet_root: Path,
        features_root: Path,
        audit_logger: AuditLogger,
    ) -> None:
        adapter = ParquetAdapter(parquet_root, vault_cutoff_days=None)
        store = FeatureStore(features_root, vault_cutoff_days=None)
        dsn = os.environ["MAHORAGA_TEST_DSN"]
        pre_id = _snapshot_audit_head(dsn)

        # --- 1. OHLCV ingest -----------------------------------------
        _ingest_ohlcv(adapter, audit_logger)

        # --- 2. Feature pipeline -------------------------------------
        pipeline = FeaturePipeline(
            adapter=adapter,
            store=store,
            features=[SMA(window=20), PlaceholderFeature("sentiment_score")],
            manifest_root=str(parquet_root),
            audit_writer=PostgresAuditWriter(dsn=dsn),
            audit_actor=_ACTOR,
        )
        result = pipeline.compute(
            tickers=["SPY"], start=_START, end=_END,
        )
        assert result.rows_written == 30
        assert result.failures == []
        assert sorted(result.feature_columns) == ["sentiment_score", "sma_20"]

        # --- 3. Feature parquet written on disk ----------------------
        partition_path = features_root / "features" / "SPY" / "2026.parquet"
        assert partition_path.exists()
        feature_partition = pq.read_table(partition_path).to_pandas()
        assert len(feature_partition) == 30
        assert set(feature_partition.columns) >= {
            "ticker", "bar_timestamp", "sma_20", "sentiment_score",
            "source", "fetched_at", "revision_at",
        }
        assert (feature_partition["source"] == "feature-pipeline").all()

        # --- 4. PIT read after pipeline run sees all 30 rows ---------
        read_back = store.read(
            keys=["SPY"],
            start=datetime.combine(_START, datetime.min.time(), tzinfo=UTC),
            end=datetime.combine(_END, datetime.max.time(), tzinfo=UTC),
            features=[SMA(window=20), PlaceholderFeature("sentiment_score")],
        )
        assert len(read_back) == 30
        # SMA-20 has 19-bar warmup → 11 non-null rows; sentiment placeholder is 0.0 everywhere
        assert read_back["sma_20"].notna().sum() == 11
        assert (read_back["sentiment_score"] == 0.0).all()

        # --- 5. PIT read at asof BEFORE pipeline ran sees nothing ----
        pre_compute_asof = (
            feature_partition["fetched_at"].min() - timedelta(seconds=1)
        ).to_pydatetime()
        pre_view = store.read(
            keys=["SPY"],
            start=datetime.combine(_START, datetime.min.time(), tzinfo=UTC),
            end=datetime.combine(_END, datetime.max.time(), tzinfo=UTC),
            asof=pre_compute_asof,
            features=[SMA(window=20), PlaceholderFeature("sentiment_score")],
        )
        assert pre_view.empty

        # --- 6. Manifest has 2 rows: ingest + feature pipeline -------
        manifest_path = parquet_root / "manifests" / "ingest-runs.parquet"
        manifest = pq.read_table(manifest_path).to_pandas()
        assert len(manifest) == 2
        assert set(manifest["source"]) == {"yfinance", "feature-pipeline"}

        # --- 7. Audit chain: 2 new rows, action ingest + compute -----
        rows = _query_audit_rows(dsn, since_id=pre_id)
        assert len(rows) == 2
        actions = [r[3] for r in rows]
        assert actions == ["ingest", "compute"]
        compute_payload = rows[1][4]
        assert compute_payload["source"] == "feature-pipeline"
        assert compute_payload["rows_written"] == 30
        assert compute_payload["feature_count"] == 2

        # --- 8. Hash chain links across both rows --------------------
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT hash FROM audit.events WHERE id <= %s "
                "ORDER BY id DESC LIMIT 1",
                (pre_id,),
            )
            prev_row = cur.fetchone()
            seed_hash = bytes(prev_row[0]) if prev_row else None
        prev = seed_hash
        for row in rows:
            stored_prev = row[5]
            stored_prev_bytes = bytes(stored_prev) if stored_prev is not None else None
            assert stored_prev_bytes == prev, (
                f"hash chain broken at id={row[0]}: expected prev="
                f"{prev.hex() if prev else None}, got "
                f"{stored_prev_bytes.hex() if stored_prev_bytes else None}"
            )
            prev = bytes(row[6])

        # --- 9. Coverage gate: SMA warmup fails, placeholder exempt -
        coverage_by_name = {c.feature: c for c in result.coverage}
        sma = coverage_by_name["sma_20"]
        sentiment = coverage_by_name["sentiment_score"]
        assert sma.passed is False
        assert sma.null_rate_pct > 1.0
        assert sentiment.passed is True
        assert sentiment.placeholder is True

    def test_idempotent_recompute_no_duplicate_rows(
        self,
        parquet_root: Path,
        features_root: Path,
        audit_logger: AuditLogger,
    ) -> None:
        adapter = ParquetAdapter(parquet_root, vault_cutoff_days=None)
        store = FeatureStore(features_root, vault_cutoff_days=None)
        _ingest_ohlcv(adapter, audit_logger)

        pipeline = FeaturePipeline(
            adapter=adapter,
            store=store,
            features=[SMA(window=20)],
        )
        first = pipeline.compute(tickers=["SPY"], start=_START, end=_END)
        # Second run should write 0 new rows: dedupe on (ticker, bar_timestamp).
        second = pipeline.compute(tickers=["SPY"], start=_START, end=_END)
        assert first.rows_written == 30
        assert second.rows_written == 0

        partition_path = features_root / "features" / "SPY" / "2026.parquet"
        partition = pq.read_table(partition_path).to_pandas()
        assert len(partition) == 30  # not 60

    def test_feature_store_vault_blocks_recent_window(
        self,
        parquet_root: Path,
        features_root: Path,
        audit_logger: AuditLogger,
    ) -> None:
        # The feature store enforces the same 180-day embargo posture as
        # ParquetAdapter. Reading a window that overlaps "now - 180d"
        # without an override must raise.
        adapter = ParquetAdapter(parquet_root, vault_cutoff_days=None)
        store = FeatureStore(features_root, vault_cutoff_days=180)
        _ingest_ohlcv(adapter, audit_logger)
        FeaturePipeline(
            adapter=adapter,
            store=FeatureStore(features_root, vault_cutoff_days=None),
            features=[SMA(window=20)],
        ).compute(tickers=["SPY"], start=_START, end=_END)

        with pytest.raises(VaultEmbargoError):
            store.read(
                keys=["SPY"],
                start=datetime.combine(_START, datetime.min.time(), tzinfo=UTC),
                end=datetime.combine(_END, datetime.max.time(), tzinfo=UTC),
                features=[SMA(window=20)],
            )

        # Override path with a reason must succeed.
        overridden = store.read(
            keys=["SPY"],
            start=datetime.combine(_START, datetime.min.time(), tzinfo=UTC),
            end=datetime.combine(_END, datetime.max.time(), tzinfo=UTC),
            features=[SMA(window=20)],
            vault_override=True,
            vault_override_reason="integration test exercising vault override",
        )
        assert len(overridden) == 30
