"""Define neutral contracts for saved partitions and bounded fixture inputs."""

from __future__ import annotations

# standard library imports
from collections.abc import Generator
from datetime import datetime
from typing import BinaryIO, Protocol, runtime_checkable

# project library imports
from market_data.contracts.archive_evidence import ArchiveCapture
from market_data.contracts.binance import Trade
from market_data.contracts.events import MarketEventRecord
from market_data.contracts.occurrences import Occurrence
from market_data.contracts.raw import RawObject, RequestBinding
from market_data.contracts.requests import SourceRequest


@runtime_checkable
class SavedPartitionReader(Protocol):
    """Read one immutable saved source partition as normalized occurrences."""

    @property
    def request(self) -> SourceRequest:
        """Return the immutable source request bound to this partition.

        Returns:
            The request whose source, instrument and partition bind the reader.
        """

    def read(self, store: ByteReader, *, max_bytes: int) -> Generator[Occurrence]:
        """Stream validated occurrences from the retained raw store.

        Args:
            store: Immutable raw store containing the reader's retained object.
            max_bytes: Positive bound for compressed and expanded source bytes.

        Returns:
            Generator preserving source order and lineage. Exhaust it for complete
            validation, or close an abandoned prefix to release its resources.
        """


@runtime_checkable
class FixtureReader(Protocol):
    """Decode one bounded fixture line into a bound neutral market event."""

    def decode(
        self,
        line: str,
        *,
        local_received: datetime,
        local_ingested: datetime,
        source_sequence: int,
        source_digest: str,
    ) -> tuple[SourceRequest, MarketEventRecord]:
        """Decode one source line with its retained receipt and digest metadata.

        Args:
            line: One bounded source line without its file terminator.
            local_received: Original local receipt timestamp.
            local_ingested: Original local durable-ingestion timestamp.
            source_sequence: Original zero-based source line position.
            source_digest: SHA-256 digest of the retained source bytes.

        Returns:
            The bound source request and neutral market-event record.
        """


@runtime_checkable
class OccurrenceVerifier(Protocol):
    """Re-decode one occurrence through its installed source adapter."""

    def check(self, item: Occurrence) -> tuple[datetime, datetime | None]:
        """Verify source bytes and return observation and original-knowledge clocks.

        Args:
            item: Occurrence whose source bytes and decoded event must agree.

        Returns:
            The observation instant and optional original knowledge timestamp.
        """


class ByteReader(Protocol):
    """Verify complete immutable objects before exposing their original bytes."""

    def open(self, *, descriptor: RawObject, request: RequestBinding) -> BinaryIO:
        """Open a fully verified object bound to an independently validated request.

        Args:
            descriptor: Expected content digest, byte count and original clocks.
            request: Validated neutral source identity.

        Returns:
            Binary stream owned and closed by the caller.
        """
        ...


@runtime_checkable
class ArchiveCaptureVerifier(Protocol):
    """Decode complete corroborating native responses at their provider boundary."""

    def captures(self, evidence: ArchiveCapture) -> tuple[Trade, ...]:
        """Re-decode source bytes and refuse gaps or conflicting captured payloads.

        Args:
            evidence: Complete native response slices bound to the archive selection.

        Returns:
            Captured individual Binance trades with original recorder clocks.
        """
