"""Read verified daily Binance trade archives without inferring capture coverage."""

from __future__ import annotations

# standard library imports
import csv
from collections.abc import Generator
from datetime import datetime, timedelta
from typing import Literal
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile
from zlib import error as ZlibError

# third party library imports
import msgspec

# project library imports
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest


class ArchiveRow(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Retain one exact CSV record, its zero-based position and raw-object origin.

    Selection bounds are half-open UTC research bounds, not a claim that this row
    falls within them. The origin's clocks describe acquisition, never capture.
    The reader does not filter, sort, decode numbers or synthesize control events.
    """

    origin: RawObject
    selection_start: datetime
    selection_end: datetime
    position: int
    payload: bytes

    def __post_init__(self) -> None:
        """Reject malformed origins, selection bounds, positions and raw CSV records.

        Raises:
            ValueError: Metadata, UTF-8 or the seven-column single-line CSV is invalid.
        """
        if type(self.origin) is not RawObject:
            raise ValueError("archive row requires a raw-object origin")
        self.origin.__post_init__()
        for bound in (self.selection_start, self.selection_end):
            if not isinstance(bound, datetime) or bound.utcoffset() != timedelta(0):
                raise ValueError("archive selection bounds must be UTC")
        if self.selection_start >= self.selection_end:
            raise ValueError("archive selection must be nonempty")
        if type(self.position) is not int or self.position < 0:
            raise ValueError("archive row position must be a nonnegative integer")
        if type(self.payload) is not bytes or not self.payload:
            raise ValueError("archive row requires nonempty source bytes")
        self.columns()

    def columns(self) -> tuple[str, ...]:
        """Parse source text without interpreting trade values or changing retained bytes.

        Returns:
            Seven nonempty text fields in source order; numeric semantics remain undecoded.

        Raises:
            ValueError: UTF-8, CSV syntax or the bounded single-line trade layout is invalid.
        """
        try:
            rows = tuple(csv.reader([self.payload.decode("utf-8")], strict=True))
            if len(rows) != 1 or len(rows[0]) != 7 or not all(rows[0]):
                raise ValueError("expected seven nonempty CSV fields")
            if any("\n" in field or "\r" in field for field in rows[0]):
                raise ValueError("multiline trade fields are unsupported")
            return tuple(rows[0])
        except (UnicodeError, csv.Error, ValueError) as error:
            raise ValueError(f"invalid Binance CSV at row {self.position}: {error}") from error


class BinanceArchiveRows(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Bind one expected daily partition to a completed object, or its explicit absence.

    Empty CSV content yields no rows; an absent completion or absent stored object
    raises FileNotFoundError. Neither outcome proves recorder completeness. Pending
    receipts are not completions. Use DomainCodec for retained records if needed.
    """

    request: SourceRequest
    descriptor: RawObject | None
    recorder_coverage: Literal["unknown"] = "unknown"

    def __post_init__(self) -> None:
        """Revalidate request, object binding and the absence of recorder evidence.

        Raises:
            ValueError: The partition is foreign, malformed or claims known coverage.
        """
        if type(self.request) is not SourceRequest or self.recorder_coverage != "unknown":
            raise ValueError("archive rows require a request and unknown recorder coverage")
        self.request.__post_init__()
        if self.request.manifest.job.provider != "binance-archive":
            raise ValueError("archive rows require the Binance daily archive provider")
        if self.descriptor is not None:
            if type(self.descriptor) is not RawObject:
                raise ValueError("archive rows require a RawObject descriptor")
            self.descriptor.__post_init__()
            if self.descriptor.request_identity != self.request.identity:
                raise ValueError("archive row request identity mismatch")

    @classmethod
    def from_manifest(cls, manifest: AcquisitionManifest) -> tuple[BinanceArchiveRows, ...]:
        """Select every expected daily object using the existing manifest prefix validation.

        Args:
            manifest: Explicit acquisition state, including incomplete runs without HTTP.

        Returns:
            Readers in request order, including absent completions for expected partitions.
        """
        manifest.__post_init__()
        return tuple(
            cls(
                request=request,
                descriptor=manifest.completed[index] if index < len(manifest.completed) else None,
            )
            for index, request in enumerate(SourceRequest.partition(manifest.run))
        )

    def read(
        self, store: RawStore, *, max_bytes: int, max_row_bytes: int = 4096
    ) -> Generator[ArchiveRow]:
        """Stream bounded verified UTF-8 CSV rows with original ordering and exact bytes.

        Args:
            store: Immutable raw storage; the caller excludes external mutation.
            max_bytes: Positive cap applied separately to compressed and expanded bytes.
            max_row_bytes: Positive maximum record size including LF or CRLF terminators.

        Yields:
            Raw records with origin and selection bounds, including equal-time rows.

        Raises:
            FileNotFoundError: An expected completion or its stored object is absent.
            ValueError: Bounds, binding, integrity, ZIP, UTF-8 or CSV validation fails.
            OSError: Stored bytes cannot be read.

        Notes:
            Exhaust the iterator to establish full CSV/CRC validation. Close it when
            abandoning a prefix. A yielded prefix is not an accepted dataset. Single-line
            individual-trade CSV only; no header, timestamp or financial decoding occurs.
        """
        self.__post_init__()
        for limit in (max_bytes, max_row_bytes):
            if type(limit) is not int or limit <= 0:
                raise ValueError("archive byte limits must be positive integers")
        descriptor = self.descriptor
        if descriptor is None:
            raise FileNotFoundError(f"missing daily archive completion: {self.request.identity}")
        if descriptor.size_bytes > max_bytes:
            raise ValueError("compressed archive exceeds max_bytes")
        name = f"{self.request.instrument.symbol}-trades-{self.request.start.date()}.csv"
        try:
            with store.open(descriptor=descriptor, request=self.request) as saved:
                with ZipFile(saved) as archive:
                    entries = archive.infolist()
                    if len(entries) != 1 or entries[0].filename != name:
                        raise ValueError("Binance ZIP must contain exactly the requested CSV")
                    entry = entries[0]
                    if entry.compress_type != ZIP_DEFLATED or entry.flag_bits & 1:
                        raise ValueError("Binance ZIP must use unencrypted deflate")
                    if entry.file_size > max_bytes:
                        raise ValueError("expanded archive exceeds max_bytes")
                    with archive.open(entry) as member:
                        size, position = 0, 0
                        while payload := member.readline(min(max_row_bytes, max_bytes - size) + 1):
                            size += len(payload)
                            if size > max_bytes or len(payload) > max_row_bytes:
                                raise ValueError(f"archive byte limit exceeded at row {position}")
                            yield ArchiveRow(
                                origin=descriptor,
                                selection_start=self.request.manifest.job.start,
                                selection_end=self.request.manifest.job.end,
                                position=position,
                                payload=payload,
                            )
                            position += 1
                        if size != entry.file_size:
                            raise ValueError("expanded archive size mismatch")
        except (BadZipFile, EOFError, ZlibError) as error:
            raise ValueError("Binance archive has invalid or truncated ZIP bytes") from error
