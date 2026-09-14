"""Describe retained raw bytes and verify an existing file against its request."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Self

# third party library imports
import msgspec

# project library imports
from alpha_research.data.requests import SourceRequest


class RawObject(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Bind exact saved bytes to a request partition and original local clocks.

    ``sha256`` and ``size_bytes`` describe the retained representation, including
    compression headers and trailers. ``request_identity`` is the existing
    SourceRequest identity, which already binds the instrument and partition.
    ``retrieval_reference`` is an opaque, non-secret provenance reference, never
    a URL to fetch. Receipt and ingestion are supplied UTC instants; verification
    neither infers nor replaces them. Empty bytes are representable, not evidence
    of a complete or quiet source interval. Serialize with the existing DomainCodec.
    """

    schema_version: Literal["1"] = "1"
    sha256: str
    size_bytes: int
    request_identity: str
    retrieval_reference: str
    ts_received: datetime
    ts_ingested: datetime

    def __post_init__(self) -> None:
        """Reject malformed identities, sizes, references and original timestamps.

        Raises:
            ValueError: A field type, value, schema or clock ordering is invalid.
        """
        if self.schema_version != "1":
            raise ValueError("unsupported raw-object schema version")
        for name, digest in (("sha256", self.sha256), ("request_identity", self.request_identity)):
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("size_bytes must be a nonnegative integer")
        reference = self.retrieval_reference
        if (
            not isinstance(reference, str)
            or not 1 <= len(reference) <= 256
            or reference != reference.strip()
            or not reference.isprintable()
        ):
            raise ValueError("retrieval_reference must contain 1-256 printable trimmed characters")
        for name, timestamp in (
            ("ts_received", self.ts_received),
            ("ts_ingested", self.ts_ingested),
        ):
            if not isinstance(timestamp, datetime) or timestamp.utcoffset() != timedelta(0):
                raise ValueError(f"{name} must be timezone-aware UTC")
        if self.ts_ingested < self.ts_received:
            raise ValueError("ts_ingested must not precede ts_received")

    @classmethod
    def from_file(
        cls,
        path: Path,
        *,
        request: SourceRequest,
        retrieval_reference: str,
        ts_received: datetime,
        ts_ingested: datetime,
    ) -> Self:
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
        if type(request) is not SourceRequest:
            raise ValueError("raw object requires a SourceRequest")
        request_identity = request.identity
        digest, size = cls._fingerprint(path)
        return cls(
            sha256=digest,
            size_bytes=size,
            request_identity=request_identity,
            retrieval_reference=retrieval_reference,
            ts_received=ts_received,
            ts_ingested=ts_ingested,
        )

    def verify(self, path: Path, *, request: SourceRequest) -> Self:
        """Recheck metadata, request binding and all retained bytes without changing state.

        Args:
            path: Existing saved file; callers must prevent concurrent writes.
            request: Independently expected request, checked before file access.

        Returns:
            This descriptor after successful verification, with original clocks intact.

        Raises:
            ValueError: Metadata, request binding, byte count or SHA-256 differs.
            OSError: The saved file cannot be opened or read.
        """
        self.__post_init__()
        if type(request) is not SourceRequest or request.identity != self.request_identity:
            raise ValueError("raw object request identity mismatch")
        digest, size = self._fingerprint(path)
        if size != self.size_bytes:
            raise ValueError(f"raw object size mismatch: expected {self.size_bytes}, got {size}")
        if digest != self.sha256:
            raise ValueError(f"raw object SHA-256 mismatch: expected {self.sha256}, got {digest}")
        return self

    @staticmethod
    def _fingerprint(path: Path) -> tuple[str, int]:
        """Hash and count the same binary stream without decoding or decompressing it."""
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            while chunk := source.read(1_048_576):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size
