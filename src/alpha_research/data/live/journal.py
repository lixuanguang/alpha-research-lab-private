"""Durable append-only recording with shared content-addressed raw publication."""

from __future__ import annotations

# standard library imports
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec

# project library imports
from alpha_research.data.live.config import CaptureRequest
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.serialization import DomainCodec


class CaptureRecord(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Preserve exact received message bytes and local UTC receipt order/precision.

    Receipt is Unix nanoseconds observed immediately after a complete WebSocket
    message reaches the application. Source clocks remain in raw bytes and may
    be absent. Control records carry fixed local reasons, never exception bodies.
    """

    kind: Literal["session", "frame", "snapshot", "gap", "session_end", "end"]
    epoch: int
    received_ns: int
    raw: bytes = b""
    reason: str = ""

    def __post_init__(self) -> None:
        """Require valid control scope and a positive UTC receipt instant."""
        if self.epoch < 0 or self.received_ns <= 0:
            raise ValueError("invalid capture epoch or receipt timestamp")


class CaptureJournal:
    """Fsync each append before use; incomplete journals remain inspectable after death.

    One writer owns a unique directory. Published objects reuse RawStore; no
    partial journal is admitted as a completed capture. The final manifest is
    installed by durable rename only after raw publication. Peak disk use is at
    most twice max_bytes plus bounded request/descriptor metadata.
    """

    def __init__(self, root: Path, request: CaptureRequest) -> None:
        """Bind a fresh capture directory; create it explicitly with start before use.

        Args:
            root: Unique caller-owned local recording directory.
            request: Immutable recording, configuration and implementation binding.
        """
        self.root, self.request = root, request
        self.codec = DomainCodec()
        self.size = 0
        self.count = 0

    def start(self) -> None:
        """Exclusively provision and synchronize the request and journal directory."""
        self.root.mkdir(parents=True, exist_ok=False)
        self._write_new(self.root / "request.json", self.codec.encode_json(self.request))
        self._write_new(self.root / "journal.jsonl", b"")
        self._sync_directory(self.root.parent)

    def append(self, record: CaptureRecord) -> None:
        """Persist one message, reserving bounded space for terminal loss diagnostics.

        Args:
            record: One complete received message or scoped session transition.

        Raises:
            OverflowError: The journal has reached its configured storage budget.
        """
        encoded = self.codec.encode_json(record) + b"\n"
        reserve = 4096 if record.kind in ("frame", "snapshot", "session") else 0
        if self.size + len(encoded) > self.request.config.max_bytes - reserve:
            raise OverflowError("capture storage limit")
        with (self.root / "journal.jsonl").open("ab") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        self.size += len(encoded)
        self.count += 1

    def finish(self, received_ns: int) -> RawObject:
        """Publish exact durable input and descriptor; interrupted stages never imply completion.

        Args:
            received_ns: Original recording receipt instant as Unix nanoseconds.

        Returns:
            RawObject descriptor binding the published journal bytes.
        """
        timestamp = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=received_ns // 1000)
        descriptor = RawObject.from_file(
            self.root / "journal.jsonl",
            request=self.request,
            retrieval_reference=f"live:{self.request.recording_id}",
            ts_received=timestamp,
            ts_ingested=max(timestamp, datetime.now(UTC)),
        )
        RawStore(self.root).publish(
            self.root / "journal.jsonl", descriptor=descriptor, request=self.request
        )
        self._write_new(self.root / "manifest.pending", self.codec.encode_json(descriptor))
        os.replace(self.root / "manifest.pending", self.root / "manifest.json")
        self._sync_directory(self.root)
        return descriptor

    def records(self, *, completed: bool = True) -> Iterator[CaptureRecord]:
        """Verify completed bytes or inspect only the newline-terminated interrupted prefix.

        Incomplete inspection always ends with an explicit unknown-loss gap,
        including when process death happened exactly at a line boundary.

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
            source = RawStore(self.root).open(descriptor=descriptor, request=self.request)
        else:
            source = (self.root / "journal.jsonl").open("rb")
        last_epoch, last_ns = 0, 1
        with source:
            while line := source.readline(self.request.config.max_bytes + 1):
                if len(line) > self.request.config.max_bytes:
                    raise ValueError("journal line exceeds bound")
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

    @staticmethod
    def _sync_directory(path: Path) -> None:
        """Make new names durable on the supported local filesystem."""
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write_new(self, path: Path, payload: bytes) -> None:
        """Create and sync owned metadata without overwriting a prior attempt."""
        with path.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        self._sync_directory(path.parent)
