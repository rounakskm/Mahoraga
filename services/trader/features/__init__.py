"""Feature engineering pipeline for Mahoraga.

See `docs/superpowers/specs/phase-1-foundation/feature-pipeline-spec.md`.
"""

# Side-effect imports populate BUILTIN_FEATURES via register_feature(...) calls.
# Tests that want only a specific category pass an explicit `features=[...]`
# kwarg to FeaturePipeline rather than relying on the default registry.
from services.trader.features import (
    macro,  # noqa: F401, E402
    momentum,  # noqa: F401, E402
    statistical,  # noqa: F401, E402
    trend,  # noqa: F401, E402
    volatility,  # noqa: F401, E402
    volume,  # noqa: F401, E402
)
from services.trader.features.base import (
    BUILTIN_FEATURES,
    Feature,
    FeatureCategory,
    FeatureContext,
    FeatureFrame,
    register_feature,
)
from services.trader.features.pipeline import FeaturePipeline, FeatureRunResult  # noqa: E402

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
