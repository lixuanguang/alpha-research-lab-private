"""Load and enforce the B08 artifact supply-chain policy."""

from __future__ import annotations

# standard library imports
import hashlib
import re
import tomllib
from datetime import date
from pathlib import Path, PurePosixPath
from typing import cast

# project library imports
from alpha_research_governance.artifact_supply_chain.models import (
    ArtifactSupplyChainError,
    ArtifactSupplyChainPolicy,
    ArtifactTool,
    LockIdentity,
)
from alpha_research_governance.change_risk import ChangeRiskInput, RiskClass
from alpha_research_governance.change_risk import load_policy as load_change_risk_policy
from alpha_research_governance.evidence import (
    EvidenceGovernanceError,
    PackageEvidenceProfile,
    PackageGateRequirement,
    validate_manifest,
    validate_package_evidence,
)

_ARTIFACT_SUPPLY_CHAIN_PACKAGE_ID = "B08"
_CANONICAL_INSTRUMENT_IDENTITY_SUCCESSOR_PACKAGE_ID = "C01"
_ARTIFACT_SUPPLY_CHAIN_GATE_IDS = (
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
    "QG15",
)
_ARTIFACT_SUPPLY_CHAIN_OPEN_FINDING_IDS = ("B08-F01", "B08-F02", "B08-F03")
_SUPPORTED_ARTIFACT_KINDS = ("binary", "configuration_bundle", "container", "model")
_NATIVE_LIBRARY_FILENAME_MARKERS = (".dll", ".dylib", ".so", ".so.")
_LOWERCASE_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_TOOL_COMMAND_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
_POLICY_ROOT_KEYS = {
    "accountable_owner_role",
    "applicable_gate_ids",
    "as_of_date",
    "findings",
    "formats",
    "identity",
    "limits",
    "local_evidence_commit_sha",
    "local_evidence_manifest_path",
    "locks",
    "open_finding_ids",
    "operating_track",
    "package_status",
    "review_due_on",
    "risk_class",
    "roadmap_package",
    "schema_version",
    "signing",
    "successor_package",
    "supported_artifact_kinds",
    "native_library_markers",
    "toolchain",
    "tools",
}
_POLICY_TABLE_KEYS = {
    "formats": {"provenance_predicate_type", "spdx_version", "statement_type"},
    "identity": {"build_type", "builder_id", "source_repository"},
    "limits": {"maximum_archive_members", "maximum_artifact_bytes"},
    "signing": {
        "oidc_issuer",
        "required_environment",
        "revoked_signer_identities",
        "signer_identity",
        "trusted_context",
    },
    "toolchain": {"path", "sha256"},
}
_POLICY_FINDING_KEYS = {
    "closure_condition",
    "finding_id",
    "owner_role",
    "unavailable_evidence",
}
_POLICY_LOCK_KEYS = {"path", "sha256"}
_POLICY_TOOL_KEYS = {"command", "version"}
_ARTIFACT_SUPPLY_CHAIN_EVIDENCE_PROFILE = PackageEvidenceProfile(
    roadmap_package_id=_ARTIFACT_SUPPLY_CHAIN_PACKAGE_ID,
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
        for gate_id in _ARTIFACT_SUPPLY_CHAIN_GATE_IDS
    ),
    expected_package_status="partial",
    expected_finding_ids=_ARTIFACT_SUPPLY_CHAIN_OPEN_FINDING_IDS,
    approvals_permitted=False,
    waivers_permitted=False,
    additional_required_gates_permitted=True,
)


def compute_regular_file_sha256(file_path: Path) -> str:
    """Hash the bytes read from a final path component admitted as a regular file.

    The final component is checked with ``is_symlink()`` and ``is_file()`` before
    opening it. This is a non-atomic filesystem admission check: parent-directory
    symlinks are followed, and a concurrent replacement can occur between the
    check and the read. The function does not constrain the path to the repository.

    Args:
        file_path: Path to the file whose complete contents should be hashed.

    Returns:
        The lowercase hexadecimal SHA-256 digest of the bytes read from the file.

    Raises:
        ArtifactSupplyChainError: If the final path component is missing, is not a
            regular file, or is a symlink.
        OSError: If filesystem inspection, opening, or reading the path fails.
    """
    if file_path.is_symlink() or not file_path.is_file():
        raise ArtifactSupplyChainError([f"required regular file is missing or unsafe: {file_path}"])
    digest = hashlib.sha256()
    with file_path.open("rb") as file_stream:
        for content_block in iter(lambda: file_stream.read(1024 * 1024), b""):
            digest.update(content_block)
    return digest.hexdigest()


