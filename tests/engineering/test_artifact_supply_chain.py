"""Focused tests for artifact identity, integrity, and path boundaries."""

from __future__ import annotations

# standard library imports
import json
import subprocess
import zipfile
from collections.abc import Mapping
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.artifact_supply_chain import (
    ArtifactSupplyChainError,
    create_bundle,
    load_policy,
    sign_bundle,
    validate_repository,
    verify_bundle,
)
from alpha_research_governance.artifact_supply_chain.policy import compute_regular_file_sha256

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs/architecture/artifact-supply-chain.toml"
SOURCE_COMMIT = "a" * 40


def _allow_release(_root: Path) -> None:
    """Allow the isolated bundle fixture to exercise artifact behavior.

    Args:
        _root: Repository root supplied by the release gate.
    """


class DeterministicToolRunner:
    """Simulate Syft and Cosign with deterministic local fixture files."""

    def __init__(self, *, native_files: tuple[str, ...] = ("lib/libnative.so",)) -> None:
        """Set the SBOM native inventory and command history.

        Args:
            native_files: Archive member names reported by the synthetic SBOM.
        """
        self.native_files = native_files
        self.commands: list[tuple[str, ...]] = []
        self.failure: str | None = None

    def __call__(
        self, command: list[str], working_directory: Path, environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        """Record and execute one deterministic tool simulation.

        Args:
            command: Tool argv supplied by the artifact boundary.
            working_directory: Unused fixture working directory.
            environment: Process environment supplied by the boundary.

        Returns:
            A synthetic completed-process result.

        Raises:
            AssertionError: If the boundary requests an unsupported invocation.
        """
        del working_directory
        self.commands.append(tuple(command))
        if self.failure == command[0]:
            return subprocess.CompletedProcess(command, 7, "", "synthetic failure")
        if command[:2] == ["syft", "version"]:
            return subprocess.CompletedProcess(command, 0, "Version:       1.51.1\n", "")
        if command[:2] == ["cosign", "version"]:
            return subprocess.CompletedProcess(command, 0, "GitVersion:    v3.1.3\n", "")
        if command[:2] == ["syft", "scan"]:
            assert environment["SYFT_FILE_METADATA_SELECTION"] == "all"
            output = Path(command[command.index("--output") + 1].split("=", 1)[1])
            files: list[dict[str, str]] = [
                {"SPDXID": f"SPDXRef-{index}", "fileName": name}
                for index, name in enumerate(self.native_files)
            ]
            sbom: dict[str, object] = {
                "SPDXID": "SPDXRef-DOCUMENT",
                "creationInfo": {
                    "created": "2026-09-07T00:00:00Z",
                    "creators": ["Tool: syft-1.51.1"],
                },
                "dataLicense": "CC0-1.0",
                "documentNamespace": "https://syft.invalid/fixture",
                "files": files,
                "name": "fixture",
                "packages": [],
                "relationships": [],
                "spdxVersion": "SPDX-2.3",
            }
            output.write_text(
                json.dumps(sbom),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["cosign", "sign-blob"]:
            bundle = Path(command[command.index("--bundle") + 1])
            bundle.write_text(
                '{"mediaType":"application/vnd.dev.sigstore.bundle.v0.3+json"}\n', encoding="utf-8"
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["cosign", "verify-blob"]:
            return subprocess.CompletedProcess(command, 0, "Verified OK\n", "")
        raise AssertionError(f"unsupported fixture command: {command!r}")


def _fixture_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """Create a small archive and passed-test report for bundle creation."""
    artifact = tmp_path / "service.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("bin/service", "executable")
        archive.writestr("lib/libnative.so", "native")
    tests = tmp_path / "tests.json"
    tests.write_text('{"outcome":"passed"}\n', encoding="utf-8")
    return artifact, tests


def test_policy_and_repository_file_identities_are_current() -> None:
    """Accept the compact policy and its current project/lock bytes."""
    policy = validate_repository(REPOSITORY_ROOT)
    assert policy.project_path == "pyproject.toml"
    assert tuple(lock.path for lock in policy.locks) == ("uv.lock",)
    assert policy.syft.version == "1.51.1"
    assert policy.cosign.version == "3.1.3"


def test_regular_file_digest_rejects_symlinks_and_directories(tmp_path: Path) -> None:
    """Keep artifact policy hashes fail-closed for unsafe final path components."""
    regular = tmp_path / "regular.txt"
    regular.write_text("bytes", encoding="utf-8")
    assert compute_regular_file_sha256(regular)
    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(ArtifactSupplyChainError, match="missing or unsafe"):
        compute_regular_file_sha256(directory)
    link = tmp_path / "link.txt"
    link.symlink_to(regular)
    with pytest.raises(ArtifactSupplyChainError, match="missing or unsafe"):
        compute_regular_file_sha256(link)


def test_policy_rejects_unknown_fields_and_floating_tools(tmp_path: Path) -> None:
    """Keep the artifact policy closed and tool identities pinned."""
    source = POLICY_PATH.read_text(encoding="utf-8")
    unknown = tmp_path / "unknown.toml"
    unknown.write_text(
        source.replace("schema_version = 2", "schema_version = 2\nunknown = true"), encoding="utf-8"
    )
    with pytest.raises(ArtifactSupplyChainError, match="root"):
        load_policy(unknown)
    floating = tmp_path / "floating.toml"
    floating.write_text(
        source.replace('version = "1.51.1"', 'version = "latest"'), encoding="utf-8"
    )
    with pytest.raises(ArtifactSupplyChainError, match="pinned"):
        load_policy(floating)


def test_bundle_lifecycle_preserves_tamper_and_release_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Create, sign, and verify a deterministic bundle, then reject tampering."""
    policy = load_policy(POLICY_PATH)
    artifact, tests = _fixture_inputs(tmp_path)

    monkeypatch.setattr(
        "alpha_research_governance.artifact_supply_chain.bundle.require_release_admission",
        _allow_release,
    )
    bundle_path = tmp_path / "bundle"
    runner = DeterministicToolRunner()
    bundle = create_bundle(
        artifact,
        artifact_kind="binary",
        build_command="uv build --no-build-isolation --wheel --no-sources",
        source_commit=SOURCE_COMMIT,
        test_evidence_paths=(tests,),
        output_path=bundle_path,
        repository_root=REPOSITORY_ROOT,
        policy=policy,
        runner=runner,
        build_platform="darwin-arm64",
    )
    sign_bundle(
        bundle_path,
        signing_context="github_protected_main",
        policy=policy,
        repository_root=REPOSITORY_ROOT,
        runner=runner,
        environment={
            "GITHUB_ACTIONS": "true",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_REF_PROTECTED": "true",
            "GITHUB_SHA": SOURCE_COMMIT,
        },
    )
    verified = verify_bundle(
        bundle_path,
        expected_artifact_digest=f"sha256:{bundle.artifact_sha256}",
        repository_root=REPOSITORY_ROOT,
        policy=policy,
        runner=runner,
    )
    assert verified.artifact_sha256 == bundle.artifact_sha256
    manifest = bundle_path / "manifest.json"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("binary", "model", 1), encoding="utf-8"
    )
    with pytest.raises(ArtifactSupplyChainError):
        verify_bundle(
            bundle_path,
            expected_artifact_digest=f"sha256:{bundle.artifact_sha256}",
            repository_root=REPOSITORY_ROOT,
            policy=policy,
            runner=runner,
        )


def test_release_gate_blocks_artifact_creation_with_unresolved_native_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure the actual dependency gate runs before artifact tools."""
    policy = load_policy(POLICY_PATH)
    artifact, tests = _fixture_inputs(tmp_path)
    calls: list[str] = []

    def deny(root: Path) -> None:
        """Record the release gate and reject the unresolved native binding.

        Args:
            root: Repository root presented to the release gate.

        Raises:
            DependencyError: Always, to model unresolved dependency admission.
        """
        calls.append(str(root))
        raise DependencyError(["release blocked"])

    class DependencyError(ArtifactSupplyChainError):
        """Synthetic release-gate failure used by this boundary test."""

    monkeypatch.setattr(
        "alpha_research_governance.artifact_supply_chain.bundle.require_release_admission", deny
    )
    with pytest.raises(ArtifactSupplyChainError, match="release blocked"):
        create_bundle(
            artifact,
            artifact_kind="binary",
            build_command="uv build --no-build-isolation --wheel --no-sources",
            source_commit=SOURCE_COMMIT,
            test_evidence_paths=(tests,),
            output_path=tmp_path / "blocked",
            repository_root=REPOSITORY_ROOT,
            policy=policy,
            runner=DeterministicToolRunner(),
            build_platform="darwin-arm64",
        )
    assert calls == [str(REPOSITORY_ROOT)]
