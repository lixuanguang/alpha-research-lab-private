"""Select the installed source adapters for saved and fixture inputs."""

from __future__ import annotations

# standard library imports
import hashlib
import tarfile
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

# project library imports
from configuration import ResolvedManifest
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.providers.binance import BinanceArchiveOccurrences
from market_data.adapters.providers.tardis import TardisTradeFixture
from market_data.adapters.sources.books import BookAdapters
from market_data.adapters.sources.verification import SourceOccurrenceVerifier
from market_data.adapters.venues.bitfinex import BitfinexPublic
from market_data.adapters.venues.okx import (
    OKXArchiveDiscovery,
    OKXArchiveReader,
    OKXBook,
    OKXPublic,
)
from market_data.books import BookProjection, CaptureReplay, TradeTape
from market_data.contracts import (
    BookObservation,
    ByteReader,
    CapturedTrades,
    CaptureRecord,
    FixtureReader,
    OccurrenceVerifier,
    PublicSource,
    SavedPartitionReader,
    SourceRequest,
)
from market_data.datasets import CaptureInput
from reference_data.catalogs import InstrumentDefinition
from serialization import DomainCodec

type SavedFactory = Callable[[AcquisitionManifest], tuple[SavedPartitionReader, ...]]
type FixtureFactory = Callable[[ResolvedManifest], FixtureReader]
type VerifierFactory = Callable[[SourceRequest], OccurrenceVerifier]
type SourceCapability = tuple[str, str, str]


_SAVED_FACTORIES: Final[Mapping[SourceCapability, SavedFactory]] = MappingProxyType(
    {("binance-archive", "binance", "trade"): BinanceArchiveOccurrences.from_manifest}
)
_FIXTURE_FACTORIES: Final[Mapping[SourceCapability, FixtureFactory]] = MappingProxyType(
    {("tardis", "binance", "trade"): TardisTradeFixture}
)
_VERIFIER_FACTORIES: Final[Mapping[SourceCapability, VerifierFactory]] = MappingProxyType(
    {
        ("tardis", "binance", "trade"): SourceOccurrenceVerifier,
        ("binance-archive", "binance", "trade"): SourceOccurrenceVerifier,
    }
)


