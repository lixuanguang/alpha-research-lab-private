"""Define immutable values for the governed source topology.

Construction checks field types through ``ImmutableModel``. The topology loader
validates source existence, ownership, references and dependency direction;
record construction and in-memory lookup perform no filesystem or graph checks.
"""

from __future__ import annotations

# project library imports
from alpha_research_governance._models import ImmutableModel


class RepositoryTopologyError(ValueError):
    """Report topology findings in their supplied order.

    Attributes:
        findings: Immutable snapshot of the supplied messages, including duplicates.
    """

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        """Capture findings and join them with newlines for the exception message.

        Args:
            findings: Ordered diagnostic messages; an empty sequence is permitted.
        """
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class SourceUnit(ImmutableModel):
    """Declare one owned unit and its direct edges in the repository source graph.

    Attributes:
        unit_id: Unique source-unit identifier in the loaded topology.
        kind: Unit category: compatibility surface, library, test or tool.
        layer: Governed layer controlling dependency direction.
        owner_role: Governed role accountable for this source unit.
        supported_platforms: Platform tokens, with ``any`` admitted only on its own.
        dependencies: Direct dependency unit identifiers, in declared order.
        visibility: Unit identifiers required to match the set of direct consumers.
        sources: Explicit repository-relative source-file paths owned by this unit.
    """

    unit_id: str
    kind: str
    layer: str
    owner_role: str
    supported_platforms: tuple[str, ...]
    dependencies: tuple[str, ...]
    visibility: tuple[str, ...]
    sources: tuple[str, ...]


class RepositoryTopology(ImmutableModel):
    """Store repository-topology metadata and the declared source-unit graph.

    Loader validation establishes graph uniqueness and consistency. The ``unit``
    query searches the stored sequence without revalidating that graph.

    Attributes:
        schema_version: Topology declaration schema version.
        roadmap_package: Roadmap package owning the topology contract.
        delivery_slice: Identifier of the currently delivered topology slice.
        operating_track: Governance operating track used by the declaration.
        package_status: Declared completion status of the owning roadmap package.
        slice_status: Declared completion status of the delivery slice.
        accountable_owner_role: Governed role accountable for the topology.
        risk_class: Declared change-risk classification.
        applicable_gate_ids: Ordered quality gates required for this package.
        source_roots: Repository-relative roots whose source files require registration.
        maximum_source_files: Inclusive source-inventory size bound for validation.
        validation_workload_budget_ms: Topology validation benchmark budget in milliseconds.
        layer_order: Layers from lowest to highest; dependencies cannot point upward.
        remaining_slices: Declared topology work deferred to later slices.
        local_evidence_manifest_path: Repository-relative package evidence manifest.
        local_evidence_commit_sha: Commit to which the local evidence is bound.
        units: Source units retained in declaration order.
        finding_ids: Ordered finding identifiers recorded for the topology slice.
    """

    schema_version: int
    roadmap_package: str
    delivery_slice: str
    operating_track: str
    package_status: str
    slice_status: str
    accountable_owner_role: str
    risk_class: str
    applicable_gate_ids: tuple[str, ...]
    source_roots: tuple[str, ...]
    maximum_source_files: int
    validation_workload_budget_ms: int
    layer_order: tuple[str, ...]
    remaining_slices: tuple[str, ...]
    local_evidence_manifest_path: str
    local_evidence_commit_sha: str
    units: tuple[SourceUnit, ...]
    finding_ids: tuple[str, ...]

    def unit(self, unit_id: str) -> SourceUnit:
        """Return the first stored unit whose identifier matches exactly.

        Args:
            unit_id: Case-sensitive source-unit identifier, without normalization.

        Returns:
            The stored source unit; the record is not copied or revalidated.

        Raises:
            RepositoryTopologyError: No stored unit has the supplied identifier.
        """
        for unit in self.units:
            if unit.unit_id == unit_id:
                return unit
        raise RepositoryTopologyError([f"unknown source unit {unit_id!r}"])
