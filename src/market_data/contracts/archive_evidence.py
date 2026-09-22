"""Retain native Tardis response slices corroborating individual Binance archive trades."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta

# project library imports
from serialization import DomainCodec, WireRecord


class CaptureSlice(WireRecord, frozen=True, kw_only=True):
    """Keep a complete uncompressed native response with its actual acquisition clock.

    The interval is the Tardis API capture-time request, not exchange event time.
    Raw response bytes retain blank disconnect markers. No field asserts completeness.
    """

    start: datetime
    minutes: int
    received_at: datetime
    payload: bytes

    def __post_init__(self) -> None:
        """Reject incomplete framing, unsafe bounds and backdated acquisition clocks."""
        self._require_utc(self.start, field_name="capture start")
        self._require_utc(self.received_at, field_name="capture receipt")
        if (
            type(self.minutes) is not int
            or not 1 <= self.minutes <= 10
            or self.start.second
            or self.start.microsecond
            or self.received_at < self.start + timedelta(minutes=self.minutes)
            or type(self.payload) is not bytes
            or len(self.payload) > 20_000_000
            or (self.payload and not self.payload.endswith(b"\n"))
        ):
            raise ValueError("invalid native capture slice")


class ArchiveCapture(WireRecord, frozen=True, kw_only=True):
    """Bind native Binance trade captures to one frozen archive request and raw object.

    This proves only agreement with the retained recorder feed. It cannot establish
    upstream completeness, unseen revisions, or historical trading eligibility.
    """

    request_identity: str
    archive_sha256: str
    access_reference: str
    slices: tuple[CaptureSlice, ...]

    def __post_init__(self) -> None:
        """Require immutable contiguous native response slices and an explicit access record."""
        for digest in (self.request_identity, self.archive_sha256):
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise ValueError("capture binding requires SHA-256 identities")
        if type(self.access_reference) is not str or not self.access_reference.strip():
            raise ValueError("capture requires its retained public access reference")
        if type(self.slices) is not tuple or not self.slices or len(self.slices) > 145:
            raise ValueError("capture requires bounded native response slices")
        previous: datetime | None = None
        for item in self.slices:
            if type(item) is not CaptureSlice:
                raise TypeError("capture requires CaptureSlice records")
            item.__post_init__()
            if previous is not None and item.start != previous:
                raise ValueError("capture slices must be contiguous without overlaps")
            previous = item.start + timedelta(minutes=item.minutes)

    @property
    def identity(self) -> str:
        """Identify the exact native responses, clocks, access and archive binding.

        Returns:
            Immutable evidence SHA-256 independent of local paths.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class ArchiveAvailability(WireRecord, frozen=True, kw_only=True):
    """Attach a reverified native capture clock without changing original archive fields."""

    evidence_identity: str
    available_at: datetime

    def __post_init__(self) -> None:
        """Reject malformed source identity or a non-UTC effective availability."""
        self._require_utc(self.available_at, field_name="witness availability")
        if (
            type(self.evidence_identity) is not str
            or len(self.evidence_identity) != 64
            or any(char not in "0123456789abcdef" for char in self.evidence_identity)
        ):
            raise ValueError("availability requires capture evidence SHA-256")
