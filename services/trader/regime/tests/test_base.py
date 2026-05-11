"""Tests for the regime ABC + dataclasses (P1.5 R1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from services.trader.regime.base import (
    UNDEFINED_LABEL,
    ClassificationResult,
    CompositeRegime,
    Lens,
    RegimeRunResult,
)


class _ConstantLens(Lens):
    """Test double — every classify() returns the same canned verdict."""

    name = "test"

    def __init__(self, result: ClassificationResult) -> None:
        self._result = result

    def required_features(self) -> list[str]:
        return ["any"]

    def classify(
        self,
        *,
        feature_row: pd.Series,
        macro_row: pd.Series | None,
    ) -> ClassificationResult:
        return self._result


class TestClassificationResult:
    def test_basic_construction(self) -> None:
        r = ClassificationResult(label="bull", confidence=0.7, inputs={"x": 1.0})
        assert r.label == "bull"
        assert r.confidence == 0.7
        assert r.inputs == {"x": 1.0}

    def test_confidence_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError):
            ClassificationResult(label="bull", confidence=1.5)
        with pytest.raises(ValueError):
            ClassificationResult(label="bull", confidence=-0.1)

    def test_undefined_zero_confidence(self) -> None:
        r = ClassificationResult(label=UNDEFINED_LABEL, confidence=0.0)
        assert r.label == UNDEFINED_LABEL
        assert r.confidence == 0.0
        assert r.inputs == {}


class TestCompositeRegime:
    def test_two_lens_compose(self) -> None:
        c = CompositeRegime(
            macro="bull",
            meso="trending_low_vol",
            macro_conf=0.8,
            meso_conf=0.6,
            composite_conf=0.6,
        )
        assert c.macro == "bull"
        assert c.composite_conf == 0.6
        assert c.micro is None
        assert c.micro_conf is None

    def test_micro_slot_forward_compat(self) -> None:
        c = CompositeRegime(
            macro="bull",
            meso="ranging_low_vol",
            macro_conf=0.5,
            meso_conf=0.5,
            composite_conf=0.5,
            micro="momentum",
            micro_conf=0.9,
        )
        assert c.micro == "momentum"
        assert c.micro_conf == 0.9

    def test_invalid_confidence_rejected(self) -> None:
        with pytest.raises(ValueError):
            CompositeRegime(
                macro="bull",
                meso="trending_low_vol",
                macro_conf=2.0,
                meso_conf=0.5,
                composite_conf=0.5,
            )


class TestLensABC:
    def test_constant_lens_satisfies_contract(self) -> None:
        lens = _ConstantLens(
            ClassificationResult(label="bull", confidence=0.9, inputs={"x": 1.0})
        )
        result = lens.classify(feature_row=pd.Series(dtype="float64"), macro_row=None)
        assert result.label == "bull"
        assert lens.required_features() == ["any"]

    def test_abstract_class_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            Lens()  # type: ignore[abstract]


class TestRegimeRunResult:
    def test_default_dataclass(self) -> None:
        now = datetime.now(UTC)
        r = RegimeRunResult(
            run_id="abc",
            started_at=now,
            finished_at=now,
            scope="universe",
        )
        assert r.rows == []
        assert r.inputs_by_bar == []
        assert r.failures == []
