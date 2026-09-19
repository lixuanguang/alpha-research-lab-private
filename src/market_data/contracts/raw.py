"""Describe retained raw bytes and verify an existing file against its request."""

from __future__ import annotations

# standard library imports
from datetime import datetime, timedelta
from typing import Literal

# third party library imports
import msgspec

# project library imports


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


class RequestBinding(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Retain the validated source identity needed by neutral byte storage."""

    identity: str

    def __post_init__(self) -> None:
        """Reject malformed or unsafely replaced storage identities.

        Raises:
            ValueError: The request identity is not a lowercase SHA-256 digest.
        """
        if (
            type(self.identity) is not str
            or len(self.identity) != 64
            or any(char not in "0123456789abcdef" for char in self.identity)
        ):
            raise ValueError("request identity must be a lowercase SHA-256 digest")
