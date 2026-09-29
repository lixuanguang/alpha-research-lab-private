"""Resolve explicit offline data jobs against complete authored catalog intervals."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import ClassVar, Literal

# third party library imports
import msgspec

# project library imports
from reference_data.catalogs import CatalogSnapshot, SpotInstrument
from reference_data.instruments import InstrumentId
from serialization import DomainCodec


class _ConfigurationRecord(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Share strict identifiers and deterministic identities for cold configuration."""

    _codec: ClassVar[DomainCodec] = DomainCodec()

    @staticmethod
    def _text(value: object) -> None:
        """Require a bounded, nonempty reference without control characters."""
        if not isinstance(value, str) or not 1 <= len(value) <= 256:
            raise ValueError("configuration references must contain 1-256 characters")
        if value != value.strip() or not value.isprintable():
            raise ValueError("configuration references must be printable without outer whitespace")


class Universe(_ConfigurationRecord, frozen=True, kw_only=True):
    """Define available canonical listings without activating a job."""

    name: str
    instrument_ids: tuple[InstrumentId, ...]

    def __post_init__(self) -> None:
        """Validate a nonempty, unique and bounded instrument selection.

        Raises:
            ValueError: A name or selection is invalid.
        """
        self._text(self.name)
        if type(self.instrument_ids) is not tuple or not 1 <= len(self.instrument_ids) <= 32:
            raise ValueError("universe must contain 1-32 instrument IDs in a tuple")
        if any(type(item) is not InstrumentId for item in self.instrument_ids):
            raise ValueError("universe members must be canonical InstrumentId values")
        if len(set(self.instrument_ids)) != len(self.instrument_ids):
            raise ValueError("universe contains duplicate instrument IDs")


class DataJob(_ConfigurationRecord, frozen=True, kw_only=True):
    """Select the implemented offline trade capability and explicit non-secret inputs.

    The capture interval is UTC, half-open and minute-aligned, at most one day.
    Rights and revision references grant no access; acquisition requires explicit admission.
    """

    name: str
    universe: str
    provider: Literal["tardis", "binance-archive"]
    venue: Literal["binance"]
    product: Literal["spot"]
    dataset: Literal["raw"]
    stream: Literal["trade"]
    mode: Literal["fixture", "historical"]
    pipeline: Literal["dataset.inspect", "acquisition.fetch"]
    partition: Literal["utc-minute", "utc-day"]
    capture_policy: Literal["source-capture", "exchange-time-only"]
    source_revision: str
    rights_reference: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        """Reject unsupported capabilities and invalid bounded capture intervals.

        Raises:
            ValueError: A reference, capability, timestamp or interval is invalid.
        """
        for value in (self.name, self.universe, self.source_revision, self.rights_reference):
            self._text(value)
        selection = (
            self.provider,
            self.venue,
            self.product,
            self.dataset,
            self.stream,
            self.partition,
            self.capture_policy,
        )
        if selection not in {
            ("tardis", "binance", "spot", "raw", "trade", "utc-minute", "source-capture"),
            (
                "binance-archive",
                "binance",
                "spot",
                "raw",
                "trade",
                "utc-day",
                "exchange-time-only",
            ),
        }:
            raise ValueError("unsupported source/product/mode/pipeline or partition/capture policy")
        if (self.mode, self.pipeline) not in {
            ("fixture", "dataset.inspect"),
            ("historical", "acquisition.fetch"),
        }:
            raise ValueError("unsupported mode/pipeline combination")
        for timestamp in (self.start, self.end):
            if not isinstance(timestamp, datetime) or timestamp.utcoffset() != timedelta(0):
                raise ValueError("job timestamps must be timezone-aware UTC")
            if timestamp.second or timestamp.microsecond:
                raise ValueError("utc-minute partitions require minute-aligned timestamps")
        if not timedelta(0) < self.end - self.start <= timedelta(days=1):
            raise ValueError("job interval must be nonempty and at most one day")
        if self.provider == "binance-archive" and (
            self.mode != "historical"
            or self.end > self.start.replace(hour=0, minute=0) + timedelta(days=1)
        ):
            raise ValueError("Binance archive acquisition selects an interval within one UTC day")


