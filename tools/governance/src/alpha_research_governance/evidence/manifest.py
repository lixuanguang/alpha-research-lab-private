"""Validate SHA-bound evidence manifests."""

from __future__ import annotations

# standard library imports
import hashlib
import re
import tomllib
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

# third party library imports
from pydantic import ValidationError

# project library imports
from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.change_risk import (
    ChangeRiskInput,
    ChangeRiskPolicy,
    RiskClass,
    classify_change,
    validate_merge_approvals,
)
from alpha_research_governance.evidence.models import (
    ApprovalEvidence,
    ArtifactEvidence,
    EvidenceGovernanceError,
    EvidenceManifest,
    GateEvidence,
)
from alpha_research_governance.operating_model import OperatingModel, Operation

_COMMIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GATE = re.compile(r"^QG(?:0[1-9]|1[0-5])$")
_ROLE = re.compile(r"^[a-z][a-z0-9_]*$")
_BUNDLE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ROADMAP_ID = re.compile(r"^[A-L]0[1-8]$")
_ARTIFACT_TYPE = re.compile(r"^[a-z][a-z0-9_]*$")
_GATE_STATUSES = {"deferred", "failed", "not_applicable", "passed"}
_BUNDLE_STATUSES = {"accepted", "partial"}
_APPROVAL_STATUSES = {"approved", "pending", "rejected"}


class _ChangeInput(ImmutableModel):
    capital_at_risk: bool
    blast_radius: str
    data_model_materiality: str
    security_privilege: str
    reversibility: str
    computationally_material: bool
    economically_or_risk_relevant: bool
    model_or_trading_relevant: bool
    declared_class: str


class _GateInput(ImmutableModel):
    gate_id: str
    status: str
    rationale: str
    evidence_ids: list[str]


class _ArtifactInput(ImmutableModel):
    evidence_id: str
    artifact_type: str
    path: str
    sha256: str


class _ApprovalInput(ImmutableModel):
    reviewer_id: str
    roles: list[str]
    independent: bool
    is_author: bool
    status: str
    commit_sha: str
    evidence_url: str


class _FindingInput(ImmutableModel):
    finding_id: str
    owner_role: str
    unavailable_evidence: str
    closure_condition: str


class _EvidenceManifestInput(ImmutableModel):
    schema_version: int
    bundle_id: str
    roadmap_id: str
    commit_sha: str
    owner_role: str
    risk_class: str
    evidence_retention_class: str
    bundle_status: str
    change: _ChangeInput
    additional_required_gates: list[str]
    gates: list[_GateInput]
    artifacts: list[_ArtifactInput]
    approvals: list[_ApprovalInput]
    findings: list[_FindingInput]
    open_finding_ids: list[str]
    waived_controls: list[str]


class _ImplementationManifestInput(_EvidenceManifestInput):
    operating_domain: str
    accepted_by: str
    accepted_on: str


_ROOT_KEYS = frozenset(_EvidenceManifestInput.model_fields)
_CHANGE_KEYS = frozenset(_ChangeInput.model_fields)
_ROOT_STRING_FIELDS = frozenset(
    {
        "bundle_id",
        "roadmap_id",
        "commit_sha",
        "owner_role",
        "risk_class",
        "evidence_retention_class",
        "bundle_status",
    }
)
_ROOT_STRING_ARRAY_FIELDS = frozenset(
    {"additional_required_gates", "open_finding_ids", "waived_controls"}
)
_CHANGE_BOOLEAN_FIELDS = frozenset(
    {
        "capital_at_risk",
        "computationally_material",
        "economically_or_risk_relevant",
        "model_or_trading_relevant",
    }
)
_TABLE_ARRAY_FIELDS = frozenset({"gates", "artifacts", "approvals", "findings"})
_APPROVAL_BOOLEAN_FIELDS = frozenset({"independent", "is_author"})


