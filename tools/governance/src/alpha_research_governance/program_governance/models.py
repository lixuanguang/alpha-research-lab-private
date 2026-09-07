"""Define domain models for the program graph and KPI contract.

Validation callbacks raise ValueError when called directly; normal Pydantic
construction wraps callback failures in ValidationError. Registry loaders own
graph, policy and observation validation beyond the local model invariants.
"""

from __future__ import annotations

# standard library imports
from datetime import UTC, date, datetime, timedelta
from math import ceil
from typing import Literal, Self

# third party library imports
from pydantic import field_validator, model_validator

# project library imports
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
    """Report ordered program-governance findings in one exception.

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


class PackageNode(ImmutableModel):
    """Describe a roadmap package and its purpose-specific prerequisite groups.

    For each purpose, every all-of dependency must be satisfied, and at least
    one member of each any-of group must be satisfied. The roadmap loader checks
    references, grouping and cycles; direct construction checks field types only.

    Attributes:
        package_id: Exact roadmap package key.
        wave: Roadmap implementation wave label.
        objective: Declared capability or outcome.
        dependencies: All-of implementation prerequisite IDs.
        any_of_dependency_groups: Implementation alternatives, grouped as independent
            requirements.
        operation_release_dependencies: All-of prerequisites for operation or release.
        operation_release_any_of_dependency_groups: Alternative prerequisites for operation
            or release.
        team_handover_dependencies: All-of prerequisites for team handover.
        team_handover_any_of_dependency_groups: Alternative prerequisites for team handover.
    """

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
        """Return all-of and any-of requirements for one dependency purpose.

        Args:
            purpose: Typed implementation, operation_release or team_handover selector; callers
                must supply an admitted value.

        Returns:
            The stored pair of all-of IDs and any-of groups for that purpose, in source order.
        """
        if purpose == "implementation":
            return self.dependencies, self.any_of_dependency_groups
        if purpose == "operation_release":
            return (
                self.operation_release_dependencies,
                self.operation_release_any_of_dependency_groups,
            )
        return self.team_handover_dependencies, self.team_handover_any_of_dependency_groups

    def all_dependency_ids(self) -> tuple[str, ...]:
        """Return every referenced package once, independent of edge purpose.

        Returns:
            IDs in first-occurrence order across implementation, operation_release and
            team_handover; each purpose visits all-of IDs before flattened any-of groups.
        """
        values: list[str] = []
        for purpose in _DEPENDENCY_PURPOSES:
            dependencies, groups = self.dependency_requirements(purpose)
            values.extend(dependencies)
            values.extend(item for group in groups for item in group)
        unique_values: list[str] = []
        seen_values: set[str] = set()
        for value in values:
            if value not in seen_values:
                seen_values.add(value)
                unique_values.append(value)
        return tuple(unique_values)

    def as_json(self) -> dict[str, object]:
        """Return the stable dashboard representation of dependency requirements.

        Returns:
            A fresh dictionary with list-valued dependencies and nested groups. Legacy
            dependencies/any_of_dependency_groups keys retain the implementation view;
            dependency_purposes includes all three purposes.
        """
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
    """Retain implementation, handover and institutional state for one package.

    Completing implementation requires passed local evidence and no technical
    findings. Institutional status and pending handover remain independent. The
    program loader checks ownership, paths, findings and status-policy constraints.

    Attributes:
        package_id: Exact key of the recorded roadmap package.
        status: Historical institutional/package status, distinct from
            implementation_status.
        owner_role: Accountable role named by the program record.
        repository_local_status: Recorded local-check result; complete implementation
            requires passed.
        deferred_evidence_classes: Institutional evidence classes still unavailable.
        evidence_paths: Ordered evidence references; schema 4 loading requires one Markdown
            capability contract.
        open_finding_ids: Retained historical findings, which may include operational or
            handover obligations.
        implementation_status: Engineering progress; defaults to in_progress.
        governance_status: Scoped handover state; defaults to pending.
        domain_id: Optional domain used when the loader resolves operating rules.
        technical_finding_ids: Outstanding technical issues that prohibit complete
            implementation.
        assigned_reviewers: Principals derived by the loader from effective scoped
            assignments.
    """

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
        """Return the first evidence path as the active capability contract.

        Schema 4 loading guarantees a single Markdown contract. This property does
        not reject multiple paths retained by older schemas or direct construction.

        Returns:
            The first stored path, without checking its existence or reading its contents.

        Raises:
            IndexError: A directly constructed state has no evidence paths.
        """
        return self.evidence_paths[0]

    @model_validator(mode="after")
    def completion_requires_technical_evidence(self) -> Self:
        """Keep technical failure distinct from unstaffed governance requirements.

        Returns:
            This state after checking the local evidence requirement for complete
            implementation.

        Raises:
            ValueError: Implementation is complete but local checks have not passed or technical
                findings remain.
        """
        if self.implementation_status == "complete" and (
            self.repository_local_status != "passed" or self.technical_finding_ids
        ):
            raise ValueError("completion requires passing repository-local evidence")
        return self

    def is_solo_provisionally_satisfied(self) -> bool:
        """Return whether implementation completion satisfies a solo dependency.

        Returns:
            True exactly when implementation_status is complete, regardless of institutional or
            handover status.
        """
        return self.implementation_status == "complete"

    def as_json(self) -> dict[str, object]:
        """Return implementation and institutional state in the dashboard schema.

        Returns:
            A fresh dictionary with copied list fields. status and institutional_status both
            expose the stored institutional status; contract_path is the first evidence path.

        Raises:
            IndexError: A directly constructed state has no evidence paths.
        """
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
    """Group historical findings under one recorded migration disposition.

    The program loader checks uniqueness and finding coverage. Construction
    does not apply the disposition or close the referenced findings.

    Attributes:
        disposition: technical, operation_prerequisite or role_handover classification.
        finding_ids: Historical finding IDs sharing that disposition, in record order.
    """

    disposition: FindingDisposition
    finding_ids: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        """Return the stable program-record representation.

        Returns:
            A fresh dictionary containing the disposition and a list preserving finding-ID
            order.
        """
        return {
            "disposition": self.disposition,
            "finding_ids": list(self.finding_ids),
        }


class MetricDefinition(ImmutableModel):
    """Define an owned KPI and the event data required to measure it.

    The program loader validates kind/aggregation combinations, positive scale
    and observation counts, units, reporting periods and baseline/target coupling.
    It also prohibits manual entry and hard-gate substitution. Direct construction
    checks typed fields, exact floats and finite numbers, not those policy rules.

    Attributes:
        metric_id: Key joining observations to this KPI.
        name: Display name of the measured outcome.
        owner_role: Role accountable for the KPI definition.
        value_kind: duration or ratio, as checked by the loader.
        aggregation: Duration percentile p50/p90/p95/p99, or ratio.
        output_unit: Label carried into summaries; duration results are computed in seconds.
        direction: Declared lower_is_better or higher_is_better preference; no gate is
            derived.
        scale: Multiplier applied to the ratio of summed sufficient statistics; unused for
            durations.
        numerator_unit: Expected unit token for ratio numerators.
        denominator_unit: Expected unit token for ratio denominators.
        bounded_ratio: Whether observation loading enforces numerator no greater than
            denominator.
        minimum_observations: Minimum selected event count needed to report a value.
        window: Positive whole-day period P<n>D, applied per metric to the latest
            observation end.
        source_event_type: Required producer event type.
        producer_packages: Roadmap packages responsible for producing events.
        required_dimensions: Exact dimension keys required by the observation loader.
        collection_mode: Declared event collection mode; the loader requires
            automatic_event.
        manual_entry_allowed: Policy flag required to be False by the loader.
        baseline_status: awaiting_target_observations or available.
        baseline_value: Finite baseline float in output units, or None while unavailable.
        target_status: pending_owner_approval or approved.
        target_value: Finite target float in output units, or None while pending.
        target_approval_evidence: Approval evidence URL required with an approved target.
        hard_gate_substitute: Policy flag required to be False by the loader.
    """

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
        """Reject implicit integer-to-float conversion before field validation.

        Args:
            value: Candidate for scale, baseline_value or target_value; must be a built-in float
                or None.

        Returns:
            The original float or None. Optionality and finiteness are checked by subsequent
            field validation.

        Raises:
            ValueError: A supplied value is neither None nor an exact built-in float, including
                integers, Booleans and float subclasses.
        """
        if value is None:
            return None
        if type(value) is not float:
            raise ValueError("value must be a float")
        return value

    def as_json(self) -> dict[str, object]:
        """Return the stable dashboard representation of a KPI definition.

        Returns:
            A fresh dictionary containing the declared fields, with producer_packages and
            required_dimensions copied to lists and absent baseline/target values retained as
            None.
        """
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
    """Retain one duration interval or ratio sufficient-statistics event.

    Construction requires a positive interval with both tzinfo values equal to
    datetime.UTC and finite exact-float statistics when present. Observation
    loading additionally checks metric identity, source metadata, dimensions,
    units, positive ratio denominators, bounds, retry deduplication and overlap.

    Attributes:
        event_id: Producer event identity used by the loader to deduplicate retries.
        metric_id: KPI definition to which this observation belongs.
        source_event_type: Emitted event type checked against the metric definition.
        source_run_id: Producer run identity.
        source_revision: Producer revision digest.
        evidence_url: Reference to retained source evidence.
        window_start: UTC interval start; ratio reporting inclusion uses this bound.
        window_end: Strictly later UTC interval end; duration inclusion uses this bound.
        dimensions: Dimension key/value pairs; loader output sorts keys.
        numerator: Ratio numerator in the metric numerator unit, or None for duration
            events.
        denominator: Ratio denominator in the metric denominator unit, or None for duration
            events.
    """

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
        """Reject implicit integer-to-float conversion before field validation.

        Args:
            value: Candidate for numerator or denominator; must be a built-in float or None.

        Returns:
            The original float or None. Optionality and finiteness are checked by subsequent
            field validation.

        Raises:
            ValueError: A supplied value is neither None nor an exact built-in float, including
                integers, Booleans and float subclasses.
        """
        if value is None:
            return None
        if type(value) is not float:
            raise ValueError("value must be a float")
        return value

    @model_validator(mode="after")
    def positive_utc_window(self) -> Self:
        """Require a positive interval with timezone metadata equal to datetime.UTC.

        Returns:
            This observation with its timestamps unchanged; no timezone conversion occurs.

        Raises:
            ValueError: Either tzinfo differs from datetime.UTC, or window_end is not after
                window_start.
        """
        if self.window_start.tzinfo != UTC or self.window_end.tzinfo != UTC:
            raise ValueError("observation window must use UTC datetimes")
        if self.window_end <= self.window_start:
            raise ValueError("observation window must be positive")
        return self

    @property
    def duration_seconds(self) -> float:
        """Return the observed interval length in seconds.

        Returns:
            Floating-point total seconds from window_start to window_end, including fractional
            seconds.
        """
        return (self.window_end - self.window_start).total_seconds()


class MetricSummary(ImmutableModel):
    """Retain a measured KPI value or an explicit lack of sufficient observations.

    The aggregator emits measured with a value or insufficient_observations
    with None. Direct construction checks types and float representation without
    enforcing consistency among status, observation_count and value.

    Attributes:
        metric_id: Summarized KPI key.
        status: Aggregation result status, independent of pass/fail gate decisions.
        observation_count: Number of selected observations within the reporting window.
        value: Finite measured float, or None when observations are insufficient.
        unit: Output-unit label copied from the metric definition.
    """

    metric_id: str
    status: str
    observation_count: int
    value: float | None
    unit: str

    @field_validator("value", mode="before")
    @classmethod
    def exact_float(cls, value: object) -> float | None:
        """Reject implicit integer-to-float conversion before field validation.

        Args:
            value: Candidate for value; must be a built-in float or None.

        Returns:
            The original float or None. Optionality and finiteness are checked by subsequent
            field validation.

        Raises:
            ValueError: A supplied value is neither None nor an exact built-in float, including
                integers, Booleans and float subclasses.
        """
        if value is None:
            return None
        if type(value) is not float:
            raise ValueError("value must be a float")
        return value

    def as_json(self) -> dict[str, object]:
        """Return the stable dashboard representation of a KPI result.

        Returns:
            A fresh dictionary containing metric ID, count, status, unit and value; None is
            preserved for an unavailable value.
        """
        return {
            "metric_id": self.metric_id,
            "observation_count": self.observation_count,
            "status": self.status,
            "unit": self.unit,
            "value": self.value,
        }


class ProgramGovernance(ImmutableModel):
    """Hold the roadmap, package states and KPI contracts used by program queries.

    Use load_program and load_observations for graph, policy and event validation.
    Direct construction validates typed records without checking references or
    enforcing workload bounds. Queries and aggregation perform no I/O, mutate no
    records and do not record an institutional acceptance or hard-gate decision.

    Attributes:
        schema_version: Program schema version; versions below 3 use all dependency purposes
            for solo readiness.
        roadmap_package: Package whose explicit state supplies this program
            implementation/handover status.
        operating_track: Declared program track; readiness callers select their track
            explicitly.
        package_status: Historical institutional/package status of the governance
            capability.
        accountable_owner_role: Accountable role for the program-governance package.
        risk_class: Declared package risk class.
        applicable_gate_ids: Quality gates applicable to the package.
        as_of_date: Program snapshot date; metric reporting windows are anchored to
            observations instead.
        roadmap_path: Source roadmap path recorded by the loader.
        observation_schema_version: Event schema version required by observation loading.
        maximum_observations: Distinct-event limit enforced by the observation loader.
        aggregation_workload_budget_ms: Benchmark budget in milliseconds; aggregation does
            not enforce a timeout.
        local_evidence_manifest_path: Recorded local evidence manifest path.
        local_evidence_commit_sha: Commit identity used for local evidence validation.
        packages: Roadmap package order preserved by readiness queries.
        package_states: Explicit state records; missing records use query defaults.
        metrics: KPI definitions whose order determines the summary order.
        finding_ids: Retained program-governance findings.
        generated_status_path: Optional generated status-document path; no write occurs on
            construction.
        finding_dispositions: Recorded groups classifying historical findings.
    """

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
        """Derive program implementation status from its recorded package state.

        Returns:
            The roadmap_package state implementation_status, or planned when no state exists.
        """
        state = self.state_for(self.roadmap_package)
        return "planned" if state is None else state.implementation_status

    @property
    def governance_status(self) -> GovernanceStatus:
        """Report scoped handover independently of institutional acceptance.

        Returns:
            The roadmap_package state governance_status, or pending when no state exists.
        """
        state = self.state_for(self.roadmap_package)
        return "pending" if state is None else state.governance_status

    def state_for(self, package_id: str) -> PackageState | None:
        """Return the first explicit package state, or None when absent.

        Args:
            package_id: Exact package key to look up; roadmap membership is not checked here.

        Returns:
            The first matching stored state, or None for any unmatched key.
        """
        return next(
            (state for state in self.package_states if state.package_id == package_id),
            None,
        )

    def status_for(self, package_id: str) -> str:
        """Return the institutional/package status or the planned default.

        Args:
            package_id: Exact package key to look up; an unknown key also uses the default.

        Returns:
            The matching state status, or planned when no explicit state exists.
        """
        state = self.state_for(package_id)
        return "planned" if state is None else state.status

    def finding_disposition_for(self, finding_id: str) -> FindingDisposition | None:
        """Return a recorded migration disposition for a historical finding.

        Args:
            finding_id: Exact historical finding ID to locate.

        Returns:
            The disposition of the first group containing the ID, or None if no group contains
            it.
        """
        return next(
            (
                group.disposition
                for group in self.finding_dispositions
                if finding_id in group.finding_ids
            ),
            None,
        )

    def ready_packages(self, *, institutional: bool) -> tuple[PackageNode, ...]:
        """Return planned packages whose prerequisites satisfy the selected track.

        Candidate selection uses institutional/package status, not implementation
        status. The selected track does not change statuses or establish authorization.

        Args:
            institutional: True requires validated dependency states for all purposes. False
                requires complete implementation, using only implementation edges for schema 3+
                and all purposes for older schemas.

        Returns:
            Stored package objects in roadmap order whose status_for result is planned and whose
            selected all-of dependencies and every any-of group are satisfied. Missing
            prerequisite states are unsatisfied.
        """
        return tuple(
            package
            for package in self.packages
            if self.status_for(package.package_id) == "planned"
            and self._dependencies_ready(package, institutional=institutional)
        )

    def _dependencies_ready(self, package: PackageNode, *, institutional: bool) -> bool:
        """Check every selected all-of edge and each any-of group against stored package states."""

        def package_is_ready(package_id: str) -> bool:
            """Check one prerequisite against the selected track's completion status."""
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
        """Aggregate validated observations without treating a KPI as a hard gate.

        For each metric, the reporting cutoff is its latest supplied window_end minus
        its P<n>D period, independent of the host clock and program as_of_date. Duration
        events are included when window_end is at or after the cutoff; ratio events
        require window_start at or after it. Both cutoff comparisons are inclusive.

        Durations use the sorted sample at zero-based index ceil(p / 100 * n) - 1
        (with a lower bound of zero), without interpolation, and return seconds. Ratios
        use sum(numerator) / sum(denominator) * scale across all selected dimensions,
        not an average of event ratios. This method does not deduplicate retries,
        validate event contracts or enforce the loader/benchmark workload limits.

        Args:
            observations: Events validated by load_observations against this program, including
                known metric IDs, deduplicated retries and valid positive ratio denominators.

        Returns:
            One fresh summary per metric in definition order. Too few selected events yield
            insufficient_observations with None; otherwise the summary is measured in the metric
            output unit.

        Raises:
            KeyError: An observation references an unknown metric ID.
            ZeroDivisionError: Directly supplied ratio events have a zero selected denominator
                total.
            ValueError: A directly constructed definition has an unparsable reporting
                window/percentile, or a computed summary fails numeric validation.
            IndexError: A directly constructed duration definition permits an empty sample or
                selects a percentile index outside the sample.
        """
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
