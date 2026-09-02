"""Load and enforce the governed remote-execution control contract."""

from __future__ import annotations

import re
import tomllib
from datetime import date
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from alpha_research_governance.change_risk import ChangeRiskInput, RiskClass
from alpha_research_governance.change_risk import load_policy as load_change_risk_policy
from alpha_research_governance.evidence import (
    EvidenceGovernanceError,
    PackageEvidenceProfile,
    PackageGateRequirement,
    validate_manifest,
    validate_package_evidence,
)
from alpha_research_governance.remote_execution.models import (
    FlakePolicy,
    LocalFallback,
    QuarantineEntry,
    RemoteExecutionError,
    RemoteExecutionPolicy,
    RemoteProvider,
    RemoteTrust,
    ResourceBudget,
    ShardingPolicy,
)

_REMOTE_EXECUTION_PACKAGE_ID = "B06"
_DEPENDENCY_ADMISSION_PACKAGE_ID = "B07"
_REMOTE_TEST_SHARD_SEED = "remote-test-sharding-20260902-v1"
_REMOTE_EXECUTION_APPLICABLE_GATE_IDS = (
    "QG01",
    "QG02",
    "QG03",
    "QG04",
    "QG05",
    "QG06",
    "QG09",
    "QG10",
    "QG11",
    "QG12",
    "QG13",
    "QG14",
)
_REMOTE_EXECUTION_OPEN_FINDING_IDS = ("B06-F01", "B06-F02", "B06-F03")
_ROOT_KEYS = {
    "accountable_owner_role",
    "applicable_gate_ids",
    "findings",
    "flakes",
    "local_evidence_commit_sha",
    "local_evidence_manifest_path",
    "local_fallback",
    "open_finding_ids",
    "operating_track",
    "package_status",
    "provider",
    "resources",
    "risk_class",
    "roadmap_package",
    "schema_version",
    "sharding",
    "successor_package",
    "trust",
}
_TABLE_KEYS = {
    "provider": {
        "authentication",
        "authentication_header",
        "cache_endpoint",
        "credential_environment_variable",
        "decision_path",
        "executor_endpoint",
        "protocol",
        "provider_id",
        "results_url",
    },
    "trust": {
        "instance_name",
        "trusted_contexts",
        "untrusted_contexts",
        "upload_contexts",
        "verify_downloads",
        "workspace_credential_helpers_permitted",
    },
    "resources": {
        "local_cpu",
        "local_jobs",
        "local_memory_mb",
        "remote_jobs",
        "remote_retries",
        "remote_retry_max_delay_seconds",
        "remote_timeout_seconds",
    },
    "sharding": {"algorithm", "maximum_targets", "seed", "shard_count"},
    "flakes": {
        "as_of_date",
        "maximum_quarantine_days",
        "normal_test_attempts",
        "quarantines",
        "quarantine_repeat_count",
    },
    "local_fallback": {
        "build_targets",
        "remote_cache_disabled",
        "remote_execution_disabled",
        "remote_upload_disabled",
        "test_targets",
    },
}
_FINDING_KEYS = {"closure_condition", "finding_id", "owner_role", "unavailable_evidence"}
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_INSTANCE = re.compile(r"^[a-z0-9][a-z0-9._/-]{1,191}$")
_ENVIRONMENT_VARIABLE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_ROLE = re.compile(r"^[a-z][a-z0-9_]*$")
_BAZEL_LABEL = re.compile(r"^//(?:[^\s:]+(?::[^\s:]+)?|:[^\s:]+)$")
_QUARANTINE_KEYS = {"expires_on", "owner_role", "reason", "target"}
_LOCAL_EVIDENCE_PROFILE = PackageEvidenceProfile(
    roadmap_package_id=_REMOTE_EXECUTION_PACKAGE_ID,
    accountable_owner_role="platform",
    risk_class=RiskClass.R2,
    classification_facts=ChangeRiskInput(
        capital_at_risk=False,
        blast_radius="shared_domain",
        data_model_materiality="shared_or_candidate",
        security_privilege="shared_sensitive",
        reversibility="compatibility_window",
        computationally_material=True,
        economically_or_risk_relevant=False,
        model_or_trading_relevant=False,
        declared_class=RiskClass.R2,
    ),
    gate_requirements=tuple(
        PackageGateRequirement(gate_id=gate_id, status="passed")
        for gate_id in _REMOTE_EXECUTION_APPLICABLE_GATE_IDS
    ),
    expected_package_status="partial",
    expected_finding_ids=_REMOTE_EXECUTION_OPEN_FINDING_IDS,
    approvals_permitted=False,
    waivers_permitted=False,
    additional_required_gates_permitted=False,
)