def _manifest_input_error(path: Path, error: ValidationError) -> EvidenceGovernanceError:
    details = error.errors(include_url=False, include_input=False)
    if any(
        len(detail["loc"]) == 1 and detail["type"] in {"missing", "extra_forbidden"}
        for detail in details
    ):
        return EvidenceGovernanceError([f"{path}: fields must be exactly {sorted(_ROOT_KEYS)!r}"])

    detail = details[0]
    location = detail["loc"]
    error_type = detail["type"]
    if not location:
        return EvidenceGovernanceError([f"{path} must be a TOML table"])

    root_field = str(location[0])
    if root_field == "schema_version":
        return EvidenceGovernanceError([f"{path}: schema_version must be 1"])
    if root_field in _ROOT_STRING_FIELDS:
        return EvidenceGovernanceError([f"{path}.{root_field} must be a non-empty string"])
    if root_field in _ROOT_STRING_ARRAY_FIELDS:
        return EvidenceGovernanceError([f"{root_field} must be an array of non-empty strings"])
    if root_field == "change":
        if len(location) == 1:
            return EvidenceGovernanceError(["change must be a TOML table"])
        if error_type in {"missing", "extra_forbidden"}:
            return EvidenceGovernanceError(
                [f"change fields must be exactly {sorted(_CHANGE_KEYS)!r}"]
            )
        field = str(location[1])
        if field in _CHANGE_BOOLEAN_FIELDS:
            return EvidenceGovernanceError([f"change.{field} must be Boolean"])
        return EvidenceGovernanceError([f"change.{field} must be a non-empty string"])
    if root_field in _TABLE_ARRAY_FIELDS:
        if len(location) < 3 or not isinstance(location[1], int):
            return EvidenceGovernanceError([f"{root_field} must be an array of TOML tables"])
        context = f"{root_field}[{location[1] + 1}]"
        if error_type in {"missing", "extra_forbidden"}:
            return EvidenceGovernanceError([f"{context} has missing or unknown fields"])
        field = str(location[2])
        if root_field == "gates" and field == "evidence_ids":
            return EvidenceGovernanceError(
                [f"{context}.evidence_ids must be an array of non-empty strings"]
            )
        if root_field == "approvals" and field == "roles":
            return EvidenceGovernanceError(
                [f"{context}.roles must be an array of non-empty strings"]
            )
        if root_field == "approvals" and field in _APPROVAL_BOOLEAN_FIELDS:
            return EvidenceGovernanceError([f"{context}.{field} must be Boolean"])
        qualifier = (
            "a string"
            if root_field == "approvals" and field == "evidence_url"
            else "a non-empty string"
        )
        return EvidenceGovernanceError([f"{context}.{field} must be {qualifier}"])
    return EvidenceGovernanceError([f"{path}: manifest model validation failed"])


def _validated_strings(
    value: list[str], *, context: str, allow_empty: bool = False
) -> tuple[str, ...]:
    if not all(value):
        raise EvidenceGovernanceError([f"{context} must be an array of non-empty strings"])
    values = tuple(value)
    if not allow_empty and not values:
        raise EvidenceGovernanceError([f"{context} must not be empty"])
    if len(values) != len(set(values)):
        raise EvidenceGovernanceError([f"{context} must contain unique values"])
    return values


def _validated_string(value: str, *, context: str) -> str:
    if not value:
        raise EvidenceGovernanceError([f"{context} must be a non-empty string"])
    return value


def _parse_change(value: _ChangeInput) -> ChangeRiskInput:
    declared = _validated_string(value.declared_class, context="change.declared_class")
    try:
        declared_class = RiskClass(declared)
    except ValueError as error:
        raise EvidenceGovernanceError(["change.declared_class must be R0-R4"]) from error
    return ChangeRiskInput(
        capital_at_risk=value.capital_at_risk,
        blast_radius=_validated_string(value.blast_radius, context="change.blast_radius"),
        data_model_materiality=_validated_string(
            value.data_model_materiality, context="change.data_model_materiality"
        ),
        security_privilege=_validated_string(
            value.security_privilege, context="change.security_privilege"
        ),
        reversibility=_validated_string(value.reversibility, context="change.reversibility"),
        computationally_material=value.computationally_material,
        economically_or_risk_relevant=value.economically_or_risk_relevant,
        model_or_trading_relevant=value.model_or_trading_relevant,
        declared_class=declared_class,
    )