def _require_toml_table(value: object, *, context: str) -> dict[str, object]:
    """Require a runtime dictionary for one parsed TOML table.

    Args:
        value: Parsed value expected to be a ``dict``. The object is returned as
            supplied; this helper does not copy or recursively validate it.
        context: TOML location used in a validation error message.

    Returns:
        The same dictionary object, typed for subsequent field inspection.

    Raises:
        ArtifactSupplyChainError: If ``value`` is not a dictionary.
    """
    if not isinstance(value, dict):
        raise ArtifactSupplyChainError([f"{context} must be a TOML table"])
    return cast(dict[str, object], value)


def _require_toml_table_array(value: object, *, context: str) -> list[dict[str, object]]:
    """Require an ordered list whose every item is a parsed TOML table.

    Args:
        value: Parsed value expected to be a list of dictionaries. The list may
            be empty and its items are not copied or recursively validated here.
        context: TOML location used in a validation error message.

    Returns:
        The same list object, typed for subsequent field inspection, with item
        order preserved.

    Raises:
        ArtifactSupplyChainError: If ``value`` is not a list of dictionaries.
    """
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ArtifactSupplyChainError([f"{context} must be an array of TOML tables"])
    return cast(list[dict[str, object]], value)


def _require_unique_string_tuple(
    value: object, *, context: str, allow_empty: bool = False
) -> tuple[str, ...]:
    """Require an ordered list of distinct, non-empty strings.

    Args:
        value: Parsed value expected to be a list of non-empty strings.
        context: TOML location used in a validation error message.
        allow_empty: Whether an empty list is accepted. The default is ``False``.

    Returns:
        A tuple containing the strings in their input order.

    Raises:
        ArtifactSupplyChainError: If the value is not a list of non-empty strings,
            is empty while ``allow_empty`` is false, or contains duplicates.
    """
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ArtifactSupplyChainError([f"{context} must contain non-empty strings"])
    result = tuple(cast(list[str], value))
    if (not result and not allow_empty) or len(result) != len(set(result)):
        raise ArtifactSupplyChainError([f"{context} must contain unique values"])
    return result


def _require_nonempty_string_field(table: dict[str, object], key: str, *, context: str) -> str:
    """Require a present, non-empty string field without normalizing its value.

    Args:
        table: Parsed TOML table containing the field.
        key: Field name to retrieve.
        context: TOML location used in a validation error message.

    Returns:
        The field value unchanged, including whitespace that was supplied.

    Raises:
        ArtifactSupplyChainError: If the field is absent, not a string, or empty.
    """
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ArtifactSupplyChainError([f"{context}.{key} must be a non-empty string"])
    return value


def _require_positive_integer_field(table: dict[str, object], key: str, *, context: str) -> int:
    """Require an integer field whose value is at least one.

    Boolean values are rejected even though ``bool`` is an ``int`` subclass.

    Args:
        table: Parsed TOML table containing the field.
        key: Field name to retrieve.
        context: TOML location used in a validation error message.

    Returns:
        The positive integer value unchanged.

    Raises:
        ArtifactSupplyChainError: If the field is absent, is not an integer, is
            boolean, or is less than one.
    """
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ArtifactSupplyChainError([f"{context}.{key} must be a positive integer"])
    return value


