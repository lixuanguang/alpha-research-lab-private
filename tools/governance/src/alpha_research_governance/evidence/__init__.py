"""Canonical merge-request and evidence-governance API."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from alpha_research_governance.change_risk import classify_change
from alpha_research_governance.change_risk import load_policy as load_change_risk_policy
from alpha_research_governance.evidence.manifest import validate_manifest
from alpha_research_governance.evidence.models import (
    ApprovalEvidence,
    ArtifactEvidence,
    EvidenceGovernanceError,
    EvidenceManifest,
    EvidencePolicy,
    GateEvidence,
    MrField,
    PackageEvidenceProfile,
    PackageGateRequirement,
)
from alpha_research_governance.evidence.mr import (
    validate_github_event,
    validate_mr_body,
    validate_template,
)
from alpha_research_governance.evidence.package import validate_package_evidence
from alpha_research_governance.evidence.policy import load_policy

__all__ = [
    "ApprovalEvidence",
    "ArtifactEvidence",
    "EvidenceGovernanceError",
    "EvidenceManifest",
    "EvidencePolicy",
    "GateEvidence",
    "MrField",
    "PackageEvidenceProfile",
    "PackageGateRequirement",
    "load_policy",
    "main",
    "validate_github_event",
    "validate_manifest",
    "validate_mr_body",
    "validate_package_evidence",
    "validate_repository",
    "validate_template",
]

_USAGE = (
    "usage: python -m alpha_research_governance.evidence [repository-root] "
    "[--mr-body PATH | --github-event PATH] "
    "[--manifest PATH --expected-commit-sha SHA]"
)


def _repository_path(repository_root: Path, relative: Path) -> Path:
    resolved_root = repository_root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise EvidenceGovernanceError([f"repository path escapes the root: {relative}"]) from error
    return resolved


def _input_path(repository_root: Path, value: str) -> Path:
    """Resolve a CLI input relative to the selected repository root."""
    path = Path(value)
    return path if path.is_absolute() else repository_root.resolve() / path


def validate_repository(repository_root: Path) -> tuple[EvidencePolicy, EvidenceManifest]:
    """Validate evidence policy, template, example MR, and example bundle."""
    resolved_repository_root = repository_root.resolve()
    policy = load_policy(
        resolved_repository_root / "docs" / "governance" / "merge-evidence-policy.toml"
    )
    template_path = _repository_path(resolved_repository_root, policy.template_path)
    example_mr_path = _repository_path(resolved_repository_root, policy.example_mr_body_path)
    example_manifest_path = _repository_path(resolved_repository_root, policy.example_manifest_path)
    validate_template(template_path.read_text(encoding="utf-8"), policy)
    example_fields = validate_mr_body(example_mr_path.read_text(encoding="utf-8"), policy)
    if example_fields["evidence_manifest"] != policy.example_manifest_path.as_posix():
        raise EvidenceGovernanceError(
            ["example MR evidence manifest field must match the A05 policy path"]
        )
    change_policy = load_change_risk_policy(
        resolved_repository_root / "docs" / "governance" / "change-risk-policy.toml"
    )
    manifest = validate_manifest(
        example_manifest_path,
        expected_commit_sha=policy.example_commit_sha,
        change_policy=change_policy,
    )
    if manifest.roadmap_id != "A05" or manifest.open_finding_ids != policy.finding_ids:
        raise EvidenceGovernanceError(
            ["example manifest must retain the A05 roadmap ID and policy findings"]
        )
    if {gate.gate_id for gate in manifest.gates} != set(policy.applicable_gates):
        raise EvidenceGovernanceError(
            ["example manifest must record every applicable A05 gate exactly once"]
        )
    decision = classify_change(manifest.change, change_policy)
    example_required_gates = set(decision.mandatory_gates) | set(manifest.additional_required_gates)
    if example_required_gates != set(policy.mandatory_package_gates):
        raise EvidenceGovernanceError(
            ["example manifest required gates must exactly match the A05 policy"]
        )
    if any(gate.status != "passed" for gate in manifest.gates):
        raise EvidenceGovernanceError(
            ["example manifest must pass every repository-local applicable gate"]
        )
    return policy, manifest


def _parse_arguments(arguments: Sequence[str]) -> tuple[Path, dict[str, str]]:
    repository_root: Path | None = None
    options: dict[str, str] = {}
    index = 0
    allowed = {"--expected-commit-sha", "--github-event", "--manifest", "--mr-body"}
    while index < len(arguments):
        argument = arguments[index]
        if argument.startswith("--"):
            if argument not in allowed or argument in options or index + 1 >= len(arguments):
                raise EvidenceGovernanceError([_USAGE])
            options[argument] = arguments[index + 1]
            index += 2
            continue
        if repository_root is not None:
            raise EvidenceGovernanceError([_USAGE])
        repository_root = Path(argument)
        index += 1
    if "--mr-body" in options and "--github-event" in options:
        raise EvidenceGovernanceError([_USAGE])
    if ("--manifest" in options) != ("--expected-commit-sha" in options):
        raise EvidenceGovernanceError([_USAGE])
    return (Path.cwd() if repository_root is None else repository_root), options


def main(arguments: Sequence[str] | None = None) -> int:
    """Run repository, MR-body, event, and evidence-manifest checks."""
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    try:
        repository_root, options = _parse_arguments(cli_arguments)
    except EvidenceGovernanceError as error:
        print(error, file=sys.stderr)
        return 2
    try:
        policy, _ = validate_repository(repository_root)
        if mr_body := options.get("--mr-body"):
            validate_mr_body(
                _input_path(repository_root, mr_body).read_text(encoding="utf-8"), policy
            )
        if github_event := options.get("--github-event"):
            validate_github_event(_input_path(repository_root, github_event), policy)
        if manifest_path := options.get("--manifest"):
            change_policy = load_change_risk_policy(
                repository_root.resolve() / "docs" / "governance" / "change-risk-policy.toml"
            )
            validate_manifest(
                _input_path(repository_root, manifest_path),
                expected_commit_sha=options["--expected-commit-sha"],
                change_policy=change_policy,
            )
    except (EvidenceGovernanceError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(
        f"Evidence governance passed for {len(policy.fields)} MR fields; "
        f"package status is {policy.package_status}."
    )
    return 0
