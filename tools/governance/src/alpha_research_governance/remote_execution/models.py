"""Immutable values for the governed remote-execution contract.

Construction checks field types through ``ImmutableModel``. The policy loader
checks admitted values and cross-field restrictions; runners and sharding APIs
enforce execution context and target partitions. These records perform no I/O.
"""

from __future__ import annotations

# standard library imports
from datetime import date

# project library imports
from alpha_research_governance._models import ImmutableModel


class RemoteExecutionError(ValueError):
    """Report remote-execution findings in their supplied order.

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


class RemoteProvider(ImmutableModel):
    """Describe the remote service and the source of its runtime credential.

    Attributes:
        provider_id: Admitted service provider identifier.
        protocol: Required remote execution API protocol.
        cache_endpoint: Remote action-cache/CAS endpoint.
        executor_endpoint: Remote execution endpoint.
        results_url: Base URL for hosted invocation results.
        authentication: Admitted authentication mechanism.
        credential_environment_variable: Variable name from which the runner reads the key.
        authentication_header: Header name used to send the credential to Bazel's remote API.
        decision_path: Repository-relative architecture decision admitting the service.
    """

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
    """Declare remote namespace, credential and cache-write restrictions.

    Attributes:
        instance_name: Remote execution/cache namespace.
        trusted_contexts: CI contexts permitted to use remote credentials.
        untrusted_contexts: Contexts required to remain outside that trust boundary.
        upload_contexts: Contexts permitted to upload local results to the remote cache.
        verify_downloads: Whether downloaded remote content must be verified.
        workspace_credential_helpers_permitted: Whether workspace credential helpers are allowed.
    """

    instance_name: str
    trusted_contexts: tuple[str, ...]
    untrusted_contexts: tuple[str, ...]
    upload_contexts: tuple[str, ...]
    verify_downloads: bool
    workspace_credential_helpers_permitted: bool


class ResourceBudget(ImmutableModel):
    """Store resource settings checked against the repository's Bazel configuration.

    Attributes:
        remote_jobs: Maximum concurrent jobs for remote execution.
        local_jobs: Maximum concurrent jobs for local fallback.
        local_cpu: Local CPU resource budget in CPU units.
        local_memory_mb: Local memory resource budget in megabytes.
        remote_retries: Permitted remote transport retries, separate from test attempts.
        remote_retry_max_delay_seconds: Maximum delay between remote retries in seconds.
        remote_timeout_seconds: Remote operation timeout in seconds.
    """

    remote_jobs: int
    local_jobs: int
    local_cpu: int
    local_memory_mb: int
    remote_retries: int
    remote_retry_max_delay_seconds: int
    remote_timeout_seconds: int


class ShardingPolicy(ImmutableModel):
    """Declare deterministic whole-target sharding settings.

    Attributes:
        algorithm: Admitted seeded SHA-256 modulo algorithm identifier.
        seed: Stable text included in each target's assignment digest.
        shard_count: Positive number of shards, including shards that may be empty.
        maximum_targets: Inclusive upper bound on targets in a complete partition.
    """

    algorithm: str
    seed: str
    shard_count: int
    maximum_targets: int


class QuarantineEntry(ImmutableModel):
    """Declare an expiring diagnostic repeat without removing a normal test target.

    Attributes:
        target: Exact Bazel test label retained in normal execution.
        owner_role: Governed role accountable for the quarantine.
        reason: Explanation for repeated diagnostic execution.
        expires_on: Last admitted quarantine date relative to the policy assessment date.
    """

    target: str
    owner_role: str
    reason: str
    expires_on: date


class FlakePolicy(ImmutableModel):
    """Separate authoritative test attempts from diagnostic quarantine repeats.

    Attributes:
        normal_test_attempts: Attempts per normal test, required to remain one by policy.
        quarantine_repeat_count: Diagnostic repetitions for each quarantined target.
        maximum_quarantine_days: Maximum quarantine lifetime from the assessment date.
        as_of_date: Explicit date used to validate quarantine expiry deterministically.
        quarantines: Ordered owned quarantine records; an empty tuple disables repeats.
    """

    normal_test_attempts: int
    quarantine_repeat_count: int
    maximum_quarantine_days: int
    as_of_date: date
    quarantines: tuple[QuarantineEntry, ...]


class LocalFallback(ImmutableModel):
    """Declare the graph and remote-disable switches required for local fallback.

    Attributes:
        remote_cache_disabled: Whether fallback must disable remote-cache access.
        remote_execution_disabled: Whether fallback must execute without a remote executor.
        remote_upload_disabled: Whether fallback must disable uploads of local results.
        build_targets: Governed build graph, also used by the trusted remote build runner.
        test_targets: Governed test graph used for local fallback validation.
    """

    remote_cache_disabled: bool
    remote_execution_disabled: bool
    remote_upload_disabled: bool
    build_targets: tuple[str, ...]
    test_targets: tuple[str, ...]


class RemoteExecutionPolicy(ImmutableModel):
    """Group the remote-execution policy admitted by the owning loader.

    Attributes:
        package_status: Declared roadmap completion status.
        successor_package: Roadmap package receiving deferred work.
        risk_class: Declared change-risk classification.
        applicable_gate_ids: Ordered quality gates required for this package.
        local_evidence_manifest_path: Repository-relative package evidence manifest.
        local_evidence_commit_sha: Commit to which the local evidence is bound.
        open_finding_ids: Declared unresolved package findings.
        provider: Service endpoints and authentication configuration.
        trust: Namespace and CI-context restrictions.
        resources: Concurrency, resource and transport timeout budgets.
        sharding: Deterministic partition settings for the complete test graph.
        flakes: Normal-attempt and diagnostic quarantine rules.
        local_fallback: Required remote-disabled build and test configuration.
    """

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
    """Represent one shard produced by the whole-target partitioner.

    Partition validation belongs to the sharding functions, not construction.

    Attributes:
        index: Zero-based shard index in the half-open range ``[0, count)``.
        count: Total number of shards in the complete partition.
        targets: Sorted unique test labels assigned to this shard; may be empty.
    """

    index: int
    count: int
    targets: tuple[str, ...]
