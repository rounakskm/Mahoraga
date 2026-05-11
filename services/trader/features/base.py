"""Feature ABC + registry + context types.

Every feature is a pure function of an OHLCV history (and optionally PIT-correct
macro data). Features must not read from the filesystem, network, or globals;
they take a `FeatureContext` and return a per-bar `pd.Series`.

See `docs/superpowers/specs/phase-1-foundation/feature-pipeline-spec.md` §4.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import pandas as pd
import pyarrow as pa

logger = logging.getLogger(__name__)


FeatureCategory = Literal[
    "trend", "momentum", "volatility", "volume",
    "statistical", "macro", "sentiment",
]


@dataclass(frozen=True)
class FeatureContext:
    """Inputs to a single feature evaluation."""

    ticker: str
    frame: pd.DataFrame                       # OHLCV with bar_timestamp index, sorted ascending
    asof: datetime                            # PIT cutoff for any macro lookups
    macro_fetcher: Callable[[str], pd.DataFrame] | None = None
    ohlcv_fetcher: Callable[[str], pd.DataFrame] | None = None  # for cross-ticker features


class Feature(ABC):
    """Abstract base for all features.

    Subclasses set class-level `name` and `category`; `placeholder` defaults
    to False and is True only for the sentiment placeholder.
    """

    name: str
    category: FeatureCategory
    placeholder: bool = False

    @abstractmethod
    def required_history_bars(self) -> int:
        """Minimum bars for this feature to return a non-null value."""

    @abstractmethod
    def compute(self, ctx: FeatureContext) -> pd.Series:
        """Return a per-bar value Series. Index aligns with `ctx.frame.bar_timestamp`."""

    # Convenience: features without a category-specific override fall back here.
    def __repr__(self) -> str:  # pragma: no cover (formatting only)
        return f"<Feature {self.name!r} category={self.category}>"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


BUILTIN_FEATURES: list[Feature] = []
"""Mutable list of registered features.

Per-category modules append to this list at import time via
:func:`register_feature`. Tests pass an explicit feature list to
`FeaturePipeline` and don't depend on the global registry.
"""


def register_feature(feature: Feature) -> Feature:
    """Add a feature instance to BUILTIN_FEATURES; return it for fluent use."""
    if any(f.name == feature.name for f in BUILTIN_FEATURES):
        raise ValueError(f"feature {feature.name!r} is already registered")
    BUILTIN_FEATURES.append(feature)
    return feature


def features_in(category: FeatureCategory) -> list[Feature]:
    """Filter BUILTIN_FEATURES to a single category."""
    return [f for f in BUILTIN_FEATURES if f.category == category]


def feature_names() -> list[str]:
    return [f.name for f in BUILTIN_FEATURES]


# ---------------------------------------------------------------------------
# FeatureFrame schema (PyArrow)
# ---------------------------------------------------------------------------


_FIXED_COLUMNS = [
    pa.field("ticker",        pa.string(), nullable=False),
    pa.field("bar_timestamp", pa.timestamp("us", tz="UTC"), nullable=False),
]
_TRAILING_COLUMNS = [
    pa.field("source",      pa.string(),                 nullable=False),
    pa.field("fetched_at",  pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("revision_at", pa.timestamp("us", tz="UTC"), nullable=True),
]


def feature_frame_schema(features: list[Feature]) -> pa.Schema:
    """Build the on-disk Arrow schema for the requested feature set.

    The fixed prefix (ticker + bar_timestamp) and trailing provenance fields
    (source / fetched_at / revision_at) match the OHLCV row schema so the
    same `ParquetAdapter` write path works without special-casing.
    """
    fields = list(_FIXED_COLUMNS)
    for f in features:
        fields.append(pa.field(f.name, pa.float64(), nullable=True))
    fields.extend(_TRAILING_COLUMNS)
    return pa.schema(fields)


@dataclass
class FeatureFrame:
    """Convenience wrapper around the assembled feature DataFrame.

    Held briefly during pipeline runs; not persisted as an object — the
    underlying DataFrame is what gets written to parquet.
    """

    frame: pd.DataFrame
    features: list[Feature] = field(default_factory=list)

    @property
    def feature_columns(self) -> list[str]:
        return [f.name for f in self.features]

    def non_null_counts(self) -> dict[str, int]:
        return {col: int(self.frame[col].notna().sum()) for col in self.feature_columns}
