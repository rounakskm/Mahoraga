"""Feature engineering pipeline for Mahoraga.

See `docs/superpowers/specs/phase-1-foundation/feature-pipeline-spec.md`.
"""

from services.trader.features.base import (
    BUILTIN_FEATURES,
    Feature,
    FeatureCategory,
    FeatureContext,
    FeatureFrame,
    register_feature,
)
from services.trader.features.pipeline import FeaturePipeline, FeatureRunResult

__all__ = [
    "BUILTIN_FEATURES",
    "Feature",
    "FeatureCategory",
    "FeatureContext",
    "FeatureFrame",
    "FeaturePipeline",
    "FeatureRunResult",
    "register_feature",
]
