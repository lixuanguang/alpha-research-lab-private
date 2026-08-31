"""Define domain models for the A08 program graph and KPI contract."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from math import ceil
from typing import Self

from pydantic import field_validator, model_validator

from alpha_research_governance._models import ImmutableModel


class ProgramGovernanceError(ValueError):
    """Report one or more deterministic A08 validation findings."""

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

    def as_json(self) -> dict[str, object]:
        """Return the stable dashboard representation."""
        return {
            "any_of_dependency_groups": [list(group) for group in self.any_of_dependency_groups],
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

    def is_solo_provisionally_satisfied(self) -> bool:
        """Return whether the state can satisfy a solo-bootstrap dependency."""
        return (
            self.status in {"partial", "validated"}
            and self.repository_local_status == "passed"
            and (self.status == "validated" or bool(self.deferred_evidence_classes))
        )

    def as_json(self) -> dict[str, object]:
        """Return the stable dashboard representation."""
        return {
            "deferred_evidence_classes": list(self.deferred_evidence_classes),
            "evidence_paths": list(self.evidence_paths),
            "open_finding_ids": list(self.open_finding_ids),
            "owner_role": self.owner_role,
            "package_id": self.package_id,
            "repository_local_status": self.repository_local_status,
            "status": self.status,
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
    """Validated A08 graph, state, KPI definitions, and findings."""

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

    def ready_packages(self, *, institutional: bool) -> tuple[PackageNode, ...]:
        """Return planned packages whose dependencies satisfy the selected track."""
        return tuple(
            package
            for package in self.packages
            if self.status_for(package.package_id) == "planned"
            and self._dependencies_ready(package, institutional=institutional)
        )

    def _dependencies_ready(self, package: PackageNode, *, institutional: bool) -> bool:
        def is_ready(package_id: str) -> bool:
            state = self.state_for(package_id)
            if state is None:
                return False
            if institutional:
                return state.status == "validated"
            return state.is_solo_provisionally_satisfied()

        return all(is_ready(item) for item in package.dependencies) and all(
            any(is_ready(item) for item in group) for group in package.any_of_dependency_groups
        )

    def summarize_metrics(
        self, observations: tuple[MetricObservation, ...]
    ) -> tuple[MetricSummary, ...]:
        """Aggregate observations without treating any KPI as a hard gate."""
        by_metric: dict[str, list[MetricObservation]] = {
            metric.metric_id: [] for metric in self.metrics
        }
        for observation in observations:
            by_metric[observation.metric_id].append(observation)

        summaries: list[MetricSummary] = []
        for metric in self.metrics:
            candidates = by_metric[metric.metric_id]
            if candidates:
                latest_end = max(item.window_end for item in candidates)
                window_days = int(metric.window[1:-1])
                cutoff = latest_end - timedelta(days=window_days)
                selected = [
                    item
                    for item in candidates
                    if (
                        item.window_start >= cutoff
                        if metric.value_kind == "ratio"
                        else item.window_end >= cutoff
                    )
                ]
            else:
                selected = []
            if len(selected) < metric.minimum_observations:
                summaries.append(
                    MetricSummary(
                        metric_id=metric.metric_id,
                        status="insufficient_observations",
                        observation_count=len(selected),
                        value=None,
                        unit=metric.output_unit,
                    )
                )
                continue
            if metric.value_kind == "duration":
                values = sorted(item.duration_seconds for item in selected)
                percentile = int(metric.aggregation.removeprefix("p"))
                index = max(ceil(percentile / 100 * len(values)) - 1, 0)
                value = values[index]
            else:
                numerator = sum(item.numerator or 0.0 for item in selected)
                denominator = sum(item.denominator or 0.0 for item in selected)
                value = numerator / denominator * metric.scale
            summaries.append(
                MetricSummary(
                    metric_id=metric.metric_id,
                    status="measured",
                    observation_count=len(selected),
                    value=value,
                    unit=metric.output_unit,
                )
            )
        return tuple(summaries)
