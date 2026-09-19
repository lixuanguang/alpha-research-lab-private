"""Admit bounded saved native book histories without granting causal or execution use."""

from __future__ import annotations

# standard library imports
import hashlib
import re
import tarfile
import time
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import ClassVar, Literal

# third party library imports
import msgspec

# project library imports
from alpha_research.data.live.book import Order, Wire
from alpha_research.data.live.config import CaptureRequest
from alpha_research.data.live.journal import CaptureRecord
from alpha_research.data.live.replay import CaptureReplay
from alpha_research.data.quality import QualityReport
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.data.venues.okx.book import Level, OKXBook
from alpha_research.data.venues.okx.history_config import OKXArchiveRequest
from alpha_research.data.venues.okx.history_reader import OKXArchiveReader
from alpha_research.serialization import DomainCodec


class BookObservation(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Retain one whole message boundary; positions address the manifest's original raw object.

    Orders are native L3 identities; bid/ask entries are aggregate L2 levels. Empty
    state on a control or invalid boundary must not be interpreted as an empty book.
    Full visible state is retained on market boundaries for this bounded reference
    format. Unknown archive receipt/availability and sequence remain None.
    """

    position: int
    epoch: int | None
    received_ns: int | None
    source_time: str | None
    sequence: int | None
    outcome: str
    status: str
    reason: str
    state_identity: str
    orders: tuple[Order, ...] = ()
    bids: tuple[tuple[Decimal, Level], ...] = ()
    asks: tuple[tuple[Decimal, Level], ...] = ()
    transition_ns: int | None = None
    last_durable_ns: int | None = None

    def __post_init__(self) -> None:
        """Reject malformed coordinates, status, state identity and mixed representations."""
        if (
            any(
                value is not None and (type(value) is not int or value < 0)
                for value in (
                    self.position,
                    self.epoch,
                    self.received_ns,
                    self.sequence,
                    self.transition_ns,
                    self.last_durable_ns,
                )
            )
            or type(self.position) is not int
        ):
            raise ValueError("invalid book occurrence coordinates")
        if (
            self.status not in ("degraded", "stale", "recovering", "unavailable")
            or not isinstance(self.reason, str)
            or not self.reason
            or not isinstance(self.outcome, str)
            or not self.outcome
            or not isinstance(self.state_identity, str)
            or not re.fullmatch(r"[a-f0-9]{64}", self.state_identity)
            or (self.source_time is not None and not isinstance(self.source_time, str))
            or any(type(rows) is not tuple for rows in (self.orders, self.bids, self.asks))
            or (self.orders and (self.bids or self.asks))
        ):
            raise ValueError("invalid book state or quality scope")
        for order in self.orders:
            if type(order) is not Order:
                raise ValueError("book orders require native L3 records")
            order.__post_init__()
        for price, level in self.bids + self.asks:
            if type(price) is not Decimal or not price.is_finite() or price <= 0:
                raise ValueError("book levels require positive exact prices")
            if type(level) is not Level:
                raise ValueError("book levels require aggregate size and order count")
            level.__post_init__()
        if len({order.order_id for order in self.orders}) != len(self.orders) or any(
            len({price for price, _ in side}) != len(side) for side in (self.bids, self.asks)
        ):
            raise ValueError("duplicate native order or aggregate price in canonical state")


class BookInput(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Bind a selected raw prefix to native configuration, clocks and original provenance."""

    raw: RawObject
    max_records: int
    capture: CaptureRequest | None = None
    archive: OKXArchiveRequest | None = None
    index: bytes = b""

    def __post_init__(self) -> None:
        """Require exactly one supported request and preserve archive discovery evidence."""
        if (
            type(self.raw) is not RawObject
            or type(self.index) is not bytes
            or (self.capture is not None and type(self.capture) is not CaptureRequest)
            or (self.archive is not None and type(self.archive) is not OKXArchiveRequest)
        ):
            raise ValueError("book input requires typed native provenance")
        if (self.capture is None) == (self.archive is None) or (
            type(self.max_records) is not int or not 1 <= self.max_records <= 10_000
        ):
            raise ValueError("book admission requires one native input and a bounded prefix")
        request = self.request
        request.__post_init__()
        self.raw.__post_init__()
        if self.raw.request_identity != request.identity:
            raise ValueError("book raw object differs from selected request")
        if self.archive is not None and (
            hashlib.sha256(self.index).hexdigest() != self.archive.index_sha256
            or self.archive.config.select_url(self.index) != self.archive.url
        ):
            raise ValueError("book archive discovery differs from retained request")
        if self.capture is not None and self.index:
            raise ValueError("live capture cannot acquire archive discovery evidence")

    @property
    def request(self) -> CaptureRequest | OKXArchiveRequest:
        """Return the single native binding used by immutable raw storage.

        Returns:
            Validated recording or archive request with its original implementation identity.

        Raises:
            ValueError: Neither supported binding is present.
        """
        if self.capture is not None:
            return self.capture
        if self.archive is not None:
            return self.archive
        raise ValueError("missing book source request")

    @classmethod
    def read(cls, directory: Path, *, max_records: int) -> BookInput:
        """Load a completed collector directory using its strict existing request schema.

        Args:
            directory: Original capture/archive directory; interrupted prefixes are refused.
            max_records: Explicit maximum raw positions to retain in this dataset partition.

        Returns:
            Location-independent selection; raw bytes are verified during admission.
        """
        codec = DomainCodec()
        payload = cls._read_bytes(directory / "request.json", 1_048_576)
        capture = "recording_id" in Wire.mapping(Wire.decode(payload))
        return cls(
            raw=codec.decode_json(
                cls._read_bytes(directory / "manifest.json", 1_048_576), RawObject
            ),
            max_records=max_records,
            capture=codec.decode_json(payload, CaptureRequest) if capture else None,
            archive=None if capture else codec.decode_json(payload, OKXArchiveRequest),
            index=b"" if capture else cls._read_bytes(directory / "index.json", 1_048_576),
        )

    def admit(self, store: RawStore, *, max_bytes: int) -> QualityReport:
        """Reconstruct a bounded prefix, retaining controls and refusing malformed messages.

        Args:
            store: Immutable original objects; their full digests are verified before use.
            max_bytes: Positive bound on raw and canonical bytes; archive expansion also
                retains its original configuration's bound. Memory is proportional to
                bounded canonical bytes plus the configured native visible state.

        Returns:
            Existing quality/publication gate with deterministic exploratory bytes or
            retained rejection reasons. No trade revision operation is applied to books.

        Raises:
            ValueError: The input binding itself is malformed or incompatible.
        """
        self.__post_init__()
        codec, rows, used, invalid, gaps, duplicates = DomainCodec(), [], 0, 0, 0, 0
        reasons = ["visible depth only; coverage and historical eligibility unproven"]
        try:
            if type(max_bytes) is not int or max_bytes <= 0 or self.raw.size_bytes > max_bytes:
                raise ValueError("book raw input exceeds max_bytes")
            for row in self._observations(store):
                used += len(codec.encode_json(row))
                if used > max_bytes:
                    raise ValueError("book canonical state exceeds max_bytes")
                rows.append(row)
                invalid += row.outcome == "invalid_frame"
                gaps += row.outcome in ("gap", "invalid_frame")
                duplicates += row.outcome == "duplicate"
            if invalid or not any(
                row.outcome in ("snapshot", "update") and (row.status in ("degraded", "stale"))
                for row in rows
            ):
                raise ValueError("book prefix contains invalid input or no admitted reconstruction")
            payload = codec.encode_json(BookHistory(input=self, observations=tuple(rows)))
            if len(payload) > max_bytes:
                raise ValueError("book canonical envelope exceeds max_bytes")
        except (ValueError, TypeError, OSError, OverflowError, EOFError, tarfile.TarError) as error:
            return QualityReport(
                scope="rejected",
                reasons=tuple([*reasons, str(error)]),
                invalid_count=max(1, invalid),
                gap_count=gaps,
                duplicate_count=duplicates,
                canonical=None,
            )
        if self.archive is not None:
            reasons.append("source continuity and original availability unknown")
        return QualityReport(
            scope="exploratory_degraded",
            reasons=tuple(reasons),
            invalid_count=0,
            gap_count=gaps,
            duplicate_count=duplicates,
            canonical=payload,
        )

    def _observations(self, store: RawStore) -> Iterator[BookObservation]:
        """Bind native states to their original raw positions without sorting or filling gaps."""
        with store.open(descriptor=self.raw, request=self.request) as source:
            if self.capture is not None:
                replay = CaptureReplay(self.capture.config)
                codec = DomainCodec()
                record: CaptureRecord | None = None
                for position in range(self.max_records):
                    line = source.readline(self.capture.config.max_bytes + 1)
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        raise ValueError("incomplete capture message")
                    record = codec.decode_json(line, CaptureRecord)
                    outcome = replay.apply(record)
                    book = replay.book
                    keep = outcome in ("snapshot", "update") and book.ready and not replay.invalid
                    yield BookObservation(
                        position,
                        record.epoch,
                        record.received_ns,
                        book.source_time,
                        book.sequence,
                        outcome,
                        replay.quality.status,
                        replay.quality.reason,
                        book.identity,
                        orders=tuple(sorted(book.orders.values(), key=BookInput._order_key))
                        if keep and not isinstance(book, OKXBook)
                        else (),
                        bids=tuple(sorted(book.bids.items()))
                        if keep and isinstance(book, OKXBook)
                        else (),
                        asks=tuple(sorted(book.asks.items()))
                        if keep and isinstance(book, OKXBook)
                        else (),
                        transition_ns=replay.quality.transition_ns,
                        last_durable_ns=replay.quality.last_durable_ns,
                    )
                # Completion is structural; unselected native events remain outside admission.
                for line in source:
                    record = codec.decode_json(line, CaptureRecord)
                if record is None or record.kind != "end":
                    raise ValueError("book input lacks a completed capture boundary")
            elif self.archive is not None:
                config = self.archive.config
                name: object = source.name
                if not isinstance(name, str):
                    raise ValueError("archive requires a named raw-store file")
                path = Path(name)
                deadline = time.monotonic() + config.duration_seconds
                OKXArchiveReader(config).validate(path, deadline)
                book = OKXBook(config.symbol)
                with tarfile.open(path, mode="r|gz") as archive:
                    member = archive.next()
                    stream = None if member is None else archive.extractfile(member)
                    if stream is None:
                        raise ValueError("missing archive member")
                    with stream:
                        for position in range(min(self.max_records, config.max_records)):
                            if time.monotonic() > deadline:
                                raise TimeoutError("book archive admission timed out")
                            line = stream.readline(config.max_line_bytes + 1)
                            if not line:
                                break
                            if len(line) > config.max_line_bytes or not line.endswith(b"\n"):
                                raise ValueError("incomplete or oversized archive message")
                            outcome = book.apply_archive(line)
                            if book.source_time is not None and not (
                                config.start_ms
                                <= int(book.source_time)
                                < config.start_ms + 86_400_000
                            ):
                                raise ValueError("book archive time outside selected day")
                            yield BookObservation(
                                position,
                                None,
                                None,
                                book.source_time,
                                None,
                                outcome,
                                "degraded",
                                "source continuity and original availability unknown",
                                book.identity,
                                bids=tuple(sorted(book.bids.items())),
                                asks=tuple(sorted(book.asks.items())),
                            )

    @staticmethod
    def _order_key(order: Order) -> str:
        """Order a complete L3 state deterministically without inventing queue priority."""
        return order.order_id

    @staticmethod
    def _read_bytes(path: Path, max_bytes: int) -> bytes:
        """Read bounded metadata or canonical files before decoding them."""
        with path.open("rb") as source:
            payload = source.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ValueError("book dataset file exceeds max_bytes")
        return payload


class BookHistory(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Expose typed message boundaries only with their complete input and degraded scope."""

    schema: Literal["canonical-book-prefix-v1"] = "canonical-book-prefix-v1"
    scope: Literal["exploratory_degraded"] = "exploratory_degraded"
    input: BookInput
    observations: tuple[BookObservation, ...]

    def __post_init__(self) -> None:
        """Retain an explicit version and reject empty or malformed canonical histories."""
        if (
            self.schema != "canonical-book-prefix-v1"
            or self.scope != "exploratory_degraded"
            or type(self.input) is not BookInput
            or type(self.observations) is not tuple
            or not self.observations
            or len(self.observations) > self.input.max_records
            or any(type(row) is not BookObservation for row in self.observations)
        ):
            raise ValueError("invalid canonical book history")
        self.input.__post_init__()
        for position, row in enumerate(self.observations):
            row.__post_init__()
            if row.position != position:
                raise ValueError("book history requires contiguous original positions")
            if self.input.archive is not None and any(
                value is not None
                for value in (
                    row.received_ns,
                    row.epoch,
                    row.sequence,
                    row.transition_ns,
                    row.last_durable_ns,
                )
            ):
                raise ValueError("archive book history cannot invent receipt or sequence")
            if self.input.capture is not None and (
                row.received_ns is None or row.received_ns <= 0 or row.epoch is None
            ):
                raise ValueError("captured book history requires original receipt and epoch")


class BookPartition(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Bind deterministic book bytes to the immutable input and explicit prefix selection."""

    sha256: str
    selection: BookInput

    def __post_init__(self) -> None:
        """Validate digest and native input identity before snapshot staging."""
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", self.sha256):
            raise ValueError("invalid canonical book digest")
        if type(self.selection) is not BookInput:
            raise ValueError("book partition requires a typed input")
        self.selection.__post_init__()


class BookDatasetManifest(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Version exploratory book publication separately from the unchanged trade format."""

    _codec: ClassVar[DomainCodec] = DomainCodec()
    schema_version: Literal["book-dataset-v1"] = "book-dataset-v1"
    scope: Literal["exploratory_degraded"] = "exploratory_degraded"
    normalization_identity: str
    partitions: tuple[BookPartition, ...]

    def __post_init__(self) -> None:
        """Require unique complete book selections and an identified normalizer."""
        if (
            self.schema_version != "book-dataset-v1"
            or self.scope != "exploratory_degraded"
            or not isinstance(self.normalization_identity, str)
            or not re.fullmatch(r"[a-f0-9]{64}", self.normalization_identity)
            or type(self.partitions) is not tuple
            or not self.partitions
        ):
            raise ValueError("unsupported book dataset version, scope or identity")
        selected: set[str] = set()
        for partition in self.partitions:
            if type(partition) is not BookPartition:
                raise ValueError("book manifest requires typed partitions")
            partition.__post_init__()
            identity = partition.selection.request.identity
            if identity in selected:
                raise ValueError("duplicate book source selection")
            selected.add(identity)

    @property
    def identity(self) -> str:
        """Identify the schema, ordered raw inputs, quality policy and canonical states.

        Returns:
            Stable SHA-256 independent of publication location and wall clock.
        """
        self.__post_init__()
        return hashlib.sha256(self._codec.encode_json(self)).hexdigest()

    @classmethod
    def read(
        cls,
        path: Path,
        *,
        identity: str,
        partitions: Path,
        store: RawStore,
        max_bytes: int,
        report: Callable[[str, QualityReport], None] | None = None,
    ) -> BookDatasetManifest:
        """Reproduce all selected book boundaries before admitting a saved snapshot.

        Args:
            path: Explicit immutable manifest file.
            identity: Independently expected dataset SHA-256.
            partitions: Directory of canonical files addressed by digest.
            store: Retained original raw objects, protected from external mutation.
            max_bytes: Positive bound on each canonical file and original raw object.
            report: Optional sink for each reproduced partition's quality report.

        Returns:
            Verified exploratory manifest; this format grants no trade-query capability.

        Raises:
            ValueError: Identity, format, bytes, scope or reproduced admission differs.
        """
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("book dataset requires positive max_bytes")
        manifest = cls._codec.decode_json(BookInput._read_bytes(path, max_bytes), cls)
        if manifest.identity != identity:
            raise ValueError("book dataset identity mismatch")
        for partition in manifest.partitions:
            canonical = BookInput._read_bytes(partitions / partition.sha256, max_bytes)
            if hashlib.sha256(canonical).hexdigest() != partition.sha256:
                raise ValueError("canonical book digest mismatch")
            outcome = partition.selection.admit(store, max_bytes=max_bytes)
            if outcome.require_canonical() != canonical:
                raise ValueError("canonical book differs from retained admission inputs")
            if report is not None:
                report(partition.selection.request.identity, outcome)
        return manifest
