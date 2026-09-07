"""Parse the merge-request and evidence policy strictly."""

from __future__ import annotations

# standard library imports
import re
import tomllib
from pathlib import Path
from typing import TypedDict, cast

# third party library imports
from pydantic import TypeAdapter, ValidationError

# project library imports
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


class _PolicyValidationErrorDetail(TypedDict):
    """Capture the Pydantic error fields consumed by policy diagnostics."""

    loc: tuple[int | str, ...]
    type: str


_POLICY_VALIDATION_ERROR_DETAILS = TypeAdapter(list[_PolicyValidationErrorDetail])


class _MrFieldInput(ImmutableModel):
    """Capture one strict merge-request field from the TOML input.

    The inherited immutable boundary requires exactly two string fields, forbids unknown
    fields, and provides no defaults. The loader checks lower-snake-case keys, nonblank
    headings, and uniqueness after construction.

    Attributes:
        key: Machine-readable field key as supplied by the policy.
        heading: Markdown heading associated with the field.
    """

    key: str
    heading: str


class _FindingInput(ImmutableModel):
    """Capture one strict unresolved-finding record from the TOML input.

    All four string fields are required, strict, and closed to extra keys; none has a
    default. The loader separately requires truthy values and the exact ordered A05 finding
    identifiers before retaining only those identifiers in ``EvidencePolicy``.

    Attributes:
        finding_id: Identifier of the unresolved evidence-governance finding.
        owner_role: Role accountable for closing the finding.
        unavailable_evidence: Evidence unavailable during the governed assessment.
        closure_condition: Evidence or action required to close the finding.
    """

    finding_id: str
    owner_role: str
    unavailable_evidence: str
    closure_condition: str


class _EvidencePolicyInput(ImmutableModel):
    """Define the closed base shape accepted for evidence-policy TOML.

    Every declared field is required and uses strict types; the inherited boundary rejects
    unknown root fields and supplies no input defaults. This base shape is used for the
    version-one policy and whenever the parsed ``schema_version`` does not compare equal to
    ``2``. The loader applies exact scalar values, gate rules, path syntax, field/finding
    semantics, and supported-version checks after model validation.

    Attributes:
        schema_version: Input version discriminator; semantic support is limited to 1 or 2.
        roadmap_package: Expected roadmap package identifier, checked by the loader.
        operating_track: Expected operating track, checked by the loader.
        package_status: Expected package status, checked by the loader.
        accountable_owner_role: Expected accountable role, checked by the loader.
        risk_class: Expected evidence-policy risk class, checked by the loader.
        applicable_gates: Ordered quality-gate identifiers admitted by the package.
        mandatory_package_gates: Ordered quality-gate identifiers required by the package.
        template_path: Merge-request template path string.
        example_mr_body_path: Institutional example body path string.
        example_manifest_path: Example evidence manifest path string.
        example_commit_sha: Expected example-manifest commit identity.
        mr_fields: Ordered default merge-request field records.
        findings: Ordered unresolved-finding records.
    """

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
    """Capture one strict impact-triggered merge-request field.

    ``key`` and ``heading`` retain the base input shape; required ``trigger`` has no
    default. The loader accepts exactly one each of ``migration``, ``benchmark`` and
    ``operational`` and validates combined key/heading uniqueness with the default fields.

    Attributes:
        trigger: Impact category that activates this conditional field.
    """

    trigger: str


class _EvidencePolicyV2Input(_EvidencePolicyInput):
    """Extend the base policy shape with version-two MR profiles.

    The three added fields are required strict collections or strings with no defaults, and
    this model is selected only when the parsed root has ``schema_version == 2``. The
    loader requires four ordered founder fields, validates institutional and conditional
    groups independently, and applies lexical validation to the founder example path.

    Attributes:
        institutional_mr_fields: Ordered fields retained for institutional MR bodies.
        conditional_mr_fields: Ordered impact-triggered fields for founder MR bodies.
        founder_example_mr_body_path: Repository-relative founder example path string.
    """

    institutional_mr_fields: list[_MrFieldInput]
    conditional_mr_fields: list[_ConditionalMrFieldInput]
    founder_example_mr_body_path: str