class SourceAdapters:
    """Select the small declarative set of source capabilities installed here."""

    @staticmethod
    def public(instrument: InstrumentDefinition) -> PublicSource:
        """Resolve installed public trade/reference adapters before any data access."""
        factories: dict[str, type[OKXPublic] | type[BitfinexPublic]] = {
            "okx": OKXPublic,
            "bitfinex": BitfinexPublic,
        }
        factory = factories.get(instrument.venue)
        if factory is None:
            raise ValueError("unsupported public source venue")
        source = factory()
        source.capability.admit(instrument, channel="trades", mode="replay")
        return source

    @staticmethod
    def saved(manifest: AcquisitionManifest) -> tuple[SavedPartitionReader, ...]:
        """Select readers for one validated saved acquisition manifest.

        Args:
            manifest: Complete or resumable acquisition state to bind to readers.

        Returns:
            Readers in the manifest's deterministic source-partition order.

        Raises:
            TypeError: The supplied value is not an acquisition manifest.
            ValueError: The manifest is invalid or its saved source is unsupported.
        """
        if type(manifest) is not AcquisitionManifest:
            raise TypeError("saved adapters require an AcquisitionManifest")
        manifest.__post_init__()
        capability = (manifest.run.job.provider, manifest.run.job.venue, manifest.run.job.stream)
        factory = _SAVED_FACTORIES.get(capability)
        if factory is None:
            raise ValueError(
                "unsupported saved source: "
                f"{manifest.run.job.provider}; only Binance daily archive is installed"
            )
        return factory(manifest)

    @staticmethod
    def fixture(manifest: ResolvedManifest) -> FixtureReader:
        """Select the installed fixture adapter for one resolved manifest.

        Args:
            manifest: Resolved fixture selection, including its provider and venue.

        Returns:
            A reusable reader bound to the selected fixture capability.

        Raises:
            TypeError: The supplied value is not a resolved manifest.
            ValueError: The manifest is invalid or its fixture source is unsupported.
        """
        if type(manifest) is not ResolvedManifest:
            raise TypeError("fixture adapters require a ResolvedManifest")
        manifest.__post_init__()
        capability = (
            manifest.job.provider,
            manifest.job.venue,
            manifest.job.stream,
        )
        factory = _FIXTURE_FACTORIES.get(capability)
        if factory is None:
            raise ValueError(
                f"unsupported fixture source: {capability[0]}/{capability[1]}/{capability[2]}"
            )
        return factory(manifest)

    @staticmethod
    def verifier(request: SourceRequest) -> OccurrenceVerifier:
        """Select the installed verifier for one source request.

        Args:
            request: Validated request whose retained occurrence will be checked.

        Returns:
            A reusable source-specific occurrence verifier bound to the request.

        Raises:
            TypeError: The supplied value is not a source request.
            ValueError: The request is invalid or its source capability is unsupported.
        """
        if type(request) is not SourceRequest:
            raise TypeError("occurrence verifiers require a SourceRequest")
        request.__post_init__()
        capability = (
            request.manifest.job.provider,
            request.manifest.job.venue,
            request.manifest.job.stream,
        )
        factory = _VERIFIER_FACTORIES.get(capability)
        if factory is None:
            raise ValueError(
                f"unsupported occurrence source: {capability[0]}/{capability[1]}/{capability[2]}"
            )
        return factory(request)

    @staticmethod
    def trades(selection: CaptureInput, store: ByteReader) -> Iterator[CapturedTrades]:
        """Replay a trades capture chain, predecessors first, through the venue tape.

        Positions count every record of the chain from zero, as the live trade source
        does. The final segment is bounded by ``max_records`` and must end with a
        structural capture boundary.

        Yields:
            Each message's coordinates, tape outcome, synchronization and added trades.

        Raises:
            ValueError: The input is not a trades capture or its replay is invalid.
        """
        selection.__post_init__()
        capture = selection.capture
        if capture is None or capture.config.channel != "trades":
            raise ValueError("captured trades require a trades capture input")
        replay = CaptureReplay(capture.config, book_factory=BookAdapters.create)
        codec = DomainCodec()
        position = 0
        segments = (*selection.capture_chain()[:-1], None)
        record: CaptureRecord | None = None
        for ancestor in segments:
            descriptor = selection.raw if ancestor is None else ancestor.raw
            binding = selection.request.binding if ancestor is None else ancestor.capture.binding
            limit = selection.max_records if ancestor is None else None
            with store.open(descriptor=descriptor, request=binding) as source:
                count = 0
                while limit is None or count < limit:
                    line = source.readline(capture.config.max_bytes + 1)
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        raise ValueError("incomplete trades capture message")
                    record = codec.decode_json(line, CaptureRecord)
                    outcome = replay.apply(record)
                    tape = replay.book
                    if not isinstance(tape, TradeTape):
                        raise ValueError("trades capture replay requires a trade tape")
                    yield CapturedTrades(
                        position=position,
                        epoch=record.epoch,
                        received_ns=record.received_ns,
                        kind=record.kind,
                        outcome=outcome,
                        synchronized=tape.ready and not replay.invalid,
                        state_identity=tape.identity,
                        raw_sha256=hashlib.sha256(record.raw).hexdigest(),
                        trades=tape.trades if outcome in ("snapshot", "update") else (),
                    )
                    position += 1
                    count += 1
                if ancestor is None:
                    for line in source:
                        record = codec.decode_json(line, CaptureRecord)
        if record is None or (record.kind != "end" and capture.segment is None):
            raise ValueError("trades input lacks a completed capture boundary")

    @staticmethod
    def books(selection: CaptureInput, store: ByteReader) -> Iterator[BookObservation]:
        """Reconstruct validated native input in original position order.

        Args:
            selection: Strict capture/archive request and bounded raw prefix.
            store: Immutable reader verifying all retained bytes before use.

        Yields:
            Complete native message boundaries without fabricated availability.

        Raises:
            ValueError: Discovery, completion or source reconstruction is invalid.
            TimeoutError: Archive admission exceeds its time budget.
        """
        selection.__post_init__()
        if selection.archive is not None and (
            OKXArchiveDiscovery.select_url(selection.archive.config, selection.index)
            != selection.archive.url
        ):
            raise ValueError("book archive discovery differs from retained request")
        with store.open(descriptor=selection.raw, request=selection.request.binding) as source:
            if selection.capture is not None:
                replay = CaptureReplay(selection.capture.config, book_factory=BookAdapters.create)
                codec = DomainCodec()
                for ancestor in selection.capture_chain()[:-1]:
                    with store.open(
                        descriptor=ancestor.raw, request=ancestor.capture.binding
                    ) as prior:
                        while line := prior.readline(ancestor.capture.config.max_bytes + 1):
                            if not line.endswith(b"\n"):
                                raise ValueError("incomplete capture predecessor message")
                            replay.apply(codec.decode_json(line, CaptureRecord))
                record: CaptureRecord | None = None
                for position in range(selection.max_records):
                    line = source.readline(selection.capture.config.max_bytes + 1)
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        raise ValueError("incomplete capture message")
                    record = codec.decode_json(line, CaptureRecord)
                    outcome = replay.apply(record)
                    yield BookProjection.capture(position, record, outcome, replay)
                # Completion is structural; unselected native events remain outside admission.
                for line in source:
                    record = codec.decode_json(line, CaptureRecord)
                if record is None or (record.kind != "end" and selection.capture.segment is None):
                    raise ValueError("book input lacks a completed capture boundary")
            elif selection.archive is not None:
                config = selection.archive.config
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
                        for position in range(min(selection.max_records, config.max_records)):
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