def _require_safe_repository_relative_path(value: str, *, context: str) -> str:
    """Require a lexically repository-relative POSIX path.

    This check compares ``PurePosixPath.as_posix()`` with the supplied text and
    rejects absolute paths and any ``..`` component. It does not resolve the path,
    inspect the filesystem, reject symlinks, or establish containment after
    resolution; ``.`` is accepted as a relative path.

    Args:
        value: Path text to check.
        context: Policy field used in a validation error message.

    Returns:
        The original path text unchanged.

    Raises:
        ArtifactSupplyChainError: If the path is absolute, non-canonical under
            ``PurePosixPath``, or contains a parent-directory component.
    """
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or ".." in path.parts:
        raise ArtifactSupplyChainError([f"{context} must stay inside the repository"])
    return value


def _parse_artifact_tool(tool_table: dict[str, object], *, tool_name: str) -> ArtifactTool:
    """Parse one closed artifact-tool declaration.

    The command must match the lowercase executable-name pattern and the version
    must be non-empty and free of the case-insensitive substring ``latest``. Exact
    Syft and Cosign identities are checked by ``load_policy`` after this parser.

    Args:
        tool_table: Parsed ``[tools.<tool_name>]`` table.
        tool_name: Tool key used in validation error messages.

    Returns:
        An ``ArtifactTool`` retaining the supplied command and version strings.

    Raises:
        ArtifactSupplyChainError: If the table has missing or additional fields,
            either field is empty or not a string, or the command or version is
            unsafe or floating.
    """
    if set(tool_table) != _POLICY_TOOL_KEYS:
        raise ArtifactSupplyChainError([f"tools.{tool_name} has missing or unknown fields"])
    command = _require_nonempty_string_field(tool_table, "command", context=f"tools.{tool_name}")
    version = _require_nonempty_string_field(tool_table, "version", context=f"tools.{tool_name}")
    if _ARTIFACT_TOOL_COMMAND_PATTERN.fullmatch(command) is None or "latest" in version.lower():
        raise ArtifactSupplyChainError([f"tools.{tool_name} identity is unsafe or floating"])
    return ArtifactTool(command=command, version=version)


