"""Retain one owned finite capture run and an exact append-only segment chain."""

from __future__ import annotations

# standard library imports
import fcntl
import os
import shlex
import time
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

# third party library imports
import msgspec

# project library imports
from market_data.contracts import (
    CaptureRequest,
    CaptureRunRequest,
    CaptureSegment,
    RawObject,
)
from market_data.storage.journal import CaptureJournal
from serialization import DomainCodec, sync_directory


class CaptureRunJournal:
    """Own the process lock, durable progress and immutable original segment identities."""

    def __init__(self, root: Path, request: CaptureRunRequest) -> None:
        """Bind a declared run without provisioning files or acquiring process ownership."""
        request.__post_init__()
        self.root, self.request = root, request
        self.codec = DomainCodec()
        self._lock: BinaryIO | None = None

    def open(self, *, resume: bool) -> tuple[CaptureJournal, ...]:
        """Acquire exclusive ownership and verify the retained run and segment chain.

        Args:
            resume: Reopen the exact existing run, preserving its original fixed deadline.

        Returns:
            Ordered segment journals, including a possible unsealed durable prefix.

        Raises:
            BlockingIOError: A different process still owns this run.
            ValueError: A request, segment or predecessor differs from retained identities.
        """
        if not resume:
            self.root.mkdir(parents=True, exist_ok=False)
        lock = (self.root / "owner.lock").open("ab")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            lock.close()
            raise
        self._lock = lock
        try:
            if resume:
                actual = self.codec.decode_json(
                    (self.root / "run-request.json").read_bytes(), CaptureRunRequest
                )
                if actual != self.request:
                    raise ValueError("capture resume requires the exact retained run request")
                segments = self.root / "segments"
                if not segments.exists():
                    # Provisioning died after the run request committed and before its
                    # segments directory: no segment exists, so nothing was acknowledged.
                    segments.mkdir()
                    sync_directory(self.root)
                self._set_aside_unprovisioned()
            else:
                self._write(self.root / "run-request.json", self.codec.encode_json(self.request))
                (self.root / "segments").mkdir()
                sync_directory(self.root)
            journals = self.segments()
            if not (self.root / "run-summary.json").exists():
                self.progress(status="owned", segments=len(journals))
            return journals
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        """Release process ownership without removing retained run or segment evidence."""
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    def _set_aside_unprovisioned(self) -> None:
        """Move segment directories whose provisioning never committed a cursor aside.

        ``CaptureJournal.start`` writes the request, an empty journal and then the
        cursor, and a journal accepts records only after that cursor exists. A
        directory without a cursor therefore holds no acknowledged record, and a
        crash during provisioning must not block resume. Anything else without a
        cursor is refused. Only the ownership holder may move directories.
        """
        segments = self.root / "segments"
        held = self.root / "interrupted-segments"
        for root in tuple(segments.iterdir()):
            if not root.is_dir() or (root / "cursor.json").exists():
                continue
            journal = root / "journal.jsonl"
            names = {path.name for path in root.iterdir()}
            if not names <= {"request.json", "journal.jsonl", "cursor.pending"} or (
                journal.exists() and journal.stat().st_size
            ):
                raise ValueError("capture segment without a cursor holds unacknowledged data")
            held.mkdir(exist_ok=True)
            os.rename(root, held / root.name)
            sync_directory(segments)
            sync_directory(held)
            sync_directory(self.root)

    def segments(self) -> tuple[CaptureJournal, ...]:
        """Read and validate one ordered chain; reject forks and omitted predecessors."""
        journals: list[CaptureJournal] = []
        for root in (self.root / "segments").iterdir():
            if not root.is_dir():
                raise ValueError("unexpected capture segment entry")
            request = self.codec.decode_json((root / "request.json").read_bytes(), CaptureRequest)
            if (
                request.segment is None
                or request.segment.run_identity != self.request.identity
                or root.name != request.recording_id
                or request.config != self.request.config
                or request.implementation_identity != self.request.implementation_identity
                or request.universes != self.request.universes
            ):
                raise ValueError("capture segment differs from retained run")
            journals.append(CaptureJournal(root, request))
        journals.sort(key=self._ordinal)
        if len(journals) > self.request.window.max_segments:
            raise ValueError("capture run exceeds declared segment limit")
        previous: CaptureJournal | None = None
        for ordinal, journal in enumerate(journals):
            segment = journal.request.segment
            if segment is None or segment.ordinal != ordinal:
                raise ValueError("capture run has a missing or duplicate segment")
            if previous is not None:
                cursor = previous.committed_cursor()
                if (
                    segment.previous_recording_id != previous.request.recording_id
                    or segment.previous_request_identity != previous.request.identity
                    or segment.previous_sha256 != cursor.sha256
                ):
                    raise ValueError("capture segment predecessor differs from durable prefix")
            journal.committed_cursor()
            previous = journal
        return tuple(journals)

    def start_segment(self, previous: CaptureJournal | None) -> CaptureJournal:
        """Provision the next journal using the exact already committed predecessor."""
        ordinal = 0 if previous is None else self._ordinal(previous) + 1
        if ordinal >= self.request.window.max_segments:
            raise OverflowError("capture run segment limit")
        cursor = None if previous is None else previous.committed_cursor()
        request = CaptureRequest(
            config=self.request.config,
            recording_id=str(uuid4()),
            implementation_identity=self.request.implementation_identity,
            universes=self.request.universes,
            segment=CaptureSegment(
                run_identity=self.request.identity,
                ordinal=ordinal,
                previous_recording_id=None if previous is None else previous.request.recording_id,
                previous_request_identity=None if previous is None else previous.request.identity,
                previous_sha256=None if cursor is None else cursor.sha256,
            ),
        )
        journal = CaptureJournal(self.root / "segments" / request.recording_id, request)
        journal.start()
        return journal

    def progress(self, **values: object) -> None:
        """Durably expose current ownership, fixed deadline and caller-observed progress."""
        if self._lock is None:
            raise OSError("capture run process does not hold ownership")
        previous: dict[str, object] = {}
        progress = self.root / "progress.json"
        if progress.exists():
            previous.update(msgspec.json.decode(progress.read_bytes(), type=dict[str, msgspec.Raw]))
        payload: dict[str, object] = {
            **previous,
            "schema": "capture-run-progress",
            "run_identity": self.request.identity,
            "pid": os.getpid(),
            "updated_ns": time.time_ns(),
            "start_at": self.request.window.start_at,
            "ready_by": self.request.window.ready_by,
            "stop_at": self.request.window.stop_at,
            "expected_source_completion": self.request.window.stop_at,
            "verification": "separate bounded capture-run-replay command",
            "stop_instruction": (
                f"touch {shlex.quote(str(self.root.absolute() / 'stop-requested'))}"
            ),
            "resume_instruction": (
                "alpha-collect capture-run --run-directory "
                f"{shlex.quote(str(self.root.absolute()))} --resume"
            ),
            **values,
        }
        self._write(self.root / "progress.json", self.codec.encode_json(payload))

    def initial_ready_ns(self) -> int | None:
        """Read an already observed initial synchronization without inventing resumed readiness."""
        path = self.root / "progress.json"
        if not path.exists():
            return None
        fields = msgspec.json.decode(path.read_bytes(), type=dict[str, msgspec.Raw])
        encoded = fields.get("actual_ready_ns")
        if encoded is None or bytes(encoded) == b"null":
            return None
        return msgspec.json.decode(encoded, type=int)

    def finish(self, summary: dict[str, object]) -> None:
        """Durably retain the live summary before any independent post-run verification."""
        path = self.root / "run-summary.json"
        if path.exists():
            raise FileExistsError("capture run already has a final summary")
        self._write(path, self.codec.encode_json(summary))
        self.progress(status="completed", **summary)

    def sealed(self, journal: CaptureJournal, received_ns: int) -> RawObject:
        """Publish an ordinary rollover prefix without inserting any native transition."""
        descriptor = journal.finish(received_ns)
        self.progress(
            status="collecting",
            segment=self._ordinal(journal),
            recording_id=journal.request.recording_id,
            segment_committed_records=journal.count,
            segment_committed_bytes=journal.size,
            sealed_sha256=descriptor.sha256,
        )
        return descriptor

    @staticmethod
    def _ordinal(journal: CaptureJournal) -> int:
        """Return the explicit segment order after validating lineage is present."""
        if journal.request.segment is None:
            raise ValueError("capture run segment lacks lineage")
        return journal.request.segment.ordinal

    @staticmethod
    def _write(path: Path, payload: bytes) -> None:
        """Atomically synchronize mutable run progress or newly provisioned metadata."""
        pending = path.with_name(path.name + ".pending")
        with pending.open("wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(pending, path)
        sync_directory(path.parent)