class ResolvedManifest(_ConfigurationRecord, frozen=True, kw_only=True):
    """Retain actual selected metadata and implementation identity for one resolved job."""

    schema_version: Literal["1"] = "1"
    job: DataJob
    catalog: CatalogSnapshot
    instruments: tuple[SpotInstrument, ...]
    implementation_identity: str

    def __post_init__(self) -> None:
        """Reject unsafe records and require exact selected catalog bindings.

        Raises:
            ValueError: The schema, identity, selection or full-interval coverage is invalid.
        """
        if self.schema_version != "1" or type(self.job) is not DataJob:
            raise ValueError("invalid resolved manifest schema or job")
        self.job.__post_init__()
        if type(self.catalog) is not CatalogSnapshot:
            raise ValueError("manifest requires a CatalogSnapshot")
        self.catalog.validate()
        if (
            not isinstance(self.implementation_identity, str)
            or len(self.implementation_identity) != 64
            or any(char not in "0123456789abcdef" for char in self.implementation_identity)
        ):
            raise ValueError("implementation_identity must be a lowercase SHA-256 digest")
        if type(self.instruments) is not tuple or not 1 <= len(self.instruments) <= 32:
            raise ValueError("manifest requires 1-32 resolved instruments")
        ids: list[str] = []
        for instrument in self.instruments:
            if type(instrument) is not SpotInstrument:
                raise ValueError("manifest instruments must be SpotInstrument records")
            instrument.validate()
            expected_source = (
                "binance.archive.spot"
                if self.job.provider == "binance-archive"
                else "tardis.binance.spot"
            )
            if instrument.source != expected_source:
                raise ValueError("instrument source differs from the selected provider")
            resolved = self.catalog.resolve(instrument.instrument_id, self.job.start, self.job.end)
            if instrument != resolved:
                raise ValueError("manifest instrument differs from its catalog binding")
            ids.append(str(instrument.instrument_id))
        if ids != sorted(set(ids)):
            raise ValueError("manifest instruments must be unique and sorted by canonical ID")

    @property
    def identity(self) -> str:
        """Hash the complete validated resolved job and its actual bindings.

        Returns:
            Lowercase SHA-256 digest, independent of JSON input formatting.
        """
        self.__post_init__()
        return hashlib.sha256(self._codec.encode_json(self)).hexdigest()


class Configuration(_ConfigurationRecord, frozen=True, kw_only=True):
    """Parse versioned definitions and resolve only the explicitly selected data job."""

    schema_version: Literal["1"] = "1"
    universes: tuple[Universe, ...]
    jobs: tuple[DataJob, ...]

    def __post_init__(self) -> None:
        """Validate definitions, unique names and every universe reference.

        Raises:
            ValueError: Definitions are malformed, unsupported, duplicate or unbound.
        """
        if self.schema_version != "1":
            raise ValueError("unsupported configuration schema version")
        for records, expected in ((self.universes, Universe), (self.jobs, DataJob)):
            if type(records) is not tuple or not records:
                raise ValueError("configuration definitions must be nonempty tuples")
            names: set[str] = set()
            for record in records:
                if type(record) is not expected:
                    raise ValueError("configuration contains an invalid definition type")
                record.__post_init__()
                if record.name in names:
                    raise ValueError(f"duplicate configuration name: {record.name}")
                names.add(record.name)
        universe_names = {universe.name for universe in self.universes}
        for job in self.jobs:
            if job.universe not in universe_names:
                raise ValueError(f"job {job.name}: missing universe binding {job.universe}")

    def resolve(
        self, job_name: str, catalog: CatalogSnapshot, *, implementation_identity: str
    ) -> ResolvedManifest:
        """Bind a named job to its complete interval and installed implementation bytes.

        Args:
            implementation_identity: Explicit fingerprint supplied by application composition.
            job_name: Explicit job selection; catalog membership never activates a job.
            catalog: Authored catalog, preserved with its evidence and actual content identity.

        Returns:
            Immutable manifest with sorted actual instruments and all non-secret inputs.

        Raises:
            ValueError: A binding, capability or full-interval catalog coverage is invalid.
            OSError: Installed implementation files cannot be read for identification.
        """
        self.__post_init__()
        for job in self.jobs:
            if job.name == job_name:
                universe = next(item for item in self.universes if item.name == job.universe)
                instruments = tuple(
                    catalog.resolve(item, job.start, job.end)
                    for item in sorted(universe.instrument_ids, key=str)
                )
                return ResolvedManifest(
                    job=job,
                    catalog=catalog,
                    instruments=instruments,
                    implementation_identity=implementation_identity,
                )
        raise ValueError(f"unknown data-job binding: {job_name}")

    @classmethod
    def read(cls, path: Path) -> Configuration:
        """Read one bounded JSON configuration through the existing strict exact codec.

        Args:
            path: Explicit local JSON configuration file.

        Returns:
            Validated definitions without activating any pipeline.

        Raises:
            ValueError: JSON, schema, definitions or the one-MiB input bound is invalid.
            OSError: The file cannot be read.
        """
        with path.open("rb") as source:
            payload = source.read(1_048_577)
        if len(payload) > 1_048_576:
            raise ValueError("configuration exceeds one MiB")
        return cls._codec.decode_json(payload, cls)
