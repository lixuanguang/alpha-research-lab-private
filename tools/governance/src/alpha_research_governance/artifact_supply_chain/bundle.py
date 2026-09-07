"""Create, sign, publish, and consume immutable B08 artifact bundles."""

from __future__ import annotations

# standard library imports
import json
import os
import platform
import re
import shutil
import subprocess  # nosec B404  # [owner=platform; rationale=exact Syft/Cosign argv execution; expires=2027-03-01]
import tarfile
import tempfile
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import TypeGuard, cast

# project library imports
from alpha_research_governance.artifact_supply_chain.models import (
    ArtifactBundle,
    ArtifactSupplyChainError,
    ArtifactSupplyChainPolicy,
    ArtifactTool,
)
from alpha_research_governance.artifact_supply_chain.policy import compute_regular_file_sha256
from alpha_research_governance.dependency_admission.models import DependencyAdmissionError
from alpha_research_governance.dependency_admission.policy import require_release_admission

ProcessRunner = Callable[[list[str], Path, Mapping[str, str]], subprocess.CompletedProcess[str]]

_LOWERCASE_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_LOWERCASE_GIT_COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_EXPLICIT_BAZEL_TARGET_PATTERN = re.compile(r"^//(?:[^\s:]+(?::[^\s:]+)?|:[^\s:]+)$")
_SAFE_BUNDLE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,254}$")
_BUILD_PLATFORM_IDENTITY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
_MAXIMUM_JSON_DOCUMENT_BYTES = 100 * 1024 * 1024
_MAXIMUM_TEST_EVIDENCE_FILE_COUNT = 1000
_ARTIFACT_MANIFEST_KEYS = {
    "artifact",
    "build",
    "bundleVersion",
    "locks",
    "policy",
    "provenance",
    "sbom",
    "testEvidence",
    "toolchain",
}
_ARTIFACT_IDENTITY_KEYS = {"kind", "name", "path", "sha256", "size"}
_DIGESTED_FILE_RECORD_KEYS = {"path", "sha256", "size"}
_BUILD_IDENTITY_KEYS = {"platform", "sourceCommit", "target"}
_TOOLCHAIN_IDENTITY_KEYS = {"cosign", "path", "sha256", "syft"}


def _is_object_dict(value: object) -> TypeGuard[dict[object, object]]:
    """Narrow a runtime dictionary to object-valued entries."""
    return isinstance(value, dict)


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    """Narrow a runtime list to object-valued entries."""
    return isinstance(value, list)


def _serialize_canonical_json(value: object) -> bytes:
    """Serialize a value with the bundle's local deterministic JSON settings.

    Use ASCII escaping, compact separators, sorted keys, and the standard
    encoder's default acceptance of nonfinite float constants, then append one
    newline and encode the result as UTF-8. This local format does not implement
    RFC 8785.

    Args:
        value: Object accepted by the standard-library JSON encoder.

    Returns:
        UTF-8 bytes containing the serialized value and trailing newline.

    Raises:
        TypeError: If the value or its keys cannot be serialized or sorted.
        ValueError: If serialization detects a circular reference or an integer
            exceeds the interpreter's enabled conversion limit.
        RecursionError: If recursive input exceeds Python's recursion limit.
    """
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _write_canonical_json(path: Path, value: object) -> None:
    """Write the bundle's local deterministic JSON representation to a file.

    Serialize ``value`` before opening ``path``, then overwrite and truncate the
    target with ``Path.write_bytes``. The parent directory must already exist;
    this operation makes no atomicity guarantee.

    Args:
        path: Existing or new file path receiving the serialized JSON bytes.
        value: Object accepted by the standard-library JSON encoder.

    Raises:
        TypeError: If ``value`` or its keys cannot be serialized or sorted.
        ValueError: If serialization detects a circular reference or an integer
            exceeds the interpreter's enabled conversion limit.
        RecursionError: If recursive input exceeds Python's recursion limit.
        OSError: If the target cannot be written or its parent is unavailable.
    """
    path.write_bytes(_serialize_canonical_json(value))


