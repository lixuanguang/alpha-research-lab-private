"""Immutable values for the governed remote-execution contract."""

from __future__ import annotations

# standard library imports
from datetime import date

# project library imports
from alpha_research_governance._models import ImmutableModel


class RemoteExecutionError(ValueError):
    """Report one or more fail-closed remote-execution findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class RemoteProvider(ImmutableModel):
    """Selected remote execution API and authentication boundary."""

    provider_id: str
    protocol: str
    cache_endpoint: str
    executor_endpoint: str
    results_url: str
    authentication: str
    credential_environment_variable: str
    authentication_header: str
    decision_path: str


class RemoteTrust(ImmutableModel):
    """Namespace and CI-context restrictions for remote writes."""

    instance_name: str
    trusted_contexts: tuple[str, ...]
    untrusted_contexts: tuple[str, ...]
    upload_contexts: tuple[str, ...]
    verify_downloads: bool
    workspace_credential_helpers_permitted: bool


class ResourceBudget(ImmutableModel):
    """Bounded remote and local concurrency and timeout values."""

    remote_jobs: int
    local_jobs: int
    local_cpu: int
    local_memory_mb: int
    remote_retries: int
    remote_retry_max_delay_seconds: int
    remote_timeout_seconds: int


class ShardingPolicy(ImmutableModel):
    """Deterministic whole-target sharding settings."""

    algorithm: str
    seed: str
    shard_count: int
    maximum_targets: int


class QuarantineEntry(ImmutableModel):
    """One owned, reasoned, and expiring diagnostic quarantine."""

    target: str
    owner_role: str
    reason: str
    expires_on: date


class FlakePolicy(ImmutableModel):
    """Strict normal execution and diagnostic quarantine settings."""

    normal_test_attempts: int
    quarantine_repeat_count: int
    maximum_quarantine_days: int
    as_of_date: date
    quarantines: tuple[QuarantineEntry, ...]


class LocalFallback(ImmutableModel):
    """Verified remote-disabled fallback boundary."""

    remote_cache_disabled: bool
    remote_execution_disabled: bool
    remote_upload_disabled: bool
    build_targets: tuple[str, ...]
    test_targets: tuple[str, ...]


class RemoteExecutionPolicy(ImmutableModel):
    """Validated provider, trust, sharding, flake, and fallback policy."""

    package_status: str
    successor_package: str
    risk_class: str
    applicable_gate_ids: tuple[str, ...]
    local_evidence_manifest_path: str
    local_evidence_commit_sha: str
    open_finding_ids: tuple[str, ...]
    provider: RemoteProvider
    trust: RemoteTrust
    resources: ResourceBudget
    sharding: ShardingPolicy
    flakes: FlakePolicy
    local_fallback: LocalFallback


class TestShard(ImmutableModel):
    """One deterministic shard in a complete test-target partition."""

    index: int
    count: int
    targets: tuple[str, ...]
