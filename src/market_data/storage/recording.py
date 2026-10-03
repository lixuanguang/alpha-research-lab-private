"""Read one retained recording, a single journal or a segment chain, by run-wide position."""

from __future__ import annotations

# standard library imports
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# project library imports
from market_data.contracts import (
    CaptureCursor,
    CaptureRecord,
    CaptureRequest,
    CaptureRunRequest,
    RecordingRequest,
)
from market_data.storage.capture_run import CaptureRunJournal
from market_data.storage.journal import CaptureJournal
from serialization import DomainCodec


@dataclass(frozen=True, slots=True)
class RecordingCursor:
    """Expose a recording's acknowledged run-wide prefix and each segment's own cursor."""

    records: int
    offset: int
    sha256: str
    segments: tuple[CaptureCursor, ...]


@dataclass(frozen=True, slots=True)
class SegmentPosition:
    """Locate one run-wide record position inside its segment journal."""

    ordinal: int
    recording_id: str
    position: int


class CaptureRecording:
    """Read a source recording that consumers address by one key and one identity.

    A single recording delegates exactly to its ``CaptureJournal``. A chain is read
    as one recording: rollover adds no record, so positions are one contiguous
    run-wide sequence, and only the last segment may lack its seal.
    """

    def __init__(self, root: Path, request: RecordingRequest) -> None:
        """Bind a recording directory to the request the caller already holds.

        Args:
            root: Directory holding ``request.json`` or a chain's ``run-request.json``.
            request: The recording's single or whole-run request.
        """
        request.__post_init__()
        self.root, self.request = root, request

    @classmethod
    def read(cls, root: Path) -> CaptureRecording:
        """Open a retained recording from its one request file and its key-named directory.

        Raises:
            ValueError: No single request file, or the directory is not named by its key.
        """
        codec = DomainCodec()
        single, chain = root / "request.json", root / "run-request.json"
        request: RecordingRequest
        if single.is_file() and not chain.exists():
            request = codec.decode_json(single.read_bytes(), CaptureRequest)
        elif chain.is_file() and not single.exists():
            request = codec.decode_json(chain.read_bytes(), CaptureRunRequest)
        else:
            raise ValueError("capture recording requires exactly one request file")
        if root.name != request.recording_key:
            raise ValueError("capture recording directory differs from its key")
        return cls(root, request)

    @classmethod
    def discover(cls, source_root: Path) -> tuple[CaptureRecording, ...]:
        """Find every recording under one source's run directory, ordered by key.

        Each lies at ``<key>/<key>/``; the outer directory holds the source result.
        """
        roots = {
            path.parent
            for name in ("request.json", "run-request.json")
            for path in source_root.glob(f"*/*/{name}")
        }
        recordings = tuple(cls.read(root) for root in sorted(roots))
        if any(recording.root.parent.name != recording.key for recording in recordings):
            raise ValueError("capture recording parent differs from its key")
        return recordings

    @property
    def key(self) -> str:
        """Return the recording ID, or the run ID that names a whole chain."""
        return self.request.recording_key

    @property
    def identity(self) -> str:
        """Return the source identity that consumers bind; segments never change it."""
        return self.request.identity

    @property
    def completed(self) -> bool:
        """Report a sealed single journal, or a retained chain summary over sealed segments."""
        if isinstance(self.request, CaptureRequest):
            return (self.root / "manifest.json").is_file()
        return (self.root / "run-summary.json").is_file() and all(
            (path / "manifest.json").is_file() for path, _, _ in self._segments()
        )

    def cursor(self) -> RecordingCursor:
        """Return the acknowledged prefix from cursor files alone, at constant cost per segment.

        Raises:
            ValueError: A cursor or chain lineage differs from its retained request.
        """
        if isinstance(self.request, CaptureRequest):
            cursor = self._cursor(self.root, self.request)
            return RecordingCursor(cursor.records, cursor.offset, cursor.sha256, (cursor,))
        cursors = tuple(cursor for _, _, cursor in self._segments())
        if not cursors:
            raise ValueError("capture chain has no provisioned segment")
        return RecordingCursor(
            sum(cursor.records for cursor in cursors),
            sum(cursor.offset for cursor in cursors),
            cursors[-1].sha256,
            cursors,
        )

    def records(self, *, completed: bool = True) -> Iterator[CaptureRecord]:
        """Yield records in run-wide order, verified like ``CaptureJournal.records``.

        Args:
            completed: Require a complete recording, or inspect the interrupted prefix,
                which ends with exactly one unknown-tail gap.

        Yields:
            Persisted records, then the interrupted-tail gap when not completed.

        Raises:
            ValueError: The recording is incomplete when required, an earlier segment
                is unsealed, or bytes or lineage differ from their cursors.
        """
        if isinstance(self.request, CaptureRequest):
            yield from CaptureJournal(self.root, self.request).records(completed=completed)
            return
        if completed and not self.completed:
            raise ValueError("capture chain is not complete")
        journals = CaptureRunJournal(self.root, self.request).segments()
        epoch, received_ns = 0, 1
        for ordinal, journal in enumerate(journals):
            if (journal.root / "manifest.json").is_file():
                records: Iterator[CaptureRecord] = journal.records(completed=True)
            elif ordinal != len(journals) - 1:
                raise ValueError("capture chain has an unsealed earlier segment")
            else:
                # The journal's own tail gap would carry this segment's clocks only.
                records = self._without_tail(journal.records(completed=False))
            for record in records:
                epoch, received_ns = record.epoch, record.received_ns
                yield record
        if not completed:
            yield CaptureRecord(
                kind="gap",
                epoch=epoch,
                received_ns=received_ns,
                reason="interrupted_persistence_unknown_tail",
            )

    def locate(self, position: int) -> SegmentPosition:
        """Map a run-wide position to its segment and local position.

        Raises:
            IndexError: The position is outside the acknowledged prefix.
        """
        if type(position) is not int or position < 0:
            raise IndexError("capture position must be a nonnegative integer")
        if isinstance(self.request, CaptureRequest):
            if position >= self.cursor().records:
                raise IndexError("capture position is beyond the acknowledged prefix")
            return SegmentPosition(0, self.request.recording_id, position)
        first = 0
        for path, request, cursor in self._segments():
            if position < first + cursor.records:
                segment = request.segment
                if segment is None:
                    raise ValueError("capture segment lacks lineage")
                return SegmentPosition(segment.ordinal, path.name, position - first)
            first += cursor.records
        raise IndexError("capture position is beyond the acknowledged prefix")

    def _segments(self) -> tuple[tuple[Path, CaptureRequest, CaptureCursor], ...]:
        """Order a chain's segments and bind each predecessor without hashing journals."""
        if not isinstance(self.request, CaptureRunRequest):
            raise ValueError("capture recording is not a segment chain")
        codec = DomainCodec()
        found: list[tuple[int, Path, CaptureRequest]] = []
        for path in (self.root / "segments").iterdir():
            request = codec.decode_json((path / "request.json").read_bytes(), CaptureRequest)
            segment = request.segment
            if (
                segment is None
                or segment.run_identity != self.request.identity
                or path.name != request.recording_id
                or request.config != self.request.config
                or request.implementation_identity != self.request.implementation_identity
                or request.universes != self.request.universes
            ):
                raise ValueError("capture segment differs from retained run")
            found.append((segment.ordinal, path, request))
        found.sort(key=self._ordinal)
        result: list[tuple[Path, CaptureRequest, CaptureCursor]] = []
        for expected, (ordinal, path, request) in enumerate(found):
            segment = request.segment
            if ordinal != expected or segment is None:
                raise ValueError("capture run has a missing or duplicate segment")
            if result:
                previous_path, previous, previous_cursor = result[-1]
                if (
                    segment.previous_recording_id != previous_path.name
                    or segment.previous_request_identity != previous.identity
                    or segment.previous_sha256 != previous_cursor.sha256
                ):
                    raise ValueError("capture segment predecessor differs from durable prefix")
            result.append((path, request, self._cursor(path, request)))
        return tuple(result)

    @staticmethod
    def _ordinal(item: tuple[int, Path, CaptureRequest]) -> int:
        """Order discovered segments by their declared ordinal."""
        return item[0]

    @staticmethod
    def _without_tail(records: Iterator[CaptureRecord]) -> Iterator[CaptureRecord]:
        """Yield an interrupted journal's durable records without its synthetic last gap."""
        previous: CaptureRecord | None = None
        for record in records:
            if previous is not None:
                yield previous
            previous = record

    @staticmethod
    def _cursor(root: Path, request: CaptureRequest) -> CaptureCursor:
        """Decode one journal's acknowledged cursor and bind it to its request."""
        cursor = DomainCodec().decode_json((root / "cursor.json").read_bytes(), CaptureCursor)
        cursor.__post_init__()
        if cursor.request_identity != request.identity:
            raise ValueError("capture cursor differs from its request")
        return cursor