_EXPECTED_ROOT_KEYS = frozenset(_EvidencePolicyInput.model_fields)


def _policy_input_error(path: Path, error: ValidationError) -> EvidenceGovernanceError:
    """Translate the first strict input-model error into a stable domain finding.

    The mapping handles root shape/scalar errors, gate and path fields, and indexed MR-field
    or finding tables; unrecognized locations use a generic policy-model message. It reads
    only the first Pydantic error detail. Root missing/extra-field diagnostics use the
    version-one ``_EXPECTED_ROOT_KEYS`` set even when a version-two model produced the error.

    Args:
        path: Policy path included in root-level diagnostic messages.
        error: Pydantic validation failure from an input model.

    Returns:
        An ``EvidenceGovernanceError`` containing the selected domain-level finding.
    """
    raw_details: object = error.errors(include_url=False, include_input=False)
    details = _POLICY_VALIDATION_ERROR_DETAILS.validate_python(raw_details, strict=True)
    detail = details[0]
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
    """Check string-list entries for emptiness and duplicates while preserving order.

    This helper expects the strict list already produced by an input model. An empty list
    passes here because ``all([])`` is true; the caller applies any required cardinality or
    exact-set rule. Whitespace-only strings are also accepted because only empty strings
    are rejected.

    Args:
        value: Strictly typed list of policy strings.
        context: Field label included in a domain error.

    Returns:
        A tuple containing the original values in input order.

    Raises:
        EvidenceGovernanceError: If an entry is empty or a value appears more than once.
    """
    if not all(value):
        raise EvidenceGovernanceError([f"{context} must contain non-empty strings"])
    values = tuple(value)
    if len(values) != len(set(values)):
        raise EvidenceGovernanceError([f"{context} must contain unique values"])
    return values


def _repository_relative_path(value: str, *, context: str) -> Path:
    """Convert a policy path after lexical relative-path checks.

    The host ``Path`` constructor determines normalization of repeated separators and
    ``.`` components. Absolute paths and explicit ``..`` components are rejected; ``.``
    itself is allowed. This helper does not resolve symlinks, check repository containment,
    or test that the resulting path exists.

    Args:
        value: Non-empty path string from the policy.
        context: Field label included in a domain error.

    Returns:
        A host ``Path`` constructed from the accepted string.

    Raises:
        EvidenceGovernanceError: If ``value`` is empty, absolute, or contains ``..``.
    """
    if not value:
        raise EvidenceGovernanceError([f"{context} must be a repository-relative path"])
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise EvidenceGovernanceError([f"{context} must stay inside the repository"])
    return path


