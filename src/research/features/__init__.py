"""Expose versioned trailing-price diagnostics and their explicit window contract."""

# project library imports
from research.features.offline import (
    FeastOfflineWorker,
    FeatureAccessError,
    FeatureEntity,
    FeatureObservation,
    FeatureParity,
    OfflineFeatureAccess,
    OfflineFeatureBridge,
    OfflineFeatureComparison,
    OfflineFeatureDefinition,
    OfflineFeatureRequest,
    OfflineFeatureResult,
)
from research.features.windows import (
    FeatureDefinition,
    FeatureFactory,
    FeatureRegistry,
    FeatureValue,
    PricePoint,
    PriceWindow,
    TrailingReturn,
    WindowPolicy,
)

__all__ = [
    "FeastOfflineWorker",
    "FeatureAccessError",
    "FeatureDefinition",
    "FeatureEntity",
    "FeatureFactory",
    "FeatureObservation",
    "FeatureParity",
    "FeatureRegistry",
    "FeatureValue",
    "OfflineFeatureAccess",
    "OfflineFeatureBridge",
    "OfflineFeatureComparison",
    "OfflineFeatureDefinition",
    "OfflineFeatureRequest",
    "OfflineFeatureResult",
    "PricePoint",
    "PriceWindow",
    "TrailingReturn",
    "WindowPolicy",
]
