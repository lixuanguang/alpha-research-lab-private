"""Resolve reviewed installed candidate factories without importing names from configuration."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

# project library imports
from research.experiments import CandidateComponent, Fingerprint
from research.features import FeatureKernel, FeatureSchema, TransformAdapter
from strategies import DecisionPolicy

if TYPE_CHECKING:
    # project library imports
    from research.models import EstimatorAdapter
    from research.reports import ChartDefinition, MetricDefinition


@dataclass(frozen=True)
class FeatureFactory:
    """Bind reviewed feature construction to retrievable implementation bytes."""

    implementation_sha256: str
    create: Callable[[FeatureSchema, bytes], FeatureKernel]


@dataclass(frozen=True)
class PolicyFactory:
    """Bind reviewed policy construction to retrievable implementation bytes."""

    implementation_sha256: str
    create: Callable[[bytes], DecisionPolicy]


@dataclass(frozen=True)
class TransformFactory:
    """Bind reviewed transform construction; inference never invokes fitting."""

    implementation_sha256: str
    create: Callable[[bytes], TransformAdapter]


@dataclass(frozen=True)
class EstimatorFactory:
    """Bind reviewed estimator construction; fitted bytes are loaded separately."""

    implementation_sha256: str
    create: Callable[[bytes], EstimatorAdapter]


@dataclass(frozen=True)
class MetricFactory:
    """Bind an existing study metric definition to its reviewed factory."""

    implementation_sha256: str
    create: Callable[[bytes], MetricDefinition]


@dataclass(frozen=True)
class ChartFactory:
    """Bind an existing study chart definition to its reviewed factory."""

    implementation_sha256: str
    create: Callable[[bytes], ChartDefinition]


class CandidateComponents:
    """Own immutable explicit factory selections, with no dynamic imports or fallback.

    The composition root verifies and registers installed implementation bytes.
    SHA-256 equality here is compatibility/integrity, not trusted installation.
    Keys are local registered names, never Python import paths to evaluate.
    """

    def __init__(
        self,
        *,
        features: Mapping[str, FeatureFactory],
        policies: Mapping[str, PolicyFactory],
        transforms: Mapping[str, TransformFactory] | None = None,
        estimators: Mapping[str, EstimatorFactory] | None = None,
        metrics: Mapping[str, MetricFactory] | None = None,
        charts: Mapping[str, ChartFactory] | None = None,
    ) -> None:
        """Snapshot the factories selected by the application, without constructing components."""
        self._features = dict(features)
        self._policies = dict(policies)
        self._transforms = {} if transforms is None else dict(transforms)
        self._estimators = {} if estimators is None else dict(estimators)
        self._metrics = {} if metrics is None else dict(metrics)
        self._charts = {} if charts is None else dict(charts)

    def admit(self, selected: tuple[CandidateComponent, ...]) -> None:
        """Reject every missing factory or changed implementation before constructing any."""
        inventories = {
            "feature": {k: v.implementation_sha256 for k, v in self._features.items()},
            "policy": {k: v.implementation_sha256 for k, v in self._policies.items()},
            "transform": {k: v.implementation_sha256 for k, v in self._transforms.items()},
            "estimator": {k: v.implementation_sha256 for k, v in self._estimators.items()},
            "metric": {k: v.implementation_sha256 for k, v in self._metrics.items()},
            "chart": {k: v.implementation_sha256 for k, v in self._charts.items()},
        }
        for component in selected:
            component.__post_init__()
            actual = inventories[component.role].get(component.factory_key)
            if actual != component.implementation_sha256:
                raise ValueError("candidate factory is absent or its implementation differs")
            Fingerprint(name=component.factory_key, sha256=actual)

    def feature(
        self, selected: CandidateComponent, schema: FeatureSchema, parameters: bytes
    ) -> FeatureKernel:
        """Construct the selected kernel and reject a substituted schema."""
        self.admit((selected,))
        if selected.role != "feature":
            raise ValueError("feature factory requires a feature component")
        result = self._features[selected.factory_key].create(schema, parameters)
        if result.schema != schema or result.schema.identity != selected.identity:
            raise ValueError("candidate feature factory returned a different definition")
        return result

    def policy(self, selected: CandidateComponent, parameters: bytes) -> DecisionPolicy:
        """Construct the selected decision policy and reject changed parameters/formulas."""
        self.admit((selected,))
        if selected.role != "policy":
            raise ValueError("policy factory requires a policy component")
        result = self._policies[selected.factory_key].create(parameters)
        if result.identity != selected.identity:
            raise ValueError("candidate policy factory returned a different identity")
        return result

    def transform(self, selected: CandidateComponent, parameters: bytes) -> TransformAdapter:
        """Resolve exact preprocessing semantics without fitting state."""
        self.admit((selected,))
        if selected.role != "transform":
            raise ValueError("transform factory requires a transform component")
        result = self._transforms[selected.factory_key].create(parameters)
        if result.identity != selected.identity:
            raise ValueError("candidate transform factory returned a different identity")
        return result

    def estimator(self, selected: CandidateComponent, parameters: bytes) -> EstimatorAdapter:
        """Resolve exact prediction semantics without fitting state."""
        self.admit((selected,))
        if selected.role != "estimator":
            raise ValueError("estimator factory requires an estimator component")
        result = self._estimators[selected.factory_key].create(parameters)
        if result.identity != selected.identity:
            raise ValueError("candidate estimator factory returned a different identity")
        return result

    def metric(self, selected: CandidateComponent, parameters: bytes) -> MetricDefinition:
        """Load the same versioned metric definition used by the research report."""
        self.admit((selected,))
        if selected.role != "metric":
            raise ValueError("metric factory requires a metric component")
        result = self._metrics[selected.factory_key].create(parameters)
        if result.identity.sha256 != selected.identity:
            raise ValueError("candidate metric factory returned a different identity")
        return result

    def chart(self, selected: CandidateComponent, parameters: bytes) -> ChartDefinition:
        """Load the same versioned chart definition used by the research report."""
        self.admit((selected,))
        if selected.role != "chart":
            raise ValueError("chart factory requires a chart component")
        result = self._charts[selected.factory_key].create(parameters)
        if result.identity.sha256 != selected.identity:
            raise ValueError("candidate chart factory returned a different identity")
        return result
