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
    """Capture the strict, closed change-facts table from a manifest.

    This boundary model checks required keys and Python value types only. It does not
    check that string values are non-empty, belong to the configured policy, or agree
    with a computed risk class; those semantic checks happen while the manifest is
    parsed. The inherited frozen model prevents attribute replacement, and this model
    has no mutable fields to expose through shallow freezing.

    Attributes:
        capital_at_risk: Whether the change can put capital at risk.
        blast_radius: Policy dimension describing the affected scope.
        data_model_materiality: Policy dimension describing data or model impact.
        security_privilege: Policy dimension describing privilege impact.
        reversibility: Policy dimension describing rollback or recovery constraints.
        computationally_material: Whether computational validation is relevant.
        economically_or_risk_relevant: Whether economic or risk validation is relevant.
        model_or_trading_relevant: Whether model or trading validation is relevant.
        declared_class: Requested risk class, recomputed and checked later.
    """

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
    """Capture one strict quality-gate table before semantic gate validation.

    All fields are required and unknown fields are rejected by ``ImmutableModel``.
    The list of evidence IDs is shallow-frozen only: the model cannot have its
    attribute reassigned, but the contained ``evidence_ids`` list remains mutable.
    ``_parse_gates`` copies it into an immutable tuple and applies the empty,
    uniqueness, identifier, status, and passed-gate rules.

    Attributes:
        gate_id: Quality-gate identifier supplied by the TOML document.
        status: Candidate gate disposition.
        rationale: Human-readable reason for the disposition.
        evidence_ids: Artifact IDs claimed to support the gate; an empty list is
            structurally valid and is checked against status later.
    """

    gate_id: str
    status: str
    rationale: str
    evidence_ids: list[str]


class _ArtifactInput(ImmutableModel):
    """Capture one strict artifact reference and its claimed digest.

    Construction enforces the closed four-field input shape and strict string
    types, but it does not inspect the filesystem or verify the digest. Semantic
    identifier and SHA-256 syntax checks belong to ``_parse_artifacts``; path
    containment and resolution belong to the later filesystem helpers.

    Attributes:
        evidence_id: Artifact key referenced by quality gates.
        artifact_type: Repository-defined category for the artifact.
        path: Candidate path relative to the manifest's bundle directory.
        sha256: Claimed lowercase SHA-256 digest of the artifact bytes.
    """

    evidence_id: str
    artifact_type: str
    path: str
    sha256: str


class _ApprovalInput(ImmutableModel):
    """Capture one strict approval claim before acceptance checks.

    The model is a closed structural boundary: it requires the listed fields and
    preserves exact strings, while leaving URL, role, status, and commit semantics
    to ``_parse_approvals``. Its ``roles`` list is only shallow-frozen; the parser
    turns it into a validated immutable role set. An empty evidence URL is accepted
    at this boundary so pending and rejected records can omit external evidence;
    approved records must later provide a credential-free HTTPS URL.

    Attributes:
        reviewer_id: Claimed reviewer identity.
        roles: Claimed reviewer roles in source order.
        independent: Whether the reviewer claims independent review.
        is_author: Whether the reviewer is the change author.
        status: Approval disposition: approved, pending, or rejected after parsing.
        commit_sha: Commit to which the review claim is bound.
        evidence_url: Optional-for-non-approved reference retained verbatim.
    """

    reviewer_id: str
    roles: list[str]
    independent: bool
    is_author: bool
    status: str
    commit_sha: str
    evidence_url: str


class _FindingInput(ImmutableModel):
    """Capture one strict unresolved-finding record from a manifest.

    The model guarantees four required string fields and rejects unknown fields;
    it does not enforce non-empty content, identifier syntax, role syntax, or the
    relationship to ``open_finding_ids``. ``_parse_findings`` performs those
    non-empty and duplicate checks and retains only the ordered finding IDs for
    the resulting manifest.

    Attributes:
        finding_id: Identifier of the unresolved finding.
        owner_role: Role accountable for closing the finding.
        unavailable_evidence: Evidence unavailable at the current assessment point.
        closure_condition: Evidence or action required to close the finding.
    """

    finding_id: str
    owner_role: str
    unavailable_evidence: str
    closure_condition: str


