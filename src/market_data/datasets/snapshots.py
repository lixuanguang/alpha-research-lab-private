"""Publish complete local datasets at one immutable directory visibility boundary."""

from __future__ import annotations

# standard library imports
import errno
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar, cast, overload

# project library imports
from market_data.datasets.books import BookDatasetManifest, BookPartition
from market_data.datasets.manifests import DatasetManifest, DatasetPartition
from market_data.datasets.readers import DatasetReaders
from market_data.storage import RawStore
from market_data.validation import QualityReport
from serialization import DomainCodec


class SnapshotStore[Manifest: DatasetManifest | BookDatasetManifest = DatasetManifest]:
    """Own atomic publication in an existing, durably provisioned local directory.

    Callers retain the referenced raw store and exclude external mutation/removal
    of both stores and their ancestors. Concurrent API publishers are supported.
    Same-filesystem directory rename and file/directory fsync are required.
    Process death may leave hidden staging directories; readers never select them.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()

    @overload
    def __init__(
        self: SnapshotStore[DatasetManifest], root: Path, raw: RawStore, *, readers: DatasetReaders
    ) -> None: ...

    @overload
    def __init__(
        self, root: Path, raw: RawStore, *, readers: DatasetReaders, manifest_type: type[Manifest]
    ) -> None: ...

    def __init__(
        self,
        root: Path,
        raw: RawStore,
        *,
        readers: DatasetReaders,
        manifest_type: type[Manifest] | type[DatasetManifest] = DatasetManifest,
    ) -> None:
        """Bind stable publication and raw-input locations without filesystem effects.

        Args:
            readers: Selected readers and native re-decoders for complete verification.
            root: Existing snapshot directory on the destination filesystem.
            raw: Retained immutable raw objects required for verification and reopening.
            manifest_type: Explicit book format, or the original trade format by default.

        Raises:
            ValueError: The requested snapshot format is unsupported.
        """
        self._root = root
        if manifest_type not in (DatasetManifest, BookDatasetManifest):
            raise ValueError("unsupported snapshot manifest type")
        self._raw = raw
        self._readers = readers
        self._manifest_type: type[Manifest] | type[DatasetManifest] = manifest_type

    def publish(self, manifest: Manifest, payloads: tuple[bytes, ...], *, max_bytes: int) -> str:
        """Stage and verify the entire dataset before publishing its explicit identity.

        Args:
            manifest: Validated ordered partition identities and admission evidence.
            payloads: Corresponding canonical partition bytes, in manifest order.
            max_bytes: Positive per-file limit, including expanded raw input bytes.

        Returns:
            Dataset SHA-256 after durable publication, or verified idempotent reuse.

        Raises:
            ValueError: Limits, partition count, retained bytes or admission disagree.
            OSError: Staging, verification, rename or synchronization fails. After
                rename the complete snapshot may be visible; retry the same identity
                to verify and synchronize it. Previously published snapshots survive.
        """
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("snapshot max_bytes must be a positive integer")
        if type(manifest) is not self._manifest_type:
            raise ValueError("snapshot manifest differs from selected format")
        identity = manifest.identity
        if len(payloads) != len(manifest.partitions):
            raise ValueError("snapshot requires one payload per declared partition")
        destination = self._root / identity
        if not destination.exists():
            with TemporaryDirectory(dir=self._root, prefix=".staging-") as temporary:
                staging = Path(temporary)
                selected: tuple[DatasetPartition | BookPartition, ...] = manifest.partitions
                for partition, payload in zip(selected, payloads, strict=True):
                    self._write(staging / partition.sha256, payload, max_bytes)
                self._write(staging / "manifest.json", self._codec.encode_json(manifest), max_bytes)
                self._read(staging, identity, max_bytes)
                self._sync_directory(staging)
                try:
                    os.rename(staging, destination)
                except OSError as error:
                    if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                        raise
                    # A concurrent publisher won; verify its complete snapshot below.
        self.read(identity, max_bytes=max_bytes)
        self._sync_directory(self._root)
        return identity

    def read(
        self,
        identity: str,
        *,
        max_bytes: int,
        report: Callable[[str, QualityReport], None] | None = None,
    ) -> Manifest:
        """Reopen a complete snapshot by explicit content identity, never a mutable tag.

        Args:
            identity: Independently retained lowercase dataset SHA-256.
            max_bytes: Positive per-file limit for manifest, canonical and raw bytes.
            report: Optional synchronous sink for verified partition quality, using the
                admission already reproduced during this read. Failures propagate and
                no whole-snapshot success follows unless every partition verifies.

        Returns:
            Manifest after every referenced canonical and raw input verifies.

        Raises:
            ValueError: Identity, file kind, size, bytes or admission is invalid.
            OSError: The selected snapshot or one of its retained inputs is unavailable.
        """
        if type(identity) is not str or re.fullmatch(r"[0-9a-f]{64}", identity) is None:
            raise ValueError("snapshot requires an explicit lowercase SHA-256 identity")
        return self._read(self._root / identity, identity, max_bytes, report=report)

    def _read(
        self,
        directory: Path,
        identity: str,
        max_bytes: int,
        *,
        report: Callable[[str, QualityReport], None] | None = None,
    ) -> Manifest:
        """Verify staging or published bytes through the existing manifest boundary."""
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise ValueError("snapshot must be a directory, not a symlink")
        for path in directory.iterdir():
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("snapshot files must be regular files, not symlinks")
        manifest = self._manifest_type.read(
            directory / "manifest.json",
            identity=identity,
            partitions=directory,
            store=self._raw,
            max_bytes=max_bytes,
            report=report,
            readers=self._readers,
        )
        return cast(Manifest, manifest)

    @staticmethod
    def _write(path: Path, payload: bytes, max_bytes: int) -> None:
        """Bound, flush and synchronize one read-only staged file before verification."""
        if len(payload) > max_bytes:
            raise ValueError("snapshot file exceeds max_bytes")
        with path.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fchmod(output.fileno(), 0o444)
            os.fsync(output.fileno())

    @staticmethod
    def _sync_directory(path: Path) -> None:
        """Synchronize directory entries before acknowledging durable publication."""
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
