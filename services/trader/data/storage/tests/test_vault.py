"""Vault-embargo tests.

Covers `vault-embargo-spec.md` §6 acceptance:
- Default `vault_cutoff_days=None` preserves P1.1 behaviour
- Configured cutoff raises VaultEmbargoError on overlapping reads
- vault_override=True warns and returns data
- Boundary cases at the cutoff
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from services.trader.data.connectors.base import ConnectorResult
from services.trader.data.storage import ParquetAdapter, VaultEmbargoError, assess_vault
from services.trader.data.storage.tests.conftest import make_ohlcv_frame


def _result(frame: pd.DataFrame, source: str = "yfinance") -> ConnectorResult:
    return ConnectorResult(
        frame=frame,
        source=source,
        fetched_at=datetime.now(UTC),
        rows=len(frame),
    )


# --- assess_vault unit tests --------------------------------------------


class TestAssessVault:
    def test_disabled_when_cutoff_days_none(self) -> None:
        d = assess_vault(
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 5, 9, tzinfo=UTC),
            asof=datetime(2026, 5, 9, tzinfo=UTC),
            vault_cutoff_days=None,
        )
        assert d.enforced is False
        assert d.overlaps_vault is False
        assert d.cutoff_dt is None

    def test_inside_vault(self) -> None:
        asof = datetime(2026, 5, 9, tzinfo=UTC)
        d = assess_vault(
            start=datetime(2026, 4, 1, tzinfo=UTC),
            end=asof,
            asof=asof,
            vault_cutoff_days=180,
        )
        assert d.enforced and d.overlaps_vault

    def test_just_outside_vault(self) -> None:
        asof = datetime(2026, 5, 9, tzinfo=UTC)
        # Window ending exactly at the cutoff is "outside" by spec (`end > cutoff`)
        cutoff = asof - timedelta(days=180)
        d = assess_vault(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=cutoff,
            asof=asof,
            vault_cutoff_days=180,
        )
        assert d.enforced
        assert d.overlaps_vault is False  # boundary: end == cutoff is outside

    def test_one_microsecond_inside(self) -> None:
        asof = datetime(2026, 5, 9, tzinfo=UTC)
        cutoff = asof - timedelta(days=180)
        d = assess_vault(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=cutoff + timedelta(microseconds=1),
            asof=asof,
            vault_cutoff_days=180,
        )
        assert d.overlaps_vault is True

    def test_negative_days_rejected(self) -> None:
        with pytest.raises(ValueError, match=">= 0"):
            assess_vault(
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 2, tzinfo=UTC),
                asof=datetime(2026, 5, 9, tzinfo=UTC),
                vault_cutoff_days=-1,
            )


# --- ParquetAdapter integration with vault ------------------------------


class TestAdapterDefault:
    """The default `vault_cutoff_days=None` must preserve P1.1 behaviour."""

    def test_default_no_vault_enforcement(self, tmp_path: Path) -> None:
        adapter = ParquetAdapter(tmp_path)
        df = make_ohlcv_frame(ticker="SPY", start=datetime(2026, 5, 1, tzinfo=UTC), bars=3)
        adapter.write(_result(df), kind="ohlcv")
        out = adapter.read(
            kind="ohlcv",
            keys=["SPY"],
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 5, 9, tzinfo=UTC),
            asof=datetime(2026, 5, 9, tzinfo=UTC),
        )
        # Returns data even though [May 1, May 9] is firmly inside any reasonable vault
        assert len(out) == 3

    def test_invalid_cutoff_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match=">= 0"):
            ParquetAdapter(tmp_path, vault_cutoff_days=-5)


class TestAdapterEnforced:
    @pytest.fixture
    def adapter(self, tmp_path: Path) -> ParquetAdapter:
        return ParquetAdapter(tmp_path, vault_cutoff_days=180)

    def test_overlapping_window_raises(self, adapter: ParquetAdapter) -> None:
        df = make_ohlcv_frame(ticker="SPY", start=datetime(2026, 5, 1, tzinfo=UTC), bars=3)
        adapter.write(_result(df), kind="ohlcv")
        with pytest.raises(VaultEmbargoError) as ei:
            adapter.read(
                kind="ohlcv",
                keys=["SPY"],
                start=datetime(2026, 5, 1, tzinfo=UTC),
                end=datetime(2026, 5, 9, tzinfo=UTC),
                asof=datetime(2026, 5, 9, tzinfo=UTC),
            )
        assert ei.value.start == datetime(2026, 5, 1, tzinfo=UTC)
        assert ei.value.end == datetime(2026, 5, 9, tzinfo=UTC)

    def test_window_outside_vault_succeeds(self, adapter: ParquetAdapter) -> None:
        # Data + window fully predate the 180-day cutoff
        old_df = make_ohlcv_frame(
            ticker="SPY", start=datetime(2018, 1, 8, tzinfo=UTC), bars=3
        )
        adapter.write(_result(old_df), kind="ohlcv")
        out = adapter.read(
            kind="ohlcv",
            keys=["SPY"],
            start=datetime(2018, 1, 1, tzinfo=UTC),
            end=datetime(2018, 1, 31, tzinfo=UTC),
            asof=datetime(2026, 5, 9, tzinfo=UTC),
        )
        assert len(out) == 3

    def test_override_warns_and_returns(
        self, adapter: ParquetAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        df = make_ohlcv_frame(ticker="SPY", start=datetime(2026, 5, 1, tzinfo=UTC), bars=3)
        adapter.write(_result(df), kind="ohlcv")
        with caplog.at_level(logging.WARNING):
            out = adapter.read(
                kind="ohlcv",
                keys=["SPY"],
                start=datetime(2026, 5, 1, tzinfo=UTC),
                end=datetime(2026, 5, 9, tzinfo=UTC),
                asof=datetime(2026, 5, 9, tzinfo=UTC),
                vault_override=True,
                vault_override_reason="phase-1 vault-test",
            )
        assert len(out) == 3
        assert any("vault_override=True" in r.getMessage() for r in caplog.records)

    def test_default_asof_uses_now(self, adapter: ParquetAdapter) -> None:
        # No asof passed -> uses datetime.now(UTC). A read in 1900 must be far
        # outside any reasonable vault and succeed.
        ancient = make_ohlcv_frame(
            ticker="SPY", start=datetime(1900, 1, 8, tzinfo=UTC), bars=3
        )
        adapter.write(_result(ancient), kind="ohlcv")
        out = adapter.read(
            kind="ohlcv",
            keys=["SPY"],
            start=datetime(1900, 1, 1, tzinfo=UTC),
            end=datetime(1900, 12, 31, tzinfo=UTC),
        )
        assert len(out) == 3


def test_vault_error_repr_lists_all_fields() -> None:
    err = VaultEmbargoError(
        start=datetime(2026, 4, 1, tzinfo=UTC),
        end=datetime(2026, 5, 1, tzinfo=UTC),
        asof=datetime(2026, 5, 9, tzinfo=UTC),
        vault_cutoff=datetime(2025, 11, 10, tzinfo=UTC),
    )
    msg = str(err)
    assert "2026-04-01" in msg
    assert "2026-05-01" in msg
    assert "2025-11-10" in msg
    assert "vault_override" in msg


# --- chunk V2: vault_override_reason + audit-writer wire-up -------------


class _FakeAuditWriter:
    """Records vault_override calls for assertion in tests."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.calls: list[dict[str, object]] = []

    def is_enabled(self) -> bool:
        return True

    def write(
        self, *, actor: str, action: str, payload: dict[str, object]
    ) -> bytes | None:
        if self._fail:
            raise RuntimeError("simulated postgres outage")
        self.calls.append({"actor": actor, "action": action, "payload": dict(payload)})
        return b"\x00" * 32  # fake hash