class _EvidenceManifestInput(ImmutableModel):
    """Define the closed structural shape for a version-one manifest.

    Every field is required and uses strict Python types; inherited configuration
    rejects unknown root keys and prevents attribute assignment. Collection fields
    remain ordinary lists inside the frozen model, so freezing is shallow until
    the parser copies them to tuples or sets. This model intentionally performs no
    filesystem I/O, risk recomputation, gate coverage check, approval evaluation,
    or semantic string validation.

    The loader selects this base shape for version-one documents and for roots whose
    schema discriminator does not compare equal to ``2``. Dispatch uses equality
    before strict validation, so a value such as ``2.0`` selects the implementation
    shape and is then rejected because the model requires an integer. Structural
    failures are translated before applying the semantic rules that follow model
    validation.

    Attributes:
        schema_version: Input schema discriminator; supported semantic versions are 1 and 2.
        bundle_id: Stable lower-kebab-case evidence-bundle identifier candidate.
        roadmap_id: Roadmap package identifier candidate.
        commit_sha: Source revision claimed by the bundle.
        owner_role: Accountable owner-role candidate.
        risk_class: Declared change-risk class candidate.
        evidence_retention_class: Declared retention-policy token candidate.
        bundle_status: Partial or accepted status candidate for version one.
        change: Strict change-risk facts table.
        additional_required_gates: Extra gate IDs requested by the bundle.
        gates: Raw quality-gate tables.
        artifacts: Raw artifact-reference tables.
        approvals: Raw approval-claim tables.
        findings: Raw unresolved-finding tables.
        open_finding_ids: IDs the bundle claims remain open.
        waived_controls: Control IDs the bundle claims to waive.
    """

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
    """Extend the version-one shape with local implementation acceptance claims.

    This subclass is selected when a dictionary root's ``schema_version`` compares
    equal to ``2``; strict model validation then accepts only an integer value. The
    added fields remain strict required strings at the input boundary. The manifest
    validator later requires implementation status, checks the founder and operating
    domain against the operating model, parses the date, and forbids institutional
    approvals and waivers.

    Attributes:
        operating_domain: Domain whose local completion rules apply.
        accepted_by: Principal claimed to have accepted implementation completion.
        accepted_on: ISO date text used to resolve the effective operating rules.
    """

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
    """Translate structural Pydantic errors into stable manifest diagnostics.

    The translation groups root shape errors, root scalar errors, root string-array
    errors, the nested change table, and arrays of nested tables into the public
    evidence error contract. Any top-level missing or unknown field takes precedence
    over the first detailed failure; otherwise the first detail drives the mapping.
    Root-key and schema-version wording is based on the base schema even when the
    selected implementation input produced the ``ValidationError``. This helper
    translates structural input failures only; later semantic validation errors
    are produced directly by the parser.

    Args:
        path: Manifest path used to identify root-level diagnostics.
        error: Validation failure raised by the selected strict input model.

    Returns:
        An ``EvidenceGovernanceError`` containing the contract's stable message.
    """
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
    """Validate and immutably copy a list of manifest strings.

    Validation rejects empty-string members, rejects an empty collection unless
    ``allow_empty`` is true, and rejects exact duplicate values. It does not strip,
    case-fold, normalize, or otherwise rewrite strings: surrounding whitespace is
    therefore preserved and a whitespace-only string is non-empty. The returned
    tuple is detached from the caller's mutable list.

    Args:
        value: Already type-checked string list from an input model.
        context: Field label used in the domain error message.
        allow_empty: Permit zero members while still rejecting empty-string members
            and duplicate non-empty values.

    Returns:
        Values in their original order as a tuple.

    Raises:
        EvidenceGovernanceError: A member is empty, the collection is disallowedly
            empty, or exact values repeat.
    """
    if not all(value):
        raise EvidenceGovernanceError([f"{context} must be an array of non-empty strings"])
    values = tuple(value)
    if not allow_empty and not values:
        raise EvidenceGovernanceError([f"{context} must not be empty"])
    if len(values) != len(set(values)):
        raise EvidenceGovernanceError([f"{context} must contain unique values"])
    return values


def _validated_string(value: str, *, context: str) -> str:
    """Require one non-empty manifest string without normalizing it.

    The check distinguishes an empty string from whitespace: ``"   "`` is retained
    because it is truthy, while ``""`` is rejected. Lexical patterns and policy
    membership are deliberately left to the caller that owns that field's rules.

    Args:
        value: Already type-checked candidate string.
        context: Field label used in the domain error message.

    Returns:
        The exact input string, including its original whitespace.

    Raises:
        EvidenceGovernanceError: ``value`` is the empty string.
    """
    if not value:
        raise EvidenceGovernanceError([f"{context} must be a non-empty string"])
    return value


