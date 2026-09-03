"""Deterministic success and fail-closed tests for B08 artifact controls."""

from __future__ import annotations

import json
import subprocess
import zipfile
from collections.abc import Mapping
from pathlib import Path

import pytest

from alpha_research_governance.artifact_supply_chain import (
    ArtifactSupplyChainError,
    ArtifactSupplyChainPolicy,
    create_bundle,
    load_policy,
    main,
    publish_bundle,
    sign_bundle,
    validate_repository,
    verify_bundle,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
SOURCE_COMMIT_SHA = "a" * 40
MISMATCHED_SOURCE_COMMIT_SHA = "b" * 40


class DeterministicArtifactToolRunner:
    """Produce deterministic Syft and Cosign boundary results."""

    def __init__(self, *, sbom_file_names: tuple[str, ...] = ("lib/libnative.so",)) -> None:
        self.sbom_file_names = sbom_file_names
        self.executed_commands: list[tuple[str, ...]] = []
        self.failing_command: str | None = None

    def __call__(
        self, command: list[str], working_directory: Path, environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del working_directory
        self.executed_commands.append(tuple(command))
        if self.failing_command == command[0]:
            return subprocess.CompletedProcess(command, 7, "", "synthetic failure")
        if command[:2] == ["syft", "version"]:
            return subprocess.CompletedProcess(command, 0, "Version:       1.51.1\n", "")
        if command[:2] == ["cosign", "version"]:
            return subprocess.CompletedProcess(command, 0, "GitVersion:    v3.1.3\n", "")
        if command[:2] == ["syft", "scan"]:
            assert environment["SYFT_FILE_METADATA_SELECTION"] == "all"
            sbom_output_path = Path(
                command[command.index("--output") + 1].split("=", maxsplit=1)[1]
            )
            sbom_output_path.write_text(
                json.dumps(
                    {
                        "SPDXID": "SPDXRef-DOCUMENT",
                        "creationInfo": {
                            "created": "2026-09-03T12:34:56Z",
                            "creators": ["Tool: syft-1.51.1"],
                        },
                        "dataLicense": "CC0-1.0",
                        "documentNamespace": "https://syft.invalid/random",
                        "files": [
                            {"SPDXID": f"SPDXRef-{index}", "fileName": name}
                            for index, name in enumerate(reversed(self.sbom_file_names), 1)
                        ],
                        "name": "random",
                        "packages": [],
                        "relationships": [],
                        "spdxVersion": "SPDX-2.3",
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["cosign", "sign-blob"]:
            signature_bundle_path = Path(command[command.index("--bundle") + 1])
            signature_bundle_path.write_text(
                '{"mediaType":"application/vnd.dev.sigstore.bundle.v0.3+json"}\n'
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["cosign", "verify-blob"]:
            return subprocess.CompletedProcess(command, 0, "Verified OK\n", "")
        raise AssertionError(f"unexpected command: {command!r}")


@pytest.fixture
def artifact_supply_chain_policy() -> ArtifactSupplyChainPolicy:
    return load_policy(REPOSITORY_ROOT / "docs/architecture/artifact-supply-chain.toml")


def _create_test_artifact_and_evidence(tmp_path: Path) -> tuple[Path, Path]:
    test_artifact_path = tmp_path / "service.zip"
    with zipfile.ZipFile(test_artifact_path, "w") as archive:
        archive.writestr("bin/service", "executable")
        archive.writestr("lib/libnative.so", "native")
    test_evidence_path = tmp_path / "tests.json"
    test_evidence_path.write_text('{"outcome":"passed"}\n', encoding="utf-8")
    return test_artifact_path, test_evidence_path


def _create_test_bundle(
    tmp_path: Path,
    artifact_supply_chain_policy: ArtifactSupplyChainPolicy,
    artifact_tool_runner: DeterministicArtifactToolRunner,
    *,
    name: str = "candidate",
) -> tuple[Path, str]:
    test_artifact_path, test_evidence_path = _create_test_artifact_and_evidence(tmp_path)
    bundle_path = tmp_path / name
    created_bundle = create_bundle(
        test_artifact_path,
        artifact_kind="binary",
        build_target="//platform/service:release",
        source_commit=SOURCE_COMMIT_SHA,
        test_evidence_paths=(test_evidence_path,),
        output_path=bundle_path,
        repository_root=REPOSITORY_ROOT,
        policy=artifact_supply_chain_policy,
        runner=artifact_tool_runner,
        build_platform="darwin-arm64",
    )
    return bundle_path, f"sha256:{created_bundle.artifact_sha256}"


def _sign_test_bundle_in_protected_main_context(
    bundle_path: Path,
    artifact_supply_chain_policy: ArtifactSupplyChainPolicy,
    artifact_tool_runner: DeterministicArtifactToolRunner,
) -> None:
    sign_bundle(
        bundle_path,
        signing_context="github_protected_main",
        policy=artifact_supply_chain_policy,
        repository_root=REPOSITORY_ROOT,
        runner=artifact_tool_runner,
        environment={
            "GITHUB_ACTIONS": "true",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_REF_PROTECTED": "true",
            "GITHUB_SHA": SOURCE_COMMIT_SHA,
        },
    )


def test_policy_is_closed_and_binds_tools_locks_and_blueprint_gate(
    artifact_supply_chain_policy: ArtifactSupplyChainPolicy,
) -> None:
    assert validate_repository(REPOSITORY_ROOT) == artifact_supply_chain_policy
    assert artifact_supply_chain_policy.package_status == "partial"
    assert artifact_supply_chain_policy.successor_package == "C01"
    assert artifact_supply_chain_policy.syft.version == "1.51.1"
    assert artifact_supply_chain_policy.cosign.version == "3.1.3"
    assert tuple(lock.path for lock in artifact_supply_chain_policy.locks) == (
        "MODULE.bazel.lock",
        "flake.lock",
        "requirements.bazel.txt",
        "uv.lock",
    )
    assert artifact_supply_chain_policy.applicable_gate_ids[-1] == "QG15"
    assert artifact_supply_chain_policy.open_finding_ids == (
        "B08-F01",
        "B08-F02",
        "B08-F03",
    )


def test_policy_unknown_fields_and_floating_tool_versions_fail_closed(tmp_path: Path) -> None:
    policy_source = (REPOSITORY_ROOT / "docs/architecture/artifact-supply-chain.toml").read_text(
        encoding="utf-8"
    )
    unknown_field_policy_path = tmp_path / "unknown.toml"
    unknown_field_policy_path.write_text(
        policy_source.replace("schema_version = 1", "schema_version = 1\nunknown = true"),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactSupplyChainError, match="unknown fields"):
        load_policy(unknown_field_policy_path)

    floating_version_policy_path = tmp_path / "floating.toml"
    floating_version_policy_path.write_text(
        policy_source.replace('version = "1.51.1"', 'version = "latest"'),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactSupplyChainError, match="unsafe or floating"):
        load_policy(floating_version_policy_path)


def test_creation_is_deterministic_and_binds_whole_artifact_inputs(
    tmp_path: Path, artifact_supply_chain_policy: ArtifactSupplyChainPolicy
) -> None:
    first_bundle_path, first_artifact_digest = _create_test_bundle(
        tmp_path,
        artifact_supply_chain_policy,
        DeterministicArtifactToolRunner(),
        name="first",
    )
    second_bundle_path, second_artifact_digest = _create_test_bundle(
        tmp_path,
        artifact_supply_chain_policy,
        DeterministicArtifactToolRunner(),
        name="second",
    )

    assert first_artifact_digest == second_artifact_digest
    for bundle_relative_path in (
        "manifest.json",
        "provenance.intoto.json",
        "sbom.spdx.json",
    ):
        assert (first_bundle_path / bundle_relative_path).read_bytes() == (
            second_bundle_path / bundle_relative_path
        ).read_bytes()
    artifact_manifest = json.loads(
        (first_bundle_path / "manifest.json").read_text(encoding="utf-8")
    )
    assert artifact_manifest["artifact"]["sha256"] == first_artifact_digest.removeprefix("sha256:")
    assert artifact_manifest["toolchain"] == {
        "cosign": "3.1.3",
        "path": "environments/dev/toolchain.toml",
        "sha256": "16bd96c8f8515f4db6af17a48e9edac243902397f1fd22d5f71f953278be342c",
        "syft": "1.51.1",
    }
    assert [item["path"] for item in artifact_manifest["testEvidence"]] == ["tests/tests.json"]


def test_signed_bundle_verifies_and_publishes_only_once_by_digest(
    tmp_path: Path, artifact_supply_chain_policy: ArtifactSupplyChainPolicy
) -> None:
    artifact_tool_runner = DeterministicArtifactToolRunner()
    bundle_path, artifact_digest_reference = _create_test_bundle(
        tmp_path, artifact_supply_chain_policy, artifact_tool_runner
    )
    _sign_test_bundle_in_protected_main_context(
        bundle_path, artifact_supply_chain_policy, artifact_tool_runner
    )

    verified_bundle = verify_bundle(
        bundle_path,
        expected_artifact_digest=artifact_digest_reference,
        repository_root=REPOSITORY_ROOT,
        policy=artifact_supply_chain_policy,
        runner=artifact_tool_runner,
        environment={},
    )
    assert f"sha256:{verified_bundle.artifact_sha256}" == artifact_digest_reference
    published_bundle_path = publish_bundle(
        bundle_path,
        expected_artifact_digest=artifact_digest_reference,
        registry_root=tmp_path / "registry",
        repository_root=REPOSITORY_ROOT,
        policy=artifact_supply_chain_policy,
        runner=artifact_tool_runner,
        environment={},
    )
    assert (
        published_bundle_path == tmp_path / "registry" / "sha256" / verified_bundle.artifact_sha256
    )
    with pytest.raises(ArtifactSupplyChainError, match="already published"):
        publish_bundle(
            bundle_path,
            expected_artifact_digest=artifact_digest_reference,
            registry_root=tmp_path / "registry",
            repository_root=REPOSITORY_ROOT,
            policy=artifact_supply_chain_policy,
            runner=artifact_tool_runner,
            environment={},
        )


@pytest.mark.parametrize("consumer_reference", ["latest", "service:main", "sha256:1234"])
def test_consumer_rejects_mutable_or_malformed_references(
    tmp_path: Path,
    artifact_supply_chain_policy: ArtifactSupplyChainPolicy,
    consumer_reference: str,
) -> None:
    bundle_path, _ = _create_test_bundle(
        tmp_path, artifact_supply_chain_policy, DeterministicArtifactToolRunner()
    )
    with pytest.raises(ArtifactSupplyChainError, match="immutable"):
        verify_bundle(
            bundle_path,
            expected_artifact_digest=consumer_reference,
            repository_root=REPOSITORY_ROOT,
            policy=artifact_supply_chain_policy,
            runner=DeterministicArtifactToolRunner(),
        )


def test_unsigned_tampered_and_unknown_manifest_state_is_rejected(
    tmp_path: Path, artifact_supply_chain_policy: ArtifactSupplyChainPolicy
) -> None:
    artifact_tool_runner = DeterministicArtifactToolRunner()
    bundle_path, artifact_digest_reference = _create_test_bundle(
        tmp_path, artifact_supply_chain_policy, artifact_tool_runner
    )
    with pytest.raises(ArtifactSupplyChainError, match="unsigned"):
        verify_bundle(
            bundle_path,
            expected_artifact_digest=artifact_digest_reference,
            repository_root=REPOSITORY_ROOT,
            policy=artifact_supply_chain_policy,
            runner=artifact_tool_runner,
        )
    _sign_test_bundle_in_protected_main_context(
        bundle_path, artifact_supply_chain_policy, artifact_tool_runner
    )
    (bundle_path / "artifact/service.zip").write_bytes(b"tampered")
    with pytest.raises(ArtifactSupplyChainError, match="artifact content"):
        verify_bundle(
            bundle_path,
            expected_artifact_digest=artifact_digest_reference,
            repository_root=REPOSITORY_ROOT,
            policy=artifact_supply_chain_policy,
            runner=artifact_tool_runner,
        )

    unknown_state_bundle_path, unknown_state_digest_reference = _create_test_bundle(
        tmp_path,
        artifact_supply_chain_policy,
        artifact_tool_runner,
        name="other",
    )
    _sign_test_bundle_in_protected_main_context(
        unknown_state_bundle_path, artifact_supply_chain_policy, artifact_tool_runner
    )
    manifest_path = unknown_state_bundle_path / "manifest.json"
    artifact_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_manifest["unknown"] = True
    manifest_path.write_text(json.dumps(artifact_manifest), encoding="utf-8")
    with pytest.raises(ArtifactSupplyChainError, match="unknown"):
        verify_bundle(
            unknown_state_bundle_path,
            expected_artifact_digest=unknown_state_digest_reference,
            repository_root=REPOSITORY_ROOT,
            policy=artifact_supply_chain_policy,
            runner=artifact_tool_runner,
        )


def test_native_library_omission_and_tool_failure_fail_closed(
    tmp_path: Path, artifact_supply_chain_policy: ArtifactSupplyChainPolicy
) -> None:
    with pytest.raises(ArtifactSupplyChainError, match="native/shared-library"):
        _create_test_bundle(
            tmp_path,
            artifact_supply_chain_policy,
            DeterministicArtifactToolRunner(sbom_file_names=()),
            name="missing-native",
        )
    assert not (tmp_path / "missing-native").exists()

    failing_artifact_tool_runner = DeterministicArtifactToolRunner()
    failing_artifact_tool_runner.failing_command = "syft"
    with pytest.raises(ArtifactSupplyChainError, match="synthetic failure"):
        _create_test_bundle(
            tmp_path,
            artifact_supply_chain_policy,
            failing_artifact_tool_runner,
            name="failed-tool",
        )
    assert not (tmp_path / "failed-tool").exists()

    policy_with_wrong_syft_version = artifact_supply_chain_policy.model_copy(
        update={"syft": artifact_supply_chain_policy.syft.model_copy(update={"version": "1.51.0"})}
    )
    with pytest.raises(ArtifactSupplyChainError, match="exact admitted version"):
        _create_test_bundle(
            tmp_path,
            policy_with_wrong_syft_version,
            DeterministicArtifactToolRunner(),
            name="wrong-version",
        )


def test_signing_context_sha_and_revoked_identity_fail_closed(
    tmp_path: Path, artifact_supply_chain_policy: ArtifactSupplyChainPolicy
) -> None:
    artifact_tool_runner = DeterministicArtifactToolRunner()
    bundle_path, artifact_digest_reference = _create_test_bundle(
        tmp_path, artifact_supply_chain_policy, artifact_tool_runner
    )
    with pytest.raises(ArtifactSupplyChainError, match="not trusted"):
        sign_bundle(
            bundle_path,
            signing_context="developer",
            policy=artifact_supply_chain_policy,
            runner=artifact_tool_runner,
        )
    with pytest.raises(ArtifactSupplyChainError, match="GITHUB_SHA"):
        sign_bundle(
            bundle_path,
            signing_context="github_protected_main",
            policy=artifact_supply_chain_policy,
            runner=artifact_tool_runner,
            environment={
                "GITHUB_ACTIONS": "true",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_REF_PROTECTED": "true",
                "GITHUB_SHA": MISMATCHED_SOURCE_COMMIT_SHA,
            },
        )
    _sign_test_bundle_in_protected_main_context(
        bundle_path, artifact_supply_chain_policy, artifact_tool_runner
    )
    unexpected_bundle_file_path = bundle_path / "debug.log"
    unexpected_bundle_file_path.write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(ArtifactSupplyChainError, match="unknown files"):
        verify_bundle(
            bundle_path,
            expected_artifact_digest=artifact_digest_reference,
            repository_root=REPOSITORY_ROOT,
            policy=artifact_supply_chain_policy,
            runner=artifact_tool_runner,
        )
    unexpected_bundle_file_path.unlink()
    policy_with_revoked_signer = artifact_supply_chain_policy.model_copy(
        update={"revoked_signer_identities": (artifact_supply_chain_policy.signer_identity,)},
        deep=True,
    )
    with pytest.raises(ArtifactSupplyChainError, match="revoked"):
        verify_bundle(
            bundle_path,
            expected_artifact_digest=artifact_digest_reference,
            repository_root=REPOSITORY_ROOT,
            policy=policy_with_revoked_signer,
            runner=artifact_tool_runner,
        )


def test_invalid_creation_inputs_and_cli_usage_are_rejected(
    tmp_path: Path,
    artifact_supply_chain_policy: ArtifactSupplyChainPolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    test_artifact_path, test_evidence_path = _create_test_artifact_and_evidence(tmp_path)
    with pytest.raises(ArtifactSupplyChainError, match="unsupported artifact kind"):
        create_bundle(
            test_artifact_path,
            artifact_kind="unknown",
            build_target="//platform/service:release",
            source_commit=SOURCE_COMMIT_SHA,
            test_evidence_paths=(test_evidence_path,),
            output_path=tmp_path / "candidate",
            repository_root=REPOSITORY_ROOT,
            policy=artifact_supply_chain_policy,
            runner=DeterministicArtifactToolRunner(),
        )
    assert main(["unknown"]) == 2
    assert "usage:" in capsys.readouterr().err


def test_root_package_bazel_label_is_accepted(
    tmp_path: Path, artifact_supply_chain_policy: ArtifactSupplyChainPolicy
) -> None:
    test_artifact_path, test_evidence_path = _create_test_artifact_and_evidence(tmp_path)
    created_bundle = create_bundle(
        test_artifact_path,
        artifact_kind="binary",
        build_target="//:docs_bundle",
        source_commit=SOURCE_COMMIT_SHA,
        test_evidence_paths=(test_evidence_path,),
        output_path=tmp_path / "root-label",
        repository_root=REPOSITORY_ROOT,
        policy=artifact_supply_chain_policy,
        runner=DeterministicArtifactToolRunner(),
        build_platform="darwin-arm64",
    )
    assert created_bundle.build_target == "//:docs_bundle"
