"""Retain optional individual monotonic runtime observations for bounded trials."""

from __future__ import annotations

# standard library imports
import os
from pathlib import Path

# project library imports
from serialization import DomainCodec


class RuntimeMeasurementJournal:
    """Write complete JSONL observations without changing economic input identity.

    Each row is written in one process-owned append stream. Periodic and final
    fsyncs retain an inspectable prefix if a bounded service is interrupted.
    Measurement files are trial evidence, never replay or account inputs.
    """

    def __init__(self, path: Path, *, sync_every: int = 128) -> None:
        """Open one exclusive local evidence file with a bounded sync interval."""
        if not path.is_absolute() or type(sync_every) is not int or sync_every < 1:
            raise ValueError("runtime measurement requires an absolute path and sync interval")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        self._codec = DomainCodec()
        self._sync_every = sync_every
        self._count = 0

    def record(self, observation: dict[str, object]) -> None:
        """Append one complete measured event without buffering or dropping samples."""
        if self._descriptor < 0:
            raise ValueError("runtime measurement journal is closed")
        payload = (
            self._codec.encode_json({"schema_version": "runtime-measurement-v1", **observation})
            + b"\n"
        )
        view = memoryview(payload)
        while view:
            written = os.write(self._descriptor, view)
            if written <= 0:
                raise OSError("runtime measurement write made no progress")
            view = view[written:]
        self._count += 1
        if self._count % self._sync_every == 0:
            os.fsync(self._descriptor)

    def close(self) -> None:
        """Fsync all completed rows before releasing this process-owned stream."""
        if self._descriptor >= 0:
            descriptor, self._descriptor = self._descriptor, -1
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def __enter__(self) -> RuntimeMeasurementJournal:
        """Return this open journal for one bounded service lifetime."""
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        """Close the journal on ordinary completion or visible failure."""
        self.close()