def _require_toml_table(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RemoteExecutionError([f"{context} must be a TOML table"])
    return cast(dict[str, object], value)


def _require_toml_table_array(value: object, *, context: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RemoteExecutionError([f"{context} must be an array of TOML tables"])
    return cast(list[dict[str, object]], value)


def _require_string_tuple(
    value: object, *, context: str, allow_empty: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise RemoteExecutionError([f"{context} must be an array of non-empty strings"])
    values = tuple(cast(list[str], value))
    if not allow_empty and not values:
        raise RemoteExecutionError([f"{context} must not be empty"])
    if len(values) != len(set(values)):
        raise RemoteExecutionError([f"{context} must contain unique values"])
    return values


def _require_positive_integer(table: dict[str, object], key: str, *, context: str) -> int:
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RemoteExecutionError([f"{context}.{key} must be a positive integer"])
    return value


def _require_boolean(table: dict[str, object], key: str, *, context: str) -> bool:
    value = table.get(key)
    if not isinstance(value, bool):
        raise RemoteExecutionError([f"{context}.{key} must be Boolean"])
    return value


def _require_non_empty_string(table: dict[str, object], key: str, *, context: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise RemoteExecutionError([f"{context}.{key} must be a non-empty string"])
    return value


def _require_iso_date(value: object, *, context: str) -> date:
    if not isinstance(value, date):
        raise RemoteExecutionError([f"{context} must use an unquoted YYYY-MM-DD date"])
    return value


def load_policy(path: Path) -> RemoteExecutionPolicy:
    """Load a closed, syntactically and semantically valid remote-execution policy."""
    try:
        document = _require_toml_table(
            tomllib.loads(path.read_text(encoding="utf-8")), context=str(path)
        )
    except tomllib.TOMLDecodeError as error:
        raise RemoteExecutionError([f"{path}: invalid TOML: {error}"]) from error
    if set(document) != _ROOT_KEYS:
        raise RemoteExecutionError([f"{path}: root has missing or unknown fields"])
    expected_scalars: dict[str, object] = {
        "schema_version": 1,
        "roadmap_package": _REMOTE_EXECUTION_PACKAGE_ID,
        "operating_track": "solo_bootstrap",
        "package_status": "partial",
        "accountable_owner_role": "platform",
        "risk_class": "R2",
        "successor_package": _DEPENDENCY_ADMISSION_PACKAGE_ID,
    }
    for key, expected in expected_scalars.items():
        if document.get(key) != expected:
            raise RemoteExecutionError([f"{path}: {key} must be {expected!r}"])
    if _require_string_tuple(
        document.get("applicable_gate_ids"), context="applicable_gate_ids"
    ) != (_REMOTE_EXECUTION_APPLICABLE_GATE_IDS):
        raise RemoteExecutionError(["applicable_gate_ids must match the A04 R2 gate set"])
    open_findings = _require_string_tuple(
        document.get("open_finding_ids"), context="open_finding_ids"
    )
    if open_findings != _REMOTE_EXECUTION_OPEN_FINDING_IDS:
        raise RemoteExecutionError(
            ["remote-execution partial status requires the exact open findings"]
        )
    findings = _require_toml_table_array(document.get("findings"), context="findings")
    if tuple(entry.get("finding_id") for entry in findings) != (_REMOTE_EXECUTION_OPEN_FINDING_IDS):
        raise RemoteExecutionError(["findings must define the exact open finding IDs in order"])
    if any(set(entry) != _FINDING_KEYS for entry in findings):
        raise RemoteExecutionError(["findings have missing or unknown fields"])
    if any(
        not isinstance(value, str) or not value for entry in findings for value in entry.values()
    ):
        raise RemoteExecutionError(["finding values must be non-empty strings"])

    parsed = {name: _require_toml_table(document.get(name), context=name) for name in _TABLE_KEYS}
    for name, keys in _TABLE_KEYS.items():
        if set(parsed[name]) != keys:
            raise RemoteExecutionError([f"{name} has missing or unknown fields"])

    provider = RemoteProvider(
        provider_id=_require_non_empty_string(
            parsed["provider"], "provider_id", context="provider"
        ),
        protocol=_require_non_empty_string(parsed["provider"], "protocol", context="provider"),
        cache_endpoint=_require_non_empty_string(
            parsed["provider"], "cache_endpoint", context="provider"
        ),
        executor_endpoint=_require_non_empty_string(
            parsed["provider"], "executor_endpoint", context="provider"
        ),
        results_url=_require_non_empty_string(
            parsed["provider"], "results_url", context="provider"
        ),
        authentication=_require_non_empty_string(
            parsed["provider"], "authentication", context="provider"
        ),
        credential_environment_variable=_require_non_empty_string(
            parsed["provider"], "credential_environment_variable", context="provider"
        ),
        authentication_header=_require_non_empty_string(
            parsed["provider"], "authentication_header", context="provider"
        ),
        decision_path=_require_non_empty_string(
            parsed["provider"], "decision_path", context="provider"
        ),
    )
    trust = RemoteTrust(
        instance_name=_require_non_empty_string(parsed["trust"], "instance_name", context="trust"),
        trusted_contexts=_require_string_tuple(
            parsed["trust"].get("trusted_contexts"), context="trust.trusted_contexts"
        ),
        untrusted_contexts=_require_string_tuple(
            parsed["trust"].get("untrusted_contexts"), context="trust.untrusted_contexts"
        ),
        upload_contexts=_require_string_tuple(
            parsed["trust"].get("upload_contexts"), context="trust.upload_contexts"
        ),
        verify_downloads=_require_boolean(parsed["trust"], "verify_downloads", context="trust"),
        workspace_credential_helpers_permitted=_require_boolean(
            parsed["trust"], "workspace_credential_helpers_permitted", context="trust"
        ),
    )
    resources = ResourceBudget(
        remote_jobs=_require_positive_integer(
            parsed["resources"], "remote_jobs", context="resources"
        ),
        local_jobs=_require_positive_integer(
            parsed["resources"], "local_jobs", context="resources"
        ),
        local_cpu=_require_positive_integer(parsed["resources"], "local_cpu", context="resources"),
        local_memory_mb=_require_positive_integer(
            parsed["resources"], "local_memory_mb", context="resources"
        ),
        remote_retries=_require_positive_integer(
            parsed["resources"], "remote_retries", context="resources"
        ),
        remote_retry_max_delay_seconds=_require_positive_integer(
            parsed["resources"], "remote_retry_max_delay_seconds", context="resources"
        ),
        remote_timeout_seconds=_require_positive_integer(
            parsed["resources"], "remote_timeout_seconds", context="resources"
        ),
    )
    sharding = ShardingPolicy(
        algorithm=_require_non_empty_string(parsed["sharding"], "algorithm", context="sharding"),
        seed=_require_non_empty_string(parsed["sharding"], "seed", context="sharding"),
        shard_count=_require_positive_integer(
            parsed["sharding"], "shard_count", context="sharding"
        ),
        maximum_targets=_require_positive_integer(
            parsed["sharding"], "maximum_targets", context="sharding"
        ),
    )
    as_of_date = _require_iso_date(parsed["flakes"].get("as_of_date"), context="flakes.as_of_date")
    quarantines: list[QuarantineEntry] = []
    for index, entry in enumerate(
        _require_toml_table_array(
            parsed["flakes"].get("quarantines"), context="flakes.quarantines"
        ),
        1,
    ):
        context = f"flakes.quarantines[{index}]"
        if set(entry) != _QUARANTINE_KEYS:
            raise RemoteExecutionError([f"{context} has missing or unknown fields"])
        quarantines.append(
            QuarantineEntry(
                target=_require_non_empty_string(entry, "target", context=context),
                owner_role=_require_non_empty_string(entry, "owner_role", context=context),
                reason=_require_non_empty_string(entry, "reason", context=context),
                expires_on=_require_iso_date(
                    entry.get("expires_on"), context=f"{context}.expires_on"
                ),
            )
        )
    flakes = FlakePolicy(
        normal_test_attempts=_require_positive_integer(
            parsed["flakes"], "normal_test_attempts", context="flakes"
        ),
        quarantine_repeat_count=_require_positive_integer(
            parsed["flakes"], "quarantine_repeat_count", context="flakes"
        ),
        maximum_quarantine_days=_require_positive_integer(
            parsed["flakes"], "maximum_quarantine_days", context="flakes"
        ),
        as_of_date=as_of_date,
        quarantines=tuple(quarantines),
    )
    fallback = LocalFallback(
        remote_cache_disabled=_require_boolean(
            parsed["local_fallback"], "remote_cache_disabled", context="local_fallback"
        ),
        remote_execution_disabled=_require_boolean(
            parsed["local_fallback"], "remote_execution_disabled", context="local_fallback"
        ),
        remote_upload_disabled=_require_boolean(
            parsed["local_fallback"], "remote_upload_disabled", context="local_fallback"
        ),
        build_targets=_require_string_tuple(
            parsed["local_fallback"].get("build_targets"),
            context="local_fallback.build_targets",
        ),
        test_targets=_require_string_tuple(
            parsed["local_fallback"].get("test_targets"),
            context="local_fallback.test_targets",
        ),
    )
    evidence_path = _require_non_empty_string(
        document, "local_evidence_manifest_path", context=str(path)
    )
    evidence_commit = _require_non_empty_string(
        document, "local_evidence_commit_sha", context=str(path)
    )
    try:
        policy = RemoteExecutionPolicy(
            package_status="partial",
            successor_package=_DEPENDENCY_ADMISSION_PACKAGE_ID,
            risk_class="R2",
            applicable_gate_ids=_REMOTE_EXECUTION_APPLICABLE_GATE_IDS,
            local_evidence_manifest_path=evidence_path,
            local_evidence_commit_sha=evidence_commit,
            open_finding_ids=open_findings,
            provider=provider,
            trust=trust,
            resources=resources,
            sharding=sharding,
            flakes=flakes,
            local_fallback=fallback,
        )
    except ValidationError as error:
        raise RemoteExecutionError([str(error)]) from error
    semantic_findings = _semantic_findings(policy)
    if semantic_findings:
        raise RemoteExecutionError(semantic_findings)
    return policy


def _semantic_findings(policy: RemoteExecutionPolicy) -> list[str]:
    findings: list[str] = []
    expected_provider = (
        "buildbuddy_cloud",
        "remote_execution_api_v2",
        "grpcs://remote.buildbuddy.io",
        "grpcs://remote.buildbuddy.io",
        "https://app.buildbuddy.io",
        "api_key_header",
        "BUILDBUDDY_API_KEY",
        "x-buildbuddy-api-key",
        "docs/architecture/decisions/0009-remote-execution-service.md",
    )
    observed_provider = (
        policy.provider.provider_id,
        policy.provider.protocol,
        policy.provider.cache_endpoint,
        policy.provider.executor_endpoint,
        policy.provider.results_url,
        policy.provider.authentication,
        policy.provider.credential_environment_variable,
        policy.provider.authentication_header,
        policy.provider.decision_path,
    )
    if observed_provider != expected_provider:
        findings.append("provider must match the proposed BuildBuddy Cloud ADR contract")
    if _ENVIRONMENT_VARIABLE.fullmatch(policy.provider.credential_environment_variable) is None:
        findings.append("credential environment variable must be upper snake case")
    if _INSTANCE.fullmatch(policy.trust.instance_name) is None:
        findings.append("remote instance name is invalid")
    required_namespace_fragments = ("alpha-research-lab-private", "trusted", "bazel-9.1.0")
    if any(fragment not in policy.trust.instance_name for fragment in required_namespace_fragments):
        findings.append("remote instance name must isolate repository, trust, and toolchain")
    if policy.trust.trusted_contexts != ("github_main_push",):
        findings.append("only github_main_push may be a trusted remote context")
    if policy.trust.untrusted_contexts != ("developer", "github_pull_request"):
        findings.append("developer and pull-request contexts must remain untrusted")
    if policy.trust.upload_contexts != policy.trust.trusted_contexts:
        findings.append("remote uploads must be limited to trusted contexts")
    if set(policy.trust.untrusted_contexts) & set(policy.trust.trusted_contexts):
        findings.append("trusted and untrusted contexts must be disjoint")
    if not policy.trust.verify_downloads or policy.trust.workspace_credential_helpers_permitted:
        findings.append("downloads must be verified and workspace credential helpers prohibited")
    observed_resources = (
        policy.resources.remote_jobs,
        policy.resources.local_jobs,
        policy.resources.local_cpu,
        policy.resources.local_memory_mb,
        policy.resources.remote_retries,
        policy.resources.remote_retry_max_delay_seconds,
        policy.resources.remote_timeout_seconds,
    )
    if observed_resources != (25, 4, 4, 4096, 2, 3, 60):
        findings.append("resource budgets must match the reviewed remote-execution bounds")
    if policy.sharding.algorithm != "sha256_seeded_modulo_v1":
        findings.append("sharding algorithm must be sha256_seeded_modulo_v1")
    if (
        policy.sharding.seed != _REMOTE_TEST_SHARD_SEED
        or policy.sharding.shard_count != 2
        or policy.sharding.maximum_targets != 1000
    ):
        findings.append("remote execution requires two bounded deterministic shards")
    if policy.flakes.normal_test_attempts != 1:
        findings.append("normal tests must run once so flakes cannot silently pass")
    if policy.flakes.quarantine_repeat_count != 5:
        findings.append("quarantine diagnostics must run exactly five strict repetitions")
    if policy.flakes.maximum_quarantine_days != 14:
        findings.append("quarantine duration must be bounded at fourteen days")
    quarantine_targets = tuple(entry.target for entry in policy.flakes.quarantines)
    if len(quarantine_targets) != len(set(quarantine_targets)):
        findings.append("quarantine targets must be unique")
    for quarantine in policy.flakes.quarantines:
        if _ROLE.fullmatch(quarantine.owner_role) is None:
            findings.append("quarantine owner roles must be lower snake case")
        if _BAZEL_LABEL.fullmatch(quarantine.target) is None:
            findings.append("quarantines must identify valid Bazel test labels")
        duration_days = (quarantine.expires_on - policy.flakes.as_of_date).days
        if not (0 <= duration_days <= policy.flakes.maximum_quarantine_days):
            findings.append("quarantines must be active and expire within the governed duration")
    if not all(
        (
            policy.local_fallback.remote_cache_disabled,
            policy.local_fallback.remote_execution_disabled,
            policy.local_fallback.remote_upload_disabled,
        )
    ):
        findings.append("local fallback must disable cache, execution, and uploads")
    expected_build_targets = (
        "//:docs_bundle",
        "//src/alpha_research:alpha_research",
        "//tests/build/fixtures/sql:build_evidence",
        "//tools/governance/src/alpha_research_governance:all",
    )
    if policy.local_fallback.build_targets != expected_build_targets:
        findings.append("local fallback must build the complete governed build graph")
    if policy.local_fallback.test_targets != ("//...",):
        findings.append("local fallback must test the complete governed build graph")
    if _COMMIT_SHA.fullmatch(policy.local_evidence_commit_sha) is None:
        findings.append("local evidence commit must be a forty-character SHA")
    return findings


def validate_repository(repository_root: Path) -> RemoteExecutionPolicy:
    """Validate policy, integrations, trust boundaries, and local evidence."""
    policy_path = repository_root / "docs" / "architecture" / "remote-execution.toml"
    policy = load_policy(policy_path)
    findings = _semantic_findings(policy)

    integrations = {
        ".bazelrc": (
            "build:remote-execution --remote_cache=grpcs://remote.buildbuddy.io",
            "build:remote-execution --remote_executor=grpcs://remote.buildbuddy.io",
            f"build:remote-execution --remote_instance_name={policy.trust.instance_name}",
            "build:remote-execution --remote_local_fallback=false",
            "build:remote-execution --remote_verify_downloads",
            f"build:remote-execution --jobs={policy.resources.remote_jobs}",
            f"build:remote-execution --remote_retries={policy.resources.remote_retries}",
            "build:remote-execution --remote_retry_max_delay=3s",
            "build:remote-execution --remote_timeout=60s",
            "test:remote-execution --flaky_test_attempts=1",
            "test:remote-execution --runs_per_test=1",
            "build:remote-disabled-local --remote_cache=",
            "build:remote-disabled-local --remote_executor=",
            "build:remote-disabled-local --remote_upload_local_results=false",
            f"build:remote-disabled-local --jobs={policy.resources.local_jobs}",
            f"build:remote-disabled-local --local_resources=cpu={policy.resources.local_cpu}",
            "build:remote-disabled-local "
            f"--local_resources=memory={policy.resources.local_memory_mb}",
            "test:remote-quarantine-diagnostics "
            f"--runs_per_test={policy.flakes.quarantine_repeat_count}",
        ),
        "Makefile": (
            "remote-execution-policy-check:",
            "remote-build:",
            "remote-test:",
            "remote-local-fallback-check:",
        ),
        ".pre-commit-config.yaml": (
            "id: remote-execution-policy",
            "alpha-governance-remote-execution",
        ),
        ".github/workflows/ci.yml": (
            "REMOTE_EXECUTION_ENABLED",
            "secrets.BUILDBUDDY_API_KEY",
            "needs: merged-result",
            "REMOTE_CONTEXT=github_main_push",
            "REMOTE_SHARD_INDEX",
        ),
    }
    for relative_path, required_fragments in integrations.items():
        text = (repository_root / relative_path).read_text(encoding="utf-8")
        for fragment in required_fragments:
            if fragment not in text:
                findings.append(
                    f"{relative_path} is missing required remote-execution fragment {fragment!r}"
                )
    bazelrc = (repository_root / ".bazelrc").read_text(encoding="utf-8")
    if "remote_header" in bazelrc or policy.provider.credential_environment_variable in bazelrc:
        findings.append("workspace Bazel configuration must not contain remote credentials")
    if "runs_per_test_detects_flakes" in bazelrc:
        findings.append("mixed quarantine runs must fail instead of becoming a passing flake")
    workflow = (repository_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    remote_job = workflow.partition("  remote-execution:")[2]
    if "github.event_name == 'push'" not in remote_job or "refs/heads/main" not in remote_job:
        findings.append("remote execution workflow must be restricted to main pushes")

    for relative_path in (
        policy.provider.decision_path,
        policy.local_evidence_manifest_path,
        "docs/architecture/remote-execution.md",
    ):
        if not (repository_root / relative_path).is_file():
            findings.append(f"required remote-execution path is missing: {relative_path}")
    if findings:
        raise RemoteExecutionError(findings)
    try:
        manifest = validate_manifest(
            repository_root / policy.local_evidence_manifest_path,
            expected_commit_sha=policy.local_evidence_commit_sha,
            change_policy=load_change_risk_policy(
                repository_root / "docs/governance/change-risk-policy.toml"
            ),
        )
        validate_package_evidence(manifest, _LOCAL_EVIDENCE_PROFILE)
    except (EvidenceGovernanceError, OSError, ValueError) as error:
        raise RemoteExecutionError([str(error)]) from error
    return policy
