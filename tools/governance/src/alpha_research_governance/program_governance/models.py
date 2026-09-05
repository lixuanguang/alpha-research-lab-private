"""Define domain models for the program graph and KPI contract."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from math import ceil
from typing import Literal, Self

from pydantic import field_validator, model_validator

from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.operating_model import GovernanceStatus, ImplementationStatus

DependencyPurpose = Literal["implementation", "operation_release", "team_handover"]
FindingDisposition = Literal["technical", "operation_prerequisite", "role_handover"]
_DEPENDENCY_PURPOSES: tuple[DependencyPurpose, ...] = (
    "implementation",
    "operation_release",
    "team_handover",
)


class ProgramGovernanceError(ValueError):
    """Report one or more deterministic program-governance findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class PackageNode(ImmutableModel):
    """One implementation package in the authoritative roadmap DAG."""

    package_id: str
    wave: str
    objective: str
    dependencies: tuple[str, ...]
    any_of_dependency_groups: tuple[tuple[str, ...], ...]
    operation_release_dependencies: tuple[str, ...] = ()
    operation_release_any_of_dependency_groups: tuple[tuple[str, ...], ...] = ()
    team_handover_dependencies: tuple[str, ...] = ()
    team_handover_any_of_dependency_groups: tuple[tuple[str, ...], ...] = ()

    def dependency_requirements(
        self,
        purpose: DependencyPurpose,
    ) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
        """Return all-of and any-of requirements for one dependency purpose."""
        if purpose == "implementation":
            return self.dependencies, self.any_of_dependency_groups
        if purpose == "operation_release":
            return (
                self.operation_release_dependencies,
                self.operation_release_any_of_dependency_groups,
            )
        return self.team_handover_dependencies, self.team_handover_any_of_dependency_groups

    def all_dependency_ids(self) -> tuple[str, ...]:
        """Return every referenced package once, independent of edge purpose."""
        values: list[str] = []
        for purpose in _DEPENDENCY_PURPOSES:
            dependencies, groups = self.dependency_requirements(purpose)
            values.extend(dependencies)
            values.extend(item for group in groups for item in group)
        return tuple(dict.fromkeys(values))

    def as_json(self) -> dict[str, object]:
        """Return the stable dashboard representation."""
        return {
            "any_of_dependency_groups": [list(group) for group in self.any_of_dependency_groups],
            "dependency_purposes": {
                purpose: {
                    "all_of": list(self.dependency_requirements(purpose)[0]),
                    "any_of": [list(group) for group in self.dependency_requirements(purpose)[1]],
                }
                for purpose in _DEPENDENCY_PURPOSES
            },
            "dependencies": list(self.dependencies),
            "objective": self.objective,
            "package_id": self.package_id,
            "wave": self.wave,
        }


class PackageState(ImmutableModel):
    """Repository-local implementation state for one roadmap package."""

    package_id: str
    status: str
    owner_role: str
    repository_local_status: str
    deferred_evidence_classes: tuple[str, ...]
    evidence_paths: tuple[str, ...]
    open_finding_ids: tuple[str, ...]
    implementation_status: ImplementationStatus = "in_progress"
    governance_status: GovernanceStatus = "pending"
    domain_id: str | None = None
    technical_finding_ids: tuple[str, ...] = ()
    assigned_reviewers: tuple[str, ...] = ()

    @property
    def contract_path(self) -> str:
        """Return the single active capability contract for current records."""
        return self.evidence_paths[0]

    @model_validator(mode="after")
    def completion_requires_technical_evidence(self) -> Self:
        """Keep technical failure distinct from unstaffed governance requirements."""
        if self.implementation_status == "complete" and (
            self.repository_local_status != "passed" or self.technical_finding_ids
        ):
            raise ValueError("completion requires passing repository-local evidence")
        return self

    def is_solo_provisionally_satisfied(self) -> bool:
        """Return whether the state can satisfy a solo-bootstrap dependency."""
        return self.implementation_status == "complete"

    def as_json(self) -> dict[str, object]:
        """Return the stable dashboard representation."""
        return {
            "implementation_status": self.implementation_status,
            "governance_status": self.governance_status,
            "domain_id": self.domain_id,
            "technical_finding_ids": list(self.technical_finding_ids),
            "assigned_reviewers": list(self.assigned_reviewers),
            "institutional_status": self.status,
            "deferred_evidence_classes": list(self.deferred_evidence_classes),
            "contract_path": self.contract_path,
            "evidence_paths": list(self.evidence_paths),
            "open_finding_ids": list(self.open_finding_ids),
            "owner_role": self.owner_role,
            "package_id": self.package_id,
            "repository_local_status": self.repository_local_status,
            "status": self.status,
        }


