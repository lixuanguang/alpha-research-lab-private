"""Immutable values for the governed continuous-integration contract."""

from __future__ import annotations

from datetime import datetime

from alpha_research_governance._models import ImmutableModel


class CIPolicyError(ValueError):
    """Report one or more fail-closed CI-policy findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class CILane(ImmutableModel):
    """One governed CI lane and its execution scope."""

    lane_id: str
    contexts: tuple[str, ...]
    pre_commit_scope: str
    build_scope: str
    test_scope: str
    authoritative: bool


class CIPolicy(ImmutableModel):
    """Validated selection, compatibility, evidence, and lane policy."""

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
    """One normalized Git name-status record."""

    status: str
    path: str


class AffectedSelection(ImmutableModel):
    """Bazel owner and reverse-dependency targets selected for a change."""

    changed_paths: tuple[str, ...]
    owner_targets: tuple[str, ...]
    build_targets: tuple[str, ...]
    test_targets: tuple[str, ...]
    force_full: bool
    reason: str


class CIEvent(ImmutableModel):
    """One duration event emitted by a continuous-integration build or test phase."""

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