class TestOverrideReasonRequired:
    @pytest.fixture
    def adapter(self, tmp_path: Path) -> ParquetAdapter:
        return ParquetAdapter(tmp_path, vault_cutoff_days=180)

    def test_override_without_reason_raises(self, adapter: ParquetAdapter) -> None:
        df = make_ohlcv_frame(
            ticker="SPY", start=datetime(2026, 5, 1, tzinfo=UTC), bars=3
        )
        adapter.write(_result(df), kind="ohlcv")
        with pytest.raises(ValueError, match="vault_override_reason"):
            adapter.read(
                kind="ohlcv",
                keys=["SPY"],
                start=datetime(2026, 5, 1, tzinfo=UTC),
                end=datetime(2026, 5, 9, tzinfo=UTC),
                asof=datetime(2026, 5, 9, tzinfo=UTC),
                vault_override=True,
                # vault_override_reason intentionally absent
            )

    def test_override_with_blank_reason_raises(self, adapter: ParquetAdapter) -> None:
        df = make_ohlcv_frame(
            ticker="SPY", start=datetime(2026, 5, 1, tzinfo=UTC), bars=3
        )
        adapter.write(_result(df), kind="ohlcv")
        with pytest.raises(ValueError, match="vault_override_reason"):
            adapter.read(
                kind="ohlcv",
                keys=["SPY"],
                start=datetime(2026, 5, 1, tzinfo=UTC),
                end=datetime(2026, 5, 9, tzinfo=UTC),
                asof=datetime(2026, 5, 9, tzinfo=UTC),
                vault_override=True,
                vault_override_reason="   ",  # whitespace-only is rejected
            )

    def test_override_outside_vault_does_not_require_reason(
        self, adapter: ParquetAdapter
    ) -> None:
        # If the requested window doesn't overlap the vault, override is moot —
        # we shouldn't require a reason since no embargo would have fired.
        df = make_ohlcv_frame(
            ticker="SPY", start=datetime(2018, 1, 8, tzinfo=UTC), bars=3
        )
        adapter.write(_result(df), kind="ohlcv")
        out = adapter.read(
            kind="ohlcv",
            keys=["SPY"],
            start=datetime(2018, 1, 1, tzinfo=UTC),
            end=datetime(2018, 1, 31, tzinfo=UTC),
            asof=datetime(2026, 5, 9, tzinfo=UTC),
            vault_override=True,
            # no reason — fine because no overlap
        )
        assert len(out) == 3