class FindingDispositionGroup(ImmutableModel):
    """One migration disposition shared by one or more historical finding IDs."""

    disposition: FindingDisposition
    finding_ids: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        """Return the stable program-record representation."""
        return {
            "disposition": self.disposition,
            "finding_ids": list(self.finding_ids),
        }


class MetricDefinition(ImmutableModel):
    """Owned non-vanity KPI definition and automatic event contract."""

    metric_id: str
    name: str
    owner_role: str
    value_kind: str
    aggregation: str
    output_unit: str
    direction: str
    scale: float
    numerator_unit: str
    denominator_unit: str
    bounded_ratio: bool
    minimum_observations: int
    window: str
    source_event_type: str
    producer_packages: tuple[str, ...]
    required_dimensions: tuple[str, ...]
    collection_mode: str
    manual_entry_allowed: bool
    baseline_status: str
    baseline_value: float | None
    target_status: str
    target_value: float | None
    target_approval_evidence: str | None
    hard_gate_substitute: bool

    @field_validator("scale", "baseline_value", "target_value", mode="before")
    @classmethod
    def exact_float(cls, value: object) -> float | None:
        """Reject implicit integer-to-float conversion on direct construction."""
        if value is None:
            return None
        if type(value) is not float:
            raise ValueError("value must be a float")
        return value

    def as_json(self) -> dict[str, object]:
        """Return the stable dashboard representation."""
        return {
            "aggregation": self.aggregation,
            "baseline_status": self.baseline_status,
            "baseline_value": self.baseline_value,
            "bounded_ratio": self.bounded_ratio,
            "collection_mode": self.collection_mode,
            "denominator_unit": self.denominator_unit,
            "direction": self.direction,
            "hard_gate_substitute": self.hard_gate_substitute,
            "manual_entry_allowed": self.manual_entry_allowed,
            "metric_id": self.metric_id,
            "minimum_observations": self.minimum_observations,
            "name": self.name,
            "numerator_unit": self.numerator_unit,
            "output_unit": self.output_unit,
            "owner_role": self.owner_role,
            "producer_packages": list(self.producer_packages),
            "required_dimensions": list(self.required_dimensions),
            "scale": self.scale,
            "source_event_type": self.source_event_type,
            "target_approval_evidence": self.target_approval_evidence,
            "target_status": self.target_status,
            "target_value": self.target_value,
            "value_kind": self.value_kind,
            "window": self.window,
        }


class MetricObservation(ImmutableModel):
    """One automatically emitted duration or ratio observation."""

    event_id: str
    metric_id: str
    source_event_type: str
    source_run_id: str
    source_revision: str
    evidence_url: str
    window_start: datetime
    window_end: datetime
    dimensions: tuple[tuple[str, str], ...]
    numerator: float | None
    denominator: float | None

    @field_validator("numerator", "denominator", mode="before")
    @classmethod
    def exact_float(cls, value: object) -> float | None:
        """Reject implicit integer-to-float conversion on direct construction."""
        if value is None:
            return None
        if type(value) is not float:
            raise ValueError("value must be a float")
        return value

    @model_validator(mode="after")
    def positive_utc_window(self) -> Self:
        """Require an ordered UTC interval for every direct construction path."""
        if self.window_start.tzinfo != UTC or self.window_end.tzinfo != UTC:
            raise ValueError("observation window must use UTC datetimes")
        if self.window_end <= self.window_start:
            raise ValueError("observation window must be positive")
        return self

    @property
    def duration_seconds(self) -> float:
        """Return the observed interval duration."""
        return (self.window_end - self.window_start).total_seconds()


class MetricSummary(ImmutableModel):
    """Deterministic aggregation result for one KPI."""

    metric_id: str
    status: str
    observation_count: int
    value: float | None
    unit: str

    @field_validator("value", mode="before")
    @classmethod
    def exact_float(cls, value: object) -> float | None:
        """Reject implicit integer-to-float conversion on direct construction."""
        if value is None:
            return None
        if type(value) is not float:
            raise ValueError("value must be a float")
        return value

    def as_json(self) -> dict[str, object]:
        """Return the stable dashboard representation."""
        return {
            "metric_id": self.metric_id,
            "observation_count": self.observation_count,
            "status": self.status,
            "unit": self.unit,
            "value": self.value,
        }


