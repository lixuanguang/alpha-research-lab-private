"""Expose exact model construction, versioned inference and retained input admission.

Estimator adapters and versions load eagerly. The pandas-based model inputs, linear
models and studies load on first use, so an operating application that only runs
fitted estimators does not install or import the study stack.
"""

# standard library imports
from typing import TYPE_CHECKING

# project library imports
from research.models.adapters import (
    EstimatorAdapter,
    EstimatorLifecycle,
    EstimatorVersion,
    NearestExample,
)

if TYPE_CHECKING:
    # project library imports
    from research.models.inputs import ModelDataset, ModelFrame, ModelRow, ModelSignature
    from research.models.linear import (
        EstimatorFactory,
        EstimatorRegistry,
        LinearDefinition,
        LinearModel,
        LinearState,
        ModelVersion,
    )
    from research.models.study import ModelStudy, RetainedResult


def __getattr__(name: str) -> object:
    """Load the pandas-based model study surface only for its explicit consumers."""
    if name in {"ModelDataset", "ModelFrame", "ModelRow", "ModelSignature"}:
        # project library imports
        from research.models import inputs

        exports: dict[str, object] = {
            "ModelDataset": inputs.ModelDataset,
            "ModelFrame": inputs.ModelFrame,
            "ModelRow": inputs.ModelRow,
            "ModelSignature": inputs.ModelSignature,
        }
        return exports[name]
    if name in {
        "EstimatorFactory",
        "EstimatorRegistry",
        "LinearDefinition",
        "LinearModel",
        "LinearState",
        "ModelVersion",
    }:
        # project library imports
        from research.models import linear

        exports = {
            "EstimatorFactory": linear.EstimatorFactory,
            "EstimatorRegistry": linear.EstimatorRegistry,
            "LinearDefinition": linear.LinearDefinition,
            "LinearModel": linear.LinearModel,
            "LinearState": linear.LinearState,
            "ModelVersion": linear.ModelVersion,
        }
        return exports[name]
    if name in {"ModelStudy", "RetainedResult"}:
        # project library imports
        from research.models import study

        exports = {"ModelStudy": study.ModelStudy, "RetainedResult": study.RetainedResult}
        return exports[name]
    raise AttributeError(name)


__all__ = [
    "EstimatorAdapter",
    "EstimatorFactory",
    "EstimatorLifecycle",
    "EstimatorRegistry",
    "EstimatorVersion",
    "LinearDefinition",
    "LinearModel",
    "LinearState",
    "ModelDataset",
    "ModelFrame",
    "ModelRow",
    "ModelSignature",
    "ModelStudy",
    "ModelVersion",
    "NearestExample",
    "RetainedResult",
]
