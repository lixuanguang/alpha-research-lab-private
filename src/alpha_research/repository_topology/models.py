"""Immutable domain values for the B01 governed source topology."""

from __future__ import annotations

from alpha_research._models import ImmutableModel


class RepositoryTopologyError(ValueError):
    """Report one or more deterministic topology findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class SourceUnit(ImmutableModel):
    """One owned unit in the current repository source graph."""

    unit_id: str
    kind: str
    layer: str
    owner_role: str
    supported_platforms: tuple[str, ...]
    dependencies: tuple[str, ...]
    visibility: tuple[str, ...]
    sources: tuple[str, ...]


class RepositoryTopology(ImmutableModel):
    """Validated B01a registry metadata and current source units."""

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
        """Return a registered unit, failing closed for an unknown identifier."""
        for unit in self.units:
            if unit.unit_id == unit_id:
                return unit
        raise RepositoryTopologyError([f"unknown source unit {unit_id!r}"])
