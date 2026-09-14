"""Derive identified per-instrument minute requests from a resolved offline job."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from typing import ClassVar, Literal

# third party library imports
import msgspec

# project library imports
from alpha_research.configuration import ResolvedManifest
from alpha_research.reference_data import SpotInstrument
from alpha_research.serialization import DomainCodec


class SourceRequest(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Bind one minute of source capture to its complete immutable run manifest.

    ``offset_minutes`` is relative to the job's fixed ``start`` (the future HTTP
    ``from`` value). No endpoint, transport or data-access admission is implied.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()

    schema_version: Literal["1"] = "1"
    manifest: ResolvedManifest
    instrument: SpotInstrument
    offset_minutes: int

    def __post_init__(self) -> None:
        """Reject invalid manifests, instrument bindings and partition offsets.

        Raises:
            ValueError: A nested contract, binding, schema or minute offset is invalid.
        """
        if self.schema_version != "1" or type(self.manifest) is not ResolvedManifest:
            raise ValueError("invalid source request schema or manifest")
        self.manifest.__post_init__()
        if type(self.instrument) is not SpotInstrument:
            raise ValueError("source request instrument must be a SpotInstrument")
        self.instrument.validate()
        if self.instrument not in self.manifest.instruments:
            raise ValueError("source request instrument is outside the resolved universe")
        if (
            type(self.offset_minutes) is not int
            or not 0 <= self.offset_minutes < self._minute_count()
        ):
            raise ValueError("source request offset must identify a minute inside the job interval")

    @property
    def identity(self) -> str:
        """Identify source semantics without job names or unrelated universe members.

        Returns:
            SHA-256 binding the source selection, actual instrument, catalog, code,
            policies and fixed origin/offset. Renaming a job preserves this identity.
        """
        self.__post_init__()
        job = self.manifest.job
        selection = (
            job.provider,
            job.venue,
            job.product,
            job.dataset,
            job.stream,
            job.mode,
            job.pipeline,
            job.partition,
            job.capture_policy,
            job.source_revision,
            job.rights_reference,
        )
        content = (
            self.schema_version,
            selection,
            self.instrument,
            job.start,
            self.offset_minutes,
            self.manifest.catalog.identity,
            self.manifest.implementation_identity,
        )
        return hashlib.sha256(self._codec.encode_json(content)).hexdigest()

    @property
    def start(self) -> datetime:
        """Return the inclusive UTC capture boundary.

        Returns:
            Fixed job start plus the integer minute offset.
        """
        return self.manifest.job.start + timedelta(minutes=self.offset_minutes)

    @property
    def end(self) -> datetime:
        """Return the exclusive UTC capture boundary.

        Returns:
            Exactly one minute after this request's start.
        """
        return self.start + timedelta(minutes=1)

    def _minute_count(self) -> int:
        """Count complete minutes without floating-point timestamp arithmetic."""
        return (self.manifest.job.end - self.manifest.job.start) // timedelta(minutes=1)

    @classmethod
    def partition(cls, manifest: ResolvedManifest) -> tuple[SourceRequest, ...]:
        """Resolve deterministic minute-major, then canonical-instrument request order.

        Args:
            manifest: Fully resolved bounded offline job and catalog bindings.

        Returns:
            Immutable requests covering every selected instrument's complete interval.

        Raises:
            ValueError: The manifest or a derived request violates its contract.
        """
        manifest.__post_init__()
        minutes = (manifest.job.end - manifest.job.start) // timedelta(minutes=1)
        return tuple(
            cls(manifest=manifest, instrument=instrument, offset_minutes=offset)
            for offset in range(minutes)
            for instrument in manifest.instruments
        )
