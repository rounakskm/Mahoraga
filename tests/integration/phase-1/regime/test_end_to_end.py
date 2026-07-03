"""End-to-end Phase-1 regime-detector integration test (P1.5 R4).

Wires the full chain (yfinance fake → ParquetAdapter → FeaturePipeline
→ RegimeDetector) under real Postgres so a single test exercises:

1. OHLCV ingest writes raw bars + 1 manifest row + 1 audit.events row.
2. FeaturePipeline reads PIT-correct OHLCV, computes features, writes
   feature parquet + 1 manifest row + 1 audit.events row.
3. RegimeDetector reads hand-built feature/macro inputs (the synthetic
   30-bar window is too short for `realized_vol_pct_60` warmup; label
   correctness is exercised by per-lens unit tests in R1/R2), writes
   regime parquet + 1 manifest row + 1 audit.events row.
4. Manifest now has exactly 3 rows: yfinance + feature-pipeline +
   regime-detector.
5. audit.events has 3 new rows under our actor, with actions
   `ingest`, `compute`, `classify` in order.
6. The hash chain across those 3 rows verifies link-by-link from the
   pre-test seed hash.
7. Regime PIT read at `asof` earlier than `fetched_at` excludes the
   freshly written classification rows.

CI runs this in the `integration-smoke` job. Locally, `docker compose
up -d postgres` + `MAHORAGA_TEST_DSN`.
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
from services.trader.features import FeaturePipeline
from services.trader.features.store import FeatureStore
from services.trader.features.trend import SMA
from services.trader.regime import (
    MacroLens,
    MesoLens,
    RegimeDetector,
    RegimeStore,
)

_ACTOR = "test-phase1-regime-e2e"
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
def regime_root(tmp_path: Path) -> Path:
    return tmp_path / "regime-root"


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


# --- regime detector inputs --------------------------------------------


def _regime_feature_frame() -> pd.DataFrame:
    """Hand-built feature inputs the regime detector can classify cleanly.

    The 30-bar synthetic isn't long enough for the pipeline's
    `realized_vol_pct_60` warmup, so the integration test asserts the
    detector path works on a deterministic input — label correctness
    itself is covered by the per-lens unit tests under
    `services/trader/regime/tests/`.
    """
    return pd.DataFrame(
        {
            "bar_timestamp": pd.to_datetime(
                ["2026-01-05", "2026-01-06", "2026-01-07"], utc=True
            ),
            "adx_14": [40.0, 12.0, 35.0],
            "realized_vol_pct_60": [0.0, 80.0, 20.0],
        }
    )


def _regime_macro_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bar_timestamp": pd.to_datetime(
                ["2026-01-05", "2026-01-06", "2026-01-07"], utc=True
            ),
            "yield_2s10s": [0.5, -0.10, 0.4],
            "vix_level": [14.0, 35.0, 14.0],
            "dxy_change_20d": [-1.0, 2.0, -1.0],
        }
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


def _snapshot_audit_head(dsn: str) -> int:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM audit.events ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else 0


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


# --- tests --------------------------------------------------------------


class TestRegimeDetectorEndToEnd:
    def test_full_path_writes_parquet_manifests_and_audit_chain(
        self,
        parquet_root: Path,
        features_root: Path,
        regime_root: Path,
        audit_logger: AuditLogger,
    ) -> None:
        adapter = ParquetAdapter(parquet_root, vault_cutoff_days=None)
        feature_store = FeatureStore(features_root, vault_cutoff_days=None)
        regime_store = RegimeStore(regime_root, vault_cutoff_days=None)
        dsn = os.environ["MAHORAGA_TEST_DSN"]
        pre_id = _snapshot_audit_head(dsn)

        # --- 1. OHLCV ingest --------------------------------------
        _ingest_ohlcv(adapter, audit_logger)

        # --- 2. Feature pipeline ----------------------------------
        feature_pipeline = FeaturePipeline(
            adapter=adapter,
            store=feature_store,
            features=[SMA(window=20)],
            manifest_root=str(parquet_root),
            audit_writer=PostgresAuditWriter(dsn=dsn),
            audit_actor=_ACTOR,
        )
        feature_pipeline.compute(
            tickers=["SPY"], start=_START, end=_END
        )

        # --- 3. Regime detector ------------------------------------
        detector = RegimeDetector(
            lenses=[MesoLens(), MacroLens()],
            store=regime_store,
            manifest_root=str(parquet_root),
            audit_writer=PostgresAuditWriter(dsn=dsn),
            audit_actor=_ACTOR,
        )
        result = detector.classify(
            scope="universe",
            feature_frame=_regime_feature_frame(),
            macro_frame=_regime_macro_frame(),
        )
        assert len(result.rows) == 3
        # The 3-bar input produces deterministic labels — sanity-check
        labels = [(row.meso, row.macro) for row in result.rows]
        assert labels == [
            ("trending_low_vol", "bull"),
            ("ranging_high_vol", "bear"),
            ("trending_low_vol", "bull"),
        ]

        # --- 4. Regime parquet on disk -----------------------------
        partition_path = regime_root / "regime" / "universe" / "2026.parquet"
        assert partition_path.exists()
        regime_partition = pq.read_table(partition_path).to_pandas()
        assert len(regime_partition) == 3
        assert (regime_partition["source"] == "regime-detector").all()

        # --- 5. PIT read after the run sees all 3 rows ------------
        read_back = regime_store.read(
            scopes=["universe"],
            start=datetime(2026, 1, 5, tzinfo=UTC),
            end=datetime(2026, 1, 7, 23, 59, tzinfo=UTC),
            lens_names=["meso", "macro"],
        )
        assert len(read_back) == 3

        # --- 6. PIT read at asof BEFORE the run sees nothing ------
        pre_compute_asof = (
            regime_partition["fetched_at"].min() - timedelta(seconds=1)
        ).to_pydatetime()
        pre_view = regime_store.read(
            scopes=["universe"],
            start=datetime(2026, 1, 5, tzinfo=UTC),
            end=datetime(2026, 1, 7, 23, 59, tzinfo=UTC),
            asof=pre_compute_asof,
            lens_names=["meso", "macro"],
        )
        assert pre_view.empty

        # --- 7. Manifest has 3 rows: ingest + compute + classify --
        manifest_path = parquet_root / "manifests" / "ingest-runs.parquet"
        manifest = pq.read_table(manifest_path).to_pandas()
        assert len(manifest) == 3
        assert set(manifest["source"]) == {
            "yfinance", "feature-pipeline", "regime-detector",
        }

        # --- 8. Audit chain: 3 new rows, actions in order ---------
        rows = _query_audit_rows(dsn, since_id=pre_id)
        assert len(rows) == 3
        actions = [r[3] for r in rows]
        assert actions == ["ingest", "compute", "classify"]
        classify_payload = rows[2][4]
        assert classify_payload["source"] == "regime-detector"
        assert classify_payload["scope"] == "universe"
        assert classify_payload["rows_written"] == 3
        assert classify_payload["lens_count"] == 2
        assert classify_payload["lens_names"] == ["meso", "macro"]

        # --- 9. Hash chain links across all 3 rows ----------------
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
            stored_prev_bytes = (
                bytes(stored_prev) if stored_prev is not None else None
            )
            assert stored_prev_bytes == prev, (
                f"hash chain broken at id={row[0]}: expected prev="
                f"{prev.hex() if prev else None}, got "
                f"{stored_prev_bytes.hex() if stored_prev_bytes else None}"
            )
            prev = bytes(row[6])

    def test_idempotent_reclassify_no_duplicate_rows(
        self,
        parquet_root: Path,
        regime_root: Path,
        audit_logger: AuditLogger,
    ) -> None:
        regime_store = RegimeStore(regime_root, vault_cutoff_days=None)
        # Two detectors share the same store; second run writes 0 new rows.
        detector_a = RegimeDetector(
            lenses=[MesoLens(), MacroLens()], store=regime_store
        )
        detector_b = RegimeDetector(
            lenses=[MesoLens(), MacroLens()], store=regime_store
        )
        detector_a.classify(
            scope="universe",
            feature_frame=_regime_feature_frame(),
            macro_frame=_regime_macro_frame(),
        )
        detector_b.classify(
            scope="universe",
            feature_frame=_regime_feature_frame(),
            macro_frame=_regime_macro_frame(),
        )
        partition_path = regime_root / "regime" / "universe" / "2026.parquet"
        partition = pq.read_table(partition_path).to_pandas()
        assert len(partition) == 3  # not 6
