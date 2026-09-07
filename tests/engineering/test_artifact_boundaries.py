"""Regression tests for retained artifact lifecycle boundaries."""

from __future__ import annotations

# standard library imports
import json
import subprocess
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import cast

# third party library imports
import pytest

# project library imports
from alpha_research_governance.artifact_supply_chain import (
    ArtifactSupplyChainError,
    ArtifactSupplyChainPolicy,
    create_bundle,
    load_policy,
    publish_bundle,
    sign_bundle,
    verify_bundle,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs/architecture/artifact-supply-chain.toml"
BUILD_COMMAND = "uv build --no-build-isolation --wheel --no-sources"
SOURCE_COMMIT = "a" * 40
SIGNING_ENVIRONMENT = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_REF_PROTECTED": "true",
    "GITHUB_SHA": SOURCE_COMMIT,
}


class DeterministicToolRunner:
    """Simulate pinned Syft and Cosign calls without network access."""

    def __init__(self, *, native_files: tuple[str, ...] = ("lib/libnative.so",)) -> None:
        """Initialize the synthetic native inventory and command history.

        Args:
            native_files: Archive member names emitted by the synthetic SBOM.
        """
        self.native_files = native_files
        self.commands: list[tuple[str, ...]] = []
        self.failure: tuple[str, str] | None = None

    def __call__(
        self, command: list[str], working_directory: Path, environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        """Return deterministic tool output for one lifecycle invocation.

        Args:
            command: Tool argv supplied by the artifact boundary.
            working_directory: Tool working directory, unused by this fake.
            environment: Environment supplied to the tool invocation.

        Returns:
            A synthetic completed process result.

        Raises:
            AssertionError: If the lifecycle requests an unsupported command.
        """
        del working_directory
        self.commands.append(tuple(command))
        if self.failure == tuple(command[:2]):
            return subprocess.CompletedProcess(command, 7, "", "synthetic failure")
        if command[:2] == ["syft", "version"]:
            return subprocess.CompletedProcess(command, 0, "Version:       1.51.1\n", "")
        if command[:2] == ["cosign", "version"]:
            return subprocess.CompletedProcess(command, 0, "GitVersion:    v3.1.3\n", "")
        if command[:2] == ["syft", "scan"]:
            assert environment["SYFT_FILE_METADATA_SELECTION"] == "all"
            output_path = Path(command[command.index("--output") + 1].split("=", 1)[1])
            sbom_document: dict[str, object] = {
                "SPDXID": "SPDXRef-DOCUMENT",
                "creationInfo": {
                    "created": "2026-09-07T00:00:00Z",
                    "creators": ["Tool: syft-1.51.1"],
                },
                "dataLicense": "CC0-1.0",
                "documentNamespace": "https://syft.invalid/fixture",
                "files": [
                    {"SPDXID": f"SPDXRef-{index}", "fileName": name}
                    for index, name in enumerate(self.native_files)
                ],
                "name": "fixture",
                "packages": [],
                "relationships": [],
                "spdxVersion": "SPDX-2.3",
            }
            output_path.write_text(
                json.dumps(cast(object, sbom_document)),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["cosign", "sign-blob"]:
            signature_path = Path(command[command.index("--bundle") + 1])
            signature_path.write_text(
                '{"mediaType":"application/vnd.dev.sigstore.bundle.v0.3+json"}\n',
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["cosign", "verify-blob"]:
            return subprocess.CompletedProcess(command, 0, "Verified OK\n", "")
        raise AssertionError(f"unsupported fixture command: {command!r}")


@pytest.fixture(autouse=True)
def _allow_synthetic_release_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep lifecycle tests focused on artifact boundaries."""
    monkeypatch.setattr(
        "alpha_research_governance.artifact_supply_chain.bundle.require_release_admission",
        _allow_release_admission,
    )


def _allow_release_admission(_root: Path) -> None:
    """Allow deterministic local fixtures to exercise artifact operations."""


def _fixture_inputs(
    tmp_path: Path,
    *,
    member_names: tuple[str, ...] = ("bin/service", "lib/libnative.so"),
) -> tuple[Path, Path]:
    """Create one ZIP artifact and one opaque test-evidence file."""
    artifact_path = tmp_path / "service.zip"
    with zipfile.ZipFile(artifact_path, "w") as archive:
        for member_name in member_names:
            archive.writestr(member_name, member_name.encode("utf-8"))
    evidence_path = tmp_path / "tests.json"
    evidence_path.write_text('{"outcome":"passed"}\n', encoding="utf-8")
    return artifact_path, evidence_path


def _create_candidate(
    tmp_path: Path,
    policy: ArtifactSupplyChainPolicy,
    runner: DeterministicToolRunner,
    *,
    name: str = "candidate",
    member_names: tuple[str, ...] = ("bin/service", "lib/libnative.so"),
) -> tuple[Path, str]:
    """Create one unsigned candidate and its immutable digest reference."""
    artifact_path, evidence_path = _fixture_inputs(tmp_path, member_names=member_names)
    bundle_path = tmp_path / name
    bundle = create_bundle(
        artifact_path,
        artifact_kind="binary",
        build_command=BUILD_COMMAND,
        source_commit=SOURCE_COMMIT,
        test_evidence_paths=(evidence_path,),
        output_path=bundle_path,
        repository_root=REPOSITORY_ROOT,
        policy=policy,
        runner=runner,
        build_platform="darwin-arm64",
    )
    return bundle_path, f"sha256:{bundle.artifact_sha256}"


def _sign_candidate(
    bundle_path: Path, policy: ArtifactSupplyChainPolicy, runner: DeterministicToolRunner
) -> None:
    """Sign a candidate with the protected-main synthetic context."""
    sign_bundle(
        bundle_path,
        signing_context="github_protected_main",
        policy=policy,
        repository_root=REPOSITORY_ROOT,
        runner=runner,
        environment=SIGNING_ENVIRONMENT,
    )


@pytest.fixture()
def artifact_policy() -> ArtifactSupplyChainPolicy:
    """Load the checked-in artifact policy used by lifecycle tests.

    Returns:
        The validated local artifact policy.
    """
    return load_policy(POLICY_PATH)


def test_full_lifecycle_publishes_once_and_requires_exact_digest(
    tmp_path: Path, artifact_policy: ArtifactSupplyChainPolicy
) -> None:
    """Create, sign, verify, and publish exactly one immutable digest."""
    runner = DeterministicToolRunner()
    bundle_path, digest_reference = _create_candidate(tmp_path, artifact_policy, runner)
    _sign_candidate(bundle_path, artifact_policy, runner)

    verified = verify_bundle(
        bundle_path,
        expected_artifact_digest=digest_reference,
        repository_root=REPOSITORY_ROOT,
        policy=artifact_policy,
        runner=runner,
        environment=SIGNING_ENVIRONMENT,
    )
    assert f"sha256:{verified.artifact_sha256}" == digest_reference
    published_path = publish_bundle(
        bundle_path,
        expected_artifact_digest=digest_reference,
        registry_root=tmp_path / "registry",
        repository_root=REPOSITORY_ROOT,
        policy=artifact_policy,
        runner=runner,
        environment=SIGNING_ENVIRONMENT,
    )
    assert published_path == tmp_path / "registry" / "sha256" / digest_reference.removeprefix(
        "sha256:"
    )
    with pytest.raises(ArtifactSupplyChainError, match="already published"):
        publish_bundle(
            bundle_path,
            expected_artifact_digest=digest_reference,
            registry_root=tmp_path / "registry",
            repository_root=REPOSITORY_ROOT,
            policy=artifact_policy,
            runner=runner,
            environment=SIGNING_ENVIRONMENT,
        )
    with pytest.raises(ArtifactSupplyChainError, match="does not match the consumer reference"):
        verify_bundle(
            bundle_path,
            expected_artifact_digest=f"sha256:{'b' * 64}",
            repository_root=REPOSITORY_ROOT,
            policy=artifact_policy,
            runner=runner,
            environment=SIGNING_ENVIRONMENT,
        )


def test_tampered_artifact_provenance_and_signature_identity_fail_closed(
    tmp_path: Path, artifact_policy: ArtifactSupplyChainPolicy
) -> None:
    """Reject unsigned, byte-tampered, provenance-tampered, and revoked bundles."""
    runner = DeterministicToolRunner()
    unsigned_bundle, digest_reference = _create_candidate(
        tmp_path, artifact_policy, runner, name="unsigned"
    )
    with pytest.raises(ArtifactSupplyChainError, match="unsigned"):
        verify_bundle(
            unsigned_bundle,
            expected_artifact_digest=digest_reference,
            repository_root=REPOSITORY_ROOT,
            policy=artifact_policy,
            runner=runner,
            environment=SIGNING_ENVIRONMENT,
        )

    tampered_bundle, tampered_digest = _create_candidate(
        tmp_path, artifact_policy, runner, name="tampered"
    )
    _sign_candidate(tampered_bundle, artifact_policy, runner)
    (tampered_bundle / "artifact/service.zip").write_bytes(b"tampered")
    with pytest.raises(ArtifactSupplyChainError, match="artifact content"):
        verify_bundle(
            tampered_bundle,
            expected_artifact_digest=tampered_digest,
            repository_root=REPOSITORY_ROOT,
            policy=artifact_policy,
            runner=runner,
            environment=SIGNING_ENVIRONMENT,
        )

    provenance_bundle, provenance_digest = _create_candidate(
        tmp_path, artifact_policy, runner, name="provenance"
    )
    _sign_candidate(provenance_bundle, artifact_policy, runner)
    provenance_path = provenance_bundle / "provenance.intoto.json"
    provenance_path.write_text(
        provenance_path.read_text(encoding="utf-8").replace(
            artifact_policy.builder_id, "https://invalid.example/builder"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactSupplyChainError, match="provenance"):
        verify_bundle(
            provenance_bundle,
            expected_artifact_digest=provenance_digest,
            repository_root=REPOSITORY_ROOT,
            policy=artifact_policy,
            runner=runner,
            environment=SIGNING_ENVIRONMENT,
        )

    revoked_update: dict[str, object] = {
        "revoked_signer_identities": (artifact_policy.signer_identity,)
    }
    revoked_policy = artifact_policy.model_copy(update=revoked_update)
    clean_bundle, clean_digest = _create_candidate(
        tmp_path, artifact_policy, runner, name="revoked"
    )
    _sign_candidate(clean_bundle, artifact_policy, runner)
    with pytest.raises(ArtifactSupplyChainError, match="revoked"):
        verify_bundle(
            clean_bundle,
            expected_artifact_digest=clean_digest,
            repository_root=REPOSITORY_ROOT,
            policy=revoked_policy,
            runner=runner,
            environment=SIGNING_ENVIRONMENT,
        )


def test_unsafe_bundle_paths_symlinks_and_extra_members_are_rejected(
    tmp_path: Path, artifact_policy: ArtifactSupplyChainPolicy
) -> None:
    """Reject archive limits, manifest traversal, bundle symlinks, and extra files."""
    limited_update: dict[str, object] = {"maximum_archive_members": 2}
    limited_policy = artifact_policy.model_copy(update=limited_update)
    with pytest.raises(ArtifactSupplyChainError, match="archive exceeds"):
        _create_candidate(
            tmp_path,
            limited_policy,
            DeterministicToolRunner(),
            name="too-many-members",
            member_names=("bin/service", "lib/libnative.so", "docs/readme"),
        )
    assert not (tmp_path / "too-many-members").exists()

    runner = DeterministicToolRunner()
    traversal_bundle, traversal_digest = _create_candidate(
        tmp_path, artifact_policy, runner, name="traversal"
    )
    manifest_path = traversal_bundle / "manifest.json"
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    artifact_identity = cast(dict[str, object], manifest["artifact"])
    artifact_identity["path"] = "artifact/../escape"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactSupplyChainError, match="safe relative path"):
        verify_bundle(
            traversal_bundle,
            expected_artifact_digest=traversal_digest,
            repository_root=REPOSITORY_ROOT,
            policy=artifact_policy,
            runner=runner,
            environment=SIGNING_ENVIRONMENT,
        )

    extra_bundle, extra_digest = _create_candidate(tmp_path, artifact_policy, runner, name="extra")
    _sign_candidate(extra_bundle, artifact_policy, runner)
    (extra_bundle / "debug.log").write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(ArtifactSupplyChainError, match="unknown files"):
        verify_bundle(
            extra_bundle,
            expected_artifact_digest=extra_digest,
            repository_root=REPOSITORY_ROOT,
            policy=artifact_policy,
            runner=runner,
            environment=SIGNING_ENVIRONMENT,
        )
    (extra_bundle / "debug.log").unlink()
    (extra_bundle / "unsafe-link").symlink_to(extra_bundle / "manifest.json")
    with pytest.raises(ArtifactSupplyChainError, match="unsafe symlink"):
        verify_bundle(
            extra_bundle,
            expected_artifact_digest=extra_digest,
            repository_root=REPOSITORY_ROOT,
            policy=artifact_policy,
            runner=runner,
            environment=SIGNING_ENVIRONMENT,
        )


def test_failures_clean_up_candidates_and_signatures(
    tmp_path: Path, artifact_policy: ArtifactSupplyChainPolicy
) -> None:
    """Remove staged output after tool failures during creation and signing."""
    failed_create_runner = DeterministicToolRunner()
    failed_create_runner.failure = ("syft", "scan")
    with pytest.raises(ArtifactSupplyChainError, match="synthetic failure"):
        _create_candidate(tmp_path, artifact_policy, failed_create_runner, name="failed-create")
    assert not (tmp_path / "failed-create").exists()

    runner = DeterministicToolRunner()
    bundle_path, _ = _create_candidate(tmp_path, artifact_policy, runner, name="failed-sign")
    runner.failure = ("cosign", "verify-blob")
    with pytest.raises(ArtifactSupplyChainError, match="synthetic failure"):
        _sign_candidate(bundle_path, artifact_policy, runner)
    assert not (bundle_path / "signature.sigstore.json").exists()


@pytest.mark.parametrize("operation", ["create", "sign", "verify", "publish"])
def test_release_gate_runs_before_every_lifecycle_operation(
    tmp_path: Path,
    artifact_policy: ArtifactSupplyChainPolicy,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """Block each retained lifecycle operation before its synthetic tools run."""
    runner = DeterministicToolRunner()
    if operation == "create":
        artifact_path, evidence_path = _fixture_inputs(tmp_path)
        output_path = tmp_path / "blocked-create"
        digest_reference = None
        bundle_path = None
    else:
        bundle_path, digest_reference = _create_candidate(
            tmp_path, artifact_policy, runner, name="existing"
        )
        artifact_path = None
        evidence_path = None
        output_path = None
    runner.commands.clear()

    def deny(_root: Path) -> None:
        """Reject release admission for this boundary test.

        Args:
            _root: Repository root supplied to the release gate.

        Raises:
            ArtifactSupplyChainError: Always, to simulate a blocked release.
        """
        raise ArtifactSupplyChainError(["release blocked"])

    monkeypatch.setattr(
        "alpha_research_governance.artifact_supply_chain.bundle.require_release_admission",
        deny,
    )
    with pytest.raises(ArtifactSupplyChainError, match="release blocked"):
        if operation == "create":
            assert artifact_path is not None
            assert evidence_path is not None
            assert output_path is not None
            create_bundle(
                artifact_path,
                artifact_kind="binary",
                build_command=BUILD_COMMAND,
                source_commit=SOURCE_COMMIT,
                test_evidence_paths=(evidence_path,),
                output_path=output_path,
                repository_root=REPOSITORY_ROOT,
                policy=artifact_policy,
                runner=runner,
                build_platform="darwin-arm64",
            )
        elif operation == "sign":
            assert bundle_path is not None
            _sign_candidate(bundle_path, artifact_policy, runner)
        elif operation == "verify":
            assert bundle_path is not None
            assert digest_reference is not None
            verify_bundle(
                bundle_path,
                expected_artifact_digest=digest_reference,
                repository_root=REPOSITORY_ROOT,
                policy=artifact_policy,
                runner=runner,
                environment=SIGNING_ENVIRONMENT,
            )
        else:
            assert bundle_path is not None
            assert digest_reference is not None
            publish_bundle(
                bundle_path,
                expected_artifact_digest=digest_reference,
                registry_root=tmp_path / "registry",
                repository_root=REPOSITORY_ROOT,
                policy=artifact_policy,
                runner=runner,
                environment=SIGNING_ENVIRONMENT,
            )
    assert runner.commands == []
    if output_path is not None:
        assert not output_path.exists()
    if bundle_path is not None:
        assert not (bundle_path / "signature.sigstore.json").exists()
    if operation == "publish" and digest_reference is not None:
        published_path = tmp_path / "registry" / "sha256" / digest_reference.removeprefix("sha256:")
        assert not published_path.exists()
