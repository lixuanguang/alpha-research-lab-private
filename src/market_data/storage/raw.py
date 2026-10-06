"""Publish verified raw files without replacing content-addressed objects."""

from __future__ import annotations

# standard library imports
import os
import shutil
import stat
from compression import zstd
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO, BinaryIO, ClassVar, cast

# project library imports
from market_data.contracts import RawObject, RequestBinding
from market_data.storage.objects import RawFiles
from serialization import DurableDirectory


class RawStore:
    """Own immutable byte publication in an existing, durably provisioned directory.

    The caller controls the directory and excludes external mutation/removal of
    objects and directory ancestors. Concurrent publishers through this API are
    supported. Local filesystem hard links and file/directory fsync are required;
    unsupported operations fail. Descriptors remain caller-owned, not persisted
    manifests. Hidden staging files left by process death are never read as objects.

    An object is named by its original bytes' SHA-256. It is stored either as those
    bytes, or compressed as zstd frames under the same name with ``.zst`` appended.
    A reader always receives the original bytes.
    """

    _compressed_suffix: ClassVar[str] = ".zst"
    _level: ClassVar[int] = 9
    _chunk: ClassVar[int] = 1_048_576

    def __init__(self, root: Path) -> None:
        """Bind the explicit storage directory without creating filesystem state.

        Args:
            root: Existing directory on the destination filesystem; keep it stable.
        """
        self._root = root

    def publish(
        self,
        source: Path,
        *,
        descriptor: RawObject,
        request: RequestBinding,
        compress: bool,
    ) -> Path:
        """Stage, verify and durably publish saved bytes, or verify and reuse them.

        Args:
            source: Saved regular binary file of the original bytes, copied in bounded
                chunks if the object is absent.
            descriptor: Trusted expected byte identity and original provenance.
            request: Independently expected source partition.
            compress: Store the object as zstd frames. Already compressed sources,
                such as archives replayed by path, are stored as they are.

        Returns:
            Content-addressed path after file and directory synchronization. An
            existing matching object is reused, in either encoding, even if source
            is no longer present.

        Raises:
            ValueError: Metadata, request, file kind or retained bytes conflict.
            OSError: Copy, publication or synchronization fails. Publication may
                already be visible; retry verifies and synchronizes it again.
        """
        if self._stored(descriptor, request) is None:
            if not stat.S_ISREG(source.stat().st_mode):
                raise ValueError("raw store source must be a regular file")
            destination = self._name(descriptor, request, compressed=compress)
            with NamedTemporaryFile(dir=self._root, prefix=".staging-", delete=False) as staged:
                staging = Path(staged.name)
                try:
                    with source.open("rb") as original:
                        if compress:
                            with zstd.ZstdFile(staged, "wb", level=self._level) as encoded:
                                shutil.copyfileobj(original, encoded, length=self._chunk)
                        else:
                            shutil.copyfileobj(original, staged, length=self._chunk)
                    self._seal(staged, descriptor, request, staging, destination, compress)
                finally:
                    staging.unlink(missing_ok=True)
        return self._synchronize(descriptor, request)

    def copy(self, origin: RawStore, *, descriptor: RawObject, request: RequestBinding) -> Path:
        """Publish another store's object in its stored encoding, or reuse a present one.

        Args:
            origin: Store holding the verified object.
            descriptor: Trusted expected byte identity and original provenance.
            request: Independently expected source partition.

        Returns:
            Content-addressed path after file and directory synchronization.

        Raises:
            ValueError: The origin lacks the object, or bytes or metadata conflict.
            OSError: Copy, publication or synchronization fails.
        """
        if self._stored(descriptor, request) is None:
            source = origin._stored(descriptor, request)
            if source is None:
                raise ValueError("raw object absent from origin store")
            compressed = source.name.endswith(self._compressed_suffix)
            destination = self._name(descriptor, request, compressed=compressed)
            with NamedTemporaryFile(dir=self._root, prefix=".staging-", delete=False) as staged:
                staging = Path(staged.name)
                try:
                    with source.open("rb") as original:
                        shutil.copyfileobj(original, staged, length=self._chunk)
                    self._seal(staged, descriptor, request, staging, destination, compressed)
                finally:
                    staging.unlink(missing_ok=True)
        return self._synchronize(descriptor, request)

    def open(self, *, descriptor: RawObject, request: RequestBinding) -> BinaryIO:
        """Verify the complete published object before exposing a read-only stream.

        Args:
            descriptor: Trusted expected byte identity and original provenance.
            request: Independently expected source partition.

        Returns:
            Binary stream of the original bytes positioned at zero; the caller owns
            closing it. Verification and subsequent reads require the store's
            exclusion of external mutation.

        Raises:
            ValueError: Metadata, request, nonregular object or byte integrity fails.
            OSError: The published object is absent or cannot be read.
        """
        path = self._stored(descriptor, request)
        if path is None:
            raise FileNotFoundError(f"raw object {descriptor.sha256} is absent")
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("raw store object must be a regular file, not a symlink")
        compressed = path.name.endswith(self._compressed_suffix)
        RawFiles.verify(descriptor, path, request=request, compressed=compressed)
        if compressed:
            return cast(BinaryIO, zstd.ZstdFile(path, "rb"))
        return path.open("rb")

    def stored_bytes(self, *, descriptor: RawObject, request: RequestBinding) -> int:
        """Return the bytes the object occupies on disk, compressed or not.

        Raises:
            FileNotFoundError: The object is absent.
        """
        path = self._stored(descriptor, request)
        if path is None:
            raise FileNotFoundError(f"raw object {descriptor.sha256} is absent")
        return path.lstat().st_size

    @staticmethod
    def _seal(
        staged: IO[bytes],
        descriptor: RawObject,
        request: RequestBinding,
        staging: Path,
        destination: Path,
        compressed: bool,
    ) -> None:
        """Make a staged object read-only and durable, verify it, then link it."""
        staged.flush()
        os.fchmod(staged.fileno(), 0o444)
        os.fsync(staged.fileno())
        RawFiles.verify(descriptor, staging, request=request, compressed=compressed)
        try:
            os.link(staging, destination)
        except FileExistsError:
            pass  # A concurrent publisher won; verify its bytes below.

    def _synchronize(self, descriptor: RawObject, request: RequestBinding) -> Path:
        """Verify and fsync the published object and its directory entry."""
        with self.open(descriptor=descriptor, request=request):
            pass
        path = self._stored(descriptor, request)
        if path is None:
            raise FileNotFoundError(f"raw object {descriptor.sha256} is absent")
        with path.open("rb") as published:
            os.fsync(published.fileno())
        DurableDirectory.sync(self._root)
        return path

    def _stored(self, descriptor: RawObject, request: RequestBinding) -> Path | None:
        """Return the one present encoding of the object, or None when absent."""
        present = [
            path
            for path in (
                self._name(descriptor, request, compressed=False),
                self._name(descriptor, request, compressed=True),
            )
            if os.path.lexists(path)
        ]
        if len(present) > 1:
            raise ValueError("raw object stored in two encodings")
        return present[0] if present else None

    def _name(self, descriptor: RawObject, request: RequestBinding, *, compressed: bool) -> Path:
        """Revalidate caller-owned metadata before using a digest as a filename."""
        descriptor.__post_init__()
        if type(request) is not RequestBinding or request.identity != descriptor.request_identity:
            raise ValueError("raw object request identity mismatch")
        request.__post_init__()
        return self._root / (descriptor.sha256 + (self._compressed_suffix if compressed else ""))
