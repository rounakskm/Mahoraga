"""Tests for the RegimeDetector orchestrator in its R1 in-memory form."""

from __future__ import annotations

import pandas as pd
import pytest

from services.trader.regime.base import (
    ClassificationResult,
    Lens,
)
from services.trader.regime.detector import RegimeDetector, empty_regime_frame
from services.trader.regime.meso import MesoLens


class _RaisingLens(Lens):
    """Test double — raises in classify(); detector should record + recover."""

    name = "raising"

    def required_features(self) -> list[str]:
        return []

    def classify(
        self,
        *,
        feature_row: pd.Series,
        macro_row: pd.Series | None,
    ) -> ClassificationResult:
        raise RuntimeError("boom")


def _feature_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bar_timestamp": pd.to_datetime(
                ["2026-01-05", "2026-01-06", "2026-01-07"], utc=True
            ),
            "adx_14": [40.0, 12.0, 30.0],
            "realized_vol_pct_60": [0.20, 0.80, 0.50],
        }
    )


class TestRegimeDetectorBasic:
    def test_requires_at_least_one_lens(self) -> None:
        with pytest.raises(ValueError):
            RegimeDetector(lenses=[])

    def test_meso_only_run(self) -> None:
        detector = RegimeDetector(lenses=[MesoLens()])
        result = detector.classify(
            scope="universe", feature_frame=_feature_frame()
        )
        labels = [r.meso for r in result.rows]
        assert labels == [
            "trending_low_vol",
            "ranging_high_vol",
            "trending_high_vol",
        ]
        # MACRO absent → composite = MESO confidence
        for row in result.rows:
            assert row.macro == "undefined"
            assert row.composite_conf == row.meso_conf

    def test_inputs_snapshot_per_bar(self) -> None:
        detector = RegimeDetector(lenses=[MesoLens()])
        result = detector.classify(
            scope="universe", feature_frame=_feature_frame()
        )
        assert len(result.inputs_by_bar) == 3
        assert result.inputs_by_bar[0] == {
            "adx_14": 40.0,
            "realized_vol_pct_60": 0.20,
        }

    def test_lens_exception_is_isolated(self) -> None:
        detector = RegimeDetector(lenses=[MesoLens(), _RaisingLens()])
        result = detector.classify(
            scope="universe", feature_frame=_feature_frame()
        )
        # All 3 bars produce one failure each from the raising lens
        assert len(result.failures) == 3
        # MESO labels still produced
        assert result.rows[0].meso == "trending_low_vol"


class TestRegimeDetectorMacroLookup:
    def test_macro_row_resolves_to_latest_at_or_before(self) -> None:
        """The detector's macro_lookup must return the macro row whose
        bar_timestamp is the latest ≤ the feature bar's timestamp."""

        captured: list[pd.Series | None] = []

        class _Capturing(Lens):
            name = "capturing"

            def required_features(self) -> list[str]:
                return []

            def classify(
                self,
                *,
                feature_row: pd.Series,
                macro_row: pd.Series | None,
            ) -> ClassificationResult:
                captured.append(macro_row)
                return ClassificationResult(label="x", confidence=0.5)

        detector = RegimeDetector(lenses=[_Capturing()])
        macro_frame = pd.DataFrame(
            {
                "bar_timestamp": pd.to_datetime(
                    ["2026-01-01", "2026-01-06"], utc=True
                ),
                "vix_level": [15.0, 28.0],
            }
        )
        detector.classify(
            scope="universe",
            feature_frame=_feature_frame(),
            macro_frame=macro_frame,
        )
        # Bar 1 (2026-01-05): only 2026-01-01 row is ≤; should pick vix=15
        # Bar 2 (2026-01-06): both rows ≤; latest = vix=28
        # Bar 3 (2026-01-07): both rows ≤; still latest = vix=28
        assert captured[0]["vix_level"] == 15.0
        assert captured[1]["vix_level"] == 28.0
        assert captured[2]["vix_level"] == 28.0

    def test_missing_macro_frame_returns_none(self) -> None:
        captured: list[pd.Series | None] = []

        class _Capturing(Lens):
            name = "capturing"

            def required_features(self) -> list[str]:
                return []

            def classify(
                self,
                *,
                feature_row: pd.Series,
                macro_row: pd.Series | None,
            ) -> ClassificationResult:
                captured.append(macro_row)
                return ClassificationResult(label="x", confidence=0.0)

        detector = RegimeDetector(lenses=[_Capturing()])
        detector.classify(
            scope="universe", feature_frame=_feature_frame(), macro_frame=None
        )
        assert captured == [None, None, None]


class TestEmptyRegimeFrame:
    def test_columns_match_lens_names(self) -> None:
        frame = empty_regime_frame(["meso", "macro"])
        assert "meso_label" in frame.columns
        assert "macro_label" in frame.columns
        assert "composite_conf" in frame.columns
        assert "inputs" in frame.columns
        assert len(frame) == 0
