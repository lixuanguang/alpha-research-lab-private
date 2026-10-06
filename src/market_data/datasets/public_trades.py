"""Publish and verify public trades through the existing immutable snapshot boundary.

One trade schema has two acquisition sources: REST pages (``PublicAcquisition``) and
captured websocket trades feeds (a trades ``CaptureInput``). Both produce
``PublicTradeObservation`` rows that research reads with the same field rules.
"""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

# project library imports
from market_data.acquisition import PublicAcquisition, PublicIngestion
from market_data.books import TradeTapeCoverage
from market_data.contracts import (
    CaptureTradeOrigin,
    PublicReceipt,
    PublicTrade,
    RequestBinding,
    TradeBoundary,
)
from market_data.datasets.books import CaptureInput
from market_data.datasets.readers import DatasetReaders
from market_data.storage import RawStore
from market_data.validation import QualityReport
from reference_data.catalogs import InstrumentDefinition, ReferenceHistory
from serialization import DomainCodec, WireRecord


class PublicTradeObservation(WireRecord, frozen=True, kw_only=True):
    """Bind exact trade values to their first usable local observation.

    Exactly one origin is set: a REST ``receipt`` (with the applicable reference) or
    a ``capture`` record. Original historical availability remains unknown;
    ts_knowledge is the local durable observation, never a reconstructed exchange
    or historical receipt clock.
    """

    position: int
    trade: PublicTrade
    specification_identity: str | None
    receipt: PublicReceipt | None = None
    capture: CaptureTradeOrigin | None = None

    def __post_init__(self) -> None:
        """Validate one immutable origin and an optional proven reference version."""
        if type(self.trade) is not PublicTrade or (self.receipt is None) == (self.capture is None):
            raise ValueError("invalid public trade observation")
        self.trade.__post_init__()
        if type(self.position) is not int or self.position < 0:
            raise ValueError("invalid public trade source position")
        if self.receipt is not None:
            if type(self.receipt) is not PublicReceipt:
                raise ValueError("invalid public trade observation")
            self.receipt.__post_init__()
            if self.receipt.request.kind != "trades":
                raise ValueError("invalid public trade source position")
        elif type(self.capture) is not CaptureTradeOrigin:
            raise ValueError("invalid public trade observation")
        else:
            self.capture.__post_init__()
            if self.specification_identity is not None or self.capture.index != self.position:
                raise ValueError("captured trades carry no reference and keep message order")
        if self.specification_identity is not None:
            RequestBinding(self.specification_identity)

    @property
    def instrument(self) -> InstrumentDefinition:
        """Return the listed instrument this trade was observed for."""
        if self.receipt is not None:
            return self.receipt.request.instrument
        if self.capture is None:
            raise ValueError("public trade observation has no origin")
        return self.capture.instrument

    @property
    def ordinal(self) -> int:
        """Return the origin's order: REST request ordinal or captured message position."""
        if self.receipt is not None:
            return self.receipt.request.ordinal
        if self.capture is None:
            raise ValueError("public trade observation has no origin")
        return self.capture.position

    @property
    def source_sha256(self) -> str:
        """Return the digest of the original bytes that carried this trade."""
        if self.receipt is not None:
            return self.receipt.raw.sha256
        if self.capture is None:
            raise ValueError("public trade observation has no origin")
        return self.capture.raw_sha256

    @property
    def ts_event(self) -> datetime:
        """Project original integer milliseconds exactly to aware UTC."""
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=self.trade.event_ms)

    @property
    def ts_knowledge(self) -> datetime:
        """Expose local durable observation time, with no original-availability claim."""
        if self.receipt is not None:
            return self.receipt.raw.ts_ingested
        if self.capture is None:
            raise ValueError("public trade observation has no origin")
        return self.capture.ts_knowledge


class PublicTradeHistory(WireRecord, frozen=True, kw_only=True):
    """Keep all observed versions and duplicates beside retained reference facts.

    A captured history also keeps every message's ``TradeBoundary`` in order, so a
    reader can apply the live source's synchronization, staleness and coverage rules.
    """

    references: ReferenceHistory
    observations: tuple[PublicTradeObservation, ...]
    boundaries: tuple[TradeBoundary, ...] = ()

    def __post_init__(self) -> None:
        """Require typed immutable histories; source verification is owned by publication."""
        if (
            type(self.references) is not ReferenceHistory
            or type(self.observations) is not tuple
            or type(self.boundaries) is not tuple
        ):
            raise ValueError("invalid public trade history")
        self.references.__post_init__()
        for row in self.observations:
            if type(row) is not PublicTradeObservation:
                raise ValueError("invalid public trade observation")
            row.__post_init__()
        for position, boundary in enumerate(self.boundaries):
            if type(boundary) is not TradeBoundary or boundary.position != position:
                raise ValueError("captured trade boundaries must be complete and ordered")
            boundary.__post_init__()


