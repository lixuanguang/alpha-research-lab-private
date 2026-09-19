"""Replay saved receipt order and session boundaries through the live book decoders."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

# project library imports
from alpha_research.data.live.config import CaptureConfig, CaptureRequest
from alpha_research.data.live.journal import CaptureJournal, CaptureRecord
from alpha_research.data.live.quality import ContinuousQuality
from alpha_research.data.venues.bitfinex.book import BitfinexBook
from alpha_research.data.venues.coinbase.book import CoinbaseBook
from alpha_research.data.venues.okx.book import OKXBook
from alpha_research.serialization import DomainCodec


class CaptureReplay:
    """Own one bounded recording's observable state and message-boundary parity trace."""

    def __init__(self, config: CaptureConfig) -> None:
        """Bind explicit native identity; no network, source-clock substitution or sorting.

        Args:
            config: Validated native spot source selection and resource budgets.
        """
        self.config = config
        self.quality = ContinuousQuality(
            f"{config.venue}:{config.channel}:{config.instrument_id}",
            lateness_ns=0,
            freshness_ns=config.idle_seconds * 1_000_000_000,
        )
        self.book: BitfinexBook | CoinbaseBook | OKXBook = self._new_book()
        self.epoch = -1
        self.messages = 0
        self.frames = 0
        self.duplicates = 0
        self.stale_snapshots = 0
        self.updates = 0
        self.snapshots = 0
        self.heartbeats = 0
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

    def _new_book(self) -> BitfinexBook | CoinbaseBook | OKXBook:
        """Select the already configured venue's reconstruction contract."""
        if self.config.venue == "okx":
            return OKXBook(self.config.symbol)
        return (
            BitfinexBook(self.config)
            if self.config.venue == "bitfinex"
            else CoinbaseBook(self.config)
        )

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
            self.book = self._new_book()
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
        if not self.quality.observe(
            record,
            outcome,
            ready=self.book.ready and not self.invalid,
            source_ns=self._source_ns() if outcome in ("snapshot", "update") else None,
        ):
            outcome = "invalid_frame"
            self._gap(record, "receipt_beyond_watermark")
        self._trace.update(
            self._codec.encode_json((record, outcome, self.book.identity, self.invalid))
        )
        return outcome

    def _source_ns(self) -> int | None:
        """Project freshness in integer nanoseconds while retaining original source text."""
        text = self.book.source_time
        if text is None:
            return None
        if isinstance(self.book, OKXBook):
            return int(text) * 1_000_000
        instant = datetime.fromisoformat(text)
        seconds = instant.replace(microsecond=0) - datetime(1970, 1, 1, tzinfo=UTC)
        fraction = re.search(r"[.,](\d+)", text)
        nanos = (
            0
            if fraction is None
            else int((text[fraction.start() + 1 : fraction.end()] + "000000000")[:9])
        )
        return (seconds.days * 86400 + seconds.seconds) * 1_000_000_000 + nanos

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
        counts: dict[str, object] = (
            {
                "representation": "L2",
                "orders": None,
                "levels": len(self.book.bids) + len(self.book.asks),
                "max_levels": self.config.max_orders,
                "sequence_resets": self.book.sequence_resets,
                "source_time_unit": "unix_milliseconds",
            }
            if isinstance(self.book, OKXBook)
            else {"orders": len(self.book.orders), "max_orders": self.config.max_orders}
        )
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
                    "storage_limit_unknown_tail",
                    "overload_unknown_loss",
                )
            ),
            "updates": self.updates,
            "snapshots": self.snapshots,
            "heartbeats": self.heartbeats,
            "depth": self.config.depth,
            **counts,
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
            if not completed and record.kind == "end":
                continue  # A journal end without verified publication is still interrupted.
            if not completed and replay.epoch < 0 and record.kind == "gap":
                replay.epoch = record.epoch  # Death before the first durable session.
            replay.apply(record)
        if completed and not replay.ended:
            raise ValueError("completed capture lacks terminal record")
        return replay
