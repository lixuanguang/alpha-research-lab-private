"""Compose verified Binance archive rows into normalized occurrences."""

from __future__ import annotations

# standard library imports
from collections.abc import Generator
from contextlib import closing

# project library imports
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.normalization import Occurrence
from alpha_research.data.providers.binance.rows import BinanceArchiveRows
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest


class BinanceArchiveOccurrences:
    """Read one verified Binance archive partition as normalized occurrences.

    The bound partition supplies the source request, retained research interval,
    and raw-object descriptor. Each complete archive row is decoded before the
    narrower half-open research interval is applied, so malformed excluded rows
    still reject the read. The resulting occurrences retain the row's original
    origin, position, and bytes; acquisition clocks remain on that origin.
    """

    def __init__(self, partition: BinanceArchiveRows) -> None:
        """Bind one explicit Binance archive partition.

        Args:
            partition: Verified daily archive row binding to read.

        Raises:
            TypeError: The supplied partition is not a Binance archive row binding.
            ValueError: The partition's request, descriptor, or provider contract
                is invalid.
        """
        if type(partition) is not BinanceArchiveRows:
            raise TypeError("archive occurrences require one BinanceArchiveRows partition")
        partition.__post_init__()
        self._partition = partition

    @classmethod
    def from_manifest(cls, manifest: AcquisitionManifest) -> tuple[BinanceArchiveOccurrences, ...]:
        """Construct readers for every archive partition in an acquisition.

        Args:
            manifest: Explicit acquisition state whose resolved run identifies the
                expected archive partitions and their retained completions.

        Returns:
            Readers in the deterministic partition order supplied by the manifest.

        Raises:
            ValueError: The manifest or any derived partition violates its Binance
                archive binding contract.
        """
        return tuple(cls(partition) for partition in BinanceArchiveRows.from_manifest(manifest))

    @property
    def request(self) -> SourceRequest:
        """Return the explicit source request bound to this archive reader.

        Returns:
            The immutable request for the reader's one archive partition.

        Raises:
            ValueError: The bound partition has been altered or no longer satisfies
                its Binance archive contract.
        """
        self._partition.__post_init__()
        return self._partition.request

    def read(self, store: RawStore, *, max_bytes: int) -> Generator[Occurrence]:
        """Stream selected normalized occurrences from the bound archive.

        Args:
            store: Immutable raw storage whose objects remain stable for this read.
            max_bytes: Positive compressed and expanded archive byte limit.

        Yields:
            Occurrences in source row order for events within the partition's
            half-open research interval.

        Raises:
            FileNotFoundError: The expected archive completion or stored object is
                absent.
            ValueError: Archive bytes, a source row, a decoded trade, or an
                occurrence binding violates its contract.
            OSError: The raw store cannot read the saved object.

        Notes:
            Every row is decoded before selection, including rows outside the
            research interval. Closing this generator after an abandoned prefix
            closes the underlying archive-row generator as well.
        """
        with closing(self._partition.read(store, max_bytes=max_bytes)) as rows:
            for row in rows:
                event = ArchiveTrade.from_row(row, self._partition.request)
                if row.selection_start <= event.ts_event < row.selection_end:
                    yield Occurrence(
                        request=self._partition.request,
                        origin=row.origin,
                        position=row.position,
                        raw=row.payload,
                        event=event,
                    )