def _parse_gates(value: list[_GateInput]) -> tuple[GateEvidence, ...]:
    gates: list[GateEvidence] = []
    for index, item in enumerate(value, 1):
        context = f"gates[{index}]"
        gate_id = _validated_string(item.gate_id, context=f"{context}.gate_id")
        status = _validated_string(item.status, context=f"{context}.status")
        rationale = _validated_string(item.rationale, context=f"{context}.rationale")
        evidence_ids = _validated_strings(
            item.evidence_ids, context=f"{context}.evidence_ids", allow_empty=True
        )
        if _GATE.fullmatch(gate_id) is None:
            raise EvidenceGovernanceError([f"{context}.gate_id must be QG01-QG15"])
        if status not in _GATE_STATUSES:
            raise EvidenceGovernanceError([f"{context}.status is unsupported"])
        if status == "passed" and not evidence_ids:
            raise EvidenceGovernanceError([f"{context}: passed gate requires evidence_ids"])
        gates.append(
            GateEvidence(
                gate_id=gate_id,
                status=status,
                rationale=rationale,
                evidence_ids=evidence_ids,
            )
        )
    if len({gate.gate_id for gate in gates}) != len(gates):
        raise EvidenceGovernanceError(["gate IDs must be unique"])
    return tuple(gates)


def _parse_artifacts(value: list[_ArtifactInput]) -> tuple[ArtifactEvidence, ...]:
    artifacts: list[ArtifactEvidence] = []
    for index, item in enumerate(value, 1):
        context = f"artifacts[{index}]"
        artifact = ArtifactEvidence(
            evidence_id=_validated_string(item.evidence_id, context=f"{context}.evidence_id"),
            artifact_type=_validated_string(item.artifact_type, context=f"{context}.artifact_type"),
            path=_validated_string(item.path, context=f"{context}.path"),
            sha256=_validated_string(item.sha256, context=f"{context}.sha256"),
        )
        if _BUNDLE_ID.fullmatch(artifact.evidence_id) is None:
            raise EvidenceGovernanceError([f"{context}.evidence_id must be lower-kebab-case"])
        if _ARTIFACT_TYPE.fullmatch(artifact.artifact_type) is None:
            raise EvidenceGovernanceError([f"{context}.artifact_type must be lower_snake_case"])
        if _SHA256.fullmatch(artifact.sha256) is None:
            raise EvidenceGovernanceError([f"{context}.sha256 must be a lowercase SHA-256"])
        artifacts.append(artifact)
    if len({artifact.evidence_id for artifact in artifacts}) != len(artifacts):
        raise EvidenceGovernanceError(["artifact evidence IDs must be unique"])
    if len({artifact.path for artifact in artifacts}) != len(artifacts):
        raise EvidenceGovernanceError(["artifact paths must be unique"])
    return tuple(artifacts)


def _parse_approvals(
    value: list[_ApprovalInput], *, commit_sha: str
) -> tuple[ApprovalEvidence, ...]:
    approvals: list[ApprovalEvidence] = []
    for index, item in enumerate(value, 1):
        context = f"approvals[{index}]"
        status = _validated_string(item.status, context=f"{context}.status")
        approval_commit = _validated_string(item.commit_sha, context=f"{context}.commit_sha")
        evidence_url = item.evidence_url
        if status not in _APPROVAL_STATUSES:
            raise EvidenceGovernanceError([f"{context}.status is unsupported"])
        if approval_commit != commit_sha:
            raise EvidenceGovernanceError([f"{context}.commit_sha must match the bundle commit"])
        if status == "approved":
            try:
                parsed_url = urlsplit(evidence_url)
            except ValueError as error:
                raise EvidenceGovernanceError(
                    [f"{context}: approved evidence requires a valid HTTPS URL"]
                ) from error
            has_credentials = parsed_url.username is not None or parsed_url.password is not None
            if parsed_url.scheme != "https" or not parsed_url.hostname or has_credentials:
                raise EvidenceGovernanceError(
                    [f"{context}: approved evidence requires an HTTPS URL without credentials"]
                )
        roles = _validated_strings(item.roles, context=f"{context}.roles")
        if any(_ROLE.fullmatch(role) is None for role in roles):
            raise EvidenceGovernanceError([f"{context}.roles must be lower_snake_case"])
        approval = ApprovalEvidence(
            reviewer_id=_validated_string(item.reviewer_id, context=f"{context}.reviewer_id"),
            roles=frozenset(roles),
            independent=item.independent,
            is_author=item.is_author,
            status=status,
            commit_sha=approval_commit,
            evidence_url=evidence_url,
        )
        approvals.append(approval)
    return tuple(approvals)


