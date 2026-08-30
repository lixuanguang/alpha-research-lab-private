"""Domain models for the A06 governed resource inventory."""

from __future__ import annotations

from datetime import date

from alpha_research._models import ImmutableModel


class InventoryGovernanceError(ValueError):
    """Report one or more deterministic inventory findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class KindPopulation(ImmutableModel):
    """Declared population state and owner for one inventory kind."""

    kind: str
    population_status: str
    owner_role: str
    rationale: str

    def as_json(self) -> dict[str, str]:
        """Return the stable JSON representation used by inventory queries."""
        return {
            "kind": self.kind,
            "owner_role": self.owner_role,
            "population_status": self.population_status,
            "rationale": self.rationale,
        }


class InventoryItem(ImmutableModel):
    """One versioned resource record with ownership and evidence lineage."""

    inventory_id: str
    kind: str
    record_version: int
    name: str
    owner_role: str
    criticality: str
    status: str
    dependencies: tuple[str, ...]
    retention_class: str
    source_paths: tuple[str, ...]
    lineage_refs: tuple[str, ...]
    deployment_status: str
    deployment_evidence: tuple[str, ...]
    status_evidence: tuple[str, ...]
    review_due_on: date

    def as_json(self) -> dict[str, object]:
        """Return the stable JSON representation used by inventory queries."""
        return {
            "criticality": self.criticality,
            "dependencies": list(self.dependencies),
            "deployment_evidence": list(self.deployment_evidence),
            "deployment_status": self.deployment_status,
            "inventory_id": self.inventory_id,
            "kind": self.kind,
            "lineage_refs": list(self.lineage_refs),
            "name": self.name,
            "owner_role": self.owner_role,
            "record_version": self.record_version,
            "retention_class": self.retention_class,
            "review_due_on": self.review_due_on.isoformat(),
            "source_paths": list(self.source_paths),
            "status": self.status,
            "status_evidence": list(self.status_evidence),
        }


class ResourceInventory(ImmutableModel):
    """Validated A06 catalog and package state."""

    catalog_version: int
    as_of_date: date
    inventory_scope: str
    package_status: str
    maximum_items: int
    query_workload_iterations: int
    query_workload_budget_ms: int
    local_evidence_manifest_path: str
    local_evidence_commit_sha: str
    kinds: tuple[KindPopulation, ...]
    items: tuple[InventoryItem, ...]
    finding_ids: tuple[str, ...]

    def query(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        owner_role: str | None = None,
    ) -> tuple[InventoryItem, ...]:
        """Return a deterministically ordered filtered inventory view."""
        return tuple(
            item
            for item in self.items
            if (kind is None or item.kind == kind)
            and (status is None or item.status == status)
            and (owner_role is None or item.owner_role == owner_role)
        )
