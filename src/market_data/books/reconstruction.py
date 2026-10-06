"""Replay saved receipt order and session boundaries through the live book decoders."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Callable

# project library imports
from configuration import CaptureConfig
from market_data.books.protocol import NativeBook
from market_data.contracts import CaptureRecord
from market_data.validation import ContinuousQuality
from serialization import DomainCodec


class CaptureReplay:
    """Own one bounded recording's observable state and message-boundary parity trace."""

    def __init__(
        self, config: CaptureConfig, *, book_factory: Callable[[CaptureConfig], NativeBook]
    ) -> None:
        """Bind explicit native identity; no network, source-clock substitution or sorting.

        Args:
            book_factory: Explicit native state constructor reused for each capture epoch.
            config: Validated native spot source selection and resource budgets.
        """
        self.config = config
        self._book_factory = book_factory
        self.quality = ContinuousQuality(
            f"{config.venue}:{config.channel}:{config.instrument_id}",
            lateness_ns=0,
            freshness_ns=config.idle_seconds * 1_000_000_000,
        )
        self.book = book_factory(config)
        self.epoch = -1
        self.messages = 0
        self.frames = 0
        self.duplicates = 0
        self.stale_snapshots = 0
        self.updates = 0
        self.snapshots = 0
        self.heartbeats = 0
        # Undecodable or beyond-watermark input only; reconnects are gaps, not this.
        self.invalid_frames = 0
        self.gaps: list[dict[str, object]] = []
        self.started_ns: int | None = None
        self.finished_ns: int | None = None
        self.ended = False
        self.invalid = False
        self._last_frame = b""
        self._session_ended = False
        self._stop_reason = ""
        self._trace = hashlib.sha256()
        self._codec = DomainCodec()

    def apply(self, record: CaptureRecord) -> str:
        """Apply exactly one saved message, retaining invalid states until a fresh session.

        Exact adjacent Bitfinex/Coinbase sequenced frames remain raw lineage but
        do not repeat mutations. Ambiguous repeats use the native sequence refusal.
        Prior/closed-epoch snapshots are retained without changing current state.

        Args:
            record: One complete received message or scoped session transition.

        Returns:
            Source-message classification for the applied boundary.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if self.ended:
            raise ValueError("record after capture end")
        if self.started_ns is None:
            self.started_ns = record.received_ns
        self.finished_ns = record.received_ns
        outcome: str = record.kind
        if record.kind == "session":
            if record.epoch != self.epoch + 1:
                raise ValueError("noncontiguous capture epoch")
            self.epoch = record.epoch
            self.book = self._book_factory(self.config)
            self.invalid = False
            self._last_frame = b""
            self._session_ended = False
        elif record.kind == "snapshot" and (
            record.epoch < self.epoch or (record.epoch == self.epoch and self._session_ended)
        ):
            self.messages += 1
            self.stale_snapshots += 1
            outcome = "stale_snapshot"
        elif record.epoch != self.epoch:
            raise ValueError("record outside capture epoch")
        elif record.kind in ("frame", "snapshot"):
            self.messages += 1
            self.frames += record.kind == "frame"
            if self._session_ended:
                raise ValueError("frame after session end")
            if (
                not self.invalid
                and self.book.ready
                and self.config.venue in ("bitfinex", "coinbase")
                and record.kind == "frame"
                and record.raw == self._last_frame
            ):
                self.duplicates += 1
                outcome = "duplicate"
            elif not self.invalid:
                try:
                    outcome = self.book.apply(record.raw, snapshot=record.kind == "snapshot")
                    self.updates += outcome == "update"
                    self.snapshots += outcome == "snapshot"
                    self.heartbeats += outcome == "heartbeat"
                except ValueError, KeyError, IndexError, TypeError:
                    outcome = "invalid_frame"
                    self._gap(record, outcome)
            if record.kind == "frame" and outcome != "duplicate":
                self._last_frame = (
                    record.raw if outcome in ("update", "snapshot", "heartbeat") else b""
                )
        elif record.kind == "gap":
            self._gap(record, record.reason)
        elif record.kind == "end":
            self.ended = True
            self._stop_reason = record.reason
        elif record.kind == "session_end":
            self._session_ended = True
        elif record.kind == "clock" and self._session_ended:
            raise ValueError("clock after session end")
        if not self.quality.observe(
            record,
            outcome,
            ready=self.book.ready and not self.invalid,
            source_ns=self.book.source_ns if outcome in ("snapshot", "update") else None,
        ):
            outcome = "invalid_frame"
            self._gap(record, "receipt_beyond_watermark")
        self.invalid_frames += outcome == "invalid_frame"
        self._trace.update(
            self._codec.encode_json((record, outcome, self.book.identity, self.invalid))
        )
        return outcome

    def _gap(self, record: CaptureRecord, reason: str) -> None:
        """Record scoped unknown continuity and hide partially applied invalid state."""
        self.invalid = True
        self.book.ready = False
        self.gaps.append(
            {"epoch": record.epoch, "received_ns": record.received_ns, "reason": reason}
        )

    def summary(self) -> dict[str, object]:
        """Return small non-secret evidence, including depth limits and raw-order meaning.

        Returns:
            Non-secret counts, clocks, gaps and reconstruction identities.
        """
        return {
            "venue": self.config.venue,
            "symbol": self.config.symbol,
            "instrument_id": str(self.config.instrument_id),
            "channel": self.config.channel,
            "started_ns": self.started_ns,
            "finished_ns": self.finished_ns,
            "messages": self.messages,
            "frames": self.frames,
            "duplicates": self.duplicates,
            "stale_snapshots": self.stale_snapshots,
            "retry_exhausted": (
                self.ended
                and self.epoch == self.config.retries
                and self._stop_reason
                not in (
                    "duration_limit",
                    "message_limit",
                    "supervisor_stop",
                    "storage_limit_unknown_tail",
                    "overload_unknown_loss",
                )
            ),
            "updates": self.updates,
            "snapshots": self.snapshots,
            "heartbeats": self.heartbeats,
            "depth": self.config.depth,
            **self.book.counts(self.config.max_orders),
            "gaps": self.gaps,
            "synchronized": self.book.ready and not self.invalid,
            "ended": self.ended,
            "source_sequence": self.book.sequence,
            "last_source_time": self.book.source_time,
            "book_identity": self.book.identity,
            "trace_identity": self._trace.hexdigest(),
            "epochs": self.epoch + 1,
            "quality": self.quality.summary(),
        }