def _parse_findings(value: list[_FindingInput]) -> tuple[str, ...]:
    finding_ids: list[str] = []
    for index, item in enumerate(value, 1):
        context = f"findings[{index}]"
        finding_id = _validated_string(item.finding_id, context=f"{context}.finding_id")
        _validated_string(item.owner_role, context=f"{context}.owner_role")
        _validated_string(item.unavailable_evidence, context=f"{context}.unavailable_evidence")
        _validated_string(item.closure_condition, context=f"{context}.closure_condition")
        finding_ids.append(finding_id)
    if len(finding_ids) != len(set(finding_ids)):
        raise EvidenceGovernanceError(["finding IDs must be unique"])
    return tuple(finding_ids)


def _resolve_artifact_path(bundle_root: Path, relative_text: str) -> Path:
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts:
        raise EvidenceGovernanceError([f"artifact path escapes the bundle: {relative_text}"])
    candidate = bundle_root / relative
    current = bundle_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise EvidenceGovernanceError([f"artifact path may not use symlinks: {relative_text}"])
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(bundle_root)
    except (FileNotFoundError, ValueError) as error:
        raise EvidenceGovernanceError(
            [f"artifact path is missing or outside the bundle: {relative_text}"]
        ) from error
    if not resolved.is_file():
        raise EvidenceGovernanceError([f"artifact path must be a file: {relative_text}"])
    return resolved


def _verify_artifacts(path: Path, artifacts: tuple[ArtifactEvidence, ...]) -> None:
    bundle_root = path.parent.resolve()
    for artifact in artifacts:
        artifact_path = _resolve_artifact_path(bundle_root, artifact.path)
        actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual != artifact.sha256:
            raise EvidenceGovernanceError(
                [f"artifact {artifact.evidence_id!r} SHA-256 mismatch: {artifact.path}"]
            )


