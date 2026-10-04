"""Load registered candidate components from verified installed extension distributions."""

from __future__ import annotations

# standard library imports
import base64
import hashlib
import inspect
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib.metadata import Distribution, PackageNotFoundError, distribution, distributions
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

# project library imports
from research.features import FeatureKernel, FeatureSchema, TransformAdapter
from runtime.components import (
    CandidateComponents,
    ChartFactory,
    EstimatorFactory,
    FeatureFactory,
    MetricFactory,
    PolicyFactory,
    TransformFactory,
)
from strategies import DecisionPolicy

if TYPE_CHECKING:
    # project library imports
    from research.models import EstimatorAdapter
    from research.studies import ChartDefinition, MetricDefinition


@dataclass(frozen=True)
class ExtensionFactories:
    """Name the component constructors one extension provides, by registered key."""

    features: Mapping[str, Callable[[FeatureSchema, bytes], FeatureKernel]]
    policies: Mapping[str, Callable[[bytes], DecisionPolicy]]
    transforms: Mapping[str, Callable[[bytes], TransformAdapter]] = field(default_factory=dict)
    estimators: Mapping[str, Callable[[bytes], EstimatorAdapter]] = field(default_factory=dict)
    metrics: Mapping[str, Callable[[bytes], MetricDefinition]] = field(default_factory=dict)
    charts: Mapping[str, Callable[[bytes], ChartDefinition]] = field(default_factory=dict)


class ExtensionProvider(Protocol):
    """Expose one extension's factories; registered under the component entry-point group."""

    def factories(self) -> ExtensionFactories:
        """Return the extension's component constructors by registered key."""
        ...


class InstalledExtensions:
    """Resolve candidate components only from named, verified installed distributions.

    An extension registers one provider class under the
    ``alpha_research.candidate_components`` entry-point group. Its identity is the
    SHA-256 of its installed ``RECORD``, after every recorded file is checked against
    its recorded hash. Every component it provides carries that identity as its
    implementation digest, so a candidate definition pins the exact extension code.
    Nothing is imported by path or module name from configuration.
    """

    group = "alpha_research.candidate_components"

    def __init__(self, search_paths: tuple[Path, ...] | None = None) -> None:
        """Search the interpreter's installed distributions, or only explicit directories."""
        self.search_paths = search_paths

    def identity(self, name: str) -> str:
        """Verify the named distribution's installed files and return its RECORD digest.

        Raises:
            ValueError: The distribution is absent, unrecorded or modified after install.
        """
        installed = self._distribution(name)
        record = installed.read_text("RECORD")
        files = installed.files
        if record is None or files is None:
            raise ValueError(f"extension has no installed record: {name}")
        for item in files:
            if item.hash is None:
                continue
            if item.hash.mode != "sha256":
                raise ValueError(f"extension records an unsupported file hash: {name}")
            located = Path(os.fspath(item.locate()))
            digest = base64.urlsafe_b64encode(hashlib.sha256(located.read_bytes()).digest()).rstrip(
                b"="
            )
            if digest.decode() != item.hash.value:
                raise ValueError(f"installed extension file differs from its record: {item}")
        return hashlib.sha256(record.encode()).hexdigest()

    def components(self, name: str) -> CandidateComponents:
        """Load the named extension's single registered provider as candidate factories."""
        installed = self._distribution(name)
        entries = tuple(item for item in installed.entry_points if item.group == self.group)
        if len(entries) != 1:
            raise ValueError(f"extension must register exactly one component provider: {name}")
        implementation = self.identity(name)
        provider = cast(object, entries[0].load())
        if not inspect.isclass(provider):
            raise TypeError(f"extension component provider is not a class: {name}")
        instance = cast(ExtensionProvider, cast(Callable[[], object], provider)())
        factories = instance.factories()
        if type(factories) is not ExtensionFactories:
            raise TypeError(f"extension provider returned no ExtensionFactories: {name}")
        return CandidateComponents(
            features={
                key: FeatureFactory(implementation_sha256=implementation, create=create)
                for key, create in factories.features.items()
            },
            policies={
                key: PolicyFactory(implementation_sha256=implementation, create=create)
                for key, create in factories.policies.items()
            },
            transforms={
                key: TransformFactory(implementation_sha256=implementation, create=create)
                for key, create in factories.transforms.items()
            },
            estimators={
                key: EstimatorFactory(implementation_sha256=implementation, create=create)
                for key, create in factories.estimators.items()
            },
            metrics={
                key: MetricFactory(implementation_sha256=implementation, create=create)
                for key, create in factories.metrics.items()
            },
            charts={
                key: ChartFactory(implementation_sha256=implementation, create=create)
                for key, create in factories.charts.items()
            },
        )

    def _distribution(self, name: str) -> Distribution:
        """Find exactly one installed distribution by its exact project name."""
        if not name or name.startswith("alpha-research-"):
            raise ValueError("extension names a platform or empty distribution")
        if self.search_paths is None:
            try:
                return distribution(name)
            except PackageNotFoundError as error:
                raise ValueError(f"extension is not installed: {name}") from error
        found = tuple(distributions(name=name, path=[str(item) for item in self.search_paths]))
        if len(found) != 1:
            raise ValueError(f"extension is not installed exactly once: {name}")
        return found[0]
