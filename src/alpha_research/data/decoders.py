"""Define neutral source capture context and payload decoder contracts."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

# third party library imports
import msgspec

# project library imports
from alpha_research.core import EventProvenance


class DecodeContext(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Carry one source line's capture, raw, receipt, and source metadata."""

    capture_text: str
    capture_time: datetime
    raw_line: str
    source_sequence: int
    local_received: datetime
    local_ingested: datetime | None
    source_digest: str | None
    source_id: str

    def __post_init__(self) -> None:
        """Validate and normalize the source metadata held by this context.

        Raises:
            TypeError: A context field has the wrong Python type.
            ValueError: A context field violates its source-boundary invariant.
        """
        if not isinstance(self.capture_text, str):
            raise TypeError("capture_text must be a string")
        if self.capture_text != self.capture_text.strip():
            raise ValueError("capture_text must not have surrounding whitespace")
        if not isinstance(self.capture_time, datetime):
            raise TypeError("capture_time must be a datetime")
        if self.capture_time.tzinfo is None or self.capture_time.utcoffset() is None:
            raise ValueError("capture_time must be timezone-aware")
        msgspec.structs.force_setattr(self, "capture_time", self.capture_time.astimezone(UTC))
        if not isinstance(self.raw_line, str):
            raise TypeError("raw_line must be a string")
        if self.raw_line != self.raw_line.strip():
            raise ValueError("raw_line must not have surrounding whitespace")
        if isinstance(self.source_sequence, bool) or not isinstance(self.source_sequence, int):
            raise TypeError("source_sequence must be an integer")
        if self.source_sequence < 0:
            raise ValueError("source_sequence must be nonnegative")
        if not isinstance(self.local_received, datetime):
            raise TypeError("local_received must be a datetime")
        if self.local_received.tzinfo is None or self.local_received.utcoffset() is None:
            raise ValueError("local_received must be timezone-aware")
        normalized_received = self.local_received.astimezone(UTC)
        msgspec.structs.force_setattr(self, "local_received", normalized_received)
        if self.local_ingested is not None:
            if not isinstance(self.local_ingested, datetime):
                raise TypeError("local_ingested must be a datetime")
            if self.local_ingested.tzinfo is None or self.local_ingested.utcoffset() is None:
                raise ValueError("local_ingested must be timezone-aware")
            normalized_ingested = self.local_ingested.astimezone(UTC)
            if normalized_ingested < normalized_received:
                raise ValueError("local_ingested must be later than or equal to local_received")
            msgspec.structs.force_setattr(self, "local_ingested", normalized_ingested)
        if self.source_digest is not None:
            if not isinstance(self.source_digest, str):
                raise TypeError("source_digest must be a string")
            if len(self.source_digest) != 64 or any(
                character not in "0123456789abcdef" for character in self.source_digest
            ):
                raise ValueError("source_digest must be a lowercase SHA-256 digest")
        if not isinstance(self.source_id, str):
            raise TypeError("source_id must be a string")
        if not self.source_id:
            raise ValueError("source_id must be nonempty")

    def provenance(self, *, event_time: datetime, event_id_suffix: str) -> EventProvenance:
        """Build point-event provenance from this immutable decoding context.

        Args:
            event_time: Source event instant or capture proxy.
            event_id_suffix: Stable payload-specific suffix for the event identity.

        Returns:
            Validated event provenance retaining source and receipt metadata.

        Raises:
            TypeError: A provenance field has the wrong Python type.
            ValueError: A provenance timestamp or identity invariant is invalid.
        """
        if not isinstance(event_id_suffix, str):
            raise TypeError("event_id_suffix must be a string")
        if not event_id_suffix:
            raise ValueError("event_id_suffix must be nonempty")
        digest = (
            self.source_digest
            if self.source_digest is not None
            else hashlib.sha256(self.raw_line.encode()).hexdigest()
        )
        return EventProvenance(
            source_id=self.source_id,
            event_id=f"{self.source_id}:{self.source_sequence}:{event_id_suffix}",
            source_revision=0,
            source_sequence=self.source_sequence,
            source_digest=digest,
            ts_event=event_time,
            ts_received=self.local_received,
            ts_ingested=(
                self.local_ingested if self.local_ingested is not None else self.local_received
            ),
            ts_knowledge=self.capture_time,
            ts_source_received=self.capture_time,
            valid_from=self.capture_time,
            valid_to=self.capture_time + timedelta(microseconds=1),
            knowledge_basis="source_capture",
        )


@runtime_checkable
class PayloadDecoder[DecodedT](Protocol):
    """Define the payload-decoding contract supplied to a line decoder."""

    def decode_payload(self, payload: str, context: DecodeContext) -> DecodedT:
        """Decode one complete source payload using neutral line context.

        Args:
            payload: Complete venue-native JSON text for one source message.
            context: Immutable source capture and provenance metadata.

        Returns:
            The decoded domain value.
        """


__all__ = [
    "DecodeContext",
    "PayloadDecoder",
]