class TestAuditWriterWireUp:
    def _adapter_with_audit(
        self, tmp_path: Path, *, fail: bool = False
    ) -> tuple[ParquetAdapter, _FakeAuditWriter]:
        writer = _FakeAuditWriter(fail=fail)
        adapter = ParquetAdapter(
            tmp_path,
            vault_cutoff_days=180,
            audit_writer=writer,  # type: ignore[arg-type]
            audit_actor="test-vault-actor",
        )
        return adapter, writer

    def test_override_writes_one_audit_row(self, tmp_path: Path) -> None:
        adapter, writer = self._adapter_with_audit(tmp_path)
        df = make_ohlcv_frame(
            ticker="SPY", start=datetime(2026, 5, 1, tzinfo=UTC), bars=3
        )
        adapter.write(_result(df), kind="ohlcv")
        adapter.read(
            kind="ohlcv",
            keys=["SPY", "QQQ", "IWM"],
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 5, 9, tzinfo=UTC),
            asof=datetime(2026, 5, 9, tzinfo=UTC),
            vault_override=True,
            vault_override_reason="needed for live PnL reconciliation",
        )
        assert len(writer.calls) == 1
        call = writer.calls[0]
        assert call["actor"] == "test-vault-actor"
        assert call["action"] == "vault_override"
        payload = call["payload"]
        assert payload["kind"] == "ohlcv"
        assert payload["keys_count"] == 3
        assert payload["keys_sample"] == ["SPY", "QQQ", "IWM"]
        assert payload["reason"] == "needed for live PnL reconciliation"

    def test_audit_failure_does_not_suppress_read(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        adapter, writer = self._adapter_with_audit(tmp_path, fail=True)
        df = make_ohlcv_frame(
            ticker="SPY", start=datetime(2026, 5, 1, tzinfo=UTC), bars=3
        )
        adapter.write(_result(df), kind="ohlcv")
        with caplog.at_level(logging.ERROR):
            out = adapter.read(
                kind="ohlcv",
                keys=["SPY"],
                start=datetime(2026, 5, 1, tzinfo=UTC),
                end=datetime(2026, 5, 9, tzinfo=UTC),
                asof=datetime(2026, 5, 9, tzinfo=UTC),
                vault_override=True,
                vault_override_reason="best-effort smoke",
            )
        # Read still returns data even though audit-write blew up
        assert len(out) == 3
        assert any("audit-events write failed" in r.getMessage() for r in caplog.records)

    def test_no_audit_writer_logs_skip(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # vault_cutoff_days set, but no audit_writer wired
        adapter = ParquetAdapter(tmp_path, vault_cutoff_days=180)
        df = make_ohlcv_frame(
            ticker="SPY", start=datetime(2026, 5, 1, tzinfo=UTC), bars=3
        )
        adapter.write(_result(df), kind="ohlcv")
        with caplog.at_level(logging.WARNING):
            out = adapter.read(
                kind="ohlcv",
                keys=["SPY"],
                start=datetime(2026, 5, 1, tzinfo=UTC),
                end=datetime(2026, 5, 9, tzinfo=UTC),
                asof=datetime(2026, 5, 9, tzinfo=UTC),
                vault_override=True,
                vault_override_reason="local debug",
            )
        assert len(out) == 3
        assert any(
            "audit-events row not recorded" in r.getMessage() for r in caplog.records
        )


