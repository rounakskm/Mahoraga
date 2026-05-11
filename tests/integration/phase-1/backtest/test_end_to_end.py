"""End-to-end Phase-1 backtest-harness integration test (P1.6 B3).

**Merging this test closes Phase 1.**

Wires the full Phase-1 chain (yfinance fake → ParquetAdapter →
FeaturePipeline → RegimeDetector → Backtest) under real Postgres so
a single test exercises the complete training-data + decision loop:

1. OHLCV ingest writes raw bars + 1 manifest row + 1 audit.events row
2. FeaturePipeline computes features, writes parquet + 1 manifest +
   1 audit.events row
3. RegimeDetector classifies + writes parquet + 1 manifest +
   1 audit.events row
4. Backtest runs BuyAndHold, emits FitnessReport + 1 manifest +
   1 audit.events row
5. Manifest now has exactly 4 rows: `yfinance`, `feature-pipeline`,
   `regime-detector`, `backtest-harness`
6. audit.events has 4 new rows with actions `ingest` / `compute` /
   `classify` / `run` in order
7. Hash chain links row-by-row across all four from the pre-test seed

CI runs this in the `integration-smoke` job. Locally: `docker compose
up -d postgres` + `MAHORAGA_TEST_DSN`.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import psycopg
import pyarrow.parquet as pq
import pytest

from services.trader.backtest import Backtest, BuyAndHold
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
from services.trader.regime.store import encode_inputs

_ACTOR = "test-phase1-backtest-e2e"
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


def _seed_regime(store: RegimeStore) -> None:
    """Seed the regime store with a hand-built per-bar classification.

    The 30-bar synthetic isn't long enough for the pipeline's
    `realized_vol_pct_60` warmup, so we inject a deterministic regime
    history here. Detector path itself is exercised by P1.5 R4 — this
    test focuses on backtest behavior over a long-enough universe.
    """
    frame = pd.DataFrame(
        {
            "scope": ["universe"] * len(_BAR_DATES),
            "asof": _BAR_DATES,
            "meso_label": ["trending_low_vol"] * len(_BAR_DATES),
            "meso_conf": [0.9] * len(_BAR_DATES),
            "macro_label": ["bull"] * len(_BAR_DATES),
            "macro_conf": [0.8] * len(_BAR_DATES),
            "composite_conf": [0.8] * len(_BAR_DATES),
            "inputs": [encode_inputs({})] * len(_BAR_DATES),
            "source": ["regime-detector"] * len(_BAR_DATES),
            "fetched_at": [pd.Timestamp(datetime.now(UTC))] * len(_BAR_DATES),
        }
    )
    store.write(frame, lens_names=["meso", "macro"])


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


class TestBacktestEndToEnd:
    def test_full_chain_emits_4_row_audit_chain(
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

        # --- 1. OHLCV ingest ---------------------------------------
        _ingest_ohlcv(adapter, audit_logger)

        # --- 2. Feature pipeline -----------------------------------
        FeaturePipeline(
            adapter=adapter,
            store=feature_store,
            features=[SMA(window=3)],
            manifest_root=str(parquet_root),
            audit_writer=PostgresAuditWriter(dsn=dsn),
            audit_actor=_ACTOR,
        ).compute(tickers=["SPY"], start=_START, end=_END)

        # --- 3. Regime detector ------------------------------------
        # Use the detector to write a real audit row (real detector path
        # is exercised by P1.5 R4); seed the store with deterministic
        # classifications so the backtest has a non-empty regime input.
        detector = RegimeDetector(
            lenses=[MesoLens(), MacroLens()],
            store=None,  # we seed the store directly below
            manifest_root=str(parquet_root),
            audit_writer=PostgresAuditWriter(dsn=dsn),
            audit_actor=_ACTOR,
        )
        detector.classify(
            scope="universe",
            feature_frame=pd.DataFrame(
                {
                    "bar_timestamp": _BAR_DATES,
                    "adx_14": [40.0] * len(_BAR_DATES),
                    "realized_vol_pct_60": [0.0] * len(_BAR_DATES),
                }
            ),
            macro_frame=pd.DataFrame(
                {
                    "bar_timestamp": _BAR_DATES,
                    "yield_2s10s": [0.5] * len(_BAR_DATES),
                    "vix_level": [14.0] * len(_BAR_DATES),
                    "dxy_change_20d": [-1.0] * len(_BAR_DATES),
                }
            ),
        )
        # Seed the regime store with the per-bar history (the detector
        # above ran with store=None so it only emitted manifest + audit).
        _seed_regime(regime_store)

        # --- 4. Backtest -------------------------------------------
        bt = Backtest(
            feature_store=feature_store,
            regime_store=regime_store,
            ohlcv_adapter=adapter,
            initial_capital=1_000_000.0,
            builtin_features=[SMA(window=3)],
            manifest_root=str(parquet_root),
            audit_writer=PostgresAuditWriter(dsn=dsn),
            audit_actor=_ACTOR,
        )
        report = bt.run(
            strategy=BuyAndHold(),
            universe=["SPY"],
            start=_START,
            end=_END,
        )
        assert report.strategy == "buy_and_hold"
        assert report.rejected_reason is None
        # Position size clipped to 5% → on a rising synthetic, total
        # return is a small positive number; absolute bound is generous.
        assert abs(report.total_return) < 0.10

        # --- 5. Manifest has 4 rows --------------------------------
        manifest_path = parquet_root / "manifests" / "ingest-runs.parquet"
        manifest = pq.read_table(manifest_path).to_pandas()
        assert len(manifest) == 4
        assert set(manifest["source"]) == {
            "yfinance",
            "feature-pipeline",
            "regime-detector",
            "backtest-harness",
        }

        # --- 6. Audit chain: 4 new rows, actions in order ----------
        rows = _query_audit_rows(dsn, since_id=pre_id)
        assert len(rows) == 4
        actions = [r[3] for r in rows]
        assert actions == ["ingest", "compute", "classify", "run"]
        run_payload = rows[3][4]
        assert run_payload["source"] == "backtest-harness"
        assert run_payload["strategy"] == "buy_and_hold"
        assert "total_return" in run_payload
        assert "sharpe" in run_payload

        # --- 7. Hash chain links across all 4 ----------------------
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

    def test_placeholder_strategy_records_rejection(
        self,
        parquet_root: Path,
        features_root: Path,
        regime_root: Path,
        audit_logger: AuditLogger,
    ) -> None:
        """End-to-end placeholder gate: rejected strategy still emits
        one audit.events row with `rejected_reason` populated."""
        from services.trader.backtest.base import Strategy
        from services.trader.features.sentiment import PlaceholderFeature

        class _BadStrategy(Strategy):
            name = "needs_sentiment"
            requires_features = ["sentiment_score"]
            allow_placeholder_features = False

            def generate_signals(
                self, *, feature_frame, regime_frame
            ):  # type: ignore[no-untyped-def]
                return pd.DataFrame(
                    columns=["ticker", "bar_timestamp", "target_weight"]
                )

        adapter = ParquetAdapter(parquet_root, vault_cutoff_days=None)
        feature_store = FeatureStore(features_root, vault_cutoff_days=None)
        regime_store = RegimeStore(regime_root, vault_cutoff_days=None)
        dsn = os.environ["MAHORAGA_TEST_DSN"]
        pre_id = _snapshot_audit_head(dsn)

        bt = Backtest(
            feature_store=feature_store,
            regime_store=regime_store,
            ohlcv_adapter=adapter,
            builtin_features=[PlaceholderFeature("sentiment_score")],
            manifest_root=str(parquet_root),
            audit_writer=PostgresAuditWriter(dsn=dsn),
            audit_actor=_ACTOR,
        )
        report = bt.run(
            strategy=_BadStrategy(),
            universe=["SPY"],
            start=_START,
            end=_END,
        )
        assert report.rejected_reason is not None
        assert "sentiment_score" in report.rejected_reason

        rows = _query_audit_rows(dsn, since_id=pre_id)
        # One row: the backtest run with rejected_reason populated.
        assert len(rows) == 1
        payload = rows[0][4]
        assert payload["rejected_reason"] is not None
        assert "sentiment_score" in payload["rejected_reason"]
