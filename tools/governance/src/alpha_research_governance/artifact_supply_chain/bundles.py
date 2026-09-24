"""Verify immutable local registry releases before any installer sees payload bytes."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

# project library imports
from alpha_research_governance.artifact_supply_chain.records import (
    InstallationPolicy,
    ReleaseFile,
    ReleaseManifest,
    StateEnvelope,
)
from alpha_research_governance.artifact_supply_chain.signatures import ReleaseSignatures


@dataclass(frozen=True)
class VerifiedRelease:
    """Carry verified immutable bytes rather than mutable registry paths."""

    manifest: ReleaseManifest
    manifest_bytes: bytes
    signature: bytes
    contents: tuple[tuple[str, bytes], ...]

    @property
    def identity(self) -> str:
        """Return the content address of the signed release record."""
        return hashlib.sha256(self.manifest_bytes).hexdigest()

    def content(self, name: str) -> bytes:
        """Retrieve a required authenticated file or reject an absent input."""
        for path, content in self.contents:
            if path == name:
                return content
        raise ValueError(f"release lacks required file: {name}")


class ReleaseRegistry:
    """Publish and read content-addressed signed releases on a local filesystem.

    A registry is untrusted storage. Trust comes from an independently supplied
    policy; copying a bundle or its embedded provenance never grants trust.
    """

    @staticmethod
    def read_regular(path: Path, limit: int) -> bytes:
        """Read a bounded regular file without following a leaf symlink."""
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
                raise ValueError("release input is not a bounded regular file")
            content = stream.read(limit + 1)
        if len(content) > limit:
            raise ValueError("release input exceeded its byte limit")
        return content

    @staticmethod
    def inventory(root: Path) -> tuple[str, ...]:
        """List every regular file while rejecting symlinked paths and special files."""
        if root.is_symlink() or not root.is_dir():
            raise ValueError("registry release must be a regular directory")
        names: list[str] = []
        for path in root.rglob("*"):
            metadata = path.lstat()
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("release contains a link or special file")
            name = path.relative_to(root).as_posix()
            ReleaseFile.require_path(name)
            names.append(name)
        return tuple(sorted(names))

    @classmethod
    def verify(
        cls,
        directory: Path,
        policy: InstallationPolicy,
        *,
        now: datetime,
        expected_identity: str | None = None,
    ) -> VerifiedRelease:
        """Authenticate identity, provenance inventory and compatibility before installation.

        Args:
            directory: Content-addressed bundle directory in untrusted local storage.
            policy: Independently provisioned target trust and compatibility policy.
            now: Aware UTC verification time, never supplied by the bundle.
            expected_identity: Retained installation identity; registry reads use
                the directory name.

        Returns:
            Immutable authenticated payload bytes.

        Raises:
            ValueError: Signature, trust, validity, inventory or compatibility fails.
            OSError: A required regular file cannot be read.
        """
        policy = InstallationPolicy.model_validate(policy)
        payload = cls.read_regular(directory / "release.json", 4_194_304)
        signature = cls.read_regular(directory / "release.sig", 16_384)
        manifest = ReleaseManifest.model_validate_json(payload)
        if payload != manifest.encoded():
            raise ValueError("release manifest encoding is not canonical")
        if (directory.name if expected_identity is None else expected_identity) != hashlib.sha256(
            payload
        ).hexdigest():
            raise ValueError("registry content address differs from release identity")
        if not manifest.created_at <= now < manifest.valid_until:
            raise ValueError("release is expired or not yet valid")
        verifier = ReleaseSignatures(Path(policy.ssh_keygen_executable), policy.ssh_keygen_sha256)
        authenticated = False
        for builder in policy.builders:
            if (
                builder.identity == manifest.builder
                and manifest.origin in builder.origins
                and manifest.root_distribution in builder.roots
                and builder.valid_from <= manifest.created_at < builder.valid_until
                and builder.valid_from <= now < builder.valid_until
            ):
                try:
                    verifier.verify(payload, signature, builder)
                except ValueError:
                    continue
                authenticated = True
                break
        if not authenticated:
            raise ValueError("release signature, builder or origin is not trusted")
        runtime = manifest.runtime
        if (
            runtime.platform != policy.target
            or runtime.config_schema not in policy.config_schemas
            or runtime.state_schema not in policy.state_schemas
        ):
            raise ValueError("release target, configuration or state is incompatible")
        expected = tuple(sorted(["release.json", "release.sig", *(f.path for f in manifest.files)]))
        if cls.inventory(directory) != expected:
            raise ValueError("release inventory contains missing or unknown files")
        contents: list[tuple[str, bytes]] = []
        for record in manifest.files:
            content = cls.read_regular(directory / record.path, record.size)
            if ReleaseFile.describe(record.path, content) != record:
                raise ValueError(f"release file digest or size mismatch: {record.path}")
            contents.append((record.path, content))
        verified = VerifiedRelease(manifest, payload, signature, tuple(contents))
        state = StateEnvelope.model_validate_json(verified.content("state/state.json"))
        if state.schema_version != runtime.state_schema or state.application != runtime.application:
            raise ValueError("state envelope differs from release compatibility")
        actual_state = tuple(
            ReleaseFile.describe(name.removeprefix("state/"), content)
            for name, content in verified.contents
            if name.startswith("state/") and name != "state/state.json"
        )
        if actual_state != state.files:
            raise ValueError("initial state inventory differs from its envelope")
        return verified

    @classmethod
    def publish(
        cls,
        root: Path,
        manifest: ReleaseManifest,
        signature: bytes,
        contents: tuple[tuple[str, bytes], ...],
    ) -> Path:
        """Publish a complete immutable bundle atomically, preserving identical retries.

        This storage operation grants no trust. Consumers always call ``verify``.
        """
        manifest = ReleaseManifest.model_validate(manifest)
        records = tuple(ReleaseFile.describe(name, content) for name, content in contents)
        if records != manifest.files:
            raise ValueError("published content differs from signed inventory")
        payload = manifest.encoded()
        identity = hashlib.sha256(payload).hexdigest()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = root / identity
        complete = (*contents, ("release.json", payload), ("release.sig", signature))
        if destination.exists():
            if cls.inventory(destination) != tuple(sorted(name for name, _ in complete)):
                raise ValueError("existing registry object is incomplete")
            for name, content in complete:
                if cls.read_regular(destination / name, len(content)) != content:
                    raise ValueError("existing registry object differs from publication")
            return destination
        with TemporaryDirectory(prefix=".release-", dir=root) as temporary:
            staging = Path(temporary) / "payload"
            staging.mkdir()
            for name, content in complete:
                path = staging / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                path.chmod(0o444)
            staging.rename(destination)
        return destination
