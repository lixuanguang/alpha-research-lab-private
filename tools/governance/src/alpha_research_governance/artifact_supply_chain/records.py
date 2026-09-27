"""Define signed release records and independently provisioned local target trust."""

from __future__ import annotations

# standard library imports
import base64
import hashlib
import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

# third party library imports
from pydantic import Field, model_validator

# project library imports
from alpha_research_governance._models import ImmutableModel

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identity = Annotated[str, Field(pattern=r"^[a-z][a-z0-9._-]{0,95}$")]
SchemaVersion = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,95}$")]


class ReleaseFile(ImmutableModel):
    """Bind one regular relative file to its exact bytes, including empty files."""

    path: str
    sha256: Digest
    size: Annotated[int, Field(ge=0, le=268_435_456)]

    @model_validator(mode="after")
    def validate_path(self) -> Self:
        """Reject traversal, platform aliases, control characters and ambiguous names."""
        self.require_path(self.path)
        return self

    @staticmethod
    def require_path(value: str) -> None:
        """Require a canonical portable file name inside an artifact root."""
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or re.fullmatch(r"[A-Za-z0-9_./+-]+", value) is None
        ):
            raise ValueError("unsafe release file path")

    @classmethod
    def describe(cls, path: str, content: bytes) -> Self:
        """Identify content without retaining its bytes in the signed manifest."""
        return cls(path=path, sha256=hashlib.sha256(content).hexdigest(), size=len(content))


class ReleaseRuntime(ImmutableModel):
    """Bind installation to an exact interpreter and declared operating contract."""

    python_version: Literal["3.14.7"]
    platform: Literal["darwin_arm64", "linux_x86_64"]
    contract_version: Literal["1"]
    application: Literal["collector", "execution"]
    mode: Literal["collection", "research", "paper", "shadow"]
    config_schema: SchemaVersion
    state_schema: SchemaVersion
    production_submission: Literal[False] = False

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        """Keep collector and intent-only execution placement modes distinct."""
        if (self.application == "collector") != (self.mode == "collection"):
            raise ValueError("application and operating mode are incompatible")
        account_configuration = self.config_schema == "account-runtime-v1"
        account_state = self.state_schema in ("account-journal-v2", "account-journal-v3")
        if account_configuration != account_state or (
            account_configuration
            and (self.application != "execution" or self.mode not in ("paper", "shadow"))
        ):
            raise ValueError("account configuration, state and mode are incompatible")
        return self


class ReleaseManifest(ImmutableModel):
    """Authenticate source, admission, complete payload and compatibility together."""

    schema_version: Literal["signed-release-v1"] = "signed-release-v1"
    name: Identity
    builder: Identity
    origin: str
    created_at: datetime
    valid_until: datetime
    source_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    source_dirty: bool
    build_commands: tuple[tuple[str, ...], ...]
    runtime: ReleaseRuntime
    root_distribution: Literal["alpha-research-collector", "alpha-research-execution"]
    files: tuple[ReleaseFile, ...]

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        """Reject unbounded lifetimes, incomplete provenance and inventory ambiguity."""
        for instant in (self.created_at, self.valid_until):
            if instant.tzinfo != UTC:
                raise ValueError("release timestamps must use UTC")
        if not self.created_at < self.valid_until:
            raise ValueError("release validity interval is empty")
        if not self.origin or self.origin != self.origin.strip():
            raise ValueError("release origin is missing")
        if not self.build_commands or any(
            not command or any(not part for part in command) for command in self.build_commands
        ):
            raise ValueError("release build command is missing")
        expected = "alpha-research-" + self.runtime.application
        if self.root_distribution != expected:
            raise ValueError("release root and application differ")
        paths = [item.path for item in self.files]
        if len(paths) != len(set(path.casefold() for path in paths)):
            raise ValueError("duplicate release inventory path")
        if paths != sorted(paths) or len(paths) > 8192:
            raise ValueError("release inventory must be bounded and sorted")
        if sum(item.size for item in self.files) > 536_870_912:
            raise ValueError("release payload exceeds byte budget")
        required = {
            "provenance/closure.json",
            "provenance/uv.lock",
            "provenance/dependency-admission.toml",
            "provenance/audit.json",
            "provenance/source.json",
            "configuration/config.json",
            "state/state.json",
        }
        if not required.issubset(paths):
            raise ValueError("release lacks required provenance, configuration or state")
        return self

    def encoded(self) -> bytes:
        """Return deterministic signed bytes; the record is revalidated at boundaries."""
        return self.model_dump_json().encode()


class TrustedBuilder(ImmutableModel):
    """Scope an out-of-band Ed25519 key to builders, origins and operating roots."""

    identity: Identity
    public_key: str
    origins: tuple[str, ...]
    roots: tuple[Literal["alpha-research-collector", "alpha-research-execution"], ...]
    valid_from: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def validate_trust(self) -> Self:
        """Validate exact OpenSSH Ed25519 key framing and explicit trust scopes."""
        parts = self.public_key.split(" ")
        if len(parts) != 2 or parts[0] != "ssh-ed25519":
            raise ValueError("trust requires a bare OpenSSH Ed25519 public key")
        try:
            decoded = base64.b64decode(parts[1], validate=True)
        except ValueError as error:
            raise ValueError("invalid trusted public key") from error
        if decoded[:19] != b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" or len(decoded) != 51:
            raise ValueError("invalid Ed25519 key framing")
        if not self.origins or not self.roots or len(set(self.origins)) != len(self.origins):
            raise ValueError("trust requires explicit unique scopes")
        if any(not origin or origin != origin.strip() for origin in self.origins):
            raise ValueError("invalid trusted origin")
        if (
            self.valid_from.tzinfo != UTC
            or self.valid_until.tzinfo != UTC
            or self.valid_from >= self.valid_until
        ):
            raise ValueError("invalid builder trust interval")
        return self


class InstallationPolicy(ImmutableModel):
    """Pin target tools and trust outside the untrusted registry payload.

    File ownership and provisioning of this policy are the operator's trust root.
    Release bytes cannot replace it, add keys or authorize trading.
    """

    schema_version: Literal["installation-policy-v1"] = "installation-policy-v1"
    target: Literal["darwin_arm64", "linux_x86_64"]
    python_executable: str
    python_sha256: Digest
    uv_executable: str
    uv_sha256: Digest
    ssh_keygen_executable: str
    ssh_keygen_sha256: Digest
    builders: tuple[TrustedBuilder, ...]
    config_schemas: tuple[SchemaVersion, ...]
    state_schemas: tuple[SchemaVersion, ...]

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        """Require distinct trust keys and explicit compatibility admission."""
        if (
            not self.builders
            or len({key.public_key for key in self.builders}) != len(self.builders)
            or not self.config_schemas
            or not self.state_schemas
        ):
            raise ValueError("installation policy has empty or duplicate trust")
        return self


class StateEnvelope(ImmutableModel):
    """Pin initial application state without interpreting another owner's payload.

    The application owns schema semantics. The installer requires exact schema
    equality on upgrade and rollback, and preserves the current state directory.
    """

    schema_version: SchemaVersion
    application: Literal["collector", "execution"]
    files: tuple[ReleaseFile, ...]

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        """Require a complete unique state snapshot with no reserved envelope name."""
        paths = [item.path for item in self.files]
        if paths != sorted(set(paths)) or "state.json" in paths:
            raise ValueError("invalid state inventory")
        return self