class ArtifactPolicyService:
    """Own artifact policy loading and repository validation for one boundary."""

    def __init__(self, repository_root: Path) -> None:
        """Bind ArtifactPolicyService collaborators without filesystem or process I/O.

        Args:
            repository_root: Repository root used by later service operations.
        """
        self.repository_root = repository_root

    def load_policy(self, policy_path: Path) -> ArtifactSupplyChainPolicy:
        """Load and validate the closed B08 artifact supply-chain policy.

        The file is read as UTF-8 TOML. Admission requires the exact root and nested
        table schemas, B08 metadata and ordered gate/artifact/finding values, the
        protected-main signing environment, the locked Syft ``1.51.1`` and Cosign
        ``3.1.3`` identities, the four ordered build locks, lowercase digests, lexically safe
        repository-relative paths, expected SPDX/SLSA and builder identities, and
        date values where ``review_due_on`` follows ``as_of_date``. The loader does
        not compare dates with the current date or verify referenced file contents.

        Args:
            policy_path: TOML policy file to read.

        Returns:
            An immutable ``ArtifactSupplyChainPolicy`` populated from the admitted
            policy and the module's fixed B08 contract values.

        Raises:
            ArtifactSupplyChainError: If TOML is malformed or an explicit schema,
                field, ordering, identity, digest, date, or B08 contract check fails.
                TOML decoding failures are translated and chained from the decoder
                exception. A type or model-construction failure that is not explicitly
                raised by this loader can propagate from the parsed values.
            OSError: If the policy path cannot be opened or read.
            UnicodeDecodeError: If the policy is not valid UTF-8.
            TypeError: If parsed dates and datetimes, or datetimes with incompatible
                timezone awareness, cannot be ordered.
            pydantic.ValidationError: If the immutable policy model rejects a value
                that reached construction.
        """
        try:
            raw_policy_document: dict[str, object] = tomllib.loads(
                policy_path.read_text(encoding="utf-8")
            )
            policy_document = _require_toml_table(raw_policy_document, context=str(policy_path))
        except tomllib.TOMLDecodeError as error:
            raise ArtifactSupplyChainError([f"{policy_path}: invalid TOML: {error}"]) from error
        if set(policy_document) != _POLICY_ROOT_KEYS:
            raise ArtifactSupplyChainError([f"{policy_path}: root has missing or unknown fields"])
        expected_policy_metadata: dict[str, object] = {
            "schema_version": 1,
            "roadmap_package": _ARTIFACT_SUPPLY_CHAIN_PACKAGE_ID,
            "operating_track": "solo_bootstrap",
            "package_status": "partial",
            "accountable_owner_role": "platform",
            "risk_class": "R2",
            "successor_package": _CANONICAL_INSTRUMENT_IDENTITY_SUCCESSOR_PACKAGE_ID,
        }
        for metadata_key, expected_value in expected_policy_metadata.items():
            if policy_document.get(metadata_key) != expected_value:
                raise ArtifactSupplyChainError(
                    [f"{policy_path}: {metadata_key} must be {expected_value!r}"]
                )
        if (
            _require_unique_string_tuple(
                policy_document.get("applicable_gate_ids"), context="applicable_gate_ids"
            )
            != _ARTIFACT_SUPPLY_CHAIN_GATE_IDS
        ):
            raise ArtifactSupplyChainError(["applicable_gate_ids must be A04 R2 plus B08 QG15"])
        if (
            _require_unique_string_tuple(
                policy_document.get("supported_artifact_kinds"),
                context="supported_artifact_kinds",
            )
            != _SUPPORTED_ARTIFACT_KINDS
        ):
            raise ArtifactSupplyChainError(["supported_artifact_kinds must match the B08 contract"])
        if (
            _require_unique_string_tuple(
                policy_document.get("native_library_markers"),
                context="native_library_markers",
            )
            != _NATIVE_LIBRARY_FILENAME_MARKERS
        ):
            raise ArtifactSupplyChainError(["native_library_markers must match the B08 contract"])
        configured_open_finding_ids = _require_unique_string_tuple(
            policy_document.get("open_finding_ids"), context="open_finding_ids"
        )
        finding_records = _require_toml_table_array(
            policy_document.get("findings"), context="findings"
        )
        if (
            configured_open_finding_ids != _ARTIFACT_SUPPLY_CHAIN_OPEN_FINDING_IDS
            or tuple(finding_record.get("finding_id") for finding_record in finding_records)
            != _ARTIFACT_SUPPLY_CHAIN_OPEN_FINDING_IDS
        ):
            raise ArtifactSupplyChainError(["partial B08 policy requires the exact open findings"])
        if any(set(finding_record) != _POLICY_FINDING_KEYS for finding_record in finding_records):
            raise ArtifactSupplyChainError(["findings have missing or unknown fields"])
        if any(
            not isinstance(value, str) or not value
            for finding_record in finding_records
            for value in finding_record.values()
        ):
            raise ArtifactSupplyChainError(["finding values must be non-empty strings"])

        policy_tables = {
            table_name: _require_toml_table(policy_document.get(table_name), context=table_name)
            for table_name in _POLICY_TABLE_KEYS
        }
        for table_name, expected_table_keys in _POLICY_TABLE_KEYS.items():
            if set(policy_tables[table_name]) != expected_table_keys:
                raise ArtifactSupplyChainError([f"{table_name} has missing or unknown fields"])
        artifact_tool_tables = _require_toml_table(policy_document.get("tools"), context="tools")
        if set(artifact_tool_tables) != {"cosign", "syft"}:
            raise ArtifactSupplyChainError(["tools must define exactly cosign and syft"])
        syft = _parse_artifact_tool(
            _require_toml_table(artifact_tool_tables["syft"], context="tools.syft"),
            tool_name="syft",
        )
        cosign = _parse_artifact_tool(
            _require_toml_table(artifact_tool_tables["cosign"], context="tools.cosign"),
            tool_name="cosign",
        )
        if (syft.command, syft.version, cosign.command, cosign.version) != (
            "syft",
            "1.51.1",
            "cosign",
            "3.1.3",
        ):
            raise ArtifactSupplyChainError(["artifact tools must match the locked B08 versions"])

        lock_tables = _require_toml_table_array(policy_document.get("locks"), context="locks")
        lock_identities: list[LockIdentity] = []
        for index, lock_table in enumerate(lock_tables):
            if set(lock_table) != _POLICY_LOCK_KEYS:
                raise ArtifactSupplyChainError([f"locks[{index}] has missing or unknown fields"])
            lock_path = _require_safe_repository_relative_path(
                _require_nonempty_string_field(lock_table, "path", context=f"locks[{index}]"),
                context=f"locks[{index}].path",
            )
            lock_digest = _require_nonempty_string_field(
                lock_table, "sha256", context=f"locks[{index}]"
            )
            if _LOWERCASE_SHA256_PATTERN.fullmatch(lock_digest) is None:
                raise ArtifactSupplyChainError([f"locks[{index}].sha256 must be lowercase SHA-256"])
            lock_identities.append(LockIdentity(path=lock_path, sha256=lock_digest))
        expected_lock_paths = (
            "MODULE.bazel.lock",
            "flake.lock",
            "requirements.bazel.txt",
            "uv.lock",
        )
        if tuple(lock_identity.path for lock_identity in lock_identities) != expected_lock_paths:
            raise ArtifactSupplyChainError(["locks must contain the exact sorted build lock set"])

        signing_policy = policy_tables["signing"]
        signing_environment = _require_unique_string_tuple(
            signing_policy.get("required_environment"), context="signing.required_environment"
        )
        parsed_signing_environment: list[tuple[str, str]] = []
        for environment_entry in signing_environment:
            environment_variable_name, separator, required_value = environment_entry.partition("=")
            if not separator or not environment_variable_name or not required_value:
                raise ArtifactSupplyChainError(
                    ["signing.required_environment entries must be NAME=value"]
                )
            parsed_signing_environment.append((environment_variable_name, required_value))
        if tuple(parsed_signing_environment) != (
            ("GITHUB_ACTIONS", "true"),
            ("GITHUB_REF", "refs/heads/main"),
            ("GITHUB_REF_PROTECTED", "true"),
        ):
            raise ArtifactSupplyChainError(
                ["signing environment must be the exact protected-main context"]
            )
        revoked_signer_identities = _require_unique_string_tuple(
            signing_policy.get("revoked_signer_identities"),
            context="signing.revoked_signer_identities",
            allow_empty=True,
        )
        toolchain_policy = policy_tables["toolchain"]
        toolchain_path = _require_safe_repository_relative_path(
            _require_nonempty_string_field(toolchain_policy, "path", context="toolchain"),
            context="toolchain.path",
        )
        toolchain_digest = _require_nonempty_string_field(
            toolchain_policy, "sha256", context="toolchain"
        )
        if _LOWERCASE_SHA256_PATTERN.fullmatch(toolchain_digest) is None:
            raise ArtifactSupplyChainError(["toolchain.sha256 must be lowercase SHA-256"])
        artifact_formats = policy_tables["formats"]
        build_identity = policy_tables["identity"]
        resource_limits = policy_tables["limits"]
        if (
            _require_nonempty_string_field(artifact_formats, "statement_type", context="formats")
            != "https://in-toto.io/Statement/v1"
            or _require_nonempty_string_field(
                artifact_formats, "provenance_predicate_type", context="formats"
            )
            != "https://slsa.dev/provenance/v1"
            or _require_nonempty_string_field(artifact_formats, "spdx_version", context="formats")
            != "SPDX-2.3"
        ):
            raise ArtifactSupplyChainError(["formats must match the B08 SPDX and SLSA contract"])
        expected_build_identity = {
            "builder_id": (
                "https://github.com/lixuanguang/alpha-research-lab-private/"
                ".github/workflows/ci.yml@refs/heads/main"
            ),
            "build_type": (
                "https://github.com/lixuanguang/alpha-research-lab-private/blob/main/"
                "docs/architecture/artifact-supply-chain.md#build-contract"
            ),
            "source_repository": (
                "git+https://github.com/lixuanguang/alpha-research-lab-private.git"
            ),
        }
        if any(
            build_identity.get(identity_key) != expected_value
            for identity_key, expected_value in expected_build_identity.items()
        ):
            raise ArtifactSupplyChainError(["builder, build-type, or source identity drifted"])
        if (
            signing_policy.get("signer_identity") != expected_build_identity["builder_id"]
            or signing_policy.get("oidc_issuer") != "https://token.actions.githubusercontent.com"
            or signing_policy.get("trusted_context") != "github_protected_main"
        ):
            raise ArtifactSupplyChainError(["signer identity or protected context drifted"])
        as_of_date = policy_document.get("as_of_date")
        review_due_on = policy_document.get("review_due_on")
        if not isinstance(as_of_date, date) or not isinstance(review_due_on, date):
            raise ArtifactSupplyChainError(["as_of_date and review_due_on must be unquoted dates"])
        if review_due_on <= as_of_date:
            raise ArtifactSupplyChainError(["review_due_on must follow as_of_date"])
        evidence_manifest_path = _require_safe_repository_relative_path(
            _require_nonempty_string_field(
                policy_document, "local_evidence_manifest_path", context=str(policy_path)
            ),
            context="local_evidence_manifest_path",
        )
        evidence_commit_sha = _require_nonempty_string_field(
            policy_document, "local_evidence_commit_sha", context=str(policy_path)
        )
        if re.fullmatch(r"[0-9a-f]{40}", evidence_commit_sha) is None:
            raise ArtifactSupplyChainError(["local_evidence_commit_sha must be lowercase Git SHA"])
        return ArtifactSupplyChainPolicy(
            package_status="partial",
            successor_package=_CANONICAL_INSTRUMENT_IDENTITY_SUCCESSOR_PACKAGE_ID,
            as_of_date=as_of_date,
            review_due_on=review_due_on,
            supported_artifact_kinds=_SUPPORTED_ARTIFACT_KINDS,
            native_library_markers=_NATIVE_LIBRARY_FILENAME_MARKERS,
            maximum_artifact_bytes=_require_positive_integer_field(
                resource_limits, "maximum_artifact_bytes", context="limits"
            ),
            maximum_archive_members=_require_positive_integer_field(
                resource_limits, "maximum_archive_members", context="limits"
            ),
            statement_type=_require_nonempty_string_field(
                artifact_formats, "statement_type", context="formats"
            ),
            provenance_predicate_type=_require_nonempty_string_field(
                artifact_formats, "provenance_predicate_type", context="formats"
            ),
            spdx_version=_require_nonempty_string_field(
                artifact_formats, "spdx_version", context="formats"
            ),
            builder_id=_require_nonempty_string_field(
                build_identity, "builder_id", context="identity"
            ),
            build_type=_require_nonempty_string_field(
                build_identity, "build_type", context="identity"
            ),
            source_repository=_require_nonempty_string_field(
                build_identity, "source_repository", context="identity"
            ),
            signer_identity=_require_nonempty_string_field(
                signing_policy, "signer_identity", context="signing"
            ),
            oidc_issuer=_require_nonempty_string_field(
                signing_policy, "oidc_issuer", context="signing"
            ),
            trusted_signing_context=_require_nonempty_string_field(
                signing_policy, "trusted_context", context="signing"
            ),
            signing_environment=tuple(parsed_signing_environment),
            revoked_signer_identities=revoked_signer_identities,
            toolchain_path=toolchain_path,
            toolchain_sha256=toolchain_digest,
            locks=tuple(lock_identities),
            syft=syft,
            cosign=cosign,
            applicable_gate_ids=_ARTIFACT_SUPPLY_CHAIN_GATE_IDS,
            local_evidence_manifest_path=evidence_manifest_path,
            local_evidence_commit_sha=evidence_commit_sha,
            open_finding_ids=_ARTIFACT_SUPPLY_CHAIN_OPEN_FINDING_IDS,
        )

    def validate_repository(self) -> ArtifactSupplyChainPolicy:
        """Validate the repository against its admitted B08 policy and evidence.

        The resolved root supplies the policy, four lockfiles, toolchain registry,
        integration files, change-risk policy, and local evidence manifest. Validation
        checks lock and toolchain digests, admitted Syft/Cosign versions, required
        integration fragments, signer revocation, the manifest's expected commit and
        change-risk binding, package evidence, and the exact additional ``QG15`` gate.
        Lock-file absence or digest drift is accumulated with other findings; an
        unsafe or missing toolchain file fails when its digest is computed.

        Args:
            The repository root is bound by the service constructor.

        Returns:
            The loaded ``ArtifactSupplyChainPolicy`` when every repository check passes.

        Raises:
            ArtifactSupplyChainError: If the policy is invalid, repository identities or
                integration fragments drift, findings are accumulated, toolchain parsing
                fails, the signer is revoked, or evidence validation fails. Evidence
                and toolchain-registry failures are translated and chained. An
                ``ArtifactSupplyChainError`` from a lock-file digest check is accumulated
                in the final findings; digest-check I/O errors propagate.
            OSError: If the policy, lockfile, toolchain file, or integration files cannot
                be inspected or read. Toolchain-registry and evidence read failures are
                translated where this function catches them.
            UnicodeDecodeError: If an uncaught repository text file is not UTF-8.
            TypeError: If the initial policy loader cannot compare its parsed date values.
            pydantic.ValidationError: If the initial policy loader's immutable model rejects
                a value. Such errors inside the final evidence block are translated.
        """
        resolved_repository_root = self.repository_root.resolve()
        artifact_supply_chain_policy = load_policy(
            resolved_repository_root / "docs/architecture/artifact-supply-chain.toml"
        )
        validation_findings: list[str] = []
        for lock_identity in artifact_supply_chain_policy.locks:
            try:
                observed_lock_digest = compute_regular_file_sha256(
                    resolved_repository_root / lock_identity.path
                )
            except ArtifactSupplyChainError as error:
                validation_findings.extend(error.findings)
                continue
            if observed_lock_digest != lock_identity.sha256:
                validation_findings.append(f"{lock_identity.path} digest drifted from B08 policy")
        if (
            compute_regular_file_sha256(
                resolved_repository_root / artifact_supply_chain_policy.toolchain_path
            )
            != artifact_supply_chain_policy.toolchain_sha256
        ):
            validation_findings.append(
                f"{artifact_supply_chain_policy.toolchain_path} digest drifted from B08 policy"
            )
        try:
            toolchain_registry: dict[str, object] = tomllib.loads(
                (resolved_repository_root / artifact_supply_chain_policy.toolchain_path).read_text(
                    encoding="utf-8"
                )
            )
            admitted_tool_versions = {
                item.get("tool_id"): item.get("version")
                for item in _require_toml_table_array(
                    toolchain_registry.get("tools", []), context="toolchain.tools"
                )
            }
        except (OSError, tomllib.TOMLDecodeError, TypeError) as error:
            raise ArtifactSupplyChainError([f"invalid toolchain registry: {error}"]) from error
        if (
            admitted_tool_versions.get("developer_environment.syft")
            != artifact_supply_chain_policy.syft.version
        ):
            validation_findings.append("Syft version is not admitted by the developer toolchain")
        if (
            admitted_tool_versions.get("developer_environment.cosign")
            != artifact_supply_chain_policy.cosign.version
        ):
            validation_findings.append("Cosign version is not admitted by the developer toolchain")
        required_integration_fragments = {
            "Makefile": ("artifact-supply-chain-check:", "alpha-governance-artifacts"),
            ".pre-commit-config.yaml": ("id: artifact-supply-chain", "alpha-governance-artifacts"),
            "flake.nix": ("pkgs.syft", "pkgs.cosign"),
            "docs/architecture/decisions/0001-build-and-developer-tooling.md": (
                "B08",
                "Syft",
                "Cosign",
            ),
        }
        for repository_relative_path, required_fragments in required_integration_fragments.items():
            integration_content = (resolved_repository_root / repository_relative_path).read_text(
                encoding="utf-8"
            )
            for required_fragment in required_fragments:
                if required_fragment not in integration_content:
                    validation_findings.append(
                        f"{repository_relative_path} is missing required B08 fragment "
                        f"{required_fragment!r}"
                    )
        if (
            artifact_supply_chain_policy.signer_identity
            in artifact_supply_chain_policy.revoked_signer_identities
        ):
            validation_findings.append("configured signer identity is revoked")
        if validation_findings:
            raise ArtifactSupplyChainError(validation_findings)
        try:
            manifest = validate_manifest(
                resolved_repository_root
                / artifact_supply_chain_policy.local_evidence_manifest_path,
                expected_commit_sha=artifact_supply_chain_policy.local_evidence_commit_sha,
                change_policy=load_change_risk_policy(
                    resolved_repository_root / "docs/governance/change-risk-policy.toml"
                ),
            )
            validate_package_evidence(manifest, _ARTIFACT_SUPPLY_CHAIN_EVIDENCE_PROFILE)
            if manifest.additional_required_gates != ("QG15",):
                raise ArtifactSupplyChainError(["B08 evidence must add exactly QG15"])
        except (EvidenceGovernanceError, OSError, ValueError) as error:
            raise ArtifactSupplyChainError([str(error)]) from error
        return artifact_supply_chain_policy


