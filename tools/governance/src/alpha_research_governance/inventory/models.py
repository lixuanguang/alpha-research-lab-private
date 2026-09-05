"""Define domain models for the governed resource inventory.

These immutable records and serializers perform no file or network I/O.
Registry loading validates catalog-wide ownership, references and status
evidence; direct construction validates strict field types only.
"""

from __future__ import annotations

# standard library imports
from datetime import date

# project library imports
from alpha_research_governance._models import ImmutableModel


class InventoryGovernanceError(ValueError):
    """Report ordered inventory-governance findings in one exception.

    Attributes:
        findings: Immutable tuple preserving supplied diagnostic order and duplicates.
    """

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        """Retain findings and join them into the exception message.

        Args:
            findings: Messages copied to a tuple and joined with newlines, without sorting.
        """
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class KindPopulation(ImmutableModel):
    """Declare whether an inventory kind is populated and who owns that claim.

    The inventory loader compares this declaration with actual item counts.

    Attributes:
        kind: Resource-kind key.
        population_status: Declared populated or empty state.
        owner_role: Role accountable for this resource kind.
        rationale: Explanation of the population declaration.
    """

    kind: str
    population_status: str
    owner_role: str
    rationale: str

    def as_json(self) -> dict[str, str]:
        """Return the stable JSON-compatible population record.

        Returns:
            A fresh dictionary of the four stored string fields, without encoding JSON text.
        """
        return {
            "kind": self.kind,
            "owner_role": self.owner_role,
            "population_status": self.population_status,
            "rationale": self.rationale,
        }


class InventoryItem(ImmutableModel):
    """Describe a versioned resource with ownership, dependencies and evidence lineage.

    The inventory loader checks owner roles, reference resolution, dependency
    cycles, retention/deployment states and review dates. Direct construction
    validates field types without establishing those catalog-wide guarantees.

    Attributes:
        inventory_id: Stable inventory key used by dependency and lineage references.
        kind: Declared resource-kind token.
        record_version: Version of this resource record.
        name: Human-readable resource name.
        owner_role: Role accountable for the resource.
        criticality: Declared criticality classification.
        status: Declared resource lifecycle status.
        dependencies: Inventory IDs of required resources.
        retention_class: Declared evidence/data retention class.
        source_paths: Repository source paths expected to be represented in lineage_refs.
        lineage_refs: Inventory IDs, repository paths or external evidence references
            supporting lineage.
        deployment_status: Declared deployment or activation state.
        deployment_evidence: References supporting deployment claims.
        status_evidence: References supporting lifecycle-status claims.
        review_due_on: Review deadline compared with catalog as_of_date by the loader.
    """

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
        """Return the stable JSON-compatible resource record.

        Returns:
            A fresh dictionary with tuple fields copied to lists and review_due_on rendered as
            ISO calendar-date text. Reference order is preserved; no files are read or JSON text
            encoded.
        """
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
    """Hold resource records and package metadata used by inventory queries.

    Use load_inventory for kind coverage, item bounds, ownership, references,
    lineage and dependency validation. Direct construction checks typed fields.
    The query operation filters stored records without sorting, checking external
    evidence or enforcing benchmark limits.

    Attributes:
        catalog_version: Declared resource-catalog version.
        as_of_date: Snapshot date used for review-deadline checks.
        inventory_scope: Declared scope of governed resources.
        package_status: Declared inventory-capability status.
        maximum_items: Catalog item-count bound enforced by the loader.
        query_workload_iterations: Iteration count for the governed query benchmark.
        query_workload_budget_ms: Benchmark budget in milliseconds; queries do not enforce a
            timeout.
        local_evidence_manifest_path: Recorded local evidence manifest path.
        local_evidence_commit_sha: Commit identity used to bind local evidence.
        kinds: Population declarations for resource kinds.
        items: Resource records in stored order.
        finding_ids: Retained unresolved inventory-governance findings.
    """

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
        """Return records matching all supplied filters in stored order.

        Args:
            kind: Exact case-sensitive kind, or None to leave kind unrestricted.
            status: Exact case-sensitive lifecycle status, or None to leave status unrestricted.
            owner_role: Exact case-sensitive owner role, or None to leave owner unrestricted.

        Returns:
            A tuple of the original matching item objects. None imposes no constraint; empty or
            unknown strings match only equal stored values, and no matches yield an empty tuple.
        """
        return tuple(
            item
            for item in self.items
            if (kind is None or item.kind == kind)
            and (status is None or item.status == status)
            and (owner_role is None or item.owner_role == owner_role)
        )
