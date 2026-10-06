"""Describe retained raw bytes and verify an existing file against its request."""

from __future__ import annotations

# standard library imports
import hashlib
from compression import zstd
from datetime import datetime
from pathlib import Path

# project library imports
from market_data.contracts import RawObject, RequestBinding


class RawFiles:
    """Fingerprint and verify complete files against validated source bindings."""

    @classmethod
    def describe(
        cls,
        path: Path,
        *,
        request: RequestBinding,
        retrieval_reference: str,
        ts_received: datetime,
        ts_ingested: datetime,
    ) -> RawObject:
        """Describe existing bytes without claiming transport or dataset validity.

        Args:
            path: Existing binary file, read sequentially in bounded chunks.
            request: Resolved instrument and minute partition assigned by the caller.
            retrieval_reference: Non-secret reference to the original retrieval.
            ts_received: Original local receipt instant, explicitly in UTC.
            ts_ingested: Original local ingestion instant, at or after receipt in UTC.

        Returns:
            Immutable descriptor of the bytes read and caller-supplied provenance.

        Raises:
            ValueError: Request or descriptor metadata is invalid.
            OSError: The saved file cannot be opened or read.
        """
        if type(request) is not RequestBinding:
            raise ValueError("raw object requires a validated RequestBinding")
        request.__post_init__()
        request_identity = request.identity
        digest, size = cls._fingerprint(path)
        return RawObject(
            sha256=digest,
            size_bytes=size,
            request_identity=request_identity,
            retrieval_reference=retrieval_reference,
            ts_received=ts_received,
            ts_ingested=ts_ingested,
        )

    @classmethod
    def verify(
        cls,
        descriptor: RawObject,
        path: Path,
        *,
        request: RequestBinding,
        compressed: bool = False,
    ) -> RawObject:
        """Recheck metadata, request binding and all retained bytes without changing state.

        Args:
            descriptor: Expected immutable byte identity and provenance.
            path: Existing saved file; callers must prevent concurrent writes.
            request: Independently expected request, checked before file access.
            compressed: The file holds the bytes as zstd frames; verify the original bytes.

        Returns:
            This descriptor after successful verification, with original clocks intact.

        Raises:
            ValueError: Metadata, request binding, byte count or SHA-256 differs.
            OSError: The saved file cannot be opened or read.
        """
        descriptor.__post_init__()
        if type(request) is not RequestBinding or request.identity != descriptor.request_identity:
            raise ValueError("raw object request identity mismatch")
        request.__post_init__()
        digest, size = cls._fingerprint(path, compressed=compressed)
        if size != descriptor.size_bytes:
            raise ValueError(
                f"raw object size mismatch: expected {descriptor.size_bytes}, got {size}"
            )
        if digest != descriptor.sha256:
            raise ValueError(
                f"raw object SHA-256 mismatch: expected {descriptor.sha256}, got {digest}"
            )
        return descriptor

    @staticmethod
    def _fingerprint(path: Path, *, compressed: bool = False) -> tuple[str, int]:
        """Hash and count the original bytes, decompressing a zstd object first."""
        digest = hashlib.sha256()
        size = 0
        try:
            with zstd.ZstdFile(path, "rb") if compressed else path.open("rb") as source:
                while chunk := source.read(1_048_576):
                    digest.update(chunk)
                    size += len(chunk)
        except (zstd.ZstdError, EOFError) as error:
            raise ValueError("corrupt or truncated compressed raw object") from error
        return digest.hexdigest(), size
