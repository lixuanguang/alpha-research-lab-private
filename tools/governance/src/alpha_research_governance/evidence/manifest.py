"""Validate SHA-bound A05 evidence manifests."""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from pydantic import ValidationError

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
_ROOT_KEYS = {
    "additional_required_gates",
    "approvals",
    "artifacts",
    "bundle_id",
    "bundle_status",
    "change",
    "commit_sha",
    "evidence_retention_class",
    "findings",
    "gates",
    "open_finding_ids",
    "owner_role",
    "risk_class",
    "roadmap_id",
    "schema_version",
    "waived_controls",
}


def _table(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise EvidenceGovernanceError([f"{context} must be a TOML table"])
    return cast(dict[str, object], value)


def _table_list(value: object, *, context: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise EvidenceGovernanceError([f"{context} must be an array of TOML tables"])
    return cast(list[dict[str, object]], value)


def _strings(value: object, *, context: str, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise EvidenceGovernanceError([f"{context} must be an array of non-empty strings"])
    values = tuple(cast(list[str], value))
    if not allow_empty and not values:
        raise EvidenceGovernanceError([f"{context} must not be empty"])
    if len(values) != len(set(values)):
        raise EvidenceGovernanceError([f"{context} must contain unique values"])
    return values


def _string(table: dict[str, object], key: str, *, context: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise EvidenceGovernanceError([f"{context}.{key} must be a non-empty string"])
    return value


def _boolean(table: dict[str, object], key: str, *, context: str) -> bool:
    value = table.get(key)
    if not isinstance(value, bool):
        raise EvidenceGovernanceError([f"{context}.{key} must be Boolean"])
    return value


def _parse_change(value: object) -> ChangeRiskInput:
    table = _table(value, context="change")
    expected = {
        "blast_radius",
        "capital_at_risk",
        "computationally_material",
        "data_model_materiality",
        "declared_class",
        "economically_or_risk_relevant",
        "model_or_trading_relevant",
        "reversibility",
        "security_privilege",
    }
    if set(table) != expected:
        raise EvidenceGovernanceError([f"change fields must be exactly {sorted(expected)!r}"])
    declared = _string(table, "declared_class", context="change")
    try:
        declared_class = RiskClass(declared)
    except ValueError as error:
        raise EvidenceGovernanceError(["change.declared_class must be R0-R4"]) from error
    return ChangeRiskInput(
        capital_at_risk=_boolean(table, "capital_at_risk", context="change"),
        blast_radius=_string(table, "blast_radius", context="change"),
        data_model_materiality=_string(table, "data_model_materiality", context="change"),
        security_privilege=_string(table, "security_privilege", context="change"),
        reversibility=_string(table, "reversibility", context="change"),
        computationally_material=_boolean(table, "computationally_material", context="change"),
        economically_or_risk_relevant=_boolean(
            table, "economically_or_risk_relevant", context="change"
        ),
        model_or_trading_relevant=_boolean(table, "model_or_trading_relevant", context="change"),
        declared_class=declared_class,
    )


def _parse_gates(value: object) -> tuple[GateEvidence, ...]:
    gates: list[GateEvidence] = []
    for index, item in enumerate(_table_list(value, context="gates"), 1):
        context = f"gates[{index}]"
        if set(item) != {"evidence_ids", "gate_id", "rationale", "status"}:
            raise EvidenceGovernanceError([f"{context} has missing or unknown fields"])
        gate_id = _string(item, "gate_id", context=context)
        status = _string(item, "status", context=context)
        rationale = _string(item, "rationale", context=context)
        evidence_ids = _strings(
            item.get("evidence_ids"), context=f"{context}.evidence_ids", allow_empty=True
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


def _parse_artifacts(value: object) -> tuple[ArtifactEvidence, ...]:
    artifacts: list[ArtifactEvidence] = []
    expected = {"artifact_type", "evidence_id", "path", "sha256"}
    for index, item in enumerate(_table_list(value, context="artifacts"), 1):
        context = f"artifacts[{index}]"
        if set(item) != expected:
            raise EvidenceGovernanceError([f"{context} has missing or unknown fields"])
        artifact = ArtifactEvidence(
            evidence_id=_string(item, "evidence_id", context=context),
            artifact_type=_string(item, "artifact_type", context=context),
            path=_string(item, "path", context=context),
            sha256=_string(item, "sha256", context=context),
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


def _parse_approvals(value: object, *, commit_sha: str) -> tuple[ApprovalEvidence, ...]:
    approvals: list[ApprovalEvidence] = []
    expected = {
        "commit_sha",
        "evidence_url",
        "independent",
        "is_author",
        "reviewer_id",
        "roles",
        "status",
    }
    for index, item in enumerate(_table_list(value, context="approvals"), 1):
        context = f"approvals[{index}]"
        if set(item) != expected:
            raise EvidenceGovernanceError([f"{context} has missing or unknown fields"])
        status = _string(item, "status", context=context)
        approval_commit = _string(item, "commit_sha", context=context)
        evidence_url = item.get("evidence_url")
        if status not in _APPROVAL_STATUSES:
            raise EvidenceGovernanceError([f"{context}.status is unsupported"])
        if approval_commit != commit_sha:
            raise EvidenceGovernanceError([f"{context}.commit_sha must match the bundle commit"])
        if not isinstance(evidence_url, str):
            raise EvidenceGovernanceError([f"{context}.evidence_url must be a string"])
        if status == "approved":
            parsed_url = urlsplit(evidence_url)
            if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.username:
                raise EvidenceGovernanceError(
                    [f"{context}: approved evidence requires an HTTPS URL without credentials"]
                )
        roles = _strings(item.get("roles"), context=f"{context}.roles")
        if any(_ROLE.fullmatch(role) is None for role in roles):
            raise EvidenceGovernanceError([f"{context}.roles must be lower_snake_case"])
        approval = ApprovalEvidence(
            reviewer_id=_string(item, "reviewer_id", context=context),
            roles=frozenset(roles),
            independent=_boolean(item, "independent", context=context),
            is_author=_boolean(item, "is_author", context=context),
            status=status,
            commit_sha=approval_commit,
            evidence_url=evidence_url,
        )
        approvals.append(approval)
    return tuple(approvals)


def _parse_findings(value: object) -> tuple[str, ...]:
    finding_ids: list[str] = []
    expected = {"closure_condition", "finding_id", "owner_role", "unavailable_evidence"}
    for index, item in enumerate(_table_list(value, context="findings"), 1):
        context = f"findings[{index}]"
        if set(item) != expected:
            raise EvidenceGovernanceError([f"{context} has missing or unknown fields"])
        finding_id = _string(item, "finding_id", context=context)
        _string(item, "owner_role", context=context)
        _string(item, "unavailable_evidence", context=context)
        _string(item, "closure_condition", context=context)
        finding_ids.append(finding_id)
    if len(finding_ids) != len(set(finding_ids)):
        raise EvidenceGovernanceError(["finding IDs must be unique"])
    return tuple(finding_ids)


def _artifact_path(bundle_root: Path, relative_text: str) -> Path:
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
        artifact_path = _artifact_path(bundle_root, artifact.path)
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
) -> EvidenceManifest:
    """Validate a manifest, A04 decision binding, artifact digests, and acceptance."""
    if _COMMIT_SHA.fullmatch(expected_commit_sha) is None:
        raise EvidenceGovernanceError(["expected_commit_sha must be a full lowercase SHA"])
    if path.is_symlink():
        raise EvidenceGovernanceError([f"{path}: manifest may not be a symlink"])
    try:
        parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise EvidenceGovernanceError([f"{path}: invalid TOML: {error}"]) from error
    root = _table(parsed, context=str(path))
    if set(root) != _ROOT_KEYS:
        raise EvidenceGovernanceError([f"{path}: fields must be exactly {sorted(_ROOT_KEYS)!r}"])
    if root.get("schema_version") != 1:
        raise EvidenceGovernanceError([f"{path}: schema_version must be 1"])

    bundle_id = _string(root, "bundle_id", context=str(path))
    roadmap_id = _string(root, "roadmap_id", context=str(path))
    commit_sha = _string(root, "commit_sha", context=str(path))
    owner_role = _string(root, "owner_role", context=str(path))
    risk_class = _string(root, "risk_class", context=str(path))
    retention = _string(root, "evidence_retention_class", context=str(path))
    bundle_status = _string(root, "bundle_status", context=str(path))
    if _BUNDLE_ID.fullmatch(bundle_id) is None:
        raise EvidenceGovernanceError([f"{path}: bundle_id must be lower-kebab-case"])
    if _ROADMAP_ID.fullmatch(roadmap_id) is None:
        raise EvidenceGovernanceError([f"{path}: roadmap_id must be A01-L08"])
    if commit_sha != expected_commit_sha:
        raise EvidenceGovernanceError([f"{path}: commit_sha does not match expected commit"])
    if _ROLE.fullmatch(owner_role) is None:
        raise EvidenceGovernanceError([f"{path}: owner_role must be lower_snake_case"])
    if bundle_status not in _BUNDLE_STATUSES:
        raise EvidenceGovernanceError([f"{path}: bundle_status must be partial or accepted"])

    change = _parse_change(root.get("change"))
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

    additional_gates = _strings(
        root.get("additional_required_gates"),
        context="additional_required_gates",
        allow_empty=True,
    )
    if any(_GATE.fullmatch(gate) is None for gate in additional_gates):
        raise EvidenceGovernanceError(["additional_required_gates must use QG01-QG15"])
    gates = _parse_gates(root.get("gates"))
    artifacts = _parse_artifacts(root.get("artifacts"))
    approvals = _parse_approvals(root.get("approvals"), commit_sha=commit_sha)
    finding_ids = _parse_findings(root.get("findings"))
    open_finding_ids = _strings(
        root.get("open_finding_ids"), context="open_finding_ids", allow_empty=True
    )
    if open_finding_ids != finding_ids:
        raise EvidenceGovernanceError(["open_finding_ids must exactly match findings"])
    waived_controls = _strings(
        root.get("waived_controls"), context="waived_controls", allow_empty=True
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

    if bundle_status == "partial":
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
    )


def validate_manifest(
    path: Path,
    *,
    expected_commit_sha: str,
    change_policy: ChangeRiskPolicy,
) -> EvidenceManifest:
    """Validate evidence while preserving the public domain-error contract."""
    try:
        return _validate_manifest(
            path,
            expected_commit_sha=expected_commit_sha,
            change_policy=change_policy,
        )
    except ValidationError as error:
        raise EvidenceGovernanceError([f"{path}: manifest model validation failed"]) from error