def _validate_manifest(
    path: Path,
    *,
    expected_commit_sha: str,
    change_policy: ChangeRiskPolicy,
    operating_model: OperatingModel | None,
    operation: Operation,
) -> EvidenceManifest:
    """Validate a manifest, change-risk binding, artifact digests, and acceptance."""
    if _COMMIT_SHA.fullmatch(expected_commit_sha) is None:
        raise EvidenceGovernanceError(["expected_commit_sha must be a full lowercase SHA"])
    if path.is_symlink():
        raise EvidenceGovernanceError([f"{path}: manifest may not be a symlink"])
    try:
        parsed_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise EvidenceGovernanceError([f"{path}: invalid TOML: {error}"]) from error
    try:
        input_model = (
            _ImplementationManifestInput
            if isinstance(parsed_document, dict) and parsed_document.get("schema_version") == 2
            else _EvidenceManifestInput
        )
        manifest_document = input_model.model_validate(parsed_document)
    except ValidationError as error:
        raise _manifest_input_error(path, error) from error
    if manifest_document.schema_version not in {1, 2}:
        raise EvidenceGovernanceError([f"{path}: schema_version must be 1 or 2"])

    bundle_id = _validated_string(manifest_document.bundle_id, context=f"{path}.bundle_id")
    roadmap_id = _validated_string(manifest_document.roadmap_id, context=f"{path}.roadmap_id")
    commit_sha = _validated_string(manifest_document.commit_sha, context=f"{path}.commit_sha")
    owner_role = _validated_string(manifest_document.owner_role, context=f"{path}.owner_role")
    risk_class = _validated_string(manifest_document.risk_class, context=f"{path}.risk_class")
    retention = _validated_string(
        manifest_document.evidence_retention_class,
        context=f"{path}.evidence_retention_class",
    )
    bundle_status = _validated_string(
        manifest_document.bundle_status, context=f"{path}.bundle_status"
    )
    if _BUNDLE_ID.fullmatch(bundle_id) is None:
        raise EvidenceGovernanceError([f"{path}: bundle_id must be lower-kebab-case"])
    if _ROADMAP_ID.fullmatch(roadmap_id) is None:
        raise EvidenceGovernanceError([f"{path}: roadmap_id must be A01-L08"])
    if commit_sha != expected_commit_sha:
        raise EvidenceGovernanceError([f"{path}: commit_sha does not match expected commit"])
    if _ROLE.fullmatch(owner_role) is None:
        raise EvidenceGovernanceError([f"{path}: owner_role must be lower_snake_case"])
    implementation = isinstance(manifest_document, _ImplementationManifestInput)
    if implementation and bundle_status != "implementation_accepted":
        raise EvidenceGovernanceError(["schema_version 2 requires implementation_accepted status"])
    if not implementation and bundle_status not in _BUNDLE_STATUSES:
        raise EvidenceGovernanceError([f"{path}: bundle_status must be partial or accepted"])

    change = _parse_change(manifest_document.change)
    try:
        decision = classify_change(change, change_policy)
    except ValueError as error:
        raise EvidenceGovernanceError([str(error)]) from error
    if risk_class != decision.risk_class.value:
        raise EvidenceGovernanceError([f"{path}: risk_class does not match A04 classification"])
    if retention != decision.evidence_retention_class:
        raise EvidenceGovernanceError(
            [f"{path}: evidence_retention_class does not match A04 classification"]
        )

    additional_gates = _validated_strings(
        manifest_document.additional_required_gates,
        context="additional_required_gates",
        allow_empty=True,
    )
    if any(_GATE.fullmatch(gate) is None for gate in additional_gates):
        raise EvidenceGovernanceError(["additional_required_gates must use QG01-QG15"])
    gates = _parse_gates(manifest_document.gates)
    artifacts = _parse_artifacts(manifest_document.artifacts)
    approvals = _parse_approvals(manifest_document.approvals, commit_sha=commit_sha)
    finding_ids = _parse_findings(manifest_document.findings)
    open_finding_ids = _validated_strings(
        manifest_document.open_finding_ids,
        context="open_finding_ids",
        allow_empty=True,
    )
    if open_finding_ids != finding_ids:
        raise EvidenceGovernanceError(["open_finding_ids must exactly match findings"])
    waived_controls = _validated_strings(
        manifest_document.waived_controls,
        context="waived_controls",
        allow_empty=True,
    )

    gates_by_id = {gate.gate_id: gate for gate in gates}
    required_gates = set(decision.mandatory_gates) | set(additional_gates)
    missing_gates = required_gates - set(gates_by_id)
    if missing_gates:
        raise EvidenceGovernanceError([f"required gates are missing: {sorted(missing_gates)}"])
    invalid_required = sorted(
        gate_id for gate_id in required_gates if gates_by_id[gate_id].status == "not_applicable"
    )
    if invalid_required:
        raise EvidenceGovernanceError(
            [f"required gates cannot be not_applicable: {invalid_required}"]
        )
    evidence_ids = {artifact.evidence_id for artifact in artifacts}
    unknown_evidence = sorted(
        {
            evidence_id
            for gate in gates
            for evidence_id in gate.evidence_ids
            if evidence_id not in evidence_ids
        }
    )
    if unknown_evidence:
        raise EvidenceGovernanceError([f"gates reference unknown evidence: {unknown_evidence}"])
    _verify_artifacts(path, artifacts)

    class_policy = change_policy.class_policy(decision.risk_class)
    prohibited_waivers = class_policy.risk_class is RiskClass.R4 and (
        change_policy.hard_controls & set(waived_controls)
    )
    if prohibited_waivers:
        raise EvidenceGovernanceError(["R4 manifest cannot waive a non-waivable hard control"])

    accepted_on: date | None = None
    if isinstance(manifest_document, _ImplementationManifestInput):
        if operating_model is None:
            raise EvidenceGovernanceError(
                ["implementation acceptance requires the operating model"]
            )
        if operation != "implementation":
            raise EvidenceGovernanceError(
                ["implementation evidence cannot authorize institutional operations"]
            )
        if manifest_document.accepted_by != operating_model.founder_principal:
            raise EvidenceGovernanceError(
                ["implementation acceptance requires the recorded founder"]
            )
        if approvals or waived_controls:
            raise EvidenceGovernanceError(
                ["implementation evidence cannot contain institutional approvals or waivers"]
            )
        incomplete_implementation = tuple(
            gate.gate_id
            for gate in gates
            if (gate.gate_id in required_gates and gate.status != "passed")
            or gate.status in {"failed", "deferred"}
        )
        try:
            accepted_on = date.fromisoformat(manifest_document.accepted_on)
            rules = operating_model.resolve(
                domain_id=manifest_document.operating_domain,
                operation=operation,
                on_date=accepted_on,
            )
            rules.require_local_completion(
                repository_local_status="failed" if incomplete_implementation else "passed",
                technical_finding_ids=open_finding_ids,
            )
        except ValueError as error:
            raise EvidenceGovernanceError([str(error)]) from error
    elif bundle_status == "partial":
        if not open_finding_ids:
            raise EvidenceGovernanceError(["partial bundle requires at least one open finding"])
    else:
        incomplete = sorted(
            gate_id for gate_id in required_gates if gates_by_id[gate_id].status != "passed"
        )
        if incomplete:
            raise EvidenceGovernanceError([f"accepted bundle has incomplete gates: {incomplete}"])
        if open_finding_ids:
            raise EvidenceGovernanceError(["accepted bundle cannot retain open findings"])
        if any(approval.status != "approved" for approval in approvals):
            raise EvidenceGovernanceError(["accepted bundle cannot retain non-approved reviews"])
        review_approvals = tuple(approval.as_review_approval() for approval in approvals)
        try:
            validate_merge_approvals(
                decision,
                review_approvals,
                change=change,
                waived_controls=waived_controls,
                policy=change_policy,
            )
        except ValueError as error:
            raise EvidenceGovernanceError([str(error)]) from error

    return EvidenceManifest(
        bundle_id=bundle_id,
        roadmap_id=roadmap_id,
        commit_sha=commit_sha,
        owner_role=owner_role,
        risk_class=risk_class,
        evidence_retention_class=retention,
        additional_required_gates=additional_gates,
        bundle_status=bundle_status,
        waived_controls=waived_controls,
        open_finding_ids=open_finding_ids,
        change=change,
        gates=gates,
        artifacts=artifacts,
        approvals=approvals,
        schema_version=2 if implementation else 1,
        operating_domain=(
            manifest_document.operating_domain
            if isinstance(manifest_document, _ImplementationManifestInput)
            else None
        ),
        accepted_by=(
            manifest_document.accepted_by
            if isinstance(manifest_document, _ImplementationManifestInput)
            else None
        ),
        accepted_on=accepted_on,
    )


def validate_manifest(
    path: Path,
    *,
    expected_commit_sha: str,
    change_policy: ChangeRiskPolicy,
    operating_model: OperatingModel | None = None,
    operation: Operation = "implementation",
) -> EvidenceManifest:
    """Validate evidence while preserving the public domain-error contract."""
    try:
        return _validate_manifest(
            path,
            expected_commit_sha=expected_commit_sha,
            change_policy=change_policy,
            operating_model=operating_model,
            operation=operation,
        )
    except ValidationError as error:
        raise EvidenceGovernanceError([f"{path}: manifest model validation failed"]) from error
