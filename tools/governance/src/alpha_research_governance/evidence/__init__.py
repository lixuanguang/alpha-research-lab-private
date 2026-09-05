"""Canonical merge-request and evidence-governance API."""

from __future__ import annotations

# standard library imports
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

# project library imports
from alpha_research_governance.change_risk import classify_change
from alpha_research_governance.change_risk import load_policy as load_change_risk_policy
from alpha_research_governance.evidence.manifest import validate_manifest
from alpha_research_governance.evidence.models import (
    ApprovalEvidence,
    ArtifactEvidence,
    ConditionalMrField,
    EvidenceGovernanceError,
    EvidenceManifest,
    EvidencePolicy,
    GateEvidence,
    MrContext,
    MrField,
    PackageEvidenceProfile,
    PackageGateRequirement,
)
from alpha_research_governance.evidence.mr import (
    classify_mr,
    lint_github_event,
    validate_github_event,
    validate_mr_body,
    validate_template,
)
from alpha_research_governance.evidence.package import validate_package_evidence
from alpha_research_governance.evidence.policy import load_policy
from alpha_research_governance.operating_model import Operation, load_operating_model

__all__ = [
    "ApprovalEvidence",
    "ArtifactEvidence",
    "ConditionalMrField",
    "EvidenceGovernanceError",
    "EvidenceManifest",
    "EvidencePolicy",
    "GateEvidence",
    "MrContext",
    "MrField",
    "PackageEvidenceProfile",
    "PackageGateRequirement",
    "classify_mr",
    "lint_github_event",
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
    "[--manifest PATH --expected-commit-sha SHA] [--operation OPERATION]"
)


def _repository_path(repository_root: Path, relative: Path) -> Path:
    """Resolve a policy path and reject locations outside the repository root.

    Args:
        repository_root: Repository root that bounds the resolved path.
        relative: Policy-provided path to resolve beneath the root.

    Returns:
        An absolute, normalized path within ``repository_root``.

    Raises:
        EvidenceGovernanceError: If the resolved path escapes the repository root.
        OSError: If path resolution fails.
    """
    resolved_root = repository_root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise EvidenceGovernanceError([f"repository path escapes the root: {relative}"]) from error
    return resolved


def _input_path(repository_root: Path, value: str) -> Path:
    """Construct a CLI input path relative to the selected repository root.

    Args:
        repository_root: Repository root used for relative input values.
        value: Absolute or repository-relative path supplied on the command line.

    Returns:
        The unchanged absolute path, or a path rooted at the resolved repository root.
        Neither form is checked for repository containment.
    """
    path = Path(value)
    return path if path.is_absolute() else repository_root.resolve() / path


def validate_repository(repository_root: Path) -> tuple[EvidencePolicy, EvidenceManifest]:
    """Validate evidence policy, template, example MR, and example bundle.

    Args:
        repository_root: Repository root containing the A05 policy and its referenced
            template, examples, change-risk policy, and manifest artifacts.

    Returns:
        A pair containing the validated evidence policy followed by its validated example
        manifest. The manifest includes the policy-bound change classification and gate
        evidence.

    Raises:
        EvidenceGovernanceError: If any policy, template, example MR, change-risk binding,
            manifest, gate, finding, or artifact check fails.
        ChangeRiskPolicyError: If the repository change-risk policy cannot be loaded or
            validated.
        OSError: If a referenced repository file cannot be resolved or read.
        UnicodeDecodeError: If a referenced repository file is not valid UTF-8.
    """
    resolved_repository_root = repository_root.resolve()
    policy = load_policy(
        resolved_repository_root / "docs" / "governance" / "merge-evidence-policy.toml"
    )
    template_path = _repository_path(resolved_repository_root, policy.template_path)
    example_mr_path = _repository_path(resolved_repository_root, policy.example_mr_body_path)
    example_manifest_path = _repository_path(resolved_repository_root, policy.example_manifest_path)
    validate_template(template_path.read_text(encoding="utf-8"), policy)
    example_fields = validate_mr_body(
        example_mr_path.read_text(encoding="utf-8"), policy, profile="institutional"
    )
    if policy.founder_example_mr_body_path is not None:
        founder_example = _repository_path(
            resolved_repository_root, policy.founder_example_mr_body_path
        )
        validate_mr_body(founder_example.read_text(encoding="utf-8"), policy)
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
    """Parse evidence options and enforce supported combinations.

    Args:
        arguments: Ordered command-line tokens containing an optional repository root and
            supported option/value pairs.

    Returns:
        A pair containing the selected repository root, defaulting to the current working
        directory, and a mapping from each supplied option to its following value.

    Raises:
        EvidenceGovernanceError: If an option is unknown, duplicated, missing its value,
            combined with an incompatible option, or supplied with an invalid operation.
    """
    repository_root: Path | None = None
    options: dict[str, str] = {}
    index = 0
    allowed = {"--expected-commit-sha", "--github-event", "--manifest", "--mr-body", "--operation"}
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
    if "--operation" in options and (
        "--manifest" not in options
        or options["--operation"]
        not in {"implementation", "institutional_acceptance", "release", "activation"}
    ):
        raise EvidenceGovernanceError([_USAGE])
    return (Path.cwd() if repository_root is None else repository_root), options


def main(arguments: Sequence[str] | None = None) -> int:
    """Run repository, MR-body, event, and evidence-manifest checks.

    The command reads policy and evidence files, may print JSON metadata for
    ``--github-event``, and uses ``implementation`` as the default ``--operation`` for
    manifest validation. Governance, filesystem, and value failures from validation are
    caught; failures while resolving the default working directory, printing output, or
    handling unexpected conditions propagate to the caller.

    Args:
        arguments: Optional command-line arguments. Omit this value to consume
            ``sys.argv[1:]``; provide an optional repository root and supported evidence
            input options.

    Returns:
        ``0`` after printing the validation summary, ``1`` after printing a handled
        governance, filesystem, or value failure to stderr, or ``2`` after printing usage
        for invalid argument combinations.

    Raises:
        OSError: If resolving the default working directory or writing output fails
            outside the validation handler.
    """
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    try:
        repository_root, options = _parse_arguments(cli_arguments)
    except EvidenceGovernanceError as error:
        print(error, file=sys.stderr)
        return 2
    try:
        policy, _ = validate_repository(repository_root)
        change_policy = load_change_risk_policy(
            repository_root.resolve() / "docs" / "governance" / "change-risk-policy.toml"
        )
        if mr_body := options.get("--mr-body"):
            validate_mr_body(
                _input_path(repository_root, mr_body).read_text(encoding="utf-8"),
                policy,
                change_policy=change_policy,
            )
        if github_event := options.get("--github-event"):
            metadata = lint_github_event(
                _input_path(repository_root, github_event),
                policy,
                repository_root=repository_root,
                change_policy=change_policy,
            )
            print(json.dumps(metadata, sort_keys=True))
        if manifest_path := options.get("--manifest"):
            validate_manifest(
                _input_path(repository_root, manifest_path),
                expected_commit_sha=options["--expected-commit-sha"],
                change_policy=change_policy,
                operating_model=load_operating_model(
                    repository_root.resolve() / "docs" / "governance" / "domain-ownership.toml"
                ),
                operation=cast(Operation, options.get("--operation", "implementation")),
            )
    except (EvidenceGovernanceError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(
        f"Evidence governance passed for {len(policy.fields)} default MR fields; "
        "institutional fixtures retain their recorded acceptance status."
    )
    return 0