def _parse_change(value: _ChangeInput) -> ChangeRiskInput:
    """Convert strict change facts into the change-risk domain input.

    Each textual dimension and the declared class must be non-empty, while boolean
    trigger facts pass through unchanged. The declared class is converted from its
    string representation to ``RiskClass``; this helper does not classify the
    dimensions or compare the declaration with a policy. The caller performs that
    recomputation after conversion.

    Args:
        value: Structurally validated change table from the manifest boundary model.

    Returns:
        A ``ChangeRiskInput`` with the same facts and an enum-valued declaration.

    Raises:
        EvidenceGovernanceError: A textual field is empty or the declaration is
            outside the supported R0-R4 classes. The enum conversion error is
            translated and retained as its cause.
    """
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
    """Parse gate tables and enforce their local evidence relationships.

    Items are processed in source order. Each gate requires non-empty ID, status,
    and rationale strings; evidence IDs may be an empty collection, but passed
    gates must name at least one. IDs must match QG01-QG15, statuses must be one of
    deferred, failed, not_applicable, or passed, and gate IDs must be unique across
    the complete list. Evidence references are only checked for non-empty unique
    strings here; existence in the artifact set is checked by the manifest loader.

    Args:
        value: Structurally validated gate tables from the input model.

    Returns:
        Gate records in manifest order, with evidence IDs detached as tuples.

    Raises:
        EvidenceGovernanceError: A field is empty, a gate or status is unsupported,
            a passed gate has no evidence, an evidence ID repeats within a gate, or
            a gate ID repeats across gates. Field and item errors are reported as
            encountered before the final duplicate-ID check.
    """
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
    """Parse artifact claims and enforce local identifier and digest rules.

    Each record's four strings must be non-empty. Evidence IDs use lower-kebab-case,
    artifact types use lower_snake_case, and digests use exactly 64 lowercase
    hexadecimal characters. Artifact IDs and path strings must be unique across
    the complete list. This function does not resolve paths, reject traversal or
    symlinks, read bytes, or compare digests; those checks belong to the filesystem
    helpers invoked later.

    Args:
        value: Structurally validated artifact tables from the input model.

    Returns:
        Artifact records in source order, retaining exact path text and digest text.

    Raises:
        EvidenceGovernanceError: A field is empty, a lexical identifier or digest is
            invalid, or an artifact ID or path repeats. Filesystem errors are not
            raised by this parser because it performs no filesystem access.
    """
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
    """Parse approval claims and enforce status, role, URL, and commit bindings.

    Records are processed in source order. Status must be approved, pending, or
    rejected, and every approval's commit must exactly equal the bundle commit.
    Approved records additionally require a parseable HTTPS URL with a hostname and
    no username or password; pending and rejected records may retain an empty URL.
    Roles must be a non-empty, duplicate-free list of lower_snake_case strings.
    Reviewer IDs must be non-empty but are not required to be unique here because
    the change-risk approval evaluator owns distinct-reviewer counting.

    This parser does not decide whether approval claims satisfy a risk class, whether
    a reviewer is independent, or whether an author may approve. It also preserves
    exact text and does not validate a standalone SHA pattern for ``commit_sha``;
    the enclosing manifest's expected commit binding supplies that constraint. URL
    queries, fragments, and ports are accepted when the URL parser accepts them;
    only the HTTPS, hostname, and credential conditions above are enforced.

    Args:
        value: Structurally validated approval tables from the input model.
        commit_sha: Commit identity that every claim must name exactly.

    Returns:
        Approval records in source order, with roles converted to immutable sets.

    Raises:
        EvidenceGovernanceError: A status, commit, role, reviewer ID, or approved
            URL violates the rules. URL parser ``ValueError`` failures are translated
            to the same domain error with their cause preserved; helper validation
            errors propagate in their original order.
    """
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
    """Validate finding records and retain their ordered identifiers.

    Every record's four strings must be non-empty, but this helper intentionally
    does not enforce finding-ID syntax, owner-role syntax, or package membership.
    IDs must be unique across the complete list. Descriptions are validated for
    presence and then discarded because the returned manifest tracks only IDs;
    package-specific callers may apply additional checks to the source records.

    Args:
        value: Structurally validated finding tables from the input model.

    Returns:
        Finding IDs in their original manifest order.

    Raises:
        EvidenceGovernanceError: A required string is empty or a finding ID repeats.
    """
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
    """Resolve one artifact path while enforcing bundle containment.

    The check is lexical before resolution: absolute paths and any ``..`` component
    are rejected. Every path component, including the final one, is checked for a
    symlink before strict resolution. Resolution then requires the target to exist
    and verifies that its resolved path remains relative to ``bundle_root``; the
    target must be a regular file. The returned path is the resolved path used for
    reading and hashing.

    These checks protect the intended bundle boundary but do not provide an atomic
    filesystem snapshot. A path can be replaced between metadata checks and a later
    read, and callers needing stronger guarantees must supply external coordination.
    The helper also assumes the supplied root is already the intended resolved
    bundle root; ``_verify_artifacts`` establishes that root from the manifest path.

    Args:
        bundle_root: Resolved directory that bounds permissible artifacts.
        relative_text: Exact manifest path text, expected to be relative to the root.

    Returns:
        Existing regular file path after strict resolution.

    Raises:
        EvidenceGovernanceError: The text is absolute or traverses parents, a
            component is a symlink, the target is missing or resolves outside the
            root, or the target is not a file. Missing-target and containment
            ``ValueError``/``FileNotFoundError`` failures retain their causes.
        OSError: A filesystem operation fails for a reason other than missing path
            or containment validation, such as permission denial.
        RuntimeError: Path resolution encounters a symlink loop that is not rejected
            by the component checks.
    """
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
    """Read each declared artifact and compare its SHA-256 digest.

    The manifest's parent directory is resolved as the bundle root, then artifacts
    are resolved and read in tuple order. Path safety is delegated to
    ``_resolve_artifact_path`` and digest mismatches identify both the evidence ID
    and source path. An empty file is valid when its claimed digest matches.

    Verification reads ordinary filesystem bytes and therefore is not an atomic
    snapshot: a file may change after resolution or while it is being read. The
    function does not retry, lock, or retain bytes, and it does not catch unrelated
    filesystem I/O failures.

    Args:
        path: Manifest path whose parent directory contains the bundle.
        artifacts: Parsed artifact claims with validated lowercase SHA-256 values.

    Raises:
        EvidenceGovernanceError: An artifact path violates containment/file rules or
            the bytes' digest differs from the claim.
        OSError: Resolving the bundle root, inspecting metadata, or reading an
            artifact fails for an unrelated filesystem reason.
        RuntimeError: Path resolution encounters a symlink loop that is not rejected
            by the component checks.
    """
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
    """Validate a SHA-bound evidence manifest and return its typed contents.

    The validator first requires a full lowercase 40- or 64-character
    ``expected_commit_sha``, rejects a symlink at the manifest path, reads UTF-8
    TOML, and selects the strict legacy schema (version 1) or implementation
    schema (version 2). It then validates root identities, binds the manifest
    commit exactly to ``expected_commit_sha``, recomputes change risk with
    ``change_policy``, parses gates, artifacts, approvals and findings, checks
    required-gate and evidence-reference relationships, and reads each declared
    artifact to verify its SHA-256 digest. Artifact paths must be relative,
    remain within the resolved manifest-parent bundle root, and must not traverse
    symlink components appended below that root; reads are ordinary, non-atomic
    filesystem operations.

    Version 1 accepts ``partial`` or ``accepted`` bundles. A partial bundle must
    retain an open finding; an accepted bundle must have complete required gates,
    no open findings, approved reviews, and pass merge-approval validation.
    Version 2 is for local implementation acceptance: it requires
    ``implementation_accepted``, an ``operating_model``, the recorded founder,
    no institutional approvals or waivers, and ``operation="implementation"``.
    Its accepted date resolves the operating rules, and every failed or deferred
    gate, including optional ones, or technical finding prevents local completion.
    The ``operating_model`` and ``operation`` arguments do not affect version 1;
    ``operation`` defaults to ``"implementation"``.

    Args:
        path: UTF-8 TOML manifest whose parent directory contains the declared
            evidence bundle and artifacts.
        expected_commit_sha: Full lowercase hexadecimal source commit, 40 or 64
            characters, that the manifest must name exactly.
        change_policy: Validated change-risk policy used to recompute the manifest
            classification and to validate accepted-bundle approvals.
        operating_model: Operating model used only for version-2 implementation
            acceptance; required for that schema and otherwise ignored.
        operation: Requested operating scope. It defaults to ``"implementation"``;
            version-2 manifests reject every other operation, while version 1 does
            not use this argument.

    Returns:
        A validated immutable ``EvidenceManifest`` with parsed gates, artifact
        claims, approvals, ordered open-finding IDs, change classification, and
        any version-2 implementation-acceptance fields.

    Raises:
        EvidenceGovernanceError: If the expected commit, manifest symlink rule,
            TOML syntax, schema shape, field contents, risk or retention binding,
            gate/evidence relationship, artifact path or digest, waiver rule,
            partial or accepted status, or version-2 implementation-completion
            requirement fails. TOML decoding, structural Pydantic validation, and
            any remaining final-model Pydantic validation are translated and their
            causes are chained; any Pydantic validation error not already translated
            by the parser is translated by this wrapper, and helper ``ValueError``
            failures for classification, URL parsing, operating-model resolution,
            and merge approvals are also translated and chained.
        OSError: If manifest or artifact path inspection, resolution, reading, or
            digest input operations fail outside translated missing/containment
            checks.
        UnicodeDecodeError: If the manifest TOML is not valid UTF-8.
        RuntimeError: If manifest-parent or artifact path resolution encounters a
            symlink loop not rejected by the component checks.
    """
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
