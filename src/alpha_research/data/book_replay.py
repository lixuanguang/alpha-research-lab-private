"""Query whole saved book messages and step known receipts on the shared replay clock."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from itertools import batched
from pathlib import Path

# project library imports
from alpha_research.data.asof import EconomicOrder
from alpha_research.data.book_datasets import (
    BookDatasetManifest,
    BookHistory,
    BookInput,
    BookObservation,
)
from alpha_research.data.raw_store import RawStore
from alpha_research.data.replay import ReplayCursor, _EventSteps
from alpha_research.data.snapshots import SnapshotStore
from alpha_research.serialization import DomainCodec


class BookReplay(_EventSteps[BookObservation]):
    """Own one bounded admitted partition; keep unknown archive availability unscheduled.

    Query batches retain every control and full message. Receipt nanoseconds remain
    exact; the shared microsecond UTC clock rounds upwards, never exposing input early.
    Save consumer state (accepted snapshot, last boundary and epoch) with each cursor.
    Restoring a cursor alone does not restore a consumer or resynchronize a live feed.
    """

    def __init__(
        self,
        canonical: bytes,
        *,
        terminal: datetime,
        config_identity: str,
        max_bytes: int,
        batch_size: int,
        cursor: ReplayCursor | None = None,
        snapshot_identity: str | None = None,
    ) -> None:
        """Bind explicitly admitted canonical bytes, also usable by bounded fixture consumers.

        Args:
            canonical: Complete MR 25 BookHistory bytes; use read for stored-input verification.
            terminal: Inclusive final UTC step time; observations after it remain queryable.
            config_identity: Resolved consumer configuration SHA-256, including timing policy.
            max_bytes: Positive canonical-input byte cap, not a process RSS limit.
            batch_size: Positive whole-message query bound; does not affect replay identity.
            cursor: Completed shared cursor paired with independently restored consumer state.
            snapshot_identity: Verified publication identity, or None for in-memory admission.

        Raises:
            ValueError: Bounds, canonical history, receipt order or checkpoint are invalid.
            TypeError: Configuration or UTC clocks have invalid types.
        """
        ReplayCursor(identity=config_identity, clock=terminal, position=None)
        if snapshot_identity is not None:
            ReplayCursor(identity=snapshot_identity, clock=terminal, position=None)
        if type(max_bytes) is not int or max_bytes <= 0 or len(canonical) > max_bytes:
            raise ValueError("book replay canonical input exceeds positive max_bytes")
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("book replay requires positive batch_size")
        self._history = DomainCodec().decode_json(canonical, BookHistory)
        self._batch_size = batch_size
        ordered: dict[EconomicOrder, BookObservation] = {}
        previous_ns = 0
        for batch in self.batches():
            for row in batch:
                if row.received_ns is None:
                    continue
                if row.received_ns < previous_ns:
                    raise ValueError("book replay receipt order regressed")
                previous_ns = row.received_ns
                instant = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
                    microseconds=(row.received_ns + 999) // 1000
                )
                if instant <= terminal:
                    ordered[(instant, row.received_ns, instant, row.epoch or 0, row.position)] = row
        identity = hashlib.sha256(
            DomainCodec().encode_json(
                ("book-replay-v1", snapshot_identity, canonical, terminal, config_identity)
            )
        ).hexdigest()
        super().__init__(ordered, identity=identity, terminal=terminal, cursor=cursor)

    @classmethod
    def read(
        cls,
        directory: Path,
        raw: RawStore,
        *,
        identity: str,
        request_identity: str,
        terminal: datetime,
        config_identity: str,
        max_bytes: int,
        batch_size: int,
        cursor: ReplayCursor | None = None,
    ) -> BookReplay:
        """Verify the whole published snapshot and select one explicit native partition.

        Args:
            directory: Published snapshot store.
            raw: Retained original bytes for independent normalization verification.
            identity: Immutable snapshot SHA-256.
            request_identity: Explicit capture/archive request in that snapshot.
            terminal: Inclusive UTC stop time.
            config_identity: Resolved consumer configuration SHA-256.
            max_bytes: Per-file verification and selected canonical-input cap.
            batch_size: Positive whole-message query bound.
            cursor: Completed checkpoint paired with consumer state.

        Returns:
            Verified partition with isolated input evidence, history and shared stepping.

        Raises:
            ValueError: Snapshot verification fails or the requested partition is absent.
        """
        manifest = SnapshotStore(directory, raw, manifest_type=BookDatasetManifest).read(
            identity, max_bytes=max_bytes
        )
        for partition in manifest.partitions:
            if partition.selection.request.identity == request_identity:
                return cls(
                    BookInput._read_bytes(directory / identity / partition.sha256, max_bytes),
                    terminal=terminal,
                    config_identity=config_identity,
                    max_bytes=max_bytes,
                    batch_size=batch_size,
                    cursor=cursor,
                    snapshot_identity=identity,
                )
        raise ValueError("book replay request absent from snapshot")

    @property
    def evidence(self) -> BookInput:
        """Expose isolated depth, clocks, raw identity and selected-prefix limitations.

        Returns:
            Original native selection; publication remains exploratory degraded.
        """
        return deepcopy(self._history.input)

    def batches(self) -> Iterator[tuple[BookObservation, ...]]:
        """Yield isolated whole-message history, including unschedulable archive records.

        Yields:
            At most batch_size observations in original raw order, without advancing time.
        """
        for batch in batched(self._history.observations, self._batch_size):
            yield deepcopy(batch)
