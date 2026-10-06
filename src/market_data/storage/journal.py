"""Durable append-only recording with shared content-addressed raw publication."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

# project library imports
from market_data.contracts import CaptureCursor, CaptureRecord, CaptureRequest, RawObject
from market_data.storage.objects import RawFiles
from market_data.storage.raw import RawStore
from serialization import DomainCodec, DurableDirectory


class CaptureJournal:
    """Fsync each append before use; incomplete journals remain inspectable after death.

    An acknowledged append survives process and kernel crashes. It survives power
    loss only where ``fsync`` flushes the device write cache; Darwin ``fsync`` does
    not, and ``F_FULLFSYNC`` is deliberately not used (see docs/data/l3-collectors.md).
    One writer owns a unique directory. Published objects reuse RawStore; no
    partial journal is admitted as a completed capture. The final manifest is
    installed by durable rename only after raw publication. Peak disk use is at
    most twice max_bytes plus bounded request/descriptor metadata.
    """

    def __init__(self, root: Path, request: CaptureRequest, *, measure_fsync: bool = False) -> None:
        """Bind a fresh capture directory; create it explicitly with start before use.

        Args:
            root: Unique caller-owned local recording directory.
            request: Immutable recording, configuration and implementation binding.
            measure_fsync: Retain individual record fsync and cursor checkpoint durations.
        """
        self.root, self.request = root, request
        self.codec = DomainCodec()
        self.size = 0
        self.count = 0
        self._digest = hashlib.sha256()
        self._writable = False
        self._measure_fsync = measure_fsync
        self.last_record_fsync_ns: int | None = None
        self.last_cursor_checkpoint_ns: int | None = None

    def start(self) -> None:
        """Exclusively provision and synchronize the request and journal directory."""
        missing_parents = []
        parent = self.root.parent
        while not parent.exists():
            missing_parents.append(parent)
            parent = parent.parent
        self.root.mkdir(parents=True, exist_ok=False)
        self._write_new(self.root / "request.json", self.codec.encode_json(self.request))
        self._write_new(self.root / "journal.jsonl", b"")
        self._checkpoint()
        self._sync_directory(self.root.parent)
        for parent in missing_parents:
            self._sync_directory(parent.parent)
        self._writable = True

    def append(self, record: CaptureRecord) -> None:
        """Persist one message, reserving bounded space for terminal loss diagnostics.

        Args:
            record: One complete received message or scoped session transition.

        Raises:
            OverflowError: The journal has reached its configured storage budget.
            OSError: The writer is not active or persistence failed; start a new recording.
        """
        if not self._writable:
            raise OSError("capture writer is not active; start a new recording")
        record.__post_init__()
        encoded = self.codec.encode_json(record) + b"\n"
        reserve = 4096 if record.kind in ("frame", "snapshot", "session", "clock") else 0
        if self.size + len(encoded) > self.request.config.max_bytes - reserve:
            raise OverflowError("capture storage limit")
        self._writable = False
        self.last_record_fsync_ns = None
        self.last_cursor_checkpoint_ns = None
        with (self.root / "journal.jsonl").open("ab") as output:
            output.write(encoded)
            output.flush()
            if self._measure_fsync:
                started_ns = time.monotonic_ns()
                os.fsync(output.fileno())
                self.last_record_fsync_ns = time.monotonic_ns() - started_ns
            else:
                os.fsync(output.fileno())
        self.size += len(encoded)
        self.count += 1
        self._digest.update(encoded)
        checkpoint_started_ns = time.monotonic_ns() if self._measure_fsync else 0
        self._checkpoint()
        if self._measure_fsync:
            self.last_cursor_checkpoint_ns = time.monotonic_ns() - checkpoint_started_ns
        self._writable = True

    def _checkpoint(self) -> None:
        """Acknowledge only a synced journal prefix through an atomic durable cursor."""
        cursor = CaptureCursor(
            self.request.identity, self.size, self.count, self._digest.hexdigest()
        )
        self._write_new(self.root / "cursor.pending", self.codec.encode_json(cursor))
        os.replace(self.root / "cursor.pending", self.root / "cursor.json")
        self._sync_directory(self.root)

    def _verify_cursor(self, source: BinaryIO) -> int:
        """Verify the committed prefix before exposing any interrupted records."""
        with (self.root / "cursor.json").open("rb") as checkpoint:
            encoded = checkpoint.read(1025)
        if len(encoded) > 1024:
            raise ValueError("capture cursor exceeds metadata bound")
        cursor = self.codec.decode_json(encoded, CaptureCursor)
        if (
            cursor.request_identity != self.request.identity
            or cursor.offset > self.request.config.max_bytes
        ):
            raise ValueError("capture cursor request or size mismatch")
        digest, count, remaining, tail = hashlib.sha256(), 0, cursor.offset, b"\n"
        while remaining:
            chunk = source.read(min(remaining, 65536))
            if not chunk:
                raise ValueError("committed capture prefix is truncated")
            digest.update(chunk)
            count += chunk.count(b"\n")
            remaining -= len(chunk)
            tail = chunk[-1:]
        if digest.hexdigest() != cursor.sha256 or count != cursor.records or tail != b"\n":
            raise ValueError("committed capture prefix differs from cursor")
        source.seek(0)
        return cursor.offset

    def finish(self, received_ns: int) -> RawObject:
        """Publish exact durable input and descriptor; interrupted stages never imply completion.

        Args:
            received_ns: Original recording receipt instant as Unix nanoseconds.

        Returns:
            RawObject descriptor binding the published journal bytes.

        Raises:
            OSError: The writer has failed, was never started or is already finished.
        """
        if not self._writable:
            raise OSError("capture writer is not active; cannot publish")
        self._writable = False
        timestamp = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=received_ns // 1000)
        descriptor = RawFiles.describe(
            self.root / "journal.jsonl",
            request=self.request.binding,
            retrieval_reference=f"live:{self.request.recording_id}",
            ts_received=timestamp,
            ts_ingested=max(timestamp, datetime.now(UTC)),
        )
        RawStore(self.root).publish(
            self.root / "journal.jsonl", descriptor=descriptor, request=self.request.binding
        )
        self._write_new(self.root / "manifest.pending", self.codec.encode_json(descriptor))
        os.replace(self.root / "manifest.pending", self.root / "manifest.json")
        self._sync_directory(self.root)
        return descriptor

    def committed_cursor(self) -> CaptureCursor:
        """Verify and return the exact durable prefix, including interrupted journals."""
        with (self.root / "journal.jsonl").open("rb") as source:
            self._verify_cursor(source)
        return self.codec.decode_json((self.root / "cursor.json").read_bytes(), CaptureCursor)

    def seal_interrupted(self) -> RawObject:
        """Publish only the committed prefix while retaining the untouched unknown tail.

        The original journal is never truncated or appended to. A resumed run
        must persist an explicit gap and acquire a new native session separately.
        Repeated sealing verifies an already published descriptor without changing it.
        """
        cursor = self.committed_cursor()
        manifest = self.root / "manifest.json"
        if manifest.exists():
            descriptor = self.codec.decode_json(manifest.read_bytes(), RawObject)
            if descriptor.sha256 != cursor.sha256 or descriptor.size_bytes != cursor.offset:
                raise ValueError("sealed capture differs from committed cursor")
            with RawStore(self.root).open(descriptor=descriptor, request=self.request.binding):
                return descriptor
        with NamedTemporaryFile(dir=self.root, prefix="committed-prefix-", delete=False) as output:
            prefix = Path(output.name)
            with (self.root / "journal.jsonl").open("rb") as source:
                remaining = cursor.offset
                while remaining:
                    chunk = source.read(min(remaining, 65536))
                    if not chunk:
                        raise ValueError("committed capture prefix is truncated")
                    output.write(chunk)
                    remaining -= len(chunk)
            output.flush()
            os.fsync(output.fileno())
        with prefix.open("rb") as source:
            line = source.readline(self.request.config.max_bytes + 1)
        received_ns = 1 if not line else self.codec.decode_json(line, CaptureRecord).received_ns
        timestamp = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=received_ns // 1000)
        descriptor = RawFiles.describe(
            prefix,
            request=self.request.binding,
            retrieval_reference=f"live:{self.request.recording_id}",
            ts_received=timestamp,
            ts_ingested=max(timestamp, datetime.now(UTC)),
        )
        RawStore(self.root).publish(prefix, descriptor=descriptor, request=self.request.binding)
        with NamedTemporaryFile(dir=self.root, prefix="manifest-", delete=False) as output:
            output.write(self.codec.encode_json(descriptor))
            output.flush()
            os.fsync(output.fileno())
            pending = Path(output.name)
        os.replace(pending, manifest)
        self._sync_directory(self.root)
        prefix.unlink()
        self._sync_directory(self.root)
        return descriptor

    def records(self, *, completed: bool = True) -> Iterator[CaptureRecord]:
        """Verify completed bytes or inspect only the newline-terminated interrupted prefix.

        Interrupted recordings admit only their verified durable cursor prefix; a
        recording without a cursor is refused. Incomplete inspection ends with an
        unknown-loss gap, including when process death happened exactly at a line
        boundary.

        Args:
            completed: Require a verified manifest, or explicitly inspect an interrupted prefix.

        Yields:
            Persisted records in original receipt order, with an interrupted-tail gap.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if completed:
            descriptor = self.codec.decode_json(
                (self.root / "manifest.json").read_bytes(), RawObject
            )
            if descriptor.size_bytes > self.request.config.max_bytes:
                raise ValueError("completed capture exceeds storage bound")
            source = RawStore(self.root).open(descriptor=descriptor, request=self.request.binding)
        else:
            source = (self.root / "journal.jsonl").open("rb")
        last_epoch, last_ns = 0, 1
        with source:
            limit = self.request.config.max_bytes
            if not completed:
                if not (self.root / "cursor.json").exists():
                    raise ValueError("unsupported capture journal schema without a cursor")
                limit = self._verify_cursor(source)
            elif os.fstat(source.fileno()).st_size > limit:
                raise ValueError("journal exceeds storage bound")
            while source.tell() < limit and (line := source.readline(limit - source.tell())):
                if not line.endswith(b"\n"):
                    if completed:
                        raise ValueError("completed capture has truncated tail")
                    break
                record = self.codec.decode_json(line, CaptureRecord)
                last_epoch, last_ns = record.epoch, record.received_ns
                yield record
        if not completed:
            yield CaptureRecord(
                kind="gap",
                epoch=last_epoch,
                received_ns=last_ns,
                reason="interrupted_persistence_unknown_tail",
            )

    # Tests substitute this seam to inject directory synchronization failures.
    _sync_directory = staticmethod(DurableDirectory.sync)

    def _write_new(self, path: Path, payload: bytes) -> None:
        """Create and sync owned metadata without overwriting a prior attempt."""
        with path.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        self._sync_directory(path.parent)
