"""Parse the merge-request and evidence policy strictly."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from pydantic import ValidationError

from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.evidence.models import (
    ConditionalMrField,
    EvidenceGovernanceError,
    EvidencePolicy,
    MrField,
)

_GATE = re.compile(r"^QG(?:0[1-9]|1[0-5])$")
_FIELD_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_COMMIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_MERGE_EVIDENCE_OPEN_FINDING_IDS = ("A05-F01", "A05-F02")
_EXPECTED_SCALARS: dict[str, object] = {
    "roadmap_package": "A05",
    "operating_track": "solo_bootstrap",
    "package_status": "partial",
    "accountable_owner_role": "platform",
    "risk_class": "R0",
}


class _MrFieldInput(ImmutableModel):
    key: str
    heading: str


class _FindingInput(ImmutableModel):
    finding_id: str
    owner_role: str
    unavailable_evidence: str
    closure_condition: str


class _EvidencePolicyInput(ImmutableModel):
    schema_version: int
    roadmap_package: str
    operating_track: str
    package_status: str
    accountable_owner_role: str
    risk_class: str
    applicable_gates: list[str]
    mandatory_package_gates: list[str]
    template_path: str
    example_mr_body_path: str
    example_manifest_path: str
    example_commit_sha: str
    mr_fields: list[_MrFieldInput]
    findings: list[_FindingInput]


class _ConditionalMrFieldInput(_MrFieldInput):
    trigger: str


class _EvidencePolicyV2Input(_EvidencePolicyInput):
    institutional_mr_fields: list[_MrFieldInput]
    conditional_mr_fields: list[_ConditionalMrFieldInput]
    founder_example_mr_body_path: str


_EXPECTED_ROOT_KEYS = frozenset(_EvidencePolicyInput.model_fields)


def _policy_input_error(path: Path, error: ValidationError) -> EvidenceGovernanceError:
    detail = error.errors(include_url=False, include_input=False)[0]
    location = detail["loc"]
    error_type = detail["type"]
    if not location:
        return EvidenceGovernanceError([f"{path}: policy root must be a TOML table"])

    root_field = location[0]
    if len(location) == 1 and error_type in {"missing", "extra_forbidden"}:
        return EvidenceGovernanceError(
            [f"{path}: fields must be exactly {sorted(_EXPECTED_ROOT_KEYS)!r}"]
        )
    if root_field in _EXPECTED_SCALARS:
        expected = _EXPECTED_SCALARS[str(root_field)]
        return EvidenceGovernanceError([f"{path}: {root_field} must be {expected!r}"])
    if root_field in {"applicable_gates", "mandatory_package_gates"}:
        return EvidenceGovernanceError([f"{root_field} must contain non-empty strings"])
    if root_field in {
        "template_path",
        "example_mr_body_path",
        "example_manifest_path",
    }:
        return EvidenceGovernanceError([f"{root_field} must be a repository-relative path"])
    if root_field == "example_commit_sha":
        return EvidenceGovernanceError([f"{path}: example_commit_sha must be a full lowercase SHA"])
    if root_field == "mr_fields":
        if len(location) < 3 or not isinstance(location[1], int):
            return EvidenceGovernanceError(["mr_fields must be an array of TOML tables"])
        index = location[1] + 1
        if error_type in {"missing", "extra_forbidden"}:
            return EvidenceGovernanceError([f"mr_fields[{index}] must contain key and heading"])
        if location[2] == "key":
            return EvidenceGovernanceError([f"mr_fields[{index}].key must be lower_snake_case"])
        if location[2] == "heading":
            return EvidenceGovernanceError([f"mr_fields[{index}].heading must not be empty"])
    if root_field == "findings":
        if len(location) < 3 or not isinstance(location[1], int):
            return EvidenceGovernanceError(["findings must be an array of TOML tables"])
        return EvidenceGovernanceError(
            [f"findings[{location[1] + 1}] has missing or unknown fields"]
        )
    return EvidenceGovernanceError([f"{path}: policy model validation failed"])


def _validated_strings(value: list[str], *, context: str) -> tuple[str, ...]:
    if not all(value):
        raise EvidenceGovernanceError([f"{context} must contain non-empty strings"])
    values = tuple(value)
    if len(values) != len(set(values)):
        raise EvidenceGovernanceError([f"{context} must contain unique values"])
    return values


def _repository_relative_path(value: str, *, context: str) -> Path:
    if not value:
        raise EvidenceGovernanceError([f"{context} must be a repository-relative path"])
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise EvidenceGovernanceError([f"{context} must stay inside the repository"])
    return path


def _load_policy(path: Path) -> EvidencePolicy:
    """Load and validate the authoritative evidence policy."""
    try:
        parsed_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise EvidenceGovernanceError([f"{path}: invalid TOML: {error}"]) from error
    try:
        input_model = (
            _EvidencePolicyV2Input
            if isinstance(parsed_document, dict) and parsed_document.get("schema_version") == 2
            else _EvidencePolicyInput
        )
        policy_document = input_model.model_validate(parsed_document)
    except ValidationError as error:
        raise _policy_input_error(path, error) from error

    for key, expected in _EXPECTED_SCALARS.items():
        if getattr(policy_document, key) != expected:
            raise EvidenceGovernanceError([f"{path}: {key} must be {expected!r}"])
    if policy_document.schema_version not in {1, 2}:
        raise EvidenceGovernanceError([f"{path}: schema_version must be 1 or 2"])

    applicable_gates = _validated_strings(
        policy_document.applicable_gates, context="applicable_gates"
    )
    mandatory_gates = _validated_strings(
        policy_document.mandatory_package_gates, context="mandatory_package_gates"
    )
    if any(_GATE.fullmatch(gate) is None for gate in applicable_gates + mandatory_gates):
        raise EvidenceGovernanceError([f"{path}: quality gates must use QG01-QG15"])
    if set(mandatory_gates) != {"QG01", "QG13", "QG15"}:
        raise EvidenceGovernanceError([f"{path}: A05 requires QG01, QG13, and QG15"])
    if not set(mandatory_gates) <= set(applicable_gates):
        raise EvidenceGovernanceError([f"{path}: mandatory gates must be applicable"])

    fields: list[MrField] = []
    for index, item in enumerate(policy_document.mr_fields, 1):
        if _FIELD_KEY.fullmatch(item.key) is None:
            raise EvidenceGovernanceError([f"mr_fields[{index}].key must be lower_snake_case"])
        if not item.heading.strip():
            raise EvidenceGovernanceError([f"mr_fields[{index}].heading must not be empty"])
        fields.append(MrField(key=item.key, heading=item.heading))
    if not fields:
        raise EvidenceGovernanceError([f"{path}: mr_fields must not be empty"])
    if len({field.key for field in fields}) != len(fields):
        raise EvidenceGovernanceError([f"{path}: MR field keys must be unique"])
    if len({field.heading for field in fields}) != len(fields):
        raise EvidenceGovernanceError([f"{path}: MR field headings must be unique"])

    institutional_fields: tuple[MrField, ...] = ()
    conditional_fields: tuple[ConditionalMrField, ...] = ()
    founder_example_path: Path | None = None
    if isinstance(policy_document, _EvidencePolicyV2Input):
        if tuple(field.key for field in fields) != (
            "problem_change",
            "affected_scope",
            "validation_result",
            "risks_reversal",
        ):
            raise EvidenceGovernanceError(["version-2 policy requires the four founder fields"])
        institutional_fields = tuple(
            MrField(key=field.key, heading=field.heading)
            for field in policy_document.institutional_mr_fields
        )
        conditional_fields = tuple(
            ConditionalMrField.model_validate(field.model_dump())
            for field in policy_document.conditional_mr_fields
        )
        if {field.trigger for field in conditional_fields} != {
            "migration",
            "benchmark",
            "operational",
        } or len(conditional_fields) != 3:
            raise EvidenceGovernanceError(["conditional fields require each impact trigger once"])
        for group in (institutional_fields, (*fields, *conditional_fields)):
            if (
                not group
                or len({field.key for field in group}) != len(group)
                or len({field.heading for field in group}) != len(group)
                or any(
                    not field.heading.strip() or not _FIELD_KEY.fullmatch(field.key)
                    for field in group
                )
            ):
                raise EvidenceGovernanceError(["MR fields require unique, non-empty keys/headings"])
        founder_example_path = _repository_relative_path(
            policy_document.founder_example_mr_body_path, context="founder_example_mr_body_path"
        )

    finding_ids: list[str] = []
    for index, finding in enumerate(policy_document.findings, 1):
        if not all(
            (
                finding.closure_condition,
                finding.finding_id,
                finding.owner_role,
                finding.unavailable_evidence,
            )
        ):
            raise EvidenceGovernanceError([f"findings[{index}] has missing or unknown fields"])
        finding_ids.append(finding.finding_id)
    if tuple(finding_ids) != _MERGE_EVIDENCE_OPEN_FINDING_IDS:
        raise EvidenceGovernanceError(
            [f"{path}: partial status requires findings {list(_MERGE_EVIDENCE_OPEN_FINDING_IDS)!r}"]
        )

    commit_sha = policy_document.example_commit_sha
    if _COMMIT_SHA.fullmatch(commit_sha) is None:
        raise EvidenceGovernanceError([f"{path}: example_commit_sha must be a full lowercase SHA"])
    return EvidencePolicy(
        template_path=_repository_relative_path(
            policy_document.template_path, context="template_path"
        ),
        example_mr_body_path=_repository_relative_path(
            policy_document.example_mr_body_path, context="example_mr_body_path"
        ),
        example_manifest_path=_repository_relative_path(
            policy_document.example_manifest_path, context="example_manifest_path"
        ),
        example_commit_sha=commit_sha,
        applicable_gates=applicable_gates,
        mandatory_package_gates=mandatory_gates,
        fields=tuple(fields),
        package_status="partial",
        finding_ids=tuple(finding_ids),
        schema_version=2 if isinstance(policy_document, _EvidencePolicyV2Input) else 1,
        institutional_fields=institutional_fields,
        conditional_fields=conditional_fields,
        founder_example_mr_body_path=founder_example_path,
    )


def load_policy(path: Path) -> EvidencePolicy:
    """Load evidence policy while preserving its public domain-error contract."""
    try:
        return _load_policy(path)
    except ValidationError as error:
        raise EvidenceGovernanceError([f"{path}: policy model validation failed"]) from error
