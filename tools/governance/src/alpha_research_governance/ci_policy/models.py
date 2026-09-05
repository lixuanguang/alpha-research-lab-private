"""Immutable values for the governed continuous-integration contract.

Construction checks field types through ``ImmutableModel``. The policy loader,
selection functions and runner enforce policy values, target validity and event
semantics respectively; these records perform no Git, Bazel or filesystem I/O.
"""

from __future__ import annotations

# standard library imports
from datetime import datetime

# project library imports
from alpha_research_governance._models import ImmutableModel


class CIPolicyError(ValueError):
    """Report CI-policy findings in their supplied order.

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


class CILane(ImmutableModel):
    """Describe one governed CI lane and its execution scope.

    Attributes:
        lane_id: Lane name, such as ``fast`` or ``full``.
        contexts: CI contexts in which the lane is admitted.
        pre_commit_scope: Declared scope of pre-commit file checks.
        build_scope: Declared build-target selection scope.
        test_scope: Declared test-target selection scope.
        authoritative: Whether this lane supplies the authoritative repository check.
    """

    lane_id: str
    contexts: tuple[str, ...]
    pre_commit_scope: str
    build_scope: str
    test_scope: str
    authoritative: bool


class CIPolicy(ImmutableModel):
    """Store selection, compatibility and lane settings admitted by the CI loader.

    Attributes:
        package_status: Declared roadmap completion status.
        successor_package: Roadmap package receiving deferred work.
        applicable_gate_ids: Ordered quality gates required for this package.
        selection_workload_budget_ms: Selection benchmark budget in milliseconds.
        maximum_changed_files: Maximum parsed path records before sorting and deduplication.
        fast_lane_target_status: Approval status of the fast-lane performance target.
        unknown_path_behavior: Required fallback when a changed path has no owner.
        selection_strategy: Governed owner/reverse-dependency selection strategy.
        full_lane_authoritative: Whether full-repository results are authoritative.
        require_merged_result_on_pull_request: Whether pull requests need merged-result CI.
        event_log_directory: Repository-relative directory for emitted duration events.
        hosted_artifact_retention_days: Retention period for hosted CI artifacts in days.
        secret_scanner_executable: Required external private-key scanner command.
        secret_scanner_version: Exact distribution version supplying that scanner.
        secret_scan_maximum_file_bytes: Maximum file size admitted to secret scanning.
        secret_pattern_ids: Ordered identifiers of the required secret patterns.
        generated_artifact_prefixes: Repository-relative directory prefixes barred in diffs.
        foundational_paths: Files or path prefixes whose changes force full selection.
        schema_module_roots: Repository-relative Protobuf module roots checked for compatibility.
        lanes: Ordered lane definitions and admitted execution contexts.
        local_evidence_manifest_path: Repository-relative package evidence manifest.
        local_evidence_commit_sha: Commit to which the local evidence is bound.
        open_finding_ids: Declared unresolved package findings.
    """

    package_status: str
    successor_package: str
    applicable_gate_ids: tuple[str, ...]
    selection_workload_budget_ms: int
    maximum_changed_files: int
    fast_lane_target_status: str
    unknown_path_behavior: str
    selection_strategy: str
    full_lane_authoritative: bool
    require_merged_result_on_pull_request: bool
    event_log_directory: str
    hosted_artifact_retention_days: int
    secret_scanner_executable: str
    secret_scanner_version: str
    secret_scan_maximum_file_bytes: int
    secret_pattern_ids: tuple[str, ...]
    generated_artifact_prefixes: tuple[str, ...]
    foundational_paths: tuple[str, ...]
    schema_module_roots: tuple[str, ...]
    lanes: tuple[CILane, ...]
    local_evidence_manifest_path: str
    local_evidence_commit_sha: str
    open_finding_ids: tuple[str, ...]


class ChangedPath(ImmutableModel):
    """Represent one path from a normalized Git name-status record.

    Rename and copy parsing retains both source and destination paths as separate
    records. Path safety and supported status codes are checked by the parser.

    Attributes:
        status: Full Git status token, retaining any rename/copy similarity score.
        path: Canonical repository-relative source or destination path.
    """

    status: str
    path: str


class AffectedSelection(ImmutableModel):
    """Carry Bazel owners and target selections through the affected-CI workflow.

    Owner selection can precede reverse-dependency queries, leaving build and test
    targets empty until attachment. A full fallback uses ``//...`` for both.

    Attributes:
        changed_paths: Sorted unique repository-relative paths considered for selection.
        owner_targets: Sorted unique direct Bazel owners, empty for full fallback.
        build_targets: Selected reverse dependencies or the full-graph target pattern.
        test_targets: Selected test dependencies or the full-graph target pattern.
        force_full: Whether selection requires the full-repository fallback.
        reason: Stable selection reason, including unresolved paths when applicable.
    """

    changed_paths: tuple[str, ...]
    owner_targets: tuple[str, ...]
    build_targets: tuple[str, ...]
    test_targets: tuple[str, ...]
    force_full: bool
    reason: str


class CIEvent(ImmutableModel):
    """Store a build or test duration event for serialization and KPI ingestion.

    The runner requires a positive UTC interval and validates run/evidence context
    before construction. Direct construction does not enforce those relationships.
    Freezing is shallow: the ``dimensions`` dictionary remains mutable.

    Attributes:
        schema_version: Emitted event schema version, currently 1.
        event_id: Identity derived from the CI run and phase.
        metric_id: Build- or test-duration metric measured in seconds.
        source_event_type: Completion event type for the build or test phase.
        source_run_id: Run identity used for evidence attribution and retry checks.
        source_revision: Full Git commit SHA measured by the event.
        evidence_url: Retained HTTPS evidence link, or an empty value for local runs.
        window_start: Inclusive phase start instant, emitted in UTC.
        window_end: Exclusive phase end instant, emitted in UTC after the start.
        dimensions: Environment, passed/failed outcome and target labels.
    """

    schema_version: int
    event_id: str
    metric_id: str
    source_event_type: str
    source_run_id: str
    source_revision: str
    evidence_url: str
    window_start: datetime
    window_end: datetime
    dimensions: dict[str, str]