def load_policy(policy_path: Path) -> ArtifactSupplyChainPolicy:
    """Load and validate the closed B08 artifact supply-chain policy.

    The file is read as UTF-8 TOML. Admission requires the exact root and nested
    table schemas, B08 metadata and ordered gate/artifact/finding values, the
    protected-main signing environment, the locked Syft ``1.51.1`` and Cosign
    ``3.1.3`` identities, the four ordered build locks, lowercase digests, lexically safe
    repository-relative paths, expected SPDX/SLSA and builder identities, and
    date values where ``review_due_on`` follows ``as_of_date``. The loader does
    not compare dates with the current date or verify referenced file contents.

    Args:
        policy_path: TOML policy file to read.

    Returns:
        An immutable ``ArtifactSupplyChainPolicy`` populated from the admitted
        policy and the module's fixed B08 contract values.

    Raises:
        ArtifactSupplyChainError: If TOML is malformed or an explicit schema,
            field, ordering, identity, digest, date, or B08 contract check fails.
            TOML decoding failures are translated and chained from the decoder
            exception. A type or model-construction failure that is not explicitly
            raised by this loader can propagate from the parsed values.
        OSError: If the policy path cannot be opened or read.
        UnicodeDecodeError: If the policy is not valid UTF-8.
        TypeError: If parsed dates and datetimes, or datetimes with incompatible
            timezone awareness, cannot be ordered.
        pydantic.ValidationError: If the immutable policy model rejects a value
            that reached construction.
    """
    return ArtifactPolicyService(policy_path.parent).load_policy(policy_path)


