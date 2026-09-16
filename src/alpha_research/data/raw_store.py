"""Publish verified raw files without replacing content-addressed objects."""

from __future__ import annotations

# standard library imports
import os
import shutil
import stat
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

# project library imports
from alpha_research.data.live.config import CaptureRequest
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.requests import SourceRequest
from alpha_research.data.venues.okx.history_config import OKXArchiveRequest


class RawStore:
    """Own immutable byte publication in an existing, durably provisioned directory.

    The caller controls the directory and excludes external mutation/removal of
    objects and directory ancestors. Concurrent publishers through this API are
    supported. Local filesystem hard links and file/directory fsync are required;
    unsupported operations fail. Descriptors remain caller-owned, not persisted
    manifests. Hidden staging files left by process death are never read as objects.
    """

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
        request: SourceRequest | CaptureRequest | OKXArchiveRequest,
    ) -> Path:
        """Stage, verify and durably publish saved bytes, or verify and reuse them.

        Args:
            source: Saved regular binary file, copied in bounded chunks if absent.
            descriptor: Trusted expected byte identity and original provenance.
            request: Independently expected source partition.

        Returns:
            Content-addressed path after file and directory synchronization. An
            existing matching object is reused even if source is no longer present.

        Raises:
            ValueError: Metadata, request, file kind or retained bytes conflict.
            OSError: Copy, publication or synchronization fails. Publication may
                already be visible; retry verifies and synchronizes it again.
        """
        destination = self._object_path(descriptor, request)
        if not destination.exists():
            if not stat.S_ISREG(source.stat().st_mode):
                raise ValueError("raw store source must be a regular file")
            with NamedTemporaryFile(dir=self._root, prefix=".staging-", delete=False) as staged:
                staging = Path(staged.name)
                try:
                    with source.open("rb") as original:
                        shutil.copyfileobj(original, staged, length=1_048_576)
                    staged.flush()
                    os.fchmod(staged.fileno(), 0o444)
                    os.fsync(staged.fileno())
                    descriptor.verify(staging, request=request)
                    try:
                        os.link(staging, destination)
                    except FileExistsError:
                        pass  # A concurrent publisher won; verify its bytes below.
                finally:
                    staging.unlink(missing_ok=True)
        with self.open(descriptor=descriptor, request=request) as published:
            os.fsync(published.fileno())
        directory = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return destination

    def open(
        self, *, descriptor: RawObject, request: SourceRequest | CaptureRequest | OKXArchiveRequest
    ) -> BinaryIO:
        """Verify the complete published object before exposing a read-only stream.

        Args:
            descriptor: Trusted expected byte identity and original provenance.
            request: Independently expected source partition.

        Returns:
            Binary stream positioned at zero; the caller owns closing it. Verification
            and subsequent reads require the store's exclusion of external mutation.

        Raises:
            ValueError: Metadata, request, nonregular object or byte integrity fails.
            OSError: The published object is absent or cannot be read.
        """
        path = self._object_path(descriptor, request)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("raw store object must be a regular file, not a symlink")
        descriptor.verify(path, request=request)
        return path.open("rb")

    def _object_path(
        self, descriptor: RawObject, request: SourceRequest | CaptureRequest | OKXArchiveRequest
    ) -> Path:
        """Revalidate caller-owned metadata before using a digest as a filename."""
        descriptor.__post_init__()
        if (
            type(request) not in (SourceRequest, CaptureRequest, OKXArchiveRequest)
            or request.identity != descriptor.request_identity
        ):
            raise ValueError("raw object request identity mismatch")
        return self._root / descriptor.sha256