def _build_mapping_rejecting_duplicate_json_keys(
    key_value_pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Build an insertion-ordered mapping while rejecting duplicate JSON keys.

    Store each supplied value directly and preserve pair order; nested values are
    not copied or recursively inspected.

    Args:
        key_value_pairs: Object-pairs callback input from ``json.loads``.

    Returns:
        A mapping containing the supplied keys and shallow, ordered values.

    Raises:
        ArtifactSupplyChainError: If a key occurs more than once in the pairs.
    """
    parsed_mapping: dict[str, object] = {}
    for key, value in key_value_pairs:
        if key in parsed_mapping:
            raise ArtifactSupplyChainError([f"JSON contains duplicate key {key!r}"])
        parsed_mapping[key] = value
    return parsed_mapping


def _read_bounded_json_object(path: Path) -> dict[str, object]:
    """Read a JSON object after a pre-read size check and reject duplicate keys.

    Check the final path component for a symlink and regular-file status, then
    compare its pre-read size with 100 MiB. Parent-directory symlinks remain
    followed; the whole text is read into memory with no bounded stream or
    atomicity guarantee. Parse with the duplicate-key hook, accept standard
    nonfinite constants, and require a dictionary at the top level. Of parser
    exceptions, only UTF-8 and JSON decode errors are translated into the domain
    error.

    Args:
        path: JSON file whose final component must be a regular non-symlink file.

    Returns:
        The parsed top-level JSON object with nested duplicate keys rejected.

    Raises:
        ArtifactSupplyChainError: If the file is unsafe, too large, malformed,
            contains duplicate keys, or does not contain a JSON object.
        OSError: If filesystem inspection or reading fails.
        ValueError: If another parser value error occurs, such as a huge integer
            literal exceeding Python's digit limit; this error is propagated.
        RecursionError: If JSON nesting exceeds Python's recursion limit.
    """
    if path.is_symlink() or not path.is_file():
        raise ArtifactSupplyChainError([f"required bundle file is missing or unsafe: {path.name}"])
    if path.stat().st_size > _MAXIMUM_JSON_DOCUMENT_BYTES:
        raise ArtifactSupplyChainError([f"{path.name} exceeds the governed JSON size limit"])
    try:
        parsed_document: object = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_build_mapping_rejecting_duplicate_json_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactSupplyChainError([f"{path.name} is not valid JSON: {error}"]) from error
    if not isinstance(parsed_document, dict):
        raise ArtifactSupplyChainError([f"{path.name} must contain a JSON object"])
    return cast(dict[str, object], parsed_document)


def _run_subprocess(
    command: list[str], working_directory: Path, environment: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with the supplied context and capture decoded text.

    Pass ``command`` as argv, copy ``environment`` for the child environment,
    use ``working_directory`` as its current directory, and capture both output
    streams without a size bound using Python's default subprocess text encoding.
    Do not impose a timeout; return nonzero statuses for the caller to inspect.

    Args:
        command: Executable and arguments passed to ``subprocess.run``.
        working_directory: Child process current working directory.
        environment: Complete environment mapping supplied to the child.

    Returns:
        The completed process, including its return code and captured text.

    Raises:
        ArtifactSupplyChainError: If the process cannot start because of an
            operating-system error.
        UnicodeDecodeError: If captured output cannot be decoded with that encoding.
    """
    try:
        return subprocess.run(  # nosec B603  # [owner=platform; rationale=validated tool and constant option argv; expires=2027-03-01]
            command,
            cwd=working_directory,
            env=dict(environment),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise ArtifactSupplyChainError([f"{command[0]} could not start: {error}"]) from error


def _run_artifact_tool(
    command: list[str],
    *,
    working_directory: Path,
    environment: Mapping[str, str],
    runner: ProcessRunner,
) -> str:
    """Run an artifact tool and combine its captured output.

    Call ``runner`` once, fail on any nonzero return code, and combine stdout
    followed by stderr before stripping whitespace. The combination is not
    chronological; exceptions from ``runner`` propagate unchanged.

    Args:
        command: Executable and arguments for the artifact-tool invocation.
        working_directory: Directory supplied to ``runner``.
        environment: Environment mapping supplied to ``runner``.
        runner: Process callback that executes or simulates ``command``.

    Returns:
        Stdout concatenated with stderr, with whitespace stripped from the ends
        of the combined string.

    Raises:
        ArtifactSupplyChainError: If the process returns a nonzero status.
    """
    completed_process = runner(command, working_directory, environment)
    if completed_process.returncode != 0:
        failure_detail = (completed_process.stdout + completed_process.stderr).strip()
        raise ArtifactSupplyChainError(
            [f"{command[0]} failed with exit {completed_process.returncode}: {failure_detail}"]
        )
    return (completed_process.stdout + completed_process.stderr).strip()


def _verify_artifact_tool_version(
    tool: ArtifactTool,
    *,
    working_directory: Path,
    environment: Mapping[str, str],
    runner: ProcessRunner,
) -> None:
    """Require the admitted artifact-tool version fragment in command output.

    Run ``[tool.command, "version"]`` through ``runner`` and search for the
    exact spacing-sensitive ``Version:       <version>`` fragment for Syft or
    ``GitVersion:    v<version>`` for every other tool. This substring check
    does not parse or compare a complete structured version, so extra output may
    surround the admitted fragment. Exceptions from ``runner`` propagate unchanged.

    Args:
        tool: Admitted executable command and version identity.
        working_directory: Directory supplied to the version command.
        environment: Environment mapping supplied to the version command.
        runner: Process callback used to invoke the tool.

    Raises:
        ArtifactSupplyChainError: If the command fails or lacks the exact
            admitted version fragment.
    """
    version_output = _run_artifact_tool(
        [tool.command, "version"],
        working_directory=working_directory,
        environment=environment,
        runner=runner,
    )
    expected_version_fragment = (
        f"Version:       {tool.version}"
        if tool.command == "syft"
        else f"GitVersion:    v{tool.version}"
    )
    if expected_version_fragment not in version_output:
        raise ArtifactSupplyChainError(
            [
                f"{tool.command} version output does not contain exact admitted "
                f"version {tool.version}"
            ]
        )


def _parse_safe_bundle_relative_path(value: object, *, context: str) -> PurePosixPath:
    """Parse a path as a safe lexical POSIX bundle-relative path.

    Accept only strings whose ``PurePosixPath`` spelling is already canonical,
    with at least one component and no absolute root, ``..`` component,
    backslash, or whitespace. Perform
    no filesystem I/O, existence check, resolution, ancestor-symlink protection,
    or filename-regex validation.

    Args:
        value: Candidate repository-style path value.
        context: Field context included in any validation error.

    Returns:
        The validated lexical path as a ``PurePosixPath``.

    Raises:
        ArtifactSupplyChainError: If ``value`` is not a string or violates the
            admitted lexical path rules.
    """
    if not isinstance(value, str):
        raise ArtifactSupplyChainError([f"{context} must be a repository-style relative path"])
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or ".." in path.parts
        or not path.parts
        or "\\" in value
        or any(character.isspace() for character in value)
    ):
        raise ArtifactSupplyChainError([f"{context} must be a safe relative path"])
    return path


def _build_file_digest_record(path: Path, relative_path: str) -> dict[str, object]:
    """Build a digest and size record for a regular file.

    Hash ``path`` with ``compute_regular_file_sha256`` and then perform a separate
    ``stat`` for its size; this sequence is non-atomic. Preserve ``relative_path``
    exactly as supplied without validating or normalizing it.

    Args:
        path: Regular file whose bytes and size are recorded.
        relative_path: Bundle-relative label stored unchanged in the record.

    Returns:
        A mapping containing the supplied path label, lowercase SHA-256 digest,
        and separately observed byte size.

    Raises:
        ArtifactSupplyChainError: If the digest helper rejects the final path
            component as missing, non-regular, or a symlink.
        OSError: If hashing or the separate size inspection fails.
    """
    return {
        "path": relative_path,
        "sha256": compute_regular_file_sha256(path),
        "size": path.stat().st_size,
    }


def _is_native_library_path(name: str) -> bool:
    """Recognize native-library names by their POSIX basename.

    Lowercase the basename and accept ``.dll``, ``.dylib``, or ``.so`` suffixes,
    or ``.so.`` anywhere in that basename. Inspect only the spelling; do not
    access the path or inspect file contents.

    Args:
        name: POSIX-style path or filename to classify by basename.

    Returns:
        ``True`` when the basename matches a native-library marker.
    """
    lowercase_filename = PurePosixPath(name).name.lower()
    return lowercase_filename.endswith((".dll", ".dylib", ".so")) or ".so." in (lowercase_filename)


def _discover_native_library_paths(
    path: Path, policy: ArtifactSupplyChainPolicy
) -> tuple[str, ...]:
    """Inventory native-library names from an artifact and its archive members.

    Include a native outer basename, prefer ZIP inventory over TAR inventory, and
    materialize all member names before enforcing
    ``policy.maximum_archive_members`` and filtering native names. ZIP
    ``namelist`` includes directory entries; TAR inventory keeps regular members
    only. Count the outer name in the bound, sort the result, and retain
    duplicates. Do not extract members or promise archive path security.

    Args:
        path: Artifact file whose outer name and archive members are inspected.
        policy: Policy providing the inclusive archive-member limit.

    Returns:
        Sorted native-library names, including any retained duplicate entries.

    Raises:
        ArtifactSupplyChainError: If archive inventory raises an operating-system,
            TAR, or bad-ZIP error, or the materialized member count exceeds policy.
    """
    artifact_member_paths: list[str] = []
    if _is_native_library_path(path.name):
        artifact_member_paths.append(path.name)
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive_reader:
                artifact_member_paths.extend(archive_reader.namelist())
        elif tarfile.is_tarfile(path):
            with tarfile.open(path) as archive_reader:
                artifact_member_paths.extend(
                    member.name for member in archive_reader.getmembers() if member.isfile()
                )
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise ArtifactSupplyChainError([f"artifact archive inventory failed: {error}"]) from error
    if len(artifact_member_paths) > policy.maximum_archive_members:
        raise ArtifactSupplyChainError(["artifact archive exceeds the governed member limit"])
    return tuple(
        sorted(
            member_path
            for member_path in artifact_member_paths
            if _is_native_library_path(member_path)
        )
    )


def _normalize_spdx_document(
    raw_spdx_document: dict[str, object], *, artifact_name: str, artifact_digest: str
) -> dict[str, object]:
    """Normalize selected SPDX metadata and lists for deterministic bundle output.

    Require ``spdxVersion == "SPDX-2.3"``, ``SPDXID == "SPDXRef-DOCUMENT"``,
    ``dataLicense == "CC0-1.0"``, and a ``creationInfo`` dictionary whose
    creators list contains ``Tool: syft-1.51.1``; perform no full SPDX validation. Shallow
    copy the root and ``creationInfo``, use ``artifact_name`` and
    ``artifact_digest`` verbatim for the normalized identity, set creation time
    to ``1970-01-01T00:00:01Z``, and sort only top-level ``files``, ``packages``,
    and ``relationships`` lists by serialized bytes. Retain nested entry values
    and their aliases unchanged apart from reordering the selected lists.

    Args:
        raw_spdx_document: Parsed Syft document to normalize.
        artifact_name: Artifact filename written into the document name field.
        artifact_digest: Artifact SHA-256 digest used in the namespace.

    Returns:
        A shallow-normalized SPDX document mapping.

    Raises:
        ArtifactSupplyChainError: If required SPDX metadata or the fixed Syft
            creator entry is absent or malformed.
        TypeError: If a sortable list entry cannot be JSON serialized.
        ValueError: If serialization detects a circular list entry or an integer
            exceeds the interpreter's enabled conversion limit.
        RecursionError: If list-entry serialization exceeds Python's recursion
            limit.
    """
    creation_information = raw_spdx_document.get("creationInfo")
    creators = (
        creation_information.get("creators") if _is_object_dict(creation_information) else None
    )
    if (
        raw_spdx_document.get("spdxVersion") != "SPDX-2.3"
        or raw_spdx_document.get("SPDXID") != "SPDXRef-DOCUMENT"
        or raw_spdx_document.get("dataLicense") != "CC0-1.0"
        or not _is_object_dict(creation_information)
        or not _is_object_list(creators)
        or "Tool: syft-1.51.1" not in creators
    ):
        raise ArtifactSupplyChainError(["Syft output is not a complete SPDX-2.3 document"])
    normalized_spdx_document = dict(raw_spdx_document)
    normalized_spdx_document["name"] = artifact_name
    normalized_spdx_document["documentNamespace"] = (
        f"https://alpha-research.invalid/spdx/sha256/{artifact_digest}"
    )
    normalized_creation_information = dict(creation_information)
    normalized_creation_information["created"] = "1970-01-01T00:00:01Z"
    normalized_spdx_document["creationInfo"] = normalized_creation_information
    for key in ("files", "packages", "relationships"):
        spdx_entries = normalized_spdx_document.get(key)
        if _is_object_list(spdx_entries):
            normalized_spdx_document[key] = sorted(spdx_entries, key=_serialize_canonical_json)
    return normalized_spdx_document


def _extract_spdx_file_names(sbom: Mapping[str, object]) -> frozenset[str]:
    """Extract normalized, deduplicated file names from an SPDX mapping.

    Treat a missing ``files`` field as empty, require a list of dictionary
    entries whose ``fileName`` is a string (including an empty string), strip
    one leading ``./`` and then one leading ``/``, and deduplicate with a
    ``frozenset``. Perform no canonical path or safety check.

    Args:
        sbom: Parsed SPDX mapping containing an optional ``files`` array.

    Returns:
        A frozenset of the normalized file-name strings.

    Raises:
        ArtifactSupplyChainError: If ``files`` is not a list or an entry is not
            a dictionary containing a string ``fileName``.
    """
    spdx_file_entries = sbom.get("files", [])
    if not isinstance(spdx_file_entries, list):
        raise ArtifactSupplyChainError(["SPDX files must be an array"])
    spdx_file_names: set[str] = set()
    for spdx_file_entry in spdx_file_entries:
        if not isinstance(spdx_file_entry, dict) or not isinstance(
            spdx_file_entry.get("fileName"), str
        ):
            raise ArtifactSupplyChainError(["SPDX file entries must contain fileName"])
        spdx_file_names.add(
            cast(str, spdx_file_entry["fileName"]).removeprefix("./").removeprefix("/")
        )
    return frozenset(spdx_file_names)


def _verify_native_library_sbom_coverage(
    artifact_path: Path, sbom: Mapping[str, object], policy: ArtifactSupplyChainPolicy
) -> None:
    """Require every discovered native-library member in the SPDX file inventory.

    Inventory native-library names from the outer artifact and its archive members,
    normalize the SPDX ``files`` names, and require each discovered name to match
    exactly or as a slash-delimited suffix of a documented path. Archive members
    are inspected but never extracted, and the supplied SPDX mapping is not modified.

    Args:
        artifact_path: Artifact whose outer name and archive members are inspected.
        sbom: Parsed SPDX mapping containing the file inventory.
        policy: Policy providing the archive-member limit.

    Raises:
        ArtifactSupplyChainError: If archive inventory or SPDX file parsing fails,
            or a native-library name is absent from the SPDX inventory.
    """
    native_library_paths = _discover_native_library_paths(artifact_path, policy)
    documented_spdx_file_names = _extract_spdx_file_names(sbom)
    missing_native_library_paths = tuple(
        native_library_path
        for native_library_path in native_library_paths
        if not any(
            documented_path == native_library_path
            or documented_path.endswith(f"/{native_library_path}")
            for documented_path in documented_spdx_file_names
        )
    )
    if missing_native_library_paths:
        raise ArtifactSupplyChainError(
            [
                "SPDX inventory omits native/shared-library members: "
                f"{missing_native_library_paths!r}"
            ]
        )


class ArtifactBundleService:
    """Own artifact lifecycle operations for one repository and policy boundary.

    The constructor stores only caller-supplied collaborators; filesystem and
    process work remains inside the lifecycle methods.
    """

    def __init__(
        self,
        policy: ArtifactSupplyChainPolicy,
        repository_root: Path,
        runner: ProcessRunner = _run_subprocess,
    ) -> None:
        """Bind ArtifactBundleService collaborators without filesystem or process I/O.

        Args:
            policy: Already validated policy object owned by the service.
            runner: Typed process callback used by later service operations.
            repository_root: Repository root used by later service operations.
        """
        self.repository_root = repository_root
        self.policy = policy
        self.runner = runner

    def _verify_current_repository_identities(self, repository_root: Path) -> None:
        """Verify policy-bound repository identities and release admission.

        Hash each admitted lockfile and the toolchain file under the resolved repository root,
        then use the module-level release-admission seam so callers retain its existing patchable
        integration point.

        Args:
            repository_root: Resolved repository root for this lifecycle invocation.

        Raises:
            ArtifactSupplyChainError: If an identity differs or release dependency admission
                rejects the repository.
            OSError: If an admitted repository identity cannot be read or hashed.
        """
        for lock_identity in self.policy.locks:
            if (
                compute_regular_file_sha256(repository_root / lock_identity.path)
                != lock_identity.sha256
            ):
                raise ArtifactSupplyChainError(
                    [f"repository lock identity drifted: {lock_identity.path}"]
                )
        if (
            compute_regular_file_sha256(repository_root / self.policy.toolchain_path)
            != self.policy.toolchain_sha256
        ):
            raise ArtifactSupplyChainError(["repository toolchain identity drifted"])
        self._require_release_dependencies(repository_root)

    def _require_release_dependencies(self, repository_root: Path) -> None:
        """Require dependency admission at the service's repository boundary.

        Delegate to the imported admission function, preserving its existing patchable seam, and
        translate domain, filesystem, and value failures at the artifact boundary.

        Args:
            repository_root: Resolved repository root used for this admission call.

        Raises:
            ArtifactSupplyChainError: If dependency admission rejects the repository or its inputs
                cannot be read or interpreted; the original error remains the cause.
        """
        self._require_release_dependencies_for_root(repository_root)

    @staticmethod
    def _require_release_dependencies_for_root(repository_root: Path) -> None:
        """Translate release-admission failures for one explicit repository root."""
        try:
            require_release_admission(repository_root)
        except (DependencyAdmissionError, OSError, ValueError) as error:
            raise ArtifactSupplyChainError(
                [f"artifact dependency admission failed: {error}"]
            ) from error

    def create_bundle(
        self,
        artifact_path: Path,
        *,
        artifact_kind: str,
        build_target: str,
        source_commit: str,
        test_evidence_paths: tuple[Path, ...],
        output_path: Path,
        build_platform: str | None = None,
    ) -> ArtifactBundle:
        """Create an unsigned candidate bundle with normalized local metadata.

        Resolve ``repository_root`` before checking every policy-declared lock and the
        toolchain file, then require release dependency admission before invoking Syft.
        Validate the artifact and evidence inputs and the destination, then run the admitted
        Syft version check with the resolved repository as its working directory. Create a
        sibling temporary staging directory and copy the complete artifact into it. Run Syft
        on that copy with the resolved repository as its working directory, normalize the
        SPDX output, and require native-library coverage without extracting archive members.
        Copy the opaque evidence files in basename order and write canonical bundle metadata.
        The candidate is exposed at ``output_path`` only after the staging directory is
        renamed there. The source commit
        and Bazel target are syntax checked and recorded; this function does not build the
        artifact or inspect Git state.

        The admission, file checks, hashing, and copies are separate filesystem observations
        and therefore are not atomic. Failures after staging is allocated trigger
        best-effort removal of that staging directory; parent-directory creation and staging
        allocation occur before that cleanup scope, and no exclusive-create or rollback
        guarantee is provided if the final rename has completed.

        Args:
            artifact_path: Path to the one artifact file to bundle. Its final component must
                be a non-symlink regular file with a safe basename and a non-empty size
                within ``policy.maximum_artifact_bytes``. Relative paths follow the process
                current directory and are not interpreted relative to ``repository_root``.
                The path is not required to be inside ``repository_root``; the complete
                file is copied to ``artifact/<basename>``.
            artifact_kind: Artifact kind that must occur in
                ``policy.supported_artifact_kinds``. It is recorded in the manifest and
                provenance.
            build_target: Explicit Bazel label, such as ``//pkg:target`` or ``//:target``,
                recorded in the build identity and provenance. No Bazel command or
                target-output check is performed.
            source_commit: Lowercase 40-character Git SHA recorded in the build identity,
                provenance source URI, and returned summary. The spelling is checked, but
                the repository ``HEAD`` and the commit's existence are not queried.
            test_evidence_paths: Non-empty tuple of evidence files, limited to 1,000
                entries. Relative paths follow the process current directory and are not
                interpreted relative to ``repository_root``. Each final component must be a
                non-symlink regular file with a safe unique basename, a positive size, and
                at most 100 MiB. Files are copied in basename order to ``tests/`` and
                recorded with their copied digest and size; their contents are treated as
                opaque bytes, with no JSON or test-outcome validation.
            output_path: Destination directory for the candidate bundle. It must not exist,
                including as a symlink. Relative paths follow the process current directory
                and are not interpreted relative to ``repository_root``. Its parent is
                created as needed; staging uses a temporary sibling beneath that parent and
                the completed staging directory is renamed to this path.
            The repository root, policy, and process runner are bound by the constructor.
            build_platform: Optional platform identity to record in the build metadata. A
                falsey value, including ``None`` or an empty string, derives lowercase
                system and machine names joined by a hyphen; the resulting identity must
                match the governed lowercase platform pattern.

        Returns:
            An ``ArtifactBundle`` containing the artifact basename, kind, complete-file
            SHA-256 digest, source commit, build target, derived or supplied platform
            identity, and manifest SHA-256 digest. The record describes preparation only and
            does not indicate that the candidate is signed or verified.

        Raises:
            ArtifactSupplyChainError: If repository identities or release dependency
                admission fail; an input, output path, platform identity, tool version, Syft
                result, SPDX document, native-library inventory, or generated bundle record
                violates the governed contract; or the destination already exists.
            OSError: If resolving or inspecting paths, hashing, copying, creating
                directories or staging, writing or removing intermediate files, or renaming
                the completed candidate fails. The default subprocess runner translates a
                process-start error into ``ArtifactSupplyChainError``.
            ValueError: If bounded Syft JSON parsing raises an unhandled parser value error,
                such as an integer-conversion limit failure.
            RecursionError: If bounded Syft JSON parsing exceeds Python's recursion limit.
            UnicodeDecodeError: If the default subprocess runner cannot decode captured Syft
                output as text.
            RuntimeError: If repository path resolution encounters a symlink loop.
        """
        repository_root = self.repository_root
        policy = self.policy
        runner = self.runner
        resolved_repository_root = repository_root.resolve()
        self._verify_current_repository_identities(resolved_repository_root)
        if artifact_kind not in policy.supported_artifact_kinds:
            raise ArtifactSupplyChainError([f"unsupported artifact kind: {artifact_kind!r}"])
        if _EXPLICIT_BAZEL_TARGET_PATTERN.fullmatch(build_target) is None:
            raise ArtifactSupplyChainError(["build target must be an explicit Bazel label"])
        if _LOWERCASE_GIT_COMMIT_SHA_PATTERN.fullmatch(source_commit) is None:
            raise ArtifactSupplyChainError(
                ["source commit must be a lowercase 40-character Git SHA"]
            )
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise ArtifactSupplyChainError(["artifact must be one regular file"])
        if _SAFE_BUNDLE_FILENAME_PATTERN.fullmatch(artifact_path.name) is None:
            raise ArtifactSupplyChainError(["artifact basename contains unsupported characters"])
        artifact_size = artifact_path.stat().st_size
        if artifact_size < 1 or artifact_size > policy.maximum_artifact_bytes:
            raise ArtifactSupplyChainError(["artifact size is empty or exceeds the governed limit"])
        if not test_evidence_paths:
            raise ArtifactSupplyChainError(["at least one test-evidence file is required"])
        if len(test_evidence_paths) > _MAXIMUM_TEST_EVIDENCE_FILE_COUNT:
            raise ArtifactSupplyChainError(["test-evidence count exceeds the governed limit"])
        if output_path.exists() or output_path.is_symlink():
            raise ArtifactSupplyChainError(["output bundle path must not already exist"])
        if len({path.name for path in test_evidence_paths}) != len(test_evidence_paths):
            raise ArtifactSupplyChainError(["test-evidence basenames must be unique"])
        for test_evidence_path in test_evidence_paths:
            if (
                test_evidence_path.is_symlink()
                or not test_evidence_path.is_file()
                or test_evidence_path.stat().st_size < 1
                or test_evidence_path.stat().st_size > _MAXIMUM_JSON_DOCUMENT_BYTES
                or _SAFE_BUNDLE_FILENAME_PATTERN.fullmatch(test_evidence_path.name) is None
            ):
                raise ArtifactSupplyChainError(
                    [f"test evidence must be a non-empty regular file: {test_evidence_path}"]
                )

        deterministic_tool_environment = dict(os.environ)
        deterministic_tool_environment.update(
            {
                "LC_ALL": "C",
                "SOURCE_DATE_EPOCH": "1",
                "SYFT_CHECK_FOR_APP_UPDATE": "false",
                "SYFT_FILE_METADATA_SELECTION": "all",
                "TZ": "UTC",
            }
        )
        _verify_artifact_tool_version(
            policy.syft,
            working_directory=resolved_repository_root,
            environment=deterministic_tool_environment,
            runner=runner,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_staging_path = Path(
            tempfile.mkdtemp(prefix=f".{output_path.name}.", dir=output_path.parent)
        )
        try:
            bundled_artifact_directory = bundle_staging_path / "artifact"
            bundled_test_evidence_directory = bundle_staging_path / "tests"
            bundled_artifact_directory.mkdir()
            bundled_test_evidence_directory.mkdir()
            stored_artifact = bundled_artifact_directory / artifact_path.name
            shutil.copyfile(artifact_path, stored_artifact)
            artifact_size = stored_artifact.stat().st_size
            if artifact_size < 1 or artifact_size > policy.maximum_artifact_bytes:
                raise ArtifactSupplyChainError(["copied artifact violates the governed size limit"])
            artifact_digest = compute_regular_file_sha256(stored_artifact)
            raw_sbom_path = bundle_staging_path / "sbom.raw.json"
            _run_artifact_tool(
                [
                    policy.syft.command,
                    "scan",
                    str(stored_artifact),
                    "--output",
                    f"spdx-json@2.3={raw_sbom_path}",
                ],
                working_directory=resolved_repository_root,
                environment=deterministic_tool_environment,
                runner=runner,
            )
            raw_spdx_document = _read_bounded_json_object(raw_sbom_path)
            normalized_spdx_document = _normalize_spdx_document(
                raw_spdx_document,
                artifact_name=artifact_path.name,
                artifact_digest=artifact_digest,
            )
            _verify_native_library_sbom_coverage(stored_artifact, normalized_spdx_document, policy)
            raw_sbom_path.unlink()
            sbom_path = bundle_staging_path / "sbom.spdx.json"
            _write_canonical_json(sbom_path, normalized_spdx_document)

            test_evidence_digest_records: list[dict[str, object]] = []

            def evidence_name(path: Path) -> str:
                """Return one evidence path's basename for deterministic ordering.

                Args:
                    path: Evidence path whose basename determines copy order.

                Returns:
                    The final path component.
                """
                return path.name

            for test_evidence_path in sorted(test_evidence_paths, key=evidence_name):
                stored_test_evidence = bundled_test_evidence_directory / test_evidence_path.name
                shutil.copyfile(test_evidence_path, stored_test_evidence)
                test_evidence_digest_records.append(
                    _build_file_digest_record(
                        stored_test_evidence, f"tests/{test_evidence_path.name}"
                    )
                )
            toolchain_path = resolved_repository_root / policy.toolchain_path
            build_platform_identity = build_platform or (
                platform.system().lower() + "-" + platform.machine().lower()
            )
            if _BUILD_PLATFORM_IDENTITY_PATTERN.fullmatch(build_platform_identity) is None:
                raise ArtifactSupplyChainError(["build platform identity is invalid"])
            provenance_statement = {
                "_type": policy.statement_type,
                "predicateType": policy.provenance_predicate_type,
                "subject": [{"name": artifact_path.name, "digest": {"sha256": artifact_digest}}],
                "predicate": {
                    "buildDefinition": {
                        "buildType": policy.build_type,
                        "externalParameters": {
                            "artifactKind": artifact_kind,
                            "buildPlatform": build_platform_identity,
                            "buildTarget": build_target,
                            "sourceCommit": source_commit,
                        },
                        "internalParameters": {},
                        "resolvedDependencies": [
                            {
                                "uri": f"{policy.source_repository}@{source_commit}",
                                "digest": {"gitCommit": source_commit},
                            },
                            *[
                                {
                                    "uri": lock_identity.path,
                                    "digest": {"sha256": lock_identity.sha256},
                                }
                                for lock_identity in policy.locks
                            ],
                            {
                                "uri": policy.toolchain_path,
                                "digest": {"sha256": policy.toolchain_sha256},
                            },
                        ],
                    },
                    "runDetails": {"builder": {"id": policy.builder_id}},
                },
            }
            provenance_path = bundle_staging_path / "provenance.intoto.json"
            _write_canonical_json(provenance_path, provenance_statement)
            policy_path = resolved_repository_root / "docs/architecture/artifact-supply-chain.toml"
            artifact_manifest = {
                "bundleVersion": 1,
                "artifact": {
                    "kind": artifact_kind,
                    "name": artifact_path.name,
                    "path": f"artifact/{artifact_path.name}",
                    "sha256": artifact_digest,
                    "size": artifact_size,
                },
                "build": {
                    "platform": build_platform_identity,
                    "sourceCommit": source_commit,
                    "target": build_target,
                },
                "locks": [
                    {"path": lock_identity.path, "sha256": lock_identity.sha256}
                    for lock_identity in policy.locks
                ],
                "policy": {
                    "path": "docs/architecture/artifact-supply-chain.toml",
                    "sha256": compute_regular_file_sha256(policy_path),
                },
                "provenance": _build_file_digest_record(provenance_path, "provenance.intoto.json"),
                "sbom": _build_file_digest_record(sbom_path, "sbom.spdx.json"),
                "testEvidence": test_evidence_digest_records,
                "toolchain": {
                    "path": policy.toolchain_path,
                    "sha256": compute_regular_file_sha256(toolchain_path),
                    "syft": policy.syft.version,
                    "cosign": policy.cosign.version,
                },
            }
            manifest_path = bundle_staging_path / "manifest.json"
            _write_canonical_json(manifest_path, artifact_manifest)
            manifest_digest = compute_regular_file_sha256(manifest_path)
            bundle_staging_path.rename(output_path)
            return ArtifactBundle(
                artifact_name=artifact_path.name,
                artifact_kind=artifact_kind,
                artifact_sha256=artifact_digest,
                source_commit=source_commit,
                build_target=build_target,
                build_platform=cast(
                    str,
                    cast(dict[str, object], artifact_manifest["build"])["platform"],
                ),
                manifest_sha256=manifest_digest,
            )
        except Exception:
            shutil.rmtree(bundle_staging_path, ignore_errors=True)
            raise

    def verify_bundle(
        self,
        bundle_path: Path,
        *,
        expected_artifact_digest: str,
        environment: Mapping[str, str] | None = None,
    ) -> ArtifactBundle:
        """Verify a signed bundle against an exact artifact digest and policy.

        Require ``expected_artifact_digest`` to be ``sha256:<64 lowercase hex>``, reject a
        symlink or non-directory bundle, and resolve ``repository_root`` before checking its
        policy-declared lock and toolchain digests and release-dependency admission. Reject
        symlinks discovered below ``bundle_path``, read the bounded manifest, enforce its
        selected schemas and identities, hash the artifact and every manifest-recorded file,
        and require the expected regular-file set. Check selected in-toto provenance
        identities and dependencies, the SBOM identity and native-library coverage, and a
        non-revoked configured signer with a non-empty signature bundle. Finally run the
        admitted Cosign version and ``verify-blob`` with the policy's certificate identity
        and OIDC issuer.

        The function itself does not write bundle or repository paths. Release-dependency
        admission may stage temporary private trust-root material and run its local verifier
        with its own helper environment. The default runner executes the admitted external
        Cosign commands without a timeout or offline mode, so its normal external-service
        behavior applies. An injected runner's successful result is accepted as supplied and
        does not itself establish cryptographic evidence.

        The bounded JSON reader limits the manifest, provenance, and SBOM documents to 100
        MiB before reading. Archive inventory applies ``policy.maximum_archive_members``
        after materializing member names; members are inventoried but never extracted.
        Verification does not reapply ``create_bundle``'s ``maximum_artifact_bytes`` or
        1,000 test-evidence count caps; test evidence is hashed and stat'ed only, never
        parsed or checked for an outcome. The checks cover selected manifest, provenance,
        and SPDX fields rather than providing full in-toto or SPDX schema validation. Digest
        and size observations are separate, non-atomic operations with no snapshot or lock;
        parent-directory symlinks remain followed.

        The ``sourceCommit`` field is pattern-checked through ``str(...)`` before
        ``ArtifactBundle`` is built. A non-string value can pass that check, such as a
        40-digit JSON integer, but strict model construction then raises
        ``pydantic.ValidationError``; it is not returned as an arbitrary parsed type.

        Args:
            bundle_path: Bundle directory to inspect. Python file operations interpret
                relative paths from the process current directory. Cosign receives the
                supplied path spelling in argv while running in this directory; use an
                absolute path or ensure relative argv paths resolve as intended.
            expected_artifact_digest: Immutable consumer reference that must exactly match
                ``sha256:`` followed by 64 lowercase hexadecimal characters and the manifest
                artifact digest.
            The repository root, policy, and process runner are bound by the constructor.
            environment: Complete environment mapping for Cosign version and verification
                calls. ``None`` snapshots ``os.environ``; a supplied mapping is copied and
                is not mutated. Release-dependency admission uses its own helper
                environment.

        Returns:
            An ``ArtifactBundle`` summary containing the verified artifact name, permitted
            kind, artifact SHA-256 digest, source commit, Bazel target, declared build
            platform, and the SHA-256 digest of the manifest bytes observed at return.

        Raises:
            ArtifactSupplyChainError: If the immutable reference, bundle directory, symlink
                policy, repository identities, release-dependency admission, manifest
                structure, selected provenance or SBOM claims, native-library coverage, file
                digest or size, signer status, signature presence, Cosign version, or Cosign
                verification fails. The default runner translates process-startup failures
                here, and ``_run_artifact_tool`` translates nonzero tool statuses here.
            OSError: If an unhandled repository or bundle filesystem operation fails while
                resolving paths, traversing, reading, hashing, statting, or inventorying
                files; a custom runner may also propagate its filesystem errors.
            UnicodeDecodeError: If an uncaught repository text read or runner output cannot
                be decoded; invalid JSON-file UTF-8 is translated to
                ``ArtifactSupplyChainError``.
            ValueError: If JSON contains an integer exceeding the interpreter's conversion
                limit or another parser value error escapes the bounded JSON helper.
            RecursionError: If JSON nesting exceeds the decoder's recursion limit.
            TypeError: If malformed nested provenance reaches an operation that the runtime
                casts do not narrow.
            AttributeError: If malformed nested provenance supplies a shape that passes the
                preceding key-set checks but has no mapping ``get`` method.
            pydantic.ValidationError: If strict ``ArtifactBundle`` construction rejects a
                parsed field, including a non-string ``sourceCommit`` that passed its
                textual pattern check.
            RuntimeError: If path resolution encounters a symlink loop.
        """
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_artifact_digest):
            raise ArtifactSupplyChainError(
                ["consumer must supply an immutable sha256:<digest> reference"]
            )
        repository_root = self.repository_root
        policy = self.policy
        runner = self.runner
        if bundle_path.is_symlink() or not bundle_path.is_dir():
            raise ArtifactSupplyChainError(["bundle must be a regular directory"])
        resolved_repository_root = repository_root.resolve()
        self._verify_current_repository_identities(resolved_repository_root)
        for bundle_entry_path in bundle_path.rglob("*"):
            if bundle_entry_path.is_symlink():
                raise ArtifactSupplyChainError(
                    [f"bundle contains unsafe symlink: {bundle_entry_path.name}"]
                )
        manifest_path = bundle_path / "manifest.json"
        signature_path = bundle_path / "signature.sigstore.json"
        artifact_manifest = _read_bounded_json_object(manifest_path)
        if (
            set(artifact_manifest) != _ARTIFACT_MANIFEST_KEYS
            or artifact_manifest.get("bundleVersion") != 1
        ):
            raise ArtifactSupplyChainError(["manifest has missing, unknown, or unsupported fields"])
        artifact_identity = artifact_manifest.get("artifact")
        build_identity = artifact_manifest.get("build")
        toolchain_identity = artifact_manifest.get("toolchain")
        if not isinstance(artifact_identity, dict):
            raise ArtifactSupplyChainError(["manifest artifact has missing or unknown fields"])
        artifact_identity = cast(dict[str, object], artifact_identity)
        if set(artifact_identity) != _ARTIFACT_IDENTITY_KEYS:
            raise ArtifactSupplyChainError(["manifest artifact has missing or unknown fields"])
        if not isinstance(build_identity, dict):
            raise ArtifactSupplyChainError(["manifest build has missing or unknown fields"])
        build_identity = cast(dict[str, object], build_identity)
        if set(build_identity) != _BUILD_IDENTITY_KEYS:
            raise ArtifactSupplyChainError(["manifest build has missing or unknown fields"])
        if not isinstance(toolchain_identity, dict):
            raise ArtifactSupplyChainError(["manifest toolchain has missing or unknown fields"])
        toolchain_identity = cast(dict[str, object], toolchain_identity)
        if set(toolchain_identity) != _TOOLCHAIN_IDENTITY_KEYS:
            raise ArtifactSupplyChainError(["manifest toolchain has missing or unknown fields"])
        artifact_path = _parse_safe_bundle_relative_path(
            artifact_identity.get("path"), context="artifact.path"
        )
        artifact_digest = artifact_identity.get("sha256")
        artifact_size = artifact_identity.get("size")
        artifact_name = artifact_identity.get("name")
        artifact_kind = artifact_identity.get("kind")
        if (
            not isinstance(artifact_digest, str)
            or _LOWERCASE_SHA256_PATTERN.fullmatch(artifact_digest) is None
            or expected_artifact_digest != f"sha256:{artifact_digest}"
        ):
            raise ArtifactSupplyChainError(
                ["artifact digest does not match the consumer reference"]
            )
        if not isinstance(artifact_name, str) or not artifact_name:
            raise ArtifactSupplyChainError(["artifact name is invalid"])
        if artifact_path.parts != ("artifact", artifact_name):
            raise ArtifactSupplyChainError(["artifact path and name do not match"])
        stored_artifact = bundle_path.joinpath(*artifact_path.parts)
        if (
            not isinstance(artifact_size, int)
            or isinstance(artifact_size, bool)
            or artifact_size < 1
            or compute_regular_file_sha256(stored_artifact) != artifact_digest
            or stored_artifact.stat().st_size != artifact_size
        ):
            raise ArtifactSupplyChainError(["artifact content does not match its identity"])
        if artifact_kind not in policy.supported_artifact_kinds:
            raise ArtifactSupplyChainError(["artifact kind is not permitted"])
        if (
            build_identity.get("sourceCommit") is None
            or _LOWERCASE_GIT_COMMIT_SHA_PATTERN.fullmatch(str(build_identity.get("sourceCommit")))
            is None
        ):
            raise ArtifactSupplyChainError(["source commit is invalid"])
        if (
            not isinstance(build_identity.get("target"), str)
            or _EXPLICIT_BAZEL_TARGET_PATTERN.fullmatch(cast(str, build_identity["target"])) is None
        ):
            raise ArtifactSupplyChainError(["build target is invalid"])
        if not isinstance(build_identity.get("platform"), str) or not build_identity["platform"]:
            raise ArtifactSupplyChainError(["build platform is invalid"])
        if toolchain_identity != {
            "path": policy.toolchain_path,
            "sha256": policy.toolchain_sha256,
            "syft": policy.syft.version,
            "cosign": policy.cosign.version,
        }:
            raise ArtifactSupplyChainError(["toolchain identity does not match policy"])
        expected_lock_identities = [
            {"path": lock_identity.path, "sha256": lock_identity.sha256}
            for lock_identity in policy.locks
        ]
        if artifact_manifest.get("locks") != expected_lock_identities:
            raise ArtifactSupplyChainError(["lock identity does not match policy"])
        policy_identity_record = artifact_manifest.get("policy")
        if not isinstance(policy_identity_record, dict):
            raise ArtifactSupplyChainError(["manifest policy identity is invalid"])
        policy_identity_record = cast(dict[str, object], policy_identity_record)
        if set(policy_identity_record) != {"path", "sha256"}:
            raise ArtifactSupplyChainError(["manifest policy identity is invalid"])
        policy_path = resolved_repository_root / "docs/architecture/artifact-supply-chain.toml"
        if policy_identity_record != {
            "path": "docs/architecture/artifact-supply-chain.toml",
            "sha256": compute_regular_file_sha256(policy_path),
        }:
            raise ArtifactSupplyChainError(["artifact policy identity drifted"])
        _, provenance_digest, _ = _verify_file_digest_record(
            bundle_path, artifact_manifest.get("provenance"), context="provenance"
        )
        sbom_relative_path, _, _ = _verify_file_digest_record(
            bundle_path, artifact_manifest.get("sbom"), context="sbom"
        )
        test_evidence_records = artifact_manifest.get("testEvidence")
        if not isinstance(test_evidence_records, list) or not test_evidence_records:
            raise ArtifactSupplyChainError(["manifest requires test evidence"])
        verified_test_evidence_records = [
            _verify_file_digest_record(bundle_path, record, context="testEvidence")
            for record in test_evidence_records
        ]
        test_evidence_relative_paths = tuple(
            str(verified_record[0]) for verified_record in verified_test_evidence_records
        )
        if (
            test_evidence_relative_paths != tuple(sorted(test_evidence_relative_paths))
            or len(test_evidence_relative_paths) != len(set(test_evidence_relative_paths))
            or any(
                relative_path.parts[0] != "tests" or len(relative_path.parts) != 2
                for relative_path, _, _ in verified_test_evidence_records
            )
        ):
            raise ArtifactSupplyChainError(
                ["test evidence paths must be unique, sorted, and contained"]
            )
        required_content_files = {
            "manifest.json",
            "provenance.intoto.json",
            "sbom.spdx.json",
            artifact_path.as_posix(),
            *test_evidence_relative_paths,
        }
        permitted_files = {*required_content_files, "signature.sigstore.json"}
        observed_bundle_files = {
            bundle_file_path.relative_to(bundle_path).as_posix()
            for bundle_file_path in bundle_path.rglob("*")
            if bundle_file_path.is_file()
        }
        if not required_content_files.issubset(
            observed_bundle_files
        ) or not observed_bundle_files.issubset(permitted_files):
            raise ArtifactSupplyChainError(["bundle contains missing or unknown files"])
        provenance_statement = _read_bounded_json_object(bundle_path / "provenance.intoto.json")
        expected_external_parameters = {
            "artifactKind": artifact_kind,
            "buildPlatform": build_identity["platform"],
            "buildTarget": build_identity["target"],
            "sourceCommit": build_identity["sourceCommit"],
        }
        try:
            provenance_predicate = cast(dict[str, object], provenance_statement["predicate"])
            build_definition = cast(dict[str, object], provenance_predicate["buildDefinition"])
            run_details = cast(dict[str, object], provenance_predicate["runDetails"])
            builder_identity = cast(dict[str, object], run_details["builder"])
        except (KeyError, TypeError) as error:
            raise ArtifactSupplyChainError(["provenance structure is incomplete"]) from error
        if (
            set(provenance_statement) != {"_type", "predicate", "predicateType", "subject"}
            or set(provenance_predicate) != {"buildDefinition", "runDetails"}
            or set(build_definition)
            != {"buildType", "externalParameters", "internalParameters", "resolvedDependencies"}
            or set(run_details) != {"builder"}
            or set(builder_identity) != {"id"}
            or build_definition.get("internalParameters") != {}
        ):
            raise ArtifactSupplyChainError(["provenance contains missing or unknown fields"])
        if (
            provenance_statement.get("_type") != policy.statement_type
            or provenance_statement.get("predicateType") != policy.provenance_predicate_type
            or provenance_statement.get("subject")
            != [{"name": artifact_name, "digest": {"sha256": artifact_digest}}]
            or build_definition.get("buildType") != policy.build_type
            or build_definition.get("externalParameters") != expected_external_parameters
            or builder_identity.get("id") != policy.builder_id
        ):
            raise ArtifactSupplyChainError(
                ["provenance identity or build definition does not match policy"]
            )
        expected_dependencies = [
            {
                "uri": f"{policy.source_repository}@{build_identity['sourceCommit']}",
                "digest": {"gitCommit": build_identity["sourceCommit"]},
            },
            *[{"uri": lock.path, "digest": {"sha256": lock.sha256}} for lock in policy.locks],
            {"uri": policy.toolchain_path, "digest": {"sha256": policy.toolchain_sha256}},
        ]
        if build_definition.get("resolvedDependencies") != expected_dependencies:
            raise ArtifactSupplyChainError(["provenance dependencies do not match policy"])
        if compute_regular_file_sha256(bundle_path / "provenance.intoto.json") != provenance_digest:
            raise ArtifactSupplyChainError(["provenance digest changed during verification"])
        sbom_document = _read_bounded_json_object(bundle_path.joinpath(*sbom_relative_path.parts))
        if (
            sbom_document.get("spdxVersion") != policy.spdx_version
            or sbom_document.get("name") != artifact_name
            or sbom_document.get("documentNamespace")
            != f"https://alpha-research.invalid/spdx/sha256/{artifact_digest}"
        ):
            raise ArtifactSupplyChainError(["SPDX identity does not match the artifact"])
        _verify_native_library_sbom_coverage(stored_artifact, sbom_document, policy)
        if policy.signer_identity in policy.revoked_signer_identities:
            raise ArtifactSupplyChainError(["configured signer identity is revoked"])
        if (
            signature_path.is_symlink()
            or not signature_path.is_file()
            or signature_path.stat().st_size < 1
        ):
            raise ArtifactSupplyChainError(["artifact is unsigned"])
        verification_environment = dict(os.environ if environment is None else environment)
        _verify_artifact_tool_version(
            policy.cosign,
            working_directory=bundle_path,
            environment=verification_environment,
            runner=runner,
        )
        _run_artifact_tool(
            [
                policy.cosign.command,
                "verify-blob",
                "--bundle",
                str(signature_path),
                "--certificate-identity",
                policy.signer_identity,
                "--certificate-oidc-issuer",
                policy.oidc_issuer,
                str(manifest_path),
            ],
            working_directory=bundle_path,
            environment=verification_environment,
            runner=runner,
        )
        return ArtifactBundle(
            artifact_name=artifact_name,
            artifact_kind=artifact_kind,
            artifact_sha256=artifact_digest,
            source_commit=cast(str, build_identity["sourceCommit"]),
            build_target=cast(str, build_identity["target"]),
            build_platform=cast(str, build_identity["platform"]),
            manifest_sha256=compute_regular_file_sha256(manifest_path),
        )

    def publish_bundle(
        self,
        bundle_path: Path,
        *,
        expected_artifact_digest: str,
        registry_root: Path,
        environment: Mapping[str, str] | None = None,
    ) -> Path:
        """Stage, verify, and publish a bundle under its artifact digest.

        Create ``<registry_root>/sha256`` and a ``.publish.*`` staging directory below it,
        copy ``bundle_path`` with ``shutil.copytree(..., symlinks=False)``, and run
        ``verify_bundle`` against the staged copy. Source symlink entries are dereferenced
        during copying before staged verification, so a source link can become regular
        published content and may pass where direct verification of the source would reject
        it. Only the final ``registry_root`` component is rejected when it is a symlink;
        ancestor directories and an existing ``sha256`` symlink are followed, and the
        registry is not required to be inside ``repository_root``. After verification, check
        for an existing ``sha256/<artifact_sha256>`` destination and rename the staged
        bundle there. The existence check and rename are not an exclusive reservation, so
        concurrent publishers are not coordinated.

        The destination move is the publication boundary. Failures before it remove the
        temporary staging tree on a best-effort basis. If the move succeeds but the
        subsequent staging-directory ``rmdir`` fails, the function raises while the
        published digest directory remains. No registry transaction, source snapshot, or
        lock protects concurrent source changes during copying or verification.

        Args:
            bundle_path: Source bundle directory to copy. A relative path is interpreted
                from the process current working directory. Its entries are copied before
                the staged copy is verified; source symlinks are followed by ``copytree``.
            expected_artifact_digest: Immutable ``sha256:<64 lowercase hex>`` reference
                forwarded to ``verify_bundle``; it must match the staged manifest's artifact
                digest.
            registry_root: Root of the content-addressed registry. A relative path is
                interpreted from the process current working directory. The function creates
                or uses ``registry_root/sha256`` and returns
                ``registry_root/sha256/<artifact_digest>``; no repository containment check
                is performed.
            The repository root, policy, and process runner are bound by the constructor.
            environment: Environment mapping forwarded to ``verify_bundle``. ``None`` makes
                verification snapshot ``os.environ``; supplied mappings are copied by the
                delegated call and are not mutated.

        Returns:
            The published bundle directory at ``registry_root/sha256/<artifact_sha256>``,
            where ``artifact_sha256`` is the verified artifact digest without the
            ``sha256:`` prefix. The returned path preserves the relative or absolute
            form of ``registry_root``.

        Raises:
            ArtifactSupplyChainError: If ``registry_root`` is a symlink, staged verification
                fails, or the verified digest directory already exists or is a symlink.
            OSError: If registry directories or temporary staging cannot be created,
                copying, verification, renaming, cleanup, or other filesystem operations
                fail. A post-rename staging cleanup failure can leave the published
                directory in place while raising.
            shutil.Error: If ``copytree`` accumulates one or more source-copy errors.
            UnicodeDecodeError: If delegated verification or its runner encounters uncaught
                text-decoding failure.
            ValueError: If delegated verification propagates an unhandled parser value
                error.
            RecursionError: If delegated verification encounters excessively nested JSON.
            TypeError: If delegated verification receives malformed nested provenance.
            AttributeError: If delegated verification reaches an unsupported nested
                provenance shape.
            pydantic.ValidationError: If delegated verification rejects the final
                ``ArtifactBundle`` summary.
            RuntimeError: If delegated path resolution encounters a symlink loop.
        """
        repository_root = self.repository_root
        policy = self.policy
        runner = self.runner
        if registry_root.is_symlink():
            raise ArtifactSupplyChainError(["registry root must not be a symlink"])
        sha256_registry_root = registry_root / "sha256"
        sha256_registry_root.mkdir(parents=True, exist_ok=True)
        publication_staging_path = Path(
            tempfile.mkdtemp(prefix=".publish.", dir=sha256_registry_root)
        )
        try:
            staged_bundle_path = publication_staging_path / "bundle"
            shutil.copytree(bundle_path, staged_bundle_path, symlinks=False)
            verified_bundle = verify_bundle(
                staged_bundle_path,
                expected_artifact_digest=expected_artifact_digest,
                repository_root=repository_root,
                policy=policy,
                runner=runner,
                environment=environment,
            )
            published_bundle_path = sha256_registry_root / verified_bundle.artifact_sha256
            if published_bundle_path.exists() or published_bundle_path.is_symlink():
                raise ArtifactSupplyChainError(["immutable artifact digest is already published"])
            staged_bundle_path.rename(published_bundle_path)
            publication_staging_path.rmdir()
        except Exception:
            shutil.rmtree(publication_staging_path, ignore_errors=True)
            raise
        return published_bundle_path


class ArtifactSignerService:
    """Own signing operations while preserving the optional legacy repository context."""

    def __init__(
        self,
        policy: ArtifactSupplyChainPolicy,
        runner: ProcessRunner = _run_subprocess,
        repository_root: Path | None = None,
    ) -> None:
        """Bind signing policy and process collaborators without I/O.

        Args:
            policy: Already validated artifact policy owned by the signer.
            runner: Typed process callback used for Cosign operations.
            repository_root: Optional repository root retained for the historical signing
                contract; ``Path.cwd()`` is used when omitted.
        """
        self.repository_root = repository_root
        self.policy = policy
        self.runner = runner

    def _require_release_dependencies(self) -> None:
        """Require dependency admission using the signer's repository context."""
        repository_root = self.repository_root or Path.cwd()
        ArtifactBundleService._require_release_dependencies_for_root(repository_root)

    def sign_bundle(
        self,
        bundle_path: Path,
        *,
        signing_context: str,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        """Sign and verify a candidate with the policy-authorized Cosign context.

        Copy the supplied environment and require the exact trusted context and every
        policy-required environment value. Read the candidate manifest and require
        ``GITHUB_SHA`` to equal its build source commit. Reject an existing signature and
        require release dependency admission before any Cosign invocation. Run the admitted
        Cosign version check and ``sign-blob`` command with the candidate directory as the
        tool working directory, require a non-empty regular ``signature.sigstore.json``, and
        then call ``verify_bundle`` using the manifest artifact digest. Verification
        rechecks repository identities, dependency admission, bundle contents, provenance,
        SBOM coverage, signer identity, issuer, and the Cosign signature. This function
        checks CI facts supplied by the caller; it does not query GitHub or independently
        prove branch-protection state.

        The final signature path is written directly rather than through an atomic
        temporary-file replacement. If a failure occurs after the signing try-block begins,
        the function calls ``unlink(missing_ok=True)`` and re-raises; cleanup is not
        transactional, and an unlink failure can replace the original exception. Context,
        environment, manifest, and existing-signature failures occur before that cleanup
        scope; the initial Cosign-version check is also before it, while the
        verification-time Cosign check is inside it.

        Args:
            bundle_path: Candidate bundle directory containing ``manifest.json``. The
                signature is written in place at ``bundle_path/signature.sigstore.json``;
                the bundle directory is then passed to full verification. The function relies on the
                supplied spelling when forming tool argv; because Cosign runs with
                ``bundle_path`` as its current directory, callers should use an absolute
                path or otherwise ensure relative argv paths resolve as intended.
            signing_context: Context identifier that must equal
                ``policy.trusted_signing_context`` exactly.
            environment: Environment snapshot to copy for signing and verification. ``None``
                copies the current process environment. The copy must contain every
                policy-required name with its exact required value, and its ``GITHUB_SHA``
                must match the manifest's build ``sourceCommit``.

        Raises:
            ArtifactSupplyChainError: If the context, required environment, manifest build
                identity, artifact identity, dependency admission, Cosign version or signing
                result is invalid; a signature already exists or is not a non-empty regular
                file; or full bundle verification rejects any repository, manifest,
                provenance, SBOM, content, signer, issuer, or signature condition.
            OSError: If the bundle, repository, signature, or verification inputs cannot be
                inspected, read, hashed, written, or removed. The default subprocess runner
                translates a process-start error into ``ArtifactSupplyChainError``.
            ValueError: If manifest or verification JSON parsing raises an unhandled parser
                value error.
            RecursionError: If manifest or verification JSON nesting exceeds Python's
                recursion limit.
            TypeError: If malformed nested provenance data reaches an unhandled verification
                operation.
            AttributeError: If malformed nested provenance data reaches an unhandled
                verification operation.
            UnicodeDecodeError: If the default subprocess runner cannot decode captured
                Cosign output as text.
            RuntimeError: If delegated repository path resolution encounters a symlink loop.
        """
        policy = self.policy
        repository_root = self.repository_root
        runner = self.runner
        signing_environment = dict(os.environ if environment is None else environment)
        if signing_context != policy.trusted_signing_context:
            raise ArtifactSupplyChainError(["signing context is not trusted"])
        missing_environment_variables = tuple(
            environment_variable_name
            for environment_variable_name, required_value in policy.signing_environment
            if signing_environment.get(environment_variable_name) != required_value
        )
        if missing_environment_variables:
            raise ArtifactSupplyChainError(
                [
                    "protected signing environment is not established: "
                    f"{missing_environment_variables!r}"
                ]
            )
        artifact_manifest = _read_bounded_json_object(bundle_path / "manifest.json")
        build_identity = artifact_manifest.get("build")
        if not isinstance(build_identity, dict) or signing_environment.get(
            "GITHUB_SHA"
        ) != build_identity.get("sourceCommit"):
            raise ArtifactSupplyChainError(["GITHUB_SHA must equal the bundle source commit"])
        signature_path = bundle_path / "signature.sigstore.json"
        if signature_path.exists() or signature_path.is_symlink():
            raise ArtifactSupplyChainError(["signature bundle already exists"])
        self._require_release_dependencies()
        _verify_artifact_tool_version(
            policy.cosign,
            working_directory=bundle_path,
            environment=signing_environment,
            runner=runner,
        )
        try:
            _run_artifact_tool(
                [
                    policy.cosign.command,
                    "sign-blob",
                    "--yes",
                    "--bundle",
                    str(signature_path),
                    str(bundle_path / "manifest.json"),
                ],
                working_directory=bundle_path,
                environment=signing_environment,
                runner=runner,
            )
            if (
                signature_path.is_symlink()
                or not signature_path.is_file()
                or signature_path.stat().st_size < 1
            ):
                raise ArtifactSupplyChainError(
                    ["Cosign did not produce a non-empty signature bundle"]
                )
            artifact_identity = artifact_manifest.get("artifact")
            if not isinstance(artifact_identity, dict) or not isinstance(
                artifact_identity.get("sha256"), str
            ):
                raise ArtifactSupplyChainError(["manifest artifact identity is invalid"])
            verify_bundle(
                bundle_path,
                expected_artifact_digest=f"sha256:{artifact_identity['sha256']}",
                repository_root=Path.cwd() if repository_root is None else repository_root,
                policy=policy,
                runner=runner,
                environment=signing_environment,
            )
        except Exception:
            signature_path.unlink(missing_ok=True)
            raise


def create_bundle(
    artifact_path: Path,
    *,
    artifact_kind: str,
    build_target: str,
    source_commit: str,
    test_evidence_paths: tuple[Path, ...],
    output_path: Path,
    repository_root: Path,
    policy: ArtifactSupplyChainPolicy,
    runner: ProcessRunner = _run_subprocess,
    build_platform: str | None = None,
) -> ArtifactBundle:
    """Create an unsigned candidate bundle with normalized local metadata.

    Resolve ``repository_root`` before checking every policy-declared lock and the
    toolchain file, then require release dependency admission before invoking Syft.
    Validate the artifact and evidence inputs and the destination, then run the admitted
    Syft version check with the resolved repository as its working directory. Create a
    sibling temporary staging directory and copy the complete artifact into it. Run Syft
    on that copy with the resolved repository as its working directory, normalize the
    SPDX output, and require native-library coverage without extracting archive members.
    Copy the opaque evidence files in basename order and write canonical bundle metadata.
    The candidate is exposed at ``output_path`` only after the staging directory is
    renamed there. The source commit
    and Bazel target are syntax checked and recorded; this function does not build the
    artifact or inspect Git state.

    The admission, file checks, hashing, and copies are separate filesystem observations
    and therefore are not atomic. Failures after staging is allocated trigger
    best-effort removal of that staging directory; parent-directory creation and staging
    allocation occur before that cleanup scope, and no exclusive-create or rollback
    guarantee is provided if the final rename has completed.

    Args:
        artifact_path: Path to the one artifact file to bundle. Its final component must
            be a non-symlink regular file with a safe basename and a non-empty size
            within ``policy.maximum_artifact_bytes``. Relative paths follow the process
            current directory and are not interpreted relative to ``repository_root``.
            The path is not required to be inside ``repository_root``; the complete
            file is copied to ``artifact/<basename>``.
        artifact_kind: Artifact kind that must occur in
            ``policy.supported_artifact_kinds``. It is recorded in the manifest and
            provenance.
        build_target: Explicit Bazel label, such as ``//pkg:target`` or ``//:target``,
            recorded in the build identity and provenance. No Bazel command or
            target-output check is performed.
        source_commit: Lowercase 40-character Git SHA recorded in the build identity,
            provenance source URI, and returned summary. The spelling is checked, but
            the repository ``HEAD`` and the commit's existence are not queried.
        test_evidence_paths: Non-empty tuple of evidence files, limited to 1,000
            entries. Relative paths follow the process current directory and are not
            interpreted relative to ``repository_root``. Each final component must be a
            non-symlink regular file with a safe unique basename, a positive size, and
            at most 100 MiB. Files are copied in basename order to ``tests/`` and
            recorded with their copied digest and size; their contents are treated as
            opaque bytes, with no JSON or test-outcome validation.
        output_path: Destination directory for the candidate bundle. It must not exist,
            including as a symlink. Relative paths follow the process current directory
            and are not interpreted relative to ``repository_root``. Its parent is
            created as needed; staging uses a temporary sibling beneath that parent and
            the completed staging directory is renamed to this path.
        repository_root: Repository root used after resolution for lock and toolchain
            hashing, release dependency admission, the Syft working directory, and
            policy file hashing. The path need not be the process current directory.
            Delegated dependency admission may run its own local verifier and temporary
            trust-root handling; those operations do not use ``runner``.
        policy: Loaded artifact-supply-chain policy supplying permitted kinds and
            limits, expected lock and toolchain identities, provenance and SPDX
            settings, and admitted Syft and Cosign versions.
        runner: Process callback for Syft version and scan invocations. The default is
            ``_run_subprocess``; it receives the argv list, the resolved repository
            working directory, and a copied environment mapping. That environment starts
            as ``os.environ`` and overrides ``LC_ALL=C``, ``SOURCE_DATE_EPOCH=1``,
            ``SYFT_CHECK_FOR_APP_UPDATE=false``, ``SYFT_FILE_METADATA_SELECTION=all``,
            and ``TZ=UTC``. A nonzero completed status becomes
            ``ArtifactSupplyChainError``; exceptions raised by a custom callback
            propagate unchanged.
        build_platform: Optional platform identity to record in the build metadata. A
            falsey value, including ``None`` or an empty string, derives lowercase
            system and machine names joined by a hyphen; the resulting identity must
            match the governed lowercase platform pattern.

    Returns:
        An ``ArtifactBundle`` containing the artifact basename, kind, complete-file
        SHA-256 digest, source commit, build target, derived or supplied platform
        identity, and manifest SHA-256 digest. The record describes preparation only and
        does not indicate that the candidate is signed or verified.

    Raises:
        ArtifactSupplyChainError: If repository identities or release dependency
            admission fail; an input, output path, platform identity, tool version, Syft
            result, SPDX document, native-library inventory, or generated bundle record
            violates the governed contract; or the destination already exists.
        OSError: If resolving or inspecting paths, hashing, copying, creating
            directories or staging, writing or removing intermediate files, or renaming
            the completed candidate fails. The default subprocess runner translates a
            process-start error into ``ArtifactSupplyChainError``.
        ValueError: If bounded Syft JSON parsing raises an unhandled parser value error,
            such as an integer-conversion limit failure.
        RecursionError: If bounded Syft JSON parsing exceeds Python's recursion limit.
        UnicodeDecodeError: If the default subprocess runner cannot decode captured Syft
            output as text.
    """
    return ArtifactBundleService(policy, repository_root, runner).create_bundle(
        artifact_path,
        artifact_kind=artifact_kind,
        build_target=build_target,
        source_commit=source_commit,
        test_evidence_paths=test_evidence_paths,
        output_path=output_path,
        build_platform=build_platform,
    )


def sign_bundle(
    bundle_path: Path,
    *,
    signing_context: str,
    policy: ArtifactSupplyChainPolicy,
    repository_root: Path | None = None,
    runner: ProcessRunner = _run_subprocess,
    environment: Mapping[str, str] | None = None,
) -> None:
    """Sign and verify a candidate with the policy-authorized Cosign context.

    Copy the supplied environment and require the exact trusted context and every
    policy-required environment value. Read the candidate manifest and require
    ``GITHUB_SHA`` to equal its build source commit. Reject an existing signature and
    require release dependency admission before any Cosign invocation. Run the admitted
    Cosign version check and ``sign-blob`` command with the candidate directory as the
    tool working directory, require a non-empty regular ``signature.sigstore.json``, and
    then call ``verify_bundle`` using the manifest artifact digest. Verification
    rechecks repository identities, dependency admission, bundle contents, provenance,
    SBOM coverage, signer identity, issuer, and the Cosign signature. This function
    checks CI facts supplied by the caller; it does not query GitHub or independently
    prove branch-protection state.

    The final signature path is written directly rather than through an atomic
    temporary-file replacement. If a failure occurs after the signing try-block begins,
    the function calls ``unlink(missing_ok=True)`` and re-raises; cleanup is not
    transactional, and an unlink failure can replace the original exception. Context,
    environment, manifest, and existing-signature failures occur before that cleanup
    scope; the initial Cosign-version check is also before it, while the
    verification-time Cosign check is inside it.

    Returns:
        ``None`` after the signature is created and full bundle verification succeeds.

    Args:
        bundle_path: Candidate bundle directory containing ``manifest.json``. The
            signature is written in place at ``bundle_path/signature.sigstore.json``;
            the bundle directory is then passed to full verification. The function relies on the
            supplied spelling when forming tool argv; because Cosign runs with
            ``bundle_path`` as its current directory, callers should use an absolute
            path or otherwise ensure relative argv paths resolve as intended.
        signing_context: Context identifier that must equal
            ``policy.trusted_signing_context`` exactly.
        policy: Loaded artifact-supply-chain policy supplying the trusted context,
            required environment values, Cosign identity and issuer, and admitted Cosign
            version.
        repository_root: Optional repository root used for release dependency admission
            and passed to full verification. If ``None``, ``Path.cwd()`` is supplied at
            each of those calls; verification resolves that path internally.
        runner: Process callback for Cosign version, signing, and verification
            invocations. The default is ``_run_subprocess``; each call receives its
            argv, ``bundle_path`` as working directory, and a copied signing
            environment. Nonzero statuses become ``ArtifactSupplyChainError``;
            callback exceptions propagate subject to the signature cleanup described above.
        environment: Environment snapshot to copy for signing and verification. ``None``
            copies the current process environment. The copy must contain every
            policy-required name with its exact required value, and its ``GITHUB_SHA``
            must match the manifest's build ``sourceCommit``.

    Raises:
        ArtifactSupplyChainError: If the context, required environment, manifest build
            identity, artifact identity, dependency admission, Cosign version or signing
            result is invalid; a signature already exists or is not a non-empty regular
            file; or full bundle verification rejects any repository, manifest,
            provenance, SBOM, content, signer, issuer, or signature condition.
        OSError: If the bundle, repository, signature, or verification inputs cannot be
            inspected, read, hashed, written, or removed. The default subprocess runner
            translates a process-start error into ``ArtifactSupplyChainError``.
        ValueError: If manifest or verification JSON parsing raises an unhandled parser
            value error.
        RecursionError: If manifest or verification JSON nesting exceeds Python's
            recursion limit.
        TypeError: If malformed nested provenance data reaches an unhandled verification
            operation.
        AttributeError: If malformed nested provenance data reaches an unhandled
            verification operation.
        UnicodeDecodeError: If the default subprocess runner cannot decode captured
            Cosign output as text.
        RuntimeError: If delegated repository path resolution encounters a symlink loop.
    """
    return ArtifactSignerService(policy, runner, repository_root).sign_bundle(
        bundle_path,
        signing_context=signing_context,
        environment=environment,
    )


def _verify_file_digest_record(
    bundle_path: Path, value: object, *, context: str
) -> tuple[PurePosixPath, str, int]:
    """Verify one bundle file against its manifest path, digest, and size.

    Require the exact digest-record fields, including a 64-character lowercase
    hexadecimal SHA-256 digest and a positive non-Boolean integer byte count.
    Validate the path lexically as a bundle-relative POSIX path, then hash and
    stat the target file. The digest and size observations are separate and
    therefore non-atomic; parent-directory symlinks remain subject to normal path
    resolution, and no files are modified.

    Args:
        bundle_path: Bundle directory containing the recorded file.
        value: Candidate manifest record with ``path``, ``sha256``, and ``size``.
        context: Manifest field context used in validation findings.

    Returns:
        The validated relative path, expected lowercase SHA-256 digest, and size in bytes.

    Raises:
        ArtifactSupplyChainError: If the record shape or fields are invalid, the
            path is unsafe, the file is missing or unsafe, or content mismatches.
        OSError: If hashing or statting the target file fails.
    """
    if not _is_object_dict(value) or set(value) != _DIGESTED_FILE_RECORD_KEYS:
        raise ArtifactSupplyChainError([f"{context} has missing or unknown fields"])
    relative_path = _parse_safe_bundle_relative_path(value.get("path"), context=f"{context}.path")
    expected_digest = value.get("sha256")
    expected_size = value.get("size")
    if (
        not isinstance(expected_digest, str)
        or _LOWERCASE_SHA256_PATTERN.fullmatch(expected_digest) is None
    ):
        raise ArtifactSupplyChainError([f"{context}.sha256 is invalid"])
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 1:
        raise ArtifactSupplyChainError([f"{context}.size is invalid"])
    resolved_file_path = bundle_path.joinpath(*relative_path.parts)
    if (
        compute_regular_file_sha256(resolved_file_path) != expected_digest
        or resolved_file_path.stat().st_size != expected_size
    ):
        raise ArtifactSupplyChainError([f"{context} content does not match its digest and size"])
    return relative_path, expected_digest, expected_size


def verify_bundle(
    bundle_path: Path,
    *,
    expected_artifact_digest: str,
    repository_root: Path,
    policy: ArtifactSupplyChainPolicy,
    runner: ProcessRunner = _run_subprocess,
    environment: Mapping[str, str] | None = None,
) -> ArtifactBundle:
    """Verify a signed bundle against an exact artifact digest and policy.

    Require ``expected_artifact_digest`` to be ``sha256:<64 lowercase hex>``, reject a
    symlink or non-directory bundle, and resolve ``repository_root`` before checking its
    policy-declared lock and toolchain digests and release-dependency admission. Reject
    symlinks discovered below ``bundle_path``, read the bounded manifest, enforce its
    selected schemas and identities, hash the artifact and every manifest-recorded file,
    and require the expected regular-file set. Check selected in-toto provenance
    identities and dependencies, the SBOM identity and native-library coverage, and a
    non-revoked configured signer with a non-empty signature bundle. Finally run the
    admitted Cosign version and ``verify-blob`` with the policy's certificate identity
    and OIDC issuer.

    The function itself does not write bundle or repository paths. Release-dependency
    admission may stage temporary private trust-root material and run its local verifier
    with its own helper environment. The default runner executes the admitted external
    Cosign commands without a timeout or offline mode, so its normal external-service
    behavior applies. An injected runner's successful result is accepted as supplied and
    does not itself establish cryptographic evidence.

    The bounded JSON reader limits the manifest, provenance, and SBOM documents to 100
    MiB before reading. Archive inventory applies ``policy.maximum_archive_members``
    after materializing member names; members are inventoried but never extracted.
    Verification does not reapply ``create_bundle``'s ``maximum_artifact_bytes`` or
    1,000 test-evidence count caps; test evidence is hashed and stat'ed only, never
    parsed or checked for an outcome. The checks cover selected manifest, provenance,
    and SPDX fields rather than providing full in-toto or SPDX schema validation. Digest
    and size observations are separate, non-atomic operations with no snapshot or lock;
    parent-directory symlinks remain followed.

    The ``sourceCommit`` field is pattern-checked through ``str(...)`` before
    ``ArtifactBundle`` is built. A non-string value can pass that check, such as a
    40-digit JSON integer, but strict model construction then raises
    ``pydantic.ValidationError``; it is not returned as an arbitrary parsed type.

    Args:
        bundle_path: Bundle directory to inspect. Python file operations interpret
            relative paths from the process current directory. Cosign receives the
            supplied path spelling in argv while running in this directory; use an
            absolute path or ensure relative argv paths resolve as intended.
        expected_artifact_digest: Immutable consumer reference that must exactly match
            ``sha256:`` followed by 64 lowercase hexadecimal characters and the manifest
            artifact digest.
        repository_root: Repository root used for current lock, toolchain, policy, and
            release-dependency checks. It is resolved before those checks; relative
            input is based on the process current working directory.
        policy: Loaded artifact-supply-chain policy supplying permitted artifact kinds,
            exact repository identities, archive-member limit, SBOM and provenance
            identities, tool versions, signer identity, and OIDC issuer.
        runner: Process callback for the Cosign version and verification commands.
            Defaults to ``_run_subprocess``, which uses ``bundle_path`` as the child
            working directory, passes a copy of ``environment``, captures decoded text
            without a timeout, and translates process-startup errors;
            ``_run_artifact_tool`` translates nonzero statuses to
            ``ArtifactSupplyChainError`` and other callback exceptions propagate.
        environment: Complete environment mapping for Cosign version and verification
            calls. ``None`` snapshots ``os.environ``; a supplied mapping is copied and
            is not mutated. Release-dependency admission uses its own helper
            environment.

    Returns:
        An ``ArtifactBundle`` summary containing the verified artifact name, permitted
        kind, artifact SHA-256 digest, source commit, Bazel target, declared build
        platform, and the SHA-256 digest of the manifest bytes observed at return.

    Raises:
        ArtifactSupplyChainError: If the immutable reference, bundle directory, symlink
            policy, repository identities, release-dependency admission, manifest
            structure, selected provenance or SBOM claims, native-library coverage, file
            digest or size, signer status, signature presence, Cosign version, or Cosign
            verification fails. The default runner translates process-startup failures
            here, and ``_run_artifact_tool`` translates nonzero tool statuses here.
        OSError: If an unhandled repository or bundle filesystem operation fails while
            resolving paths, traversing, reading, hashing, statting, or inventorying
            files; a custom runner may also propagate its filesystem errors.
        UnicodeDecodeError: If an uncaught repository text read or runner output cannot
            be decoded; invalid JSON-file UTF-8 is translated to
            ``ArtifactSupplyChainError``.
        ValueError: If JSON contains an integer exceeding the interpreter's conversion
            limit or another parser value error escapes the bounded JSON helper.
        RecursionError: If JSON nesting exceeds the decoder's recursion limit.
        TypeError: If malformed nested provenance reaches an operation that the runtime
            casts do not narrow.
        AttributeError: If malformed nested provenance supplies a shape that passes the
            preceding key-set checks but has no mapping ``get`` method.
        pydantic.ValidationError: If strict ``ArtifactBundle`` construction rejects a
            parsed field, including a non-string ``sourceCommit`` that passed its
            textual pattern check.
        RuntimeError: If path resolution encounters a symlink loop.
    """
    return ArtifactBundleService(policy, repository_root, runner).verify_bundle(
        bundle_path,
        expected_artifact_digest=expected_artifact_digest,
        environment=environment,
    )


def publish_bundle(
    bundle_path: Path,
    *,
    expected_artifact_digest: str,
    registry_root: Path,
    repository_root: Path,
    policy: ArtifactSupplyChainPolicy,
    runner: ProcessRunner = _run_subprocess,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Stage, verify, and publish a bundle under its artifact digest.

    Create ``<registry_root>/sha256`` and a ``.publish.*`` staging directory below it,
    copy ``bundle_path`` with ``shutil.copytree(..., symlinks=False)``, and run
    ``verify_bundle`` against the staged copy. Source symlink entries are dereferenced
    during copying before staged verification, so a source link can become regular
    published content and may pass where direct verification of the source would reject
    it. Only the final ``registry_root`` component is rejected when it is a symlink;
    ancestor directories and an existing ``sha256`` symlink are followed, and the
    registry is not required to be inside ``repository_root``. After verification, check
    for an existing ``sha256/<artifact_sha256>`` destination and rename the staged
    bundle there. The existence check and rename are not an exclusive reservation, so
    concurrent publishers are not coordinated.

    The destination move is the publication boundary. Failures before it remove the
    temporary staging tree on a best-effort basis. If the move succeeds but the
    subsequent staging-directory ``rmdir`` fails, the function raises while the
    published digest directory remains. No registry transaction, source snapshot, or
    lock protects concurrent source changes during copying or verification.

    Args:
        bundle_path: Source bundle directory to copy. A relative path is interpreted
            from the process current working directory. Its entries are copied before
            the staged copy is verified; source symlinks are followed by ``copytree``.
        expected_artifact_digest: Immutable ``sha256:<64 lowercase hex>`` reference
            forwarded to ``verify_bundle``; it must match the staged manifest's artifact
            digest.
        registry_root: Root of the content-addressed registry. A relative path is
            interpreted from the process current working directory. The function creates
            or uses ``registry_root/sha256`` and returns
            ``registry_root/sha256/<artifact_digest>``; no repository containment check
            is performed.
        repository_root: Repository root forwarded to ``verify_bundle`` for resolved
            policy, lock, toolchain, policy-file, and release-dependency checks.
        policy: Loaded artifact-supply-chain policy forwarded to ``verify_bundle``.
        runner: Process callback forwarded to ``verify_bundle`` for Cosign version and
            verification calls. Defaults to ``_run_subprocess``; its working directory
            for those calls is the staged bundle; the default runner has no timeout or
            offline mode.
        environment: Environment mapping forwarded to ``verify_bundle``. ``None`` makes
            verification snapshot ``os.environ``; supplied mappings are copied by the
            delegated call and are not mutated.

    Returns:
        The published bundle directory at ``registry_root/sha256/<artifact_sha256>``,
        where ``artifact_sha256`` is the verified artifact digest without the
        ``sha256:`` prefix. The returned path preserves the relative or absolute
        form of ``registry_root``.

    Raises:
        ArtifactSupplyChainError: If ``registry_root`` is a symlink, staged verification
            fails, or the verified digest directory already exists or is a symlink.
        OSError: If registry directories or temporary staging cannot be created,
            copying, verification, renaming, cleanup, or other filesystem operations
            fail. A post-rename staging cleanup failure can leave the published
            directory in place while raising.
        shutil.Error: If ``copytree`` accumulates one or more source-copy errors.
        UnicodeDecodeError: If delegated verification or its runner encounters uncaught
            text-decoding failure.
        ValueError: If delegated verification propagates an unhandled parser value
            error.
        RecursionError: If delegated verification encounters excessively nested JSON.
        TypeError: If delegated verification receives malformed nested provenance.
        AttributeError: If delegated verification reaches an unsupported nested
            provenance shape.
        pydantic.ValidationError: If delegated verification rejects the final
            ``ArtifactBundle`` summary.
        RuntimeError: If delegated path resolution encounters a symlink loop.
    """
    return ArtifactBundleService(policy, repository_root, runner).publish_bundle(
        bundle_path,
        expected_artifact_digest=expected_artifact_digest,
        registry_root=registry_root,
        environment=environment,
    )
