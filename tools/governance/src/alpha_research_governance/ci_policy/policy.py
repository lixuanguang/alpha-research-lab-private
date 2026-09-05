"""Load and validate the complete repository-local continuous-integration policy."""

from __future__ import annotations

# standard library imports
import hashlib
import subprocess  # nosec B404  # [owner=platform; rationale=required shell-free Git boundary; expires=2027-02-28]
import tomllib
from pathlib import Path, PurePosixPath
from typing import cast

# project library imports
from alpha_research_governance.change_risk import ChangeRiskInput, RiskClass
from alpha_research_governance.change_risk import load_policy as load_change_risk_policy
from alpha_research_governance.ci_policy.models import CILane, CIPolicy, CIPolicyError
from alpha_research_governance.ci_policy.secrets import secret_pattern_ids
from alpha_research_governance.evidence import (
    PackageEvidenceProfile,
    PackageGateRequirement,
    validate_manifest,
    validate_package_evidence,
)

CONTINUOUS_INTEGRATION_GATE_IDS = (
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
_CONTINUOUS_INTEGRATION_PACKAGE_ID = "B05"
_REMOTE_EXECUTION_SUCCESSOR_PACKAGE_ID = "B06"
_DEPENDENCY_ADMISSION_PACKAGE_ID = "B07"
_CONTINUOUS_INTEGRATION_FINDING_IDS = ("B05-F01", "B05-F02", "B05-F03")
_PRIVATE_KEY_SCANNER_EXECUTABLE = "detect-private-key"
_PRIVATE_KEY_SCANNER_DISTRIBUTION = "pre-commit-hooks==6.0.0"
_POLICY_KEYS = {
    "accountable_owner_role",
    "applicable_gate_ids",
    "event_log_directory",
    "fast_lane_target_status",
    "findings",
    "foundational_paths",
    "full_lane_authoritative",
    "generated_artifact_prefixes",
    "hosted_artifact_retention_days",
    "lanes",
    "local_evidence_commit_sha",
    "local_evidence_manifest_path",
    "maximum_changed_files",
    "open_finding_ids",
    "operating_track",
    "package_status",
    "parent_package",
    "require_merged_result_on_pull_request",
    "risk_class",
    "roadmap_package",
    "schema_module_roots",
    "schema_version",
    "secret_pattern_ids",
    "secret_scan_maximum_file_bytes",
    "secret_scanner_executable",
    "secret_scanner_version",
    "selection_strategy",
    "selection_workload_budget_ms",
    "successor_package",
    "unknown_path_behavior",
}
_LANE_KEYS = {
    "authoritative",
    "build_scope",
    "contexts",
    "lane_id",
    "pre_commit_scope",
    "test_scope",
}
_FINDING_KEYS = {"closure_condition", "finding_id", "owner_role", "unavailable_evidence"}


def _require_unique_string_array(value: object, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise CIPolicyError([f"{context} must be a non-empty string array"])
    values = tuple(cast(list[str], value))
    if len(values) != len(set(values)):
        raise CIPolicyError([f"{context} must contain unique values"])
    return values


def _require_positive_integer(document: dict[str, object], key: str) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise CIPolicyError([f"{key} must be a positive integer"])
    return value


def _require_safe_repository_paths(
    value: object,
    *,
    context: str,
    directory_prefixes: bool = False,
) -> tuple[str, ...]:
    values = _require_unique_string_array(value, context=context)
    for raw_path in values:
        candidate = raw_path.removesuffix("/") if directory_prefixes else raw_path
        path = PurePosixPath(candidate)
        if (
            not candidate
            or path.is_absolute()
            or path.as_posix() != candidate
            or ".." in path.parts
            or candidate.startswith("-")
            or any(ord(character) < 32 for character in candidate)
            or (directory_prefixes and not raw_path.endswith("/"))
        ):
            raise CIPolicyError([f"{context} contains an unsafe repository path: {raw_path}"])
    return values


def _parse_continuous_integration_lanes(value: object) -> tuple[CILane, ...]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise CIPolicyError(["lanes must be an array of tables"])
    lanes: list[CILane] = []
    for index, raw_lane in enumerate(cast(list[dict[str, object]], value), 1):
        if set(raw_lane) != _LANE_KEYS:
            raise CIPolicyError([f"lanes[{index}] fields drifted"])
        try:
            lanes.append(
                CILane(
                    lane_id=cast(str, raw_lane["lane_id"]),
                    contexts=_require_unique_string_array(
                        raw_lane["contexts"], context=f"lanes[{index}].contexts"
                    ),
                    pre_commit_scope=cast(str, raw_lane["pre_commit_scope"]),
                    build_scope=cast(str, raw_lane["build_scope"]),
                    test_scope=cast(str, raw_lane["test_scope"]),
                    authoritative=cast(bool, raw_lane["authoritative"]),
                )
            )
        except (KeyError, ValueError) as error:
            raise CIPolicyError([f"lanes[{index}] is invalid: {error}"]) from error
    expected = {
        "fast": (
            ("local_diff", "pull_request_head"),
            "changed",
            "affected_reverse_dependencies",
            "affected_reverse_dependencies",
            False,
        ),
        "full": (
            ("local", "main_push", "pull_request_merge"),
            "all",
            "complete_graph",
            "complete_graph",
            True,
        ),
    }
    observed = {
        lane.lane_id: (
            lane.contexts,
            lane.pre_commit_scope,
            lane.build_scope,
            lane.test_scope,
            lane.authoritative,
        )
        for lane in lanes
    }
    if observed != expected:
        raise CIPolicyError(["fast/full lane contract drifted"])
    return tuple(lanes)


def load_continuous_integration_policy(path: Path) -> CIPolicy:
    """Load the continuous-integration TOML policy with a closed schema."""
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise CIPolicyError([f"cannot load CI policy: {error}"]) from error
    if set(document) != _POLICY_KEYS:
        raise CIPolicyError(["CI policy root fields drifted"])
    exact_values = {
        "accountable_owner_role": "platform",
        "fast_lane_target_status": "pending_owner_approval",
        "full_lane_authoritative": True,
        "event_log_directory": "build/ci",
        "local_evidence_commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "local_evidence_manifest_path": (
            "docs/governance/evidence/examples/b05-r2-partial/manifest.toml"
        ),
        "operating_track": "solo_bootstrap",
        "hosted_artifact_retention_days": 30,
        "package_status": "partial",
        "parent_package": _CONTINUOUS_INTEGRATION_PACKAGE_ID,
        "require_merged_result_on_pull_request": True,
        "risk_class": "R2",
        "roadmap_package": _CONTINUOUS_INTEGRATION_PACKAGE_ID,
        "schema_version": 1,
        "secret_scanner_executable": _PRIVATE_KEY_SCANNER_EXECUTABLE,
        "secret_scanner_version": _PRIVATE_KEY_SCANNER_DISTRIBUTION,
        "selection_strategy": "bazel_owner_reverse_dependencies",
        "successor_package": _REMOTE_EXECUTION_SUCCESSOR_PACKAGE_ID,
        "unknown_path_behavior": "full_lane",
    }
    findings = [
        f"{key} must be {expected!r}"
        for key, expected in exact_values.items()
        if document.get(key) != expected
    ]
    if findings:
        raise CIPolicyError(findings)
    gate_ids = _require_unique_string_array(
        document["applicable_gate_ids"], context="applicable_gate_ids"
    )
    if gate_ids != CONTINUOUS_INTEGRATION_GATE_IDS:
        raise CIPolicyError(["applicable gates must match the exact R2 continuous-integration set"])
    patterns = _require_unique_string_array(
        document["secret_pattern_ids"], context="secret_pattern_ids"
    )
    if patterns != secret_pattern_ids():
        raise CIPolicyError(["high-confidence secret pattern set drifted"])
    open_findings = _require_unique_string_array(
        document["open_finding_ids"], context="open_finding_ids"
    )
    raw_findings = document["findings"]
    if not isinstance(raw_findings, list) or not all(
        isinstance(item, dict) for item in raw_findings
    ):
        raise CIPolicyError(["findings must be an array of tables"])
    finding_tables = cast(list[dict[str, object]], raw_findings)
    if any(set(item) != _FINDING_KEYS for item in finding_tables):
        raise CIPolicyError(["finding fields drifted"])
    if (
        open_findings != _CONTINUOUS_INTEGRATION_FINDING_IDS
        or tuple(item["finding_id"] for item in finding_tables)
        != _CONTINUOUS_INTEGRATION_FINDING_IDS
    ):
        raise CIPolicyError(["continuous-integration finding identities drifted"])
    return CIPolicy(
        package_status="partial",
        successor_package=_REMOTE_EXECUTION_SUCCESSOR_PACKAGE_ID,
        applicable_gate_ids=gate_ids,
        selection_workload_budget_ms=_require_positive_integer(
            document, "selection_workload_budget_ms"
        ),
        maximum_changed_files=_require_positive_integer(document, "maximum_changed_files"),
        fast_lane_target_status="pending_owner_approval",
        unknown_path_behavior="full_lane",
        selection_strategy="bazel_owner_reverse_dependencies",
        full_lane_authoritative=True,
        require_merged_result_on_pull_request=True,
        event_log_directory="build/ci",
        hosted_artifact_retention_days=_require_positive_integer(
            document, "hosted_artifact_retention_days"
        ),
        secret_scanner_executable=_PRIVATE_KEY_SCANNER_EXECUTABLE,
        secret_scanner_version=_PRIVATE_KEY_SCANNER_DISTRIBUTION,
        secret_scan_maximum_file_bytes=_require_positive_integer(
            document, "secret_scan_maximum_file_bytes"
        ),
        secret_pattern_ids=patterns,
        generated_artifact_prefixes=_require_safe_repository_paths(
            document["generated_artifact_prefixes"],
            context="generated_artifact_prefixes",
            directory_prefixes=True,
        ),
        foundational_paths=_require_safe_repository_paths(
            document["foundational_paths"], context="foundational_paths"
        ),
        schema_module_roots=_require_safe_repository_paths(
            document["schema_module_roots"], context="schema_module_roots"
        ),
        lanes=_parse_continuous_integration_lanes(document["lanes"]),
        local_evidence_manifest_path=cast(str, document["local_evidence_manifest_path"]),
        local_evidence_commit_sha=cast(str, document["local_evidence_commit_sha"]),
        open_finding_ids=open_findings,
    )


def _private_key_scanner_dependency_findings(root: Path) -> list[str]:
    path = root / "docs/architecture/ci-tool-dependencies.toml"
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        return [f"cannot load the continuous-integration dependency record: {error}"]
    dependencies = document.get("dependencies")
    expected_root = {
        "schema_version": 1,
        "roadmap_package": _CONTINUOUS_INTEGRATION_PACKAGE_ID,
        "operating_track": "solo_bootstrap",
        "package_status": "partial",
        "accountable_owner_role": "platform",
        "admission_owner_package": _DEPENDENCY_ADMISSION_PACKAGE_ID,
        "as_of_date": "2026-09-02",
        "runtime_installation_allowed": False,
    }
    if set(document) != {*expected_root, "dependencies"}:
        return ["dependency record root fields drifted"]
    findings = [
        f"dependency record {key} drifted"
        for key, value in expected_root.items()
        if document.get(key) != value
    ]
    if (
        not isinstance(dependencies, list)
        or len(dependencies) != 1
        or not isinstance(dependencies[0], dict)
    ):
        return [*findings, "dependency record must contain exactly one scanner"]
    dependency = cast(dict[str, object], dependencies[0])
    expected_dependency = {
        "dependency_id": "continuous_integration.pre_commit_hooks_private_key_scanner",
        "name": "pre-commit-hooks detect-private-key",
        "version": "6.0.0",
        "purpose": (
            "Detect private-key material in every governed fast or full CI source set; "
            "repository-owned high-confidence token rules supplement its intentionally "
            "narrow key detector."
        ),
        "source_url": "https://pypi.org/project/pre-commit-hooks/6.0.0/",
        "source_digest": (
            "sha256:76d8370c006f5026cdd638a397a678d26dda735a3c88137e05885a020f824034"
        ),
        "license": "MIT",
        "supported_platforms": ["darwin_arm64", "linux_x86_64"],
        "transitive_native_dependencies": ["ruamel-yaml==0.19.1 (not used by detect-private-key)"],
        "vulnerability_review": (
            "No qualified vulnerability or exploitability review is claimed; final "
            "admission remains B07-owned."
        ),
        "maintenance_review": (
            "The existing exact repository tool pin is reused; qualified maintenance "
            "review remains B07-owned."
        ),
        "rollback": (
            "Remove the continuous-integration scanner invocation, token rules, dependency "
            "record, CI lanes, and evidence together; restore the passing engineering "
            "standards validation surface."
        ),
    }
    if dependency != expected_dependency:
        findings.append("scanner dependency record drifted")
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    if (
        'name = "pre-commit-hooks"\nversion = "6.0.0"' not in lock
        or "76d8370c006f5026cdd638a397a678d26dda735a3c88137e05885a020f824034" not in lock
    ):
        findings.append("scanner version or digest is not bound to uv.lock")
    return findings


def _continuous_integration_repository_findings(root: Path, policy: CIPolicy) -> list[str]:
    findings: list[str] = []
    for module_root in policy.schema_module_roots:
        module = root / module_root
        try:
            module.resolve(strict=True).relative_to(root)
        except (FileNotFoundError, ValueError):
            findings.append(f"schema module is missing or outside the root: {module_root}")
            continue
        if module.is_symlink() or not module.is_dir() or not (module / "buf.yaml").is_file():
            findings.append(f"schema module is missing buf.yaml: {module_root}")
    registered_modules = tuple(f"{module}/" for module in policy.schema_module_roots)
    for proto in root.rglob("*.proto"):
        relative = proto.relative_to(root).as_posix()
        if not relative.startswith(registered_modules):
            findings.append(f"Protobuf source is outside a governed schema module: {relative}")
    completed = subprocess.run(  # nosec B603 B607  # [owner=platform; rationale=fixed Git argv without shell execution; expires=2027-02-28]
        ["git", "ls-files", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if completed.returncode:
        findings.append("git ls-files failed while checking generated/source separation")
    else:
        tracked = completed.stdout.decode("utf-8", errors="strict").split("\0")
        for path in tracked:
            if path and any(
                path.startswith(prefix) for prefix in policy.generated_artifact_prefixes
            ):
                findings.append(f"generated artifact is tracked as source: {path}")
    expected_fragments = {
        "Makefile": (
            "governance-check:",
            "program-status:",
            "ci-policy-check:",
            "ci-fast:",
            "ci-full:",
            "alpha-governance-ci",
        ),
        ".pre-commit-config.yaml": ("id: ci-policy", "alpha-governance-ci", "files:"),
        ".github/workflows/ci.yml": (
            "fast:",
            "merged-result:",
            "make ci-fast",
            "make ci-full",
            "verify-merged-result",
            "actions/upload-artifact@",
            "build/ci/fast-events.jsonl",
            "build/ci/full-events.jsonl",
            "retention-days: 30",
        ),
        "tools/governance/pyproject.toml": ("alpha-governance-ci",),
    }
    for relative, fragments in expected_fragments.items():
        text = (root / relative).read_text(encoding="utf-8")
        missing = [fragment for fragment in fragments if fragment not in text]
        if missing:
            findings.append(f"{relative} is missing continuous-integration interfaces: {missing}")
    return findings


def validate_continuous_integration_repository(repository_root: Path) -> CIPolicy:
    """Validate policy, scanner admission, interfaces, schemas, and evidence."""
    root = repository_root.resolve(strict=True)
    policy = load_continuous_integration_policy(root / "docs/architecture/ci-policy.toml")
    findings = _private_key_scanner_dependency_findings(
        root
    ) + _continuous_integration_repository_findings(root, policy)
    if findings:
        raise CIPolicyError(findings)
    manifest = validate_manifest(
        root / policy.local_evidence_manifest_path,
        expected_commit_sha=policy.local_evidence_commit_sha,
        change_policy=load_change_risk_policy(root / "docs/governance/change-risk-policy.toml"),
    )
    validate_package_evidence(
        manifest,
        PackageEvidenceProfile(
            roadmap_package_id=_CONTINUOUS_INTEGRATION_PACKAGE_ID,
            accountable_owner_role="platform",
            risk_class=RiskClass.R2,
            classification_facts=ChangeRiskInput(
                capital_at_risk=False,
                blast_radius="shared_domain",
                data_model_materiality="shared_or_candidate",
                security_privilege="none",
                reversibility="compatibility_window",
                computationally_material=True,
                economically_or_risk_relevant=False,
                model_or_trading_relevant=False,
                declared_class=RiskClass.R2,
            ),
            gate_requirements=tuple(
                PackageGateRequirement(gate_id=gate_id, status="passed")
                for gate_id in CONTINUOUS_INTEGRATION_GATE_IDS
            ),
            expected_package_status="partial",
            expected_finding_ids=_CONTINUOUS_INTEGRATION_FINDING_IDS,
            approvals_permitted=False,
            waivers_permitted=False,
            additional_required_gates_permitted=False,
        ),
    )
    return policy


def compute_evidence_report_sha256(path: Path) -> str:
    """Return the SHA-256 used by the retained evidence manifest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
