"""Exercise authenticated local release records with real Ed25519 signatures."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import shutil
import subprocess  # nosec B404  # [owner=platform; rationale=test actual local OpenSSH signatures; expires=2027-03-01]
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

# third party library imports
import pytest

# project library imports
from alpha_research_governance.artifact_supply_chain.bundles import ReleaseRegistry
from alpha_research_governance.artifact_supply_chain.records import (
    InstallationPolicy,
    ReleaseFile,
    ReleaseManifest,
    ReleaseRuntime,
    StateEnvelope,
    TrustedBuilder,
)
from alpha_research_governance.artifact_supply_chain.signatures import ReleaseSignatures

_NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
_SOURCE_COMMIT = "a" * 40
_REPOSITORY_ROOT = Path(__file__).parents[2]


@dataclass(frozen=True)
class SignedReleaseCase:
    """Own one isolated signed bundle and its independently supplied target trust."""

    root: Path
    key: Path
    tool: Path
    policy: InstallationPolicy
    manifest: ReleaseManifest
    contents: tuple[tuple[str, bytes], ...]
    directory: Path

    @staticmethod
    def generate_key(directory: Path, name: str) -> tuple[Path, str]:
        """Generate a fresh local Ed25519 key and return its bare public key."""
        executable = shutil.which("ssh-keygen")
        if executable is None:
            pytest.fail("the signed release tests require the OS ssh-keygen executable")
        key = directory / name
        subprocess.run(  # nosec B603  # [owner=platform; rationale=local test key generation without shell; expires=2027-03-01]
            [executable, "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
            check=True,
            capture_output=True,
            timeout=30,
        )
        public = " ".join((directory / f"{name}.pub").read_text(encoding="ascii").split()[:2])
        return key, public

    @classmethod
    def create(cls, root: Path) -> SignedReleaseCase:
        """Publish inert but complete bytes under a genuine detached signature."""
        executable = shutil.which("ssh-keygen")
        if executable is None:
            pytest.fail("the signed release tests require the OS ssh-keygen executable")
        tool = Path(executable)
        key, public = cls.generate_key(root, "builder-key")
        tool_digest = hashlib.sha256(tool.read_bytes()).hexdigest()
        python_tool = Path(sys.executable)
        python_digest = hashlib.sha256(python_tool.read_bytes()).hexdigest()
        builder = TrustedBuilder(
            identity="trusted-builder",
            public_key=public,
            origins=("local-builder",),
            roots=("alpha-research-collector",),
            valid_from=_NOW - timedelta(days=2),
            valid_until=_NOW + timedelta(days=2),
        )
        policy = InstallationPolicy(
            target="darwin_arm64",
            python_executable=str(python_tool),
            python_sha256=python_digest,
            uv_executable=str(python_tool),
            uv_sha256=python_digest,
            ssh_keygen_executable=str(tool),
            ssh_keygen_sha256=tool_digest,
            builders=(builder,),
            config_schemas=("config-v1",),
            state_schemas=("state-v1",),
        )
        initial_state = b"initial state\n"
        state_envelope = StateEnvelope(
            schema_version="state-v1",
            application="collector",
            files=(ReleaseFile.describe("checkpoint.bin", initial_state),),
        )
        payloads = {
            "provenance/closure.json": b'{"wheels":[]}\n',
            "provenance/uv.lock": b"version = 1\n",
            "provenance/dependency-admission.toml": b"admitted = true\n",
            "provenance/audit.json": b"{}\n",
            "provenance/source.json": ('{"commit":"' + _SOURCE_COMMIT + '"}\n').encode(),
            "configuration/config.json": b'{"schema_version":"config-v1"}\n',
            "state/checkpoint.bin": initial_state,
            "state/state.json": state_envelope.model_dump_json().encode(),
        }
        contents = tuple(sorted(payloads.items()))
        manifest = ReleaseManifest(
            name="collector-release",
            builder=builder.identity,
            origin="local-builder",
            created_at=_NOW - timedelta(hours=1),
            valid_until=_NOW + timedelta(days=1),
            source_commit=_SOURCE_COMMIT,
            source_dirty=False,
            build_commands=(("uv", "build", "--offline"),),
            runtime=ReleaseRuntime(
                python_version="3.14.7",
                platform="darwin_arm64",
                contract_version="1",
                application="collector",
                mode="collection",
                config_schema="config-v1",
                state_schema="state-v1",
            ),
            root_distribution="alpha-research-collector",
            files=tuple(ReleaseFile.describe(name, content) for name, content in contents),
        )
        signature = ReleaseSignatures(tool, tool_digest).sign(manifest.encoded(), key)
        directory = ReleaseRegistry.publish(root / "registry", manifest, signature, contents)
        return cls(root, key, tool, policy, manifest, contents, directory)

    def publish(
        self,
        manifest: ReleaseManifest,
        *,
        contents: tuple[tuple[str, bytes], ...] | None = None,
    ) -> Path:
        """Sign a modified record and publish it with the unchanged inventory."""
        signature = ReleaseSignatures(self.tool, self.policy.ssh_keygen_sha256).sign(
            manifest.encoded(), self.key
        )
        selected = self.contents if contents is None else contents
        return ReleaseRegistry.publish(self.root / "registry", manifest, signature, selected)

    def publish_with_content(self, name: str, content: bytes) -> Path:
        """Re-sign a deliberately changed file and its matching manifest inventory."""
        assert name in {path for path, _ in self.contents}
        contents = tuple(
            (path, content if path == name else original) for path, original in self.contents
        )
        files = tuple(ReleaseFile.describe(path, payload) for path, payload in contents)
        return self.publish(self.manifest_with(files=files), contents=contents)

    def manifest_with(
        self,
        *,
        builder: str | None = None,
        origin: str | None = None,
        runtime: ReleaseRuntime | None = None,
        root_distribution: Literal["alpha-research-collector", "alpha-research-execution"]
        | None = None,
        created_at: datetime | None = None,
        valid_until: datetime | None = None,
        files: tuple[ReleaseFile, ...] | None = None,
    ) -> ReleaseManifest:
        """Construct a revalidated record with one deliberate field variation."""
        original = self.manifest
        return ReleaseManifest(
            name=original.name,
            builder=original.builder if builder is None else builder,
            origin=original.origin if origin is None else origin,
            created_at=original.created_at if created_at is None else created_at,
            valid_until=original.valid_until if valid_until is None else valid_until,
            source_commit=original.source_commit,
            source_dirty=original.source_dirty,
            build_commands=original.build_commands,
            runtime=original.runtime if runtime is None else runtime,
            root_distribution=(
                original.root_distribution if root_distribution is None else root_distribution
            ),
            files=original.files if files is None else files,
        )

    def policy_with(
        self,
        *,
        target: Literal["darwin_arm64", "linux_x86_64"] | None = None,
        builders: tuple[TrustedBuilder, ...] | None = None,
        config_schemas: tuple[str, ...] | None = None,
        state_schemas: tuple[str, ...] | None = None,
    ) -> InstallationPolicy:
        """Construct target trust with an explicit changed compatibility scope."""
        original = self.policy
        return InstallationPolicy(
            target=original.target if target is None else target,
            python_executable=original.python_executable,
            python_sha256=original.python_sha256,
            uv_executable=original.uv_executable,
            uv_sha256=original.uv_sha256,
            ssh_keygen_executable=original.ssh_keygen_executable,
            ssh_keygen_sha256=original.ssh_keygen_sha256,
            builders=original.builders if builders is None else builders,
            config_schemas=(original.config_schemas if config_schemas is None else config_schemas),
            state_schemas=original.state_schemas if state_schemas is None else state_schemas,
        )

    def builder_with(
        self, *, public_key: str | None = None, valid_until: datetime | None = None
    ) -> TrustedBuilder:
        """Construct a newly provisioned key record without bypassing validation."""
        original = self.policy.builders[0]
        return TrustedBuilder(
            identity=original.identity,
            public_key=original.public_key if public_key is None else public_key,
            origins=original.origins,
            roots=original.roots,
            valid_from=original.valid_from,
            valid_until=original.valid_until if valid_until is None else valid_until,
        )


class TestSignedReleaseRegistry:
    """Authenticate release identity, trust scope and complete immutable bytes."""

    def test_special_manifest_input_rejects_without_blocking(self, tmp_path: Path) -> None:
        """A registry FIFO cannot stall verification before the regular-file check."""
        fifo = tmp_path / "release.json"
        os.mkfifo(fifo)
        program = (
            "import sys; from pathlib import Path; "
            "from alpha_research_governance.artifact_supply_chain.bundles "
            "import ReleaseRegistry; "
            "ReleaseRegistry.read_regular(Path(sys.argv[1]), 1024)"
        )
        completed = subprocess.run(  # nosec B603  # [owner=platform; rationale=bounded isolated FIFO rejection probe; expires=2027-03-01]
            [sys.executable, "-c", program, str(fifo)],
            capture_output=True,
            timeout=5,
            check=False,
            cwd=_REPOSITORY_ROOT,
            env={
                "PYTHONPATH": f"{_REPOSITORY_ROOT}/tools/governance/src:{_REPOSITORY_ROOT}/src",
                "PATH": "/usr/bin:/bin",
            },
        )
        assert completed.returncode != 0
        assert b"release input is not a bounded regular file" in completed.stderr

    def test_genuine_signature_and_complete_inventory_verify(self, tmp_path: Path) -> None:
        """Return the exact signed identity and contents after a genuine OS signature."""
        case = SignedReleaseCase.create(tmp_path)

        verified = ReleaseRegistry.verify(case.directory, case.policy, now=_NOW)

        assert verified.identity == case.directory.name
        assert verified.manifest == case.manifest
        assert verified.manifest_bytes == case.manifest.encoded()
        assert verified.contents == case.contents
        assert verified.content("state/checkpoint.bin") == b"initial state\n"
        assert (
            ReleaseRegistry.publish(
                tmp_path / "registry", case.manifest, verified.signature, case.contents
            )
            == case.directory
        )

    @pytest.mark.parametrize("scope", ("builder", "origin", "root", "public-key"))
    def test_signature_cannot_cross_builder_origin_root_or_key_scope(
        self, tmp_path: Path, scope: str
    ) -> None:
        """Require a matching identity, origin, operating root and actual trusted key."""
        case = SignedReleaseCase.create(tmp_path)
        directory = case.directory
        policy = case.policy
        if scope == "builder":
            directory = case.publish(case.manifest_with(builder="other-builder"))
        elif scope == "origin":
            directory = case.publish(case.manifest_with(origin="other-origin"))
        elif scope == "root":
            original = case.manifest.runtime
            runtime = ReleaseRuntime(
                python_version=original.python_version,
                platform=original.platform,
                contract_version=original.contract_version,
                application="execution",
                mode="research",
                config_schema=original.config_schema,
                state_schema=original.state_schema,
            )
            directory = case.publish(
                case.manifest_with(runtime=runtime, root_distribution="alpha-research-execution")
            )
        else:
            _, other_public = SignedReleaseCase.generate_key(tmp_path, "other-key")
            policy = case.policy_with(builders=(case.builder_with(public_key=other_public),))

        with pytest.raises(ValueError, match="signature, builder or origin is not trusted"):
            ReleaseRegistry.verify(directory, policy, now=_NOW)

    def test_signature_manifest_identity_and_payload_tampering_fail(self, tmp_path: Path) -> None:
        """Reject changed detached signatures, release records and source bytes."""
        case = SignedReleaseCase.create(tmp_path)
        signature_path = case.directory / "release.sig"
        original_signature = signature_path.read_bytes()
        signature_path.chmod(0o644)
        signature_path.write_bytes(original_signature.replace(b"SIG", b"BAD", 1))
        with pytest.raises(ValueError, match="signature, builder or origin is not trusted"):
            ReleaseRegistry.verify(case.directory, case.policy, now=_NOW)
        signature_path.write_bytes(original_signature)

        manifest_path = case.directory / "release.json"
        manifest_path.chmod(0o644)
        manifest_path.write_bytes(b" " + case.manifest.encoded())
        with pytest.raises(ValueError, match="encoding is not canonical"):
            ReleaseRegistry.verify(case.directory, case.policy, now=_NOW)

        manifest_path.write_bytes(
            case.manifest.encoded().replace(b"local-builder", b"other-builder")
        )
        with pytest.raises(ValueError, match="content address differs"):
            ReleaseRegistry.verify(case.directory, case.policy, now=_NOW)
        manifest_path.write_bytes(case.manifest.encoded())

        source_path = case.directory / "provenance/source.json"
        source_path.chmod(0o644)
        source_path.write_bytes(b'{"commit":"unexpected"}\n')
        with pytest.raises(ValueError, match="digest or size mismatch"):
            ReleaseRegistry.verify(case.directory, case.policy, now=_NOW)

    @pytest.mark.parametrize(
        "mutation",
        (
            "missing",
            "missing-manifest",
            "missing-signature",
            "unknown",
            "unsafe-name",
            "symlink",
            "directory-symlink",
        ),
    )
    def test_incomplete_or_unsafe_directory_inventory_fails(
        self, tmp_path: Path, mutation: str
    ) -> None:
        """Reject absent, extra and linked paths in untrusted registry storage."""
        case = SignedReleaseCase.create(tmp_path)
        source = case.directory / "provenance/source.json"
        if mutation == "missing":
            source.unlink()
        elif mutation == "missing-manifest":
            (case.directory / "release.json").unlink()
        elif mutation == "missing-signature":
            (case.directory / "release.sig").unlink()
        elif mutation == "unknown":
            (case.directory / "unlisted.txt").write_bytes(b"untrusted")
        elif mutation == "unsafe-name":
            (case.directory / "unlisted name.txt").write_bytes(b"untrusted")
        elif mutation == "symlink":
            source.unlink()
            source.symlink_to(tmp_path / "builder-key.pub")
        else:
            outside = tmp_path / "outside"
            outside.mkdir()
            (case.directory / "provenance/source.json").unlink()
            for path in (case.directory / "provenance").iterdir():
                path.rename(outside / path.name)
            (case.directory / "provenance").rmdir()
            (case.directory / "provenance").symlink_to(outside, target_is_directory=True)

        with pytest.raises((OSError, ValueError)):
            ReleaseRegistry.verify(case.directory, case.policy, now=_NOW)

    @pytest.mark.parametrize(
        "compatibility", ("target", "configuration", "state", "envelope", "state-inventory")
    )
    def test_target_configuration_and_state_compatibility_fails(
        self, tmp_path: Path, compatibility: str
    ) -> None:
        """Enforce target policy and the authenticated initial state envelope."""
        case = SignedReleaseCase.create(tmp_path)
        policy = case.policy
        directory = case.directory
        if compatibility == "target":
            policy = case.policy_with(target="linux_x86_64")
        elif compatibility == "configuration":
            policy = case.policy_with(config_schemas=("config-v2",))
        elif compatibility == "state":
            policy = case.policy_with(state_schemas=("state-v2",))
        else:
            state = StateEnvelope(
                schema_version="state-v2" if compatibility == "envelope" else "state-v1",
                application="collector",
                files=(
                    ReleaseFile.describe(
                        "checkpoint.bin",
                        b"different state\n"
                        if compatibility == "state-inventory"
                        else b"initial state\n",
                    ),
                ),
            )
            directory = case.publish_with_content(
                "state/state.json", state.model_dump_json().encode()
            )

        message = {
            "target": "incompatible",
            "configuration": "incompatible",
            "state": "incompatible",
            "envelope": "state envelope differs",
            "state-inventory": "initial state inventory differs",
        }[compatibility]
        with pytest.raises(ValueError, match=message):
            ReleaseRegistry.verify(directory, policy, now=_NOW)

    @pytest.mark.parametrize(
        "validity", ("future-release", "expired-release", "expired-key", "revoked-key")
    )
    def test_release_or_key_outside_trust_window_fails(self, tmp_path: Path, validity: str) -> None:
        """Reject releases outside their lifetime and keys absent from current trust."""
        case = SignedReleaseCase.create(tmp_path)
        directory = case.directory
        policy = case.policy
        if validity == "future-release":
            directory = case.publish(
                case.manifest_with(
                    created_at=_NOW + timedelta(hours=1), valid_until=_NOW + timedelta(days=1)
                )
            )
        elif validity == "expired-release":
            directory = case.publish(case.manifest_with(valid_until=_NOW - timedelta(minutes=1)))
        elif validity == "expired-key":
            policy = case.policy_with(
                builders=(case.builder_with(valid_until=_NOW - timedelta(minutes=1)),)
            )
        else:
            _, other_public = SignedReleaseCase.generate_key(tmp_path, "replacement-key")
            policy = case.policy_with(builders=(case.builder_with(public_key=other_public),))

        message = "expired or not yet valid" if "release" in validity else "not trusted"
        with pytest.raises(ValueError, match=message):
            ReleaseRegistry.verify(directory, policy, now=_NOW)


class TestReleaseRecordValidation:
    """Reject malformed signed records before they can name filesystem inputs."""

    @staticmethod
    def _file_path(record: ReleaseFile) -> str:
        """Order a duplicate-path fixture as the signed inventory requires."""
        return record.path

    @pytest.mark.parametrize(
        "path",
        ("../escape", "/absolute", "a//b", "a/./b", "a/../b", "a\\b", "a b"),
    )
    def test_unsafe_manifest_paths_fail(self, path: str) -> None:
        """Keep traversal, aliases and nonportable names out of signed inventories."""
        with pytest.raises(ValueError, match="unsafe release file path"):
            ReleaseFile.describe(path, b"payload")

    def test_malformed_manifest_and_duplicate_inventory_fail(self, tmp_path: Path) -> None:
        """Reject a malformed record and a casefold collision in required inputs."""
        case = SignedReleaseCase.create(tmp_path)
        with pytest.raises(ValueError, match="release lacks required"):
            case.manifest_with(files=())
        with pytest.raises(ValueError, match="duplicate release inventory path"):
            case.manifest_with(
                files=tuple(
                    sorted(
                        (
                            *case.manifest.files,
                            ReleaseFile.describe("state/CHECKPOINT.bin", b"other"),
                        ),
                        key=self._file_path,
                    )
                )
            )

    def test_unlisted_content_cannot_be_published(self, tmp_path: Path) -> None:
        """Prevent publication of bytes not named by the signed manifest."""
        case = SignedReleaseCase.create(tmp_path)
        with pytest.raises(ValueError, match="published content differs"):
            ReleaseRegistry.publish(
                tmp_path / "other-registry",
                case.manifest,
                (case.directory / "release.sig").read_bytes(),
                (*case.contents, ("unknown.txt", b"unexpected")),
            )
