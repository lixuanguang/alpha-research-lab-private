"""Parse the merge-request and evidence policy strictly."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from alpha_research_governance.evidence.models import (
    EvidenceGovernanceError,
    EvidencePolicy,
    MrField,
)

_GATE = re.compile(r"^QG(?:0[1-9]|1[0-5])$")
_FIELD_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_COMMIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_MERGE_EVIDENCE_OPEN_FINDING_IDS = ("A05-F01", "A05-F02")
_EXPECTED_ROOT_KEYS = {
    "accountable_owner_role",
    "applicable_gates",
    "example_commit_sha",
    "example_manifest_path",
    "example_mr_body_path",
    "findings",
    "mandatory_package_gates",
    "mr_fields",
    "operating_track",
    "package_status",
    "risk_class",
    "roadmap_package",
    "schema_version",
    "template_path",
}


def _require_table_list(value: object, *, context: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise EvidenceGovernanceError([f"{context} must be an array of TOML tables"])
    return cast(list[dict[str, object]], value)


def _require_strings(value: object, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise EvidenceGovernanceError([f"{context} must contain non-empty strings"])
    values = tuple(cast(list[str], value))
    if len(values) != len(set(values)):
        raise EvidenceGovernanceError([f"{context} must contain unique values"])
    return values


def _require_relative_path(value: object, *, context: str) -> Path:
    if not isinstance(value, str) or not value:
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
    if not isinstance(parsed_document, dict):
        raise EvidenceGovernanceError([f"{path}: policy root must be a TOML table"])
    policy_document = cast(dict[str, object], parsed_document)
    if set(policy_document) != _EXPECTED_ROOT_KEYS:
        raise EvidenceGovernanceError(
            [f"{path}: fields must be exactly {sorted(_EXPECTED_ROOT_KEYS)!r}"]
        )

    expected_scalars: dict[str, object] = {
        "schema_version": 1,
        "roadmap_package": "A05",
        "operating_track": "solo_bootstrap",
        "package_status": "partial",
        "accountable_owner_role": "platform",
        "risk_class": "R0",
    }
    for key, expected in expected_scalars.items():
        if policy_document.get(key) != expected:
            raise EvidenceGovernanceError([f"{path}: {key} must be {expected!r}"])

    applicable_gates = _require_strings(
        policy_document.get("applicable_gates"), context="applicable_gates"
    )
    mandatory_gates = _require_strings(
        policy_document.get("mandatory_package_gates"), context="mandatory_package_gates"
    )
    if any(_GATE.fullmatch(gate) is None for gate in applicable_gates + mandatory_gates):
        raise EvidenceGovernanceError([f"{path}: quality gates must use QG01-QG15"])
    if set(mandatory_gates) != {"QG01", "QG13", "QG15"}:
        raise EvidenceGovernanceError([f"{path}: A05 requires QG01, QG13, and QG15"])
    if not set(mandatory_gates) <= set(applicable_gates):
        raise EvidenceGovernanceError([f"{path}: mandatory gates must be applicable"])

    fields: list[MrField] = []
    for index, item in enumerate(
        _require_table_list(policy_document.get("mr_fields"), context="mr_fields"), 1
    ):
        if set(item) != {"heading", "key"}:
            raise EvidenceGovernanceError([f"mr_fields[{index}] must contain key and heading"])
        field_key = item.get("key")
        heading = item.get("heading")
        if not isinstance(field_key, str) or _FIELD_KEY.fullmatch(field_key) is None:
            raise EvidenceGovernanceError([f"mr_fields[{index}].key must be lower_snake_case"])
        if not isinstance(heading, str) or not heading.strip():
            raise EvidenceGovernanceError([f"mr_fields[{index}].heading must not be empty"])
        fields.append(MrField(key=field_key, heading=heading))
    if not fields:
        raise EvidenceGovernanceError([f"{path}: mr_fields must not be empty"])
    if len({field.key for field in fields}) != len(fields):
        raise EvidenceGovernanceError([f"{path}: MR field keys must be unique"])
    if len({field.heading for field in fields}) != len(fields):
        raise EvidenceGovernanceError([f"{path}: MR field headings must be unique"])

    findings = _require_table_list(policy_document.get("findings"), context="findings")
    finding_ids: list[str] = []
    for index, finding in enumerate(findings, 1):
        expected = {"closure_condition", "finding_id", "owner_role", "unavailable_evidence"}
        if set(finding) != expected or any(
            not isinstance(finding.get(key), str) or not finding.get(key) for key in expected
        ):
            raise EvidenceGovernanceError([f"findings[{index}] has missing or unknown fields"])
        finding_ids.append(cast(str, finding["finding_id"]))
    if tuple(finding_ids) != _MERGE_EVIDENCE_OPEN_FINDING_IDS:
        raise EvidenceGovernanceError(
            [f"{path}: partial status requires findings {list(_MERGE_EVIDENCE_OPEN_FINDING_IDS)!r}"]
        )

    commit_sha = policy_document.get("example_commit_sha")
    if not isinstance(commit_sha, str) or _COMMIT_SHA.fullmatch(commit_sha) is None:
        raise EvidenceGovernanceError([f"{path}: example_commit_sha must be a full lowercase SHA"])
    return EvidencePolicy(
        template_path=_require_relative_path(
            policy_document.get("template_path"), context="template_path"
        ),
        example_mr_body_path=_require_relative_path(
            policy_document.get("example_mr_body_path"), context="example_mr_body_path"
        ),
        example_manifest_path=_require_relative_path(
            policy_document.get("example_manifest_path"), context="example_manifest_path"
        ),
        example_commit_sha=commit_sha,
        applicable_gates=applicable_gates,
        mandatory_package_gates=mandatory_gates,
        fields=tuple(fields),
        package_status="partial",
        finding_ids=tuple(finding_ids),
    )


def load_policy(path: Path) -> EvidencePolicy:
    """Load evidence policy while preserving its public domain-error contract."""
    try:
        return _load_policy(path)
    except ValidationError as error:
        raise EvidenceGovernanceError([f"{path}: policy model validation failed"]) from error
