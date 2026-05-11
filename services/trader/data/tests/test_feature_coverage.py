"""Tests for `coverage.report_features` (P1.4 F5 extension)."""

from __future__ import annotations

import pandas as pd

from services.trader.data.coverage import FeatureCoverageReport, report_features


def test_full_non_null_passes() -> None:
    frame = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [10.0, 20.0, 30.0]})
    reports = report_features(frame, feature_columns=["a", "b"])
    assert all(isinstance(r, FeatureCoverageReport) for r in reports)
    by_name = {r.feature: r for r in reports}
    assert by_name["a"].null_rate_pct == 0.0
    assert by_name["a"].passed
    assert by_name["b"].null_rate_pct == 0.0


def test_null_rate_exceeds_threshold_fails() -> None:
    frame = pd.DataFrame({"a": [1.0, None, None, None]})  # 75% null
    reports = report_features(frame, feature_columns=["a"], null_rate_threshold_pct=1.0)
    assert reports[0].null_rate_pct == 75.0
    assert reports[0].passed is False


def test_placeholder_passes_regardless_of_null_rate() -> None:
    frame = pd.DataFrame({"sentiment_score": [None, None, None]})
    reports = report_features(
        frame,
        feature_columns=["sentiment_score"],
        placeholder_columns={"sentiment_score"},
    )
    r = reports[0]
    assert r.placeholder is True
    assert r.null_rate_pct == 100.0
    # Placeholder always passes
    assert r.passed is True


def test_missing_column_produces_failed_report() -> None:
    frame = pd.DataFrame({"a": [1.0, 2.0]})
    reports = report_features(frame, feature_columns=["a", "missing"])
    by_name = {r.feature: r for r in reports}
    assert by_name["missing"].bars_non_null == 0
    assert by_name["missing"].null_rate_pct == 100.0
    assert by_name["missing"].passed is False


def test_empty_frame_returns_zero_null_rate() -> None:
    frame = pd.DataFrame({"a": []})
    reports = report_features(frame, feature_columns=["a"])
    assert reports[0].bars_total == 0
    assert reports[0].null_rate_pct == 0.0
    # 0/0 by convention → passed True (no data, no failure)
    assert reports[0].passed is True


def test_summary_includes_placeholder_marker() -> None:
    frame = pd.DataFrame({"sentiment_score": [0.0, 0.0]})
    r = report_features(
        frame,
        feature_columns=["sentiment_score"],
        placeholder_columns={"sentiment_score"},
    )[0]
    assert "[PLACEHOLDER]" in r.summary
