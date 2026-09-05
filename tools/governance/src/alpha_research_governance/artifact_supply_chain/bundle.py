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
from typing import cast

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


def _serialize_canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _write_canonical_json(path: Path, value: object) -> None:
    path.write_bytes(_serialize_canonical_json(value))


def _build_mapping_rejecting_duplicate_json_keys(
    key_value_pairs: list[tuple[str, object]],
) -> dict[str, object]:
    parsed_mapping: dict[str, object] = {}
    for key, value in key_value_pairs:
        if key in parsed_mapping:
            raise ArtifactSupplyChainError([f"JSON contains duplicate key {key!r}"])
        parsed_mapping[key] = value
    return parsed_mapping


def _read_bounded_json_object(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ArtifactSupplyChainError([f"required bundle file is missing or unsafe: {path.name}"])
    if path.stat().st_size > _MAXIMUM_JSON_DOCUMENT_BYTES:
        raise ArtifactSupplyChainError([f"{path.name} exceeds the governed JSON size limit"])
    try:
        parsed_document = json.loads(
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
    return {
        "path": relative_path,
        "sha256": compute_regular_file_sha256(path),
        "size": path.stat().st_size,
    }


def _is_native_library_path(name: str) -> bool:
    lowercase_filename = PurePosixPath(name).name.lower()
    return lowercase_filename.endswith((".dll", ".dylib", ".so")) or ".so." in (lowercase_filename)


def _discover_native_library_paths(
    path: Path, policy: ArtifactSupplyChainPolicy
) -> tuple[str, ...]:
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
    creation_information = raw_spdx_document.get("creationInfo")
    if (
        raw_spdx_document.get("spdxVersion") != "SPDX-2.3"
        or raw_spdx_document.get("SPDXID") != "SPDXRef-DOCUMENT"
        or raw_spdx_document.get("dataLicense") != "CC0-1.0"
        or not isinstance(creation_information, dict)
        or not isinstance(creation_information.get("creators"), list)
        or "Tool: syft-1.51.1" not in creation_information["creators"]
    ):
        raise ArtifactSupplyChainError(["Syft output is not a complete SPDX-2.3 document"])
    normalized_spdx_document = dict(raw_spdx_document)
    normalized_spdx_document["name"] = artifact_name
    normalized_spdx_document["documentNamespace"] = (
        f"https://alpha-research.invalid/spdx/sha256/{artifact_digest}"
    )
    normalized_creation_information = dict(cast(dict[str, object], creation_information))
    normalized_creation_information["created"] = "1970-01-01T00:00:01Z"
    normalized_spdx_document["creationInfo"] = normalized_creation_information
    for key in ("files", "packages", "relationships"):
        spdx_entries = normalized_spdx_document.get(key)
        if isinstance(spdx_entries, list):
            normalized_spdx_document[key] = sorted(
                spdx_entries, key=lambda item: _serialize_canonical_json(item)
            )
    return normalized_spdx_document


def _extract_spdx_file_names(sbom: Mapping[str, object]) -> frozenset[str]:
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


def _verify_current_repository_identities(
    repository_root: Path, policy: ArtifactSupplyChainPolicy
) -> None:
    for lock_identity in policy.locks:
        if (
            compute_regular_file_sha256(repository_root / lock_identity.path)
            != lock_identity.sha256
        ):
            raise ArtifactSupplyChainError(
                [f"repository lock identity drifted: {lock_identity.path}"]
            )
    if (
        compute_regular_file_sha256(repository_root / policy.toolchain_path)
        != policy.toolchain_sha256
    ):
        raise ArtifactSupplyChainError(["repository toolchain identity drifted"])
    _require_release_dependencies(repository_root)


def _require_release_dependencies(repository_root: Path) -> None:
    try:
        require_release_admission(repository_root)
    except (DependencyAdmissionError, OSError, ValueError) as error:
        raise ArtifactSupplyChainError(
            [f"artifact dependency admission failed: {error}"]
        ) from error


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
    """Create an unsigned, deterministic whole-artifact candidate bundle."""
    resolved_repository_root = repository_root.resolve()
    _verify_current_repository_identities(resolved_repository_root, policy)
    if artifact_kind not in policy.supported_artifact_kinds:
        raise ArtifactSupplyChainError([f"unsupported artifact kind: {artifact_kind!r}"])
    if _EXPLICIT_BAZEL_TARGET_PATTERN.fullmatch(build_target) is None:
        raise ArtifactSupplyChainError(["build target must be an explicit Bazel label"])
    if _LOWERCASE_GIT_COMMIT_SHA_PATTERN.fullmatch(source_commit) is None:
        raise ArtifactSupplyChainError(["source commit must be a lowercase 40-character Git SHA"])
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
        for test_evidence_path in sorted(test_evidence_paths, key=lambda item: item.name):
            stored_test_evidence = bundled_test_evidence_directory / test_evidence_path.name
            shutil.copyfile(test_evidence_path, stored_test_evidence)
            test_evidence_digest_records.append(
                _build_file_digest_record(stored_test_evidence, f"tests/{test_evidence_path.name}")
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


def sign_bundle(
    bundle_path: Path,
    *,
    signing_context: str,
    policy: ArtifactSupplyChainPolicy,
    repository_root: Path | None = None,
    runner: ProcessRunner = _run_subprocess,
    environment: Mapping[str, str] | None = None,
) -> None:
    """Sign a candidate only in the exact protected-main keyless context."""
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
            [f"protected signing environment is not established: {missing_environment_variables!r}"]
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
    _require_release_dependencies(Path.cwd() if repository_root is None else repository_root)
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
            raise ArtifactSupplyChainError(["Cosign did not produce a non-empty signature bundle"])
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


def _verify_file_digest_record(
    bundle_path: Path, value: object, *, context: str
) -> tuple[PurePosixPath, str, int]:
    if not isinstance(value, dict) or set(value) != _DIGESTED_FILE_RECORD_KEYS:
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
    """Verify a signed bundle against an explicit immutable artifact digest."""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_artifact_digest):
        raise ArtifactSupplyChainError(
            ["consumer must supply an immutable sha256:<digest> reference"]
        )
    if bundle_path.is_symlink() or not bundle_path.is_dir():
        raise ArtifactSupplyChainError(["bundle must be a regular directory"])
    resolved_repository_root = repository_root.resolve()
    _verify_current_repository_identities(resolved_repository_root, policy)
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
    if not isinstance(artifact_identity, dict) or set(artifact_identity) != _ARTIFACT_IDENTITY_KEYS:
        raise ArtifactSupplyChainError(["manifest artifact has missing or unknown fields"])
    if not isinstance(build_identity, dict) or set(build_identity) != _BUILD_IDENTITY_KEYS:
        raise ArtifactSupplyChainError(["manifest build has missing or unknown fields"])
    if (
        not isinstance(toolchain_identity, dict)
        or set(toolchain_identity) != _TOOLCHAIN_IDENTITY_KEYS
    ):
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
        raise ArtifactSupplyChainError(["artifact digest does not match the consumer reference"])
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
    if not isinstance(policy_identity_record, dict) or set(policy_identity_record) != {
        "path",
        "sha256",
    }:
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
        artifact_kind=cast(str, artifact_kind),
        artifact_sha256=artifact_digest,
        source_commit=cast(str, build_identity["sourceCommit"]),
        build_target=cast(str, build_identity["target"]),
        build_platform=cast(str, build_identity["platform"]),
        manifest_sha256=compute_regular_file_sha256(manifest_path),
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
    """Publish once to a repository-local content-addressed registry."""
    if registry_root.is_symlink():
        raise ArtifactSupplyChainError(["registry root must not be a symlink"])
    sha256_registry_root = registry_root / "sha256"
    sha256_registry_root.mkdir(parents=True, exist_ok=True)
    publication_staging_path = Path(tempfile.mkdtemp(prefix=".publish.", dir=sha256_registry_root))
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
