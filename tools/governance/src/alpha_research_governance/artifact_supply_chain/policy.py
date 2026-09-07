"""Load the small artifact identity and integrity policy.

Artifact policy owns archive shape, provenance, signing, and repository byte
identities.  Dependency release eligibility remains in the dependency admission
module, which blocks the currently unresolved QuantLib wheel binding.
"""

from __future__ import annotations

# standard library imports
import hashlib
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import cast

# project library imports
from alpha_research_governance.artifact_supply_chain.models import (
    ArtifactSupplyChainError,
    ArtifactSupplyChainPolicy,
    ArtifactTool,
    LockIdentity,
)

_ROOT_KEYS = {
    "schema_version",
    "supported_artifact_kinds",
    "native_library_markers",
    "formats",
    "identity",
    "signing",
    "limits",
    "project",
    "tools",
    "locks",
}
_TABLE_KEYS = {
    "formats": {"statement_type", "provenance_predicate_type", "spdx_version"},
    "identity": {"builder_id", "build_type", "source_repository"},
    "signing": {
        "signer_identity",
        "oidc_issuer",
        "trusted_context",
        "required_environment",
        "revoked_signer_identities",
    },
    "limits": {"maximum_artifact_bytes", "maximum_archive_members"},
    "project": {"path", "sha256"},
}
_TOOL_KEYS = {"command", "version"}
_LOCK_KEYS = {"path", "sha256"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMAND = re.compile(r"^[a-z][a-z0-9-]*$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SUPPORTED_ARTIFACT_KINDS = ("binary", "configuration_bundle", "container", "model")
_NATIVE_MARKERS = (".dll", ".dylib", ".so", ".so.")
_BUILDER = "https://github.com/lixuanguang/alpha-research-lab-private/.github/workflows/ci.yml@refs/heads/main"
_BUILD_TYPE = "https://github.com/lixuanguang/alpha-research-lab-private/blob/main/docs/architecture/artifact-supply-chain.md#build-contract"
_SOURCE_REPOSITORY = "git+https://github.com/lixuanguang/alpha-research-lab-private.git"


def compute_regular_file_sha256(file_path: Path) -> str:
    """Hash a regular, non-symlink file.

    Args:
        file_path: File whose complete bytes are hashed.

    Returns:
        Lowercase SHA-256 digest.

    Raises:
        ArtifactSupplyChainError: If the final component is missing, non-regular,
            or a symlink.
        OSError: If the file cannot be inspected or read.
    """
    if file_path.is_symlink() or not file_path.is_file():
        raise ArtifactSupplyChainError([f"required regular file is missing or unsafe: {file_path}"])
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _table(value: object, *, context: str) -> dict[str, object]:
    """Narrow one decoded TOML table."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ArtifactSupplyChainError([f"{context} must be a TOML table"])
    return cast(dict[str, object], value)


def _tables(value: object, *, context: str) -> list[dict[str, object]]:
    """Narrow an ordered array of TOML tables."""
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ArtifactSupplyChainError([f"{context} must be an array of TOML tables"])
    return [cast(dict[str, object], item) for item in value]


def _strings(value: object, *, context: str, allow_empty: bool = False) -> tuple[str, ...]:
    """Validate an ordered tuple of unique non-empty strings."""
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ArtifactSupplyChainError([f"{context} must contain non-empty strings"])
    result = tuple(cast(list[str], value))
    if not result and not allow_empty:
        raise ArtifactSupplyChainError([f"{context} must not be empty"])
    if len(result) != len(set(result)):
        raise ArtifactSupplyChainError([f"{context} must contain unique values"])
    return result


def _field(table: dict[str, object], key: str, *, context: str) -> str:
    """Read a required non-empty string field."""
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ArtifactSupplyChainError([f"{context}.{key} must be a non-empty string"])
    return value


def _safe_path(value: str, *, context: str) -> str:
    """Require a canonical repository-relative POSIX path."""
    path = PurePosixPath(value)
    if path.is_absolute() or not value or path.as_posix() != value or ".." in path.parts:
        raise ArtifactSupplyChainError([f"{context} must stay inside the repository"])
    return value


def _tool(
    value: object, *, context: str, expected_command: str, expected_version: str
) -> ArtifactTool:
    """Parse and pin one artifact tool identity."""
    table = _table(value, context=context)
    if set(table) != _TOOL_KEYS:
        raise ArtifactSupplyChainError([f"{context} has missing or unknown fields"])
    command = _field(table, "command", context=context)
    version = _field(table, "version", context=context)
    if (
        _COMMAND.fullmatch(command) is None
        or "latest" in version.lower()
        or (command, version) != (expected_command, expected_version)
    ):
        raise ArtifactSupplyChainError([f"{context} identity is not pinned"])
    return ArtifactTool(command=command, version=version)


class ArtifactPolicyService:
    """Load and validate artifact policy for one repository root."""

    def __init__(self, repository_root: Path) -> None:
        """Bind the repository root without reading files.

        Args:
            repository_root: Root whose policy-bound files are checked.
        """
        self.repository_root = repository_root

    def load_policy(self, policy_path: Path) -> ArtifactSupplyChainPolicy:
        """Read a closed artifact policy with no governance framework dependencies.

        Args:
            policy_path: TOML policy path.

        Returns:
            The parsed artifact policy.

        Raises:
            ArtifactSupplyChainError: If the policy schema or identities are invalid.
        """
        try:
            raw_document: object = tomllib.loads(policy_path.read_text(encoding="utf-8"))
            document = _table(
                raw_document,
                context=str(policy_path),
            )
        except tomllib.TOMLDecodeError as error:
            raise ArtifactSupplyChainError([f"{policy_path}: invalid TOML: {error}"]) from error
        if set(document) != _ROOT_KEYS or document.get("schema_version") != 2:
            raise ArtifactSupplyChainError([f"{policy_path}: root has missing or unknown fields"])
        kinds = _strings(
            document.get("supported_artifact_kinds"), context="supported_artifact_kinds"
        )
        markers = _strings(document.get("native_library_markers"), context="native_library_markers")
        if kinds != _SUPPORTED_ARTIFACT_KINDS or markers != _NATIVE_MARKERS:
            raise ArtifactSupplyChainError(["artifact format or native marker contract drifted"])
        tables = {name: _table(document.get(name), context=name) for name in _TABLE_KEYS}
        for name, keys in _TABLE_KEYS.items():
            if set(tables[name]) != keys:
                raise ArtifactSupplyChainError([f"{name} has missing or unknown fields"])
        formats = tables["formats"]
        if (
            _field(formats, "statement_type", context="formats")
            != "https://in-toto.io/Statement/v1"
            or _field(formats, "provenance_predicate_type", context="formats")
            != "https://slsa.dev/provenance/v1"
            or _field(formats, "spdx_version", context="formats") != "SPDX-2.3"
        ):
            raise ArtifactSupplyChainError(["artifact formats are not admitted"])
        identity = tables["identity"]
        if {key: _field(identity, key, context="identity") for key in _TABLE_KEYS["identity"]} != {
            "builder_id": _BUILDER,
            "build_type": _BUILD_TYPE,
            "source_repository": _SOURCE_REPOSITORY,
        }:
            raise ArtifactSupplyChainError(["artifact build identity drifted"])
        limits = tables["limits"]
        limits_values: dict[str, int] = {}
        for key in _TABLE_KEYS["limits"]:
            value = limits.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ArtifactSupplyChainError([f"limits.{key} must be a positive integer"])
            limits_values[key] = value
        project = tables["project"]
        project_path = _safe_path(
            _field(project, "path", context="project"), context="project.path"
        )
        if project_path != "pyproject.toml":
            raise ArtifactSupplyChainError(["project.path must be exactly pyproject.toml"])
        project_digest = _field(project, "sha256", context="project")
        if _SHA256.fullmatch(project_digest) is None:
            raise ArtifactSupplyChainError(["project.sha256 must be lowercase SHA-256"])
        signing = tables["signing"]
        signer = _field(signing, "signer_identity", context="signing")
        oidc = _field(signing, "oidc_issuer", context="signing")
        trusted_context = _field(signing, "trusted_context", context="signing")
        if (signer, oidc, trusted_context) != (
            _BUILDER,
            "https://token.actions.githubusercontent.com",
            "github_protected_main",
        ):
            raise ArtifactSupplyChainError(["signing identity or context drifted"])
        required_environment = _strings(
            signing.get("required_environment"), context="signing.required_environment"
        )
        parsed_environment: list[tuple[str, str]] = []
        for entry in required_environment:
            name, separator, value = entry.partition("=")
            if not separator or not name or not value:
                raise ArtifactSupplyChainError(
                    ["signing.required_environment entries must be NAME=value"]
                )
            parsed_environment.append((name, value))
        if tuple(parsed_environment) != (
            ("GITHUB_ACTIONS", "true"),
            ("GITHUB_REF", "refs/heads/main"),
            ("GITHUB_REF_PROTECTED", "true"),
        ):
            raise ArtifactSupplyChainError(
                ["signing environment must be the protected-main context"]
            )
        revoked = _strings(
            signing.get("revoked_signer_identities"),
            context="signing.revoked_signer_identities",
            allow_empty=True,
        )
        locks: list[LockIdentity] = []
        for index, item in enumerate(_tables(document.get("locks"), context="locks")):
            if set(item) != _LOCK_KEYS:
                raise ArtifactSupplyChainError([f"locks[{index}] has missing or unknown fields"])
            path = _safe_path(
                _field(item, "path", context=f"locks[{index}]"), context=f"locks[{index}].path"
            )
            digest = _field(item, "sha256", context=f"locks[{index}]")
            if _SHA256.fullmatch(digest) is None:
                raise ArtifactSupplyChainError([f"locks[{index}].sha256 must be lowercase SHA-256"])
            locks.append(LockIdentity(path=path, sha256=digest))
        if tuple(item.path for item in locks) != ("uv.lock",):
            raise ArtifactSupplyChainError(["locks must contain exactly uv.lock"])
        tools = _table(document.get("tools"), context="tools")
        if set(tools) != {"cosign", "syft"}:
            raise ArtifactSupplyChainError(["tools must define exactly cosign and syft"])
        return ArtifactSupplyChainPolicy(
            supported_artifact_kinds=kinds,
            native_library_markers=markers,
            maximum_artifact_bytes=limits_values["maximum_artifact_bytes"],
            maximum_archive_members=limits_values["maximum_archive_members"],
            statement_type=_field(formats, "statement_type", context="formats"),
            provenance_predicate_type=_field(
                formats, "provenance_predicate_type", context="formats"
            ),
            spdx_version=_field(formats, "spdx_version", context="formats"),
            builder_id=_field(identity, "builder_id", context="identity"),
            build_type=_field(identity, "build_type", context="identity"),
            source_repository=_field(identity, "source_repository", context="identity"),
            signer_identity=signer,
            oidc_issuer=oidc,
            trusted_signing_context=trusted_context,
            signing_environment=tuple(parsed_environment),
            revoked_signer_identities=revoked,
            project_path=project_path,
            project_sha256=project_digest,
            locks=tuple(locks),
            syft=_tool(
                tools["syft"],
                context="tools.syft",
                expected_command="syft",
                expected_version="1.51.1",
            ),
            cosign=_tool(
                tools["cosign"],
                context="tools.cosign",
                expected_command="cosign",
                expected_version="3.1.3",
            ),
        )

    def validate_repository(self) -> ArtifactSupplyChainPolicy:
        """Validate policy-bound project and lock bytes in the repository.

        Returns:
            The validated artifact policy.

        Raises:
            ArtifactSupplyChainError: If a project, lock, signer, or path check fails.
        """
        root = self.repository_root.resolve(strict=True)
        policy = self.load_policy(root / "docs/architecture/artifact-supply-chain.toml")
        findings: list[str] = []
        for lock in policy.locks:
            try:
                observed = compute_regular_file_sha256(root / lock.path)
            except ArtifactSupplyChainError as error:
                findings.extend(error.findings)
                continue
            if observed != lock.sha256:
                findings.append(f"{lock.path} differs from its admitted SHA-256 digest")
        try:
            observed_project = compute_regular_file_sha256(root / policy.project_path)
        except ArtifactSupplyChainError as error:
            findings.extend(error.findings)
        else:
            if observed_project != policy.project_sha256:
                findings.append(f"{policy.project_path} differs from its admitted SHA-256 digest")
        if policy.signer_identity in policy.revoked_signer_identities:
            findings.append("configured signer identity is revoked")
        if findings:
            raise ArtifactSupplyChainError(findings)
        return policy


def load_policy(policy_path: Path) -> ArtifactSupplyChainPolicy:
    """Load an artifact policy from a TOML path.

    Args:
        policy_path: TOML policy path.

    Returns:
        The parsed artifact policy.

    Raises:
        ArtifactSupplyChainError: If the policy schema or identities are invalid.
    """
    return ArtifactPolicyService(policy_path.parent).load_policy(policy_path)


def validate_repository(repository_root: Path) -> ArtifactSupplyChainPolicy:
    """Validate the artifact policy and its repository-bound file identities.

    Args:
        repository_root: Repository whose project and lock bytes are checked.

    Returns:
        The validated artifact policy.

    Raises:
        ArtifactSupplyChainError: If a project, lock, signer, or path check fails.
    """
    return ArtifactPolicyService(repository_root).validate_repository()