class ProgramGovernance(ImmutableModel):
    """Validated program graph, state, KPI definitions, and findings."""

    schema_version: int
    roadmap_package: str
    operating_track: str
    package_status: str
    accountable_owner_role: str
    risk_class: str
    applicable_gate_ids: tuple[str, ...]
    as_of_date: date
    roadmap_path: str
    observation_schema_version: int
    maximum_observations: int
    aggregation_workload_budget_ms: int
    local_evidence_manifest_path: str
    local_evidence_commit_sha: str
    packages: tuple[PackageNode, ...]
    package_states: tuple[PackageState, ...]
    metrics: tuple[MetricDefinition, ...]
    finding_ids: tuple[str, ...]
    generated_status_path: str | None = None
    finding_dispositions: tuple[FindingDispositionGroup, ...] = ()

    @property
    def implementation_status(self) -> ImplementationStatus:
        """Derive A08 implementation status from its single authoritative state."""
        state = self.state_for(self.roadmap_package)
        return "planned" if state is None else state.implementation_status

    @property
    def governance_status(self) -> GovernanceStatus:
        """Report scoped handover independently of historical institutional acceptance."""
        state = self.state_for(self.roadmap_package)
        return "pending" if state is None else state.governance_status

    def state_for(self, package_id: str) -> PackageState | None:
        """Return an explicit package state, or ``None`` for planned work."""
        return next(
            (state for state in self.package_states if state.package_id == package_id),
            None,
        )

    def status_for(self, package_id: str) -> str:
        """Return explicit status or the planned default."""
        state = self.state_for(package_id)
        return "planned" if state is None else state.status

    def finding_disposition_for(self, finding_id: str) -> FindingDisposition | None:
        """Return the one-time migration disposition for a historical finding."""
        return next(
            (
                group.disposition
                for group in self.finding_dispositions
                if finding_id in group.finding_ids
            ),
            None,
        )

    def ready_packages(self, *, institutional: bool) -> tuple[PackageNode, ...]:
        """Return planned packages whose dependencies satisfy the selected track."""
        return tuple(
            package
            for package in self.packages
            if self.status_for(package.package_id) == "planned"
            and self._dependencies_ready(package, institutional=institutional)
        )

    def _dependencies_ready(self, package: PackageNode, *, institutional: bool) -> bool:
        def package_is_ready(package_id: str) -> bool:
            package_state = self.state_for(package_id)
            if package_state is None:
                return False
            if institutional:
                return package_state.status == "validated"
            return package_state.is_solo_provisionally_satisfied()

        purposes: tuple[DependencyPurpose, ...] = (
            _DEPENDENCY_PURPOSES
            if institutional or self.schema_version < 3
            else ("implementation",)
        )
        return all(
            all(package_is_ready(dependency_id) for dependency_id in dependencies)
            and all(
                any(package_is_ready(dependency_id) for dependency_id in dependency_group)
                for dependency_group in groups
            )
            for dependencies, groups in (
                package.dependency_requirements(purpose) for purpose in purposes
            )
        )

    def summarize_metrics(
        self, observations: tuple[MetricObservation, ...]
    ) -> tuple[MetricSummary, ...]:
        """Aggregate observations without treating any KPI as a hard gate."""
        observations_by_metric: dict[str, list[MetricObservation]] = {
            metric.metric_id: [] for metric in self.metrics
        }
        for observation in observations:
            observations_by_metric[observation.metric_id].append(observation)

        summaries: list[MetricSummary] = []
        for metric in self.metrics:
            metric_observations = observations_by_metric[metric.metric_id]
            if metric_observations:
                latest_window_end = max(
                    observation.window_end for observation in metric_observations
                )
                window_days = int(metric.window[1:-1])
                reporting_cutoff = latest_window_end - timedelta(days=window_days)
                selected_observations = [
                    observation
                    for observation in metric_observations
                    if (
                        observation.window_start >= reporting_cutoff
                        if metric.value_kind == "ratio"
                        else observation.window_end >= reporting_cutoff
                    )
                ]
            else:
                selected_observations = []
            if len(selected_observations) < metric.minimum_observations:
                summaries.append(
                    MetricSummary(
                        metric_id=metric.metric_id,
                        status="insufficient_observations",
                        observation_count=len(selected_observations),
                        value=None,
                        unit=metric.output_unit,
                    )
                )
                continue
            if metric.value_kind == "duration":
                duration_values = sorted(
                    observation.duration_seconds for observation in selected_observations
                )
                percentile = int(metric.aggregation.removeprefix("p"))
                percentile_index = max(
                    ceil(percentile / 100 * len(duration_values)) - 1,
                    0,
                )
                metric_value = duration_values[percentile_index]
            else:
                numerator_total = sum(
                    observation.numerator or 0.0 for observation in selected_observations
                )
                denominator_total = sum(
                    observation.denominator or 0.0 for observation in selected_observations
                )
                metric_value = numerator_total / denominator_total * metric.scale
            summaries.append(
                MetricSummary(
                    metric_id=metric.metric_id,
                    status="measured",
                    observation_count=len(selected_observations),
                    value=metric_value,
                    unit=metric.output_unit,
                )
            )
        return tuple(summaries)