def validate_repository(repository_root: Path) -> ArtifactSupplyChainPolicy:
    """Validate the repository against its admitted B08 policy and evidence.

    The resolved root supplies the policy, four lockfiles, toolchain registry,
    integration files, change-risk policy, and local evidence manifest. Validation
    checks lock and toolchain digests, admitted Syft/Cosign versions, required
    integration fragments, signer revocation, the manifest's expected commit and
    change-risk binding, package evidence, and the exact additional ``QG15`` gate.
    Lock-file absence or digest drift is accumulated with other findings; an
    unsafe or missing toolchain file fails when its digest is computed.

    Args:
        repository_root: Repository root whose B08 files and evidence are checked.

    Returns:
        The loaded ``ArtifactSupplyChainPolicy`` when every repository check passes.

    Raises:
        ArtifactSupplyChainError: If the policy is invalid, repository identities or
            integration fragments drift, findings are accumulated, toolchain parsing
            fails, the signer is revoked, or evidence validation fails. Evidence
            and toolchain-registry failures are translated and chained. An
            ``ArtifactSupplyChainError`` from a lock-file digest check is accumulated
            in the final findings; digest-check I/O errors propagate.
        OSError: If the policy, lockfile, toolchain file, or integration files cannot
            be inspected or read. Toolchain-registry and evidence read failures are
            translated where this function catches them.
        UnicodeDecodeError: If an uncaught repository text file is not UTF-8.
        TypeError: If the initial policy loader cannot compare its parsed date values.
        pydantic.ValidationError: If the initial policy loader's immutable model rejects
            a value. Such errors inside the final evidence block are translated.
    """
    return ArtifactPolicyService(repository_root).validate_repository()