class _EvidencePolicyLoader:
    """Load and project one evidence-policy TOML path into immutable policy data."""

    def __init__(self, path: Path) -> None:
        """Bind the policy path without performing I/O."""
        self._path = path

    def _load(self) -> EvidencePolicy:
        """Parse, semantically validate, and project the authoritative evidence policy.

        The TOML is read as UTF-8. A root whose parsed ``schema_version`` compares equal to
        ``2`` selects the version-two input model; every other parsed root selects the base
        model, after which strict field validation and the loader admit only integer versions 1
        and 2. Input models require all declared fields, use strict types, and reject unknown
        fields. The loader then requires the A05
        scalar contract, valid QG01-QG15 gates, mandatory gates ``QG01``, ``QG13`` and ``QG15``,
        unique ordered MR fields, and the ordered findings ``A05-F01``, ``A05-F02``. Version 2
        additionally requires the four founder fields in order, one each of the three impact
        triggers, independently unique institutional and founder/conditional field groups, and
        a lexically relative founder-example path.

        Lists retain input order when projected into tuples. The output normalizes paths to host
        ``Path`` values and keeps only finding identifiers; it verifies and discards the input
        roadmap, track, status, owner, risk, and finding-detail fields, then sets
        ``package_status`` to ``"partial"``. Version-one output uses empty institutional and
        conditional tuples and ``None`` for the founder path. Paths are not resolved or checked
        for existence here; repository callers perform those checks.

        Returns:
            The normalized immutable ``EvidencePolicy`` with ordered gates, fields, findings,
            and version-specific MR profiles.

        Raises:
            EvidenceGovernanceError: If TOML syntax, input shape, scalar contract, gate set,
                path syntax, field/finding semantics, or version-specific rules fail. TOML and
                initial input-model failures are translated here with their causes.
            ValidationError: If later conditional-field or output-model construction fails;
                the public ``load_policy`` wrapper translates this failure.
            OSError: If the file cannot be read; the read error propagates.
            UnicodeDecodeError: If the file is not valid UTF-8; the decoding error propagates.
        """
        path = self._path
        try:
            parsed_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            raise EvidenceGovernanceError([f"{path}: invalid TOML: {error}"]) from error
        try:
            parsed_table = (
                cast(dict[str, object], parsed_document)
                if isinstance(parsed_document, dict)
                else {}
            )
            input_model = (
                _EvidencePolicyV2Input
                if parsed_table.get("schema_version") == 2
                else _EvidencePolicyInput
            )
            policy_document = input_model.model_validate(parsed_document)
        except ValidationError as error:
            raise _policy_input_error(path, error) from error

        actual_scalars: dict[str, object] = {
            "roadmap_package": policy_document.roadmap_package,
            "operating_track": policy_document.operating_track,
            "package_status": policy_document.package_status,
            "accountable_owner_role": policy_document.accountable_owner_role,
            "risk_class": policy_document.risk_class,
        }
        for key, expected in _EXPECTED_SCALARS.items():
            if actual_scalars[key] != expected:
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
            conditional_field_values: list[ConditionalMrField] = []
            for field in policy_document.conditional_mr_fields:
                conditional_input: dict[str, str] = {
                    "key": field.key,
                    "heading": field.heading,
                    "trigger": field.trigger,
                }
                conditional_field_values.append(
                    ConditionalMrField.model_validate(conditional_input)
                )
            conditional_fields = tuple(conditional_field_values)
            if {field.trigger for field in conditional_fields} != {
                "migration",
                "benchmark",
                "operational",
            } or len(conditional_fields) != 3:
                raise EvidenceGovernanceError(
                    ["conditional fields require each impact trigger once"]
                )
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
                    raise EvidenceGovernanceError(
                        ["MR fields require unique, non-empty keys/headings"]
                    )
            founder_example_path = _repository_relative_path(
                policy_document.founder_example_mr_body_path,
                context="founder_example_mr_body_path",
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
                [
                    f"{path}: partial status requires findings "
                    f"{list(_MERGE_EVIDENCE_OPEN_FINDING_IDS)!r}"
                ]
            )

        commit_sha = policy_document.example_commit_sha
        if _COMMIT_SHA.fullmatch(commit_sha) is None:
            raise EvidenceGovernanceError(
                [f"{path}: example_commit_sha must be a full lowercase SHA"]
            )
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
    """Load evidence policy while preserving its public domain-error contract.

    Delegates parsing and semantic checks to the policy loader service. Domain findings raised there
    retain their order and propagate unchanged; Pydantic failures from later projection
    stages are translated to one ``EvidenceGovernanceError`` with the original cause.
    Version-one output carries empty version-two field groups and no founder path, while
    version-two output retains its ordered institutional and conditional groups.

    Args:
        path: Evidence-policy TOML file to read as UTF-8.

    Returns:
        The normalized immutable policy returned by the policy loader service.

    Raises:
        EvidenceGovernanceError: If policy parsing or semantic validation fails, or if a
            later Pydantic projection failure is translated by this public boundary.
        OSError: If reading ``path`` fails; file-system errors propagate.
        UnicodeDecodeError: If ``path`` is not valid UTF-8; the decoding error propagates.
    """
    try:
        return _EvidencePolicyLoader(path)._load()
    except ValidationError as error:
        raise EvidenceGovernanceError([f"{path}: policy model validation failed"]) from error