class PublicTradePartition(WireRecord, frozen=True, kw_only=True):
    """Bind the complete canonical history to its REST acquisition or trades capture."""

    sha256: str
    size_bytes: int
    acquisition: PublicAcquisition | None = None
    capture: CaptureInput | None = None

    def __post_init__(self) -> None:
        """Reject incomplete ingestion, a book capture and malformed canonical identities."""
        if (self.acquisition is None) == (self.capture is None):
            raise ValueError("public trade partition requires exactly one source")
        if self.acquisition is not None:
            if type(self.acquisition) is not PublicAcquisition or not self.acquisition.complete:
                raise ValueError("public dataset requires complete ingestion")
            self.acquisition.__post_init__()
        elif type(self.capture) is not CaptureInput:
            raise ValueError("public trade partition requires a typed capture input")
        else:
            self.capture.__post_init__()
            request = self.capture.capture
            if request is None or request.config.channel != "trades":
                raise ValueError("captured public trades require a trades capture")
            if request.universes is None:
                raise ValueError("captured public trades require declared universes")
        RequestBinding(self.sha256)
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise ValueError("invalid public canonical size")


class PublicTradeManifest(WireRecord, frozen=True, kw_only=True):
    """Pin a bounded public-trade snapshot without claiming historical completeness."""

    schema_version: Literal["public-trades"] = "public-trades"
    partitions: tuple[PublicTradePartition, ...]
    normalization_identity: str
    scope: Literal["locally_observed"] = "locally_observed"

    def __post_init__(self) -> None:
        """Keep one complete multi-instrument job under its existing admission limits."""
        if (
            self.schema_version != "public-trades"
            or self.scope != "locally_observed"
            or type(self.partitions) is not tuple
            or len(self.partitions) != 1
            or type(self.partitions[0]) is not PublicTradePartition
        ):
            raise ValueError("invalid public trade manifest")
        self.partitions[0].__post_init__()
        RequestBinding(self.normalization_identity)

    @property
    def identity(self) -> str:
        """Identify complete acquisition, reference lineage and canonical bytes."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    @classmethod
    def assemble_capture(
        cls,
        selection: CaptureInput,
        store: RawStore,
        *,
        readers: DatasetReaders,
        max_bytes: int,
        normalization_identity: str,
    ) -> tuple[PublicTradeManifest, bytes]:
        """Replay a trades capture chain and bind its canonical history for publication."""
        payload = cls.captured(selection, store, readers=readers, max_bytes=max_bytes)
        return cls(
            partitions=(
                PublicTradePartition(
                    capture=selection,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    size_bytes=len(payload),
                ),
            ),
            normalization_identity=normalization_identity,
        ), payload

    @staticmethod
    def captured(
        selection: CaptureInput, store: RawStore, *, readers: DatasetReaders, max_bytes: int
    ) -> bytes:
        """Re-apply every captured message; keep trades and boundaries with receipt clocks.

        Coverage follows ``TradeTapeCoverage``, the live trade source's rule. A replayed
        trade keeps its message position and its index within that message.
        """
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("public dataset requires positive max_bytes")
        request = selection.capture
        if request is None or request.config.channel != "trades":
            raise ValueError("captured public trades require a trades capture")
        config = request.config
        instrument = InstrumentDefinition(
            instrument_id=config.instrument_id,
            venue=config.venue,
            symbol=config.symbol,
            product="spot",
            base_currency=config.base_currency,
            quote_currency=config.quote_currency,
            calendar="continuous-utc",
        )
        identity = request.identity
        coverage = TradeTapeCoverage()
        codec = DomainCodec()
        observations: list[PublicTradeObservation] = []
        boundaries: list[TradeBoundary] = []
        used = 0
        for message in readers.trades(selection, store):
            boundary = TradeBoundary(
                position=message.position,
                received_ns=message.received_ns,
                covered_from_ns=coverage.step(
                    message.kind, message.synchronized, message.received_ns
                ),
            )
            boundaries.append(boundary)
            used += len(codec.encode_json(boundary))
            for index, trade in enumerate(message.trades):
                row = PublicTradeObservation(
                    position=index,
                    trade=trade,
                    specification_identity=None,
                    capture=CaptureTradeOrigin(
                        instrument=instrument,
                        request_identity=identity,
                        position=message.position,
                        index=index,
                        received_ns=message.received_ns,
                        raw_sha256=message.raw_sha256,
                    ),
                )
                used += len(codec.encode_json(row))
                observations.append(row)
            if used > max_bytes:
                raise ValueError("captured canonical observations exceed aggregate max_bytes")
        payload = codec.encode_json(
            PublicTradeHistory(
                references=ReferenceHistory(specifications=()),
                observations=tuple(observations),
                boundaries=tuple(boundaries),
            )
        )
        if len(payload) > max_bytes:
            raise ValueError("public canonical envelope exceeds max_bytes")
        return payload

    @classmethod
    def assemble(
        cls,
        acquisition: PublicAcquisition,
        store: RawStore,
        *,
        readers: DatasetReaders,
        max_bytes: int,
        normalization_identity: str,
    ) -> tuple[PublicTradeManifest, bytes]:
        """Verify every raw response and bind normalized output before atomic publication."""
        payload = cls.canonical(acquisition, store, readers=readers, max_bytes=max_bytes)
        return cls(
            partitions=(
                PublicTradePartition(
                    acquisition=acquisition,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    size_bytes=len(payload),
                ),
            ),
            normalization_identity=normalization_identity,
        ), payload

    @staticmethod
    def canonical(
        acquisition: PublicAcquisition, store: RawStore, *, readers: DatasetReaders, max_bytes: int
    ) -> bytes:
        """Re-decode every page; preserve duplicates/corrections with independent local clocks."""
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("public dataset requires positive max_bytes")
        acquisition.__post_init__()
        ingestion = PublicIngestion(readers, store)
        if not acquisition.complete or ingestion.next_request(acquisition) is not None:
            raise ValueError("public dataset requires verified completed ingestion")
        references = ingestion.references(acquisition)
        observations: list[PublicTradeObservation] = []
        used = len(DomainCodec().encode_json(references))
        for receipt in acquisition.receipts:
            if receipt.request.kind != "trades":
                continue
            if receipt.raw.size_bytes > max_bytes:
                raise ValueError("public raw page exceeds max_bytes")
            with store.open(descriptor=receipt.raw, request=receipt.request.binding) as source:
                payload = source.read(max_bytes + 1)
            page = readers.public(receipt.request.instrument).trades(
                acquisition.job, receipt.request, payload
            )
            for position, trade in enumerate(page.trades):
                event = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=trade.event_ms)
                # Retain the whole observed page: an out-of-window correction must
                # still retire an earlier version before a query filters event time.
                spec = references.resolve(
                    receipt.request.instrument.instrument_id,
                    valid_at=event,
                    known_at=receipt.raw.ts_ingested,
                )
                row = PublicTradeObservation(
                    receipt=receipt,
                    position=position,
                    trade=trade,
                    specification_identity=None if spec is None else spec.identity,
                )
                used += len(DomainCodec().encode_json(row))
                if used > max_bytes:
                    raise ValueError("public canonical observations exceed aggregate max_bytes")
                observations.append(row)
        payload = DomainCodec().encode_json(
            PublicTradeHistory(references=references, observations=tuple(observations))
        )
        if len(payload) > max_bytes:
            raise ValueError("public canonical envelope exceeds max_bytes")
        return payload

    @classmethod
    def read(
        cls,
        path: Path,
        *,
        identity: str,
        partitions: Path,
        store: RawStore,
        max_bytes: int,
        readers: DatasetReaders,
        report: Callable[[str, QualityReport], None] | None = None,
        rederive: bool = False,
    ) -> PublicTradeManifest:
        """Check, or with ``rederive`` reproduce, a pinned snapshot from its raw inputs.

        The shared SnapshotStore owns file-kind, atomic publication and filesystem
        guarantees. A changed raw response or canonical file always fails; a changed
        source decoder fails when the snapshot is re-derived, as publication does.
        """
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("public snapshot requires positive byte limit")
        with path.open("rb") as source:
            payload = source.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ValueError("public manifest exceeds max_bytes")
        manifest = DomainCodec().decode_json(payload, cls)
        if manifest.identity != identity:
            raise ValueError("public manifest identity mismatch")
        partition = manifest.partitions[0]
        with (partitions / partition.sha256).open("rb") as source:
            canonical = source.read(max_bytes + 1)
        if (
            len(canonical) != partition.size_bytes
            or len(canonical) > max_bytes
            or hashlib.sha256(canonical).hexdigest() != partition.sha256
        ):
            raise ValueError("public canonical bytes differ from manifest")
        if rederive:
            if partition.acquisition is not None:
                expected = cls.canonical(
                    partition.acquisition, store, readers=readers, max_bytes=max_bytes
                )
            elif partition.capture is not None:
                expected = cls.captured(
                    partition.capture, store, readers=readers, max_bytes=max_bytes
                )
            else:
                raise ValueError("public trade partition requires exactly one source")
            if canonical != expected:
                raise ValueError("public canonical history differs from retained source responses")
        else:
            cls._check_raw(partition, store, max_bytes=max_bytes)
        if report is not None:
            report(
                identity,
                QualityReport(
                    scope="exploratory_degraded",
                    reasons=(
                        "local observation only; original availability and "
                        "source completeness unknown",
                    ),
                    invalid_count=0,
                    gap_count=0,
                    duplicate_count=0,
                    canonical=None,
                ),
            )
        return manifest

    @staticmethod
    def _check_raw(partition: PublicTradePartition, store: RawStore, *, max_bytes: int) -> None:
        """Verify every raw input digest the partition was derived from."""
        if partition.acquisition is not None:
            inputs = tuple(
                (receipt.raw, receipt.request.binding) for receipt in partition.acquisition.receipts
            )
        elif partition.capture is not None:
            capture = partition.capture
            inputs = (
                *(
                    (ancestor.raw, ancestor.capture.binding)
                    for ancestor in capture.capture_chain()[:-1]
                ),
                (capture.raw, capture.request.binding),
            )
        else:
            raise ValueError("public trade partition requires exactly one source")
        for descriptor, binding in inputs:
            if descriptor.size_bytes > max_bytes:
                raise ValueError("public raw input exceeds max_bytes")
            with store.open(descriptor=descriptor, request=binding):
                pass
