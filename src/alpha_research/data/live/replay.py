"""Replay saved receipt order and session boundaries through the live book decoders."""

from __future__ import annotations

# standard library imports
import hashlib
from pathlib import Path

# project library imports
from alpha_research.data.live.config import CaptureConfig, CaptureRequest
from alpha_research.data.live.journal import CaptureJournal, CaptureRecord
from alpha_research.data.venues.bitfinex.book import BitfinexBook
from alpha_research.data.venues.coinbase.book import CoinbaseBook
from alpha_research.serialization import DomainCodec


class CaptureReplay:
    """Own one bounded recording's observable state and message-boundary parity trace."""

    def __init__(self, config: CaptureConfig) -> None:
        """Bind explicit native identity; no network, source-clock substitution or sorting.

        Args:
            config: Validated native spot source selection and resource budgets.
        """
        self.config = config
        self.book: BitfinexBook | CoinbaseBook = self._new_book()
        self.epoch = -1
        self.messages = 0
        self.updates = 0
        self.snapshots = 0
        self.heartbeats = 0
        self.gaps: list[dict[str, object]] = []
        self.started_ns: int | None = None
        self.finished_ns: int | None = None
        self.ended = False
        self.invalid = False
        self._trace = hashlib.sha256()
        self._codec = DomainCodec()

    def _new_book(self) -> BitfinexBook | CoinbaseBook:
        """Select the already configured venue's reconstruction contract."""
        return (
            BitfinexBook(self.config)
            if self.config.venue == "bitfinex"
            else CoinbaseBook(self.config)
        )

    def apply(self, record: CaptureRecord) -> str:
        """Apply exactly one saved message, retaining invalid states until a fresh session.

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
            self.book = self._new_book()
            self.invalid = False
        elif record.epoch != self.epoch:
            raise ValueError("record outside capture epoch")
        elif record.kind in ("frame", "snapshot"):
            self.messages += 1
            if not self.invalid:
                try:
                    outcome = self.book.apply(record.raw, snapshot=record.kind == "snapshot")
                    self.updates += outcome == "update"
                    self.snapshots += outcome == "snapshot"
                    self.heartbeats += outcome == "heartbeat"
                except ValueError, KeyError, IndexError, TypeError:
                    outcome = "invalid_frame"
                    self._gap(record, outcome)
        elif record.kind == "gap":
            self._gap(record, record.reason)
        elif record.kind == "end":
            self.ended = True
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
            "updates": self.updates,
            "snapshots": self.snapshots,
            "heartbeats": self.heartbeats,
            "orders": len(self.book.orders),
            "depth": self.config.depth,
            "max_orders": self.config.max_orders,
            "gaps": self.gaps,
            "synchronized": self.book.ready and not self.invalid,
            "ended": self.ended,
            "source_sequence": self.book.sequence,
            "last_source_time": self.book.source_time,
            "book_identity": self.book.identity,
            "trace_identity": self._trace.hexdigest(),
            "epochs": self.epoch + 1,
        }

    @classmethod
    def read(cls, root: Path, *, completed: bool = True) -> CaptureReplay:
        """Replay a verified completed capture, or explicitly inspect an interrupted prefix.

        Args:
            root: Unique caller-owned local recording directory.
            completed: Require a verified manifest, or explicitly inspect an interrupted prefix.

        Returns:
            Validated configuration, credentials or replay state owned by this boundary.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        request = DomainCodec().decode_json((root / "request.json").read_bytes(), CaptureRequest)
        replay = cls(request.config)
        for record in CaptureJournal(root, request).records(completed=completed):
            replay.apply(record)
        if completed and not replay.ended:
            raise ValueError("completed capture lacks terminal record")
        return replay
