"""Commit complete research output manifests after all immutable artifact bytes exist."""

from __future__ import annotations

# standard library imports
import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

# project library imports
from research.experiments import AttemptStore, Fingerprint
from serialization import DomainCodec, WireRecord, sync_directory
from simulation import EconomicCheckpoint


class RunCheckpoint(WireRecord, frozen=True):
    """Prevent economic state resumption across configuration, code or environment changes."""

    run_identity: str
    economic: EconomicCheckpoint
    schema_version: str = "configured-checkpoint"

    def __post_init__(self) -> None:
        """Validate schema and complete economic state before resumption."""
        Fingerprint(name="run", sha256=self.run_identity)
        if (
            self.schema_version != "configured-checkpoint"
            or type(self.economic) is not EconomicCheckpoint
        ):
            raise ValueError("unsupported configured checkpoint")
        self.economic.__post_init__()


class ResultManifest(WireRecord, frozen=True):
    """Commit exact artifact identities as the successful attempt's result."""

    artifacts: tuple[Fingerprint, ...]
    schema_version: str = "research-result"

    def __post_init__(self) -> None:
        """Reject empty, duplicate or unsupported committed artifact inventories."""
        if (
            self.schema_version != "research-result"
            or type(self.artifacts) is not tuple
            or not self.artifacts
        ):
            raise ValueError("invalid result manifest")
        for artifact in self.artifacts:
            if type(artifact) is not Fingerprint:
                raise TypeError("manifest requires artifact fingerprints")
            artifact.__post_init__()
        if len({item.name for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("duplicate result artifact")

    @classmethod
    def retain(
        cls, store: AttemptStore, attempt_id: str, artifacts: dict[str, bytes]
    ) -> ResultManifest:
        """Stage immutable output bytes before any caller can complete the attempt.

        Args:
            store: Entered single-writer store.
            attempt_id: Current execution retaining partial outputs even on failure.
            artifacts: Complete named outputs including HTML, report inputs and exact trace.

        Returns:
            Manifest of durably retained bytes; not a successful completion by itself.
        """
        return cls(
            artifacts=tuple(
                Fingerprint(name=name, sha256=store.retain(attempt_id, name, payload))
                for name, payload in sorted(artifacts.items())
            )
        )

    @classmethod
    def read(cls, store: AttemptStore, attempt_id: str) -> ResultManifest:
        """Reopen successful results only after checking every retained artifact digest.

        Args:
            store: Retained attempt store, usable read-only for inspection.
            attempt_id: Completed execution to verify.

        Returns:
            Verified output manifest; failed/incomplete outputs never count as success.

        Raises:
            ValueError: Execution is incomplete/failed or retained bytes have changed.
        """
        history = store.read(attempt_id)
        result = history.events[-1].result if history.events else None
        if history.status != "completed" or result is None:
            raise ValueError("attempt has no completed result manifest")
        manifest = DomainCodec().decode_json(result, cls)
        for artifact in manifest.artifacts:
            if (
                hashlib.sha256(store.artifact(attempt_id, artifact.name)).hexdigest()
                != artifact.sha256
            ):
                raise ValueError("retained result artifact digest mismatch")
        return manifest

    @staticmethod
    def export(path: Path, payload: bytes) -> None:
        """Atomically write a human-readable export or checkpoint on the destination filesystem.

        Args:
            path: Explicit destination; an existing different output is refused.
            payload: Complete retained bytes, never an incomplete report.

        Raises:
            ValueError: An existing destination differs from the requested immutable bytes.
        """
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError("existing export differs; select a new output path")
            return
        with NamedTemporaryFile(dir=path.parent, prefix=".report-", delete=False) as staged:
            temporary = Path(staged.name)
            try:
                staged.write(payload)
                staged.flush()
                os.fsync(staged.fileno())
                os.link(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        sync_directory(path.parent)
