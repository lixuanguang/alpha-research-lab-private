"""Define the immutable, source-independent event provenance boundary."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime
from typing import Literal, Self

# third party library imports
import msgspec

type KnowledgeBasis = Literal[
    "observed",
    "source_published",
    "source_capture",
    "assumed_delay",
]
"""Identify how the availability time of an event was established."""


class EventProvenance(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Hold immutable identity, timing, validity, and availability metadata.

    The four timestamps have distinct meanings. ``ts_event`` records when the
    source says the event occurred, ``ts_received`` records local receipt,
    ``ts_ingested`` records entry into governed storage, and ``ts_knowledge``
    records the first time the validated version could be used. The event time
    is intentionally independent of the business-validity interval because a
    reference event may announce a future state.

    Attributes:
        schema_version: Serialized event-provenance schema version.
        source_id: Stable identifier for the source assertion system.
        event_id: Stable identifier for the source event.
        source_revision: Nonnegative source revision number.
        source_sequence: Nonnegative source sequence number.
        source_digest: Lowercase SHA-256 digest of the raw source payload.
        ts_event: Source event instant, normalized to UTC.
        ts_received: Local receipt instant, normalized to UTC.
        ts_ingested: Governed-storage ingestion instant, normalized to UTC.
        ts_knowledge: Earliest usable availability instant, normalized to UTC.
        ts_source_received: Optional source-reported capture instant, normalized to UTC.
        valid_from: Inclusive business-validity interval start, normalized to UTC.
        valid_to: Exclusive business-validity interval end, normalized to UTC.
        correction_id: Optional source correction identifier.
        knowledge_basis: Basis for the availability timestamp.
    """

    schema_version: Literal["1"] = "1"
    source_id: str
    event_id: str
    source_revision: int
    source_sequence: int
    source_digest: str
    ts_event: datetime
    ts_received: datetime
    ts_ingested: datetime
    ts_knowledge: datetime
    ts_source_received: datetime | None = None
    valid_from: datetime
    valid_to: datetime
    correction_id: str | None = None
    knowledge_basis: KnowledgeBasis

    def __post_init__(self) -> None:
        """Validate construction and normalize all supplied instants to UTC.

        Raises:
            TypeError: A field has the wrong Python type.
            ValueError: A field value or temporal invariant is invalid.
        """
        self._validate_fields()
        timestamp_values: tuple[tuple[str, datetime | None], ...] = (
            ("ts_event", self.ts_event),
            ("ts_received", self.ts_received),
            ("ts_ingested", self.ts_ingested),
            ("ts_knowledge", self.ts_knowledge),
            ("ts_source_received", self.ts_source_received),
            ("valid_from", self.valid_from),
            ("valid_to", self.valid_to),
        )
        for field_name, value in timestamp_values:
            if value is not None:
                normalized = EventProvenance._normalize_utc(value, field_name=field_name)
                msgspec.structs.force_setattr(self, field_name, normalized)

    def validate(self) -> Self:
        """Recheck this provenance record before a trusted consumer uses it.

        Returns:
            This validated provenance record.

        Raises:
            TypeError: An unsafe mutation inserted a value with the wrong Python type.
            ValueError: An unsafe mutation violates a provenance invariant.
        """
        self._validate_fields()
        return self

    @property
    def ordering_key(self) -> tuple[datetime, int, int, str]:
        """Return the deterministic revision-ordering key.

        Returns:
            Knowledge instant, source sequence, revision and digest, in ordering priority.

        Raises:
            TypeError: The instance was unsafely mutated with a wrong field type.
            ValueError: The instance was unsafely mutated with invalid provenance.
        """
        validated = self.validate()
        return (
            EventProvenance._normalize_utc(validated.ts_knowledge, field_name="ts_knowledge"),
            validated.source_sequence,
            validated.source_revision,
            validated.source_digest,
        )

    def is_available(self, decision_time: datetime, valid_time: datetime) -> bool:
        """Return whether this event is usable at a decision and business time.

        Args:
            decision_time: Knowledge cutoff for the decision, as an aware datetime.
            valid_time: Business time to test against the half-open validity interval,
                as an aware datetime.

        Returns:
            ``True`` when the event was knowable by ``decision_time`` and valid at
            ``valid_time``; otherwise ``False``.

        Raises:
            TypeError: A query time has the wrong Python type.
            ValueError: A query time is naive or this instance is invalid.
        """
        validated = self.validate()
        normalized_decision_time = EventProvenance._normalize_utc(
            decision_time, field_name="decision_time"
        )
        normalized_valid_time = EventProvenance._normalize_utc(valid_time, field_name="valid_time")
        return EventProvenance._normalize_utc(
            validated.ts_knowledge, field_name="ts_knowledge"
        ) <= normalized_decision_time and EventProvenance._normalize_utc(
            validated.valid_from, field_name="valid_from"
        ) <= normalized_valid_time < EventProvenance._normalize_utc(
            validated.valid_to, field_name="valid_to"
        )

    @staticmethod
    def _require_text(value: object, *, field_name: str, allow_empty: bool = False) -> str:
        """Require a string field, optionally requiring one or more characters."""
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")
        if not allow_empty and not value:
            raise ValueError(f"{field_name} must be nonempty")
        return value

    @staticmethod
    def _normalize_utc(value: object, *, field_name: str) -> datetime:
        """Require an aware instant and return it represented in UTC.

        Args:
            value: Datetime supplied at the provenance boundary.
            field_name: Name used in the validation message.

        Returns:
            The supplied instant converted to UTC.

        Raises:
            TypeError: The value is not a datetime.
            ValueError: The datetime is naive or has no usable UTC offset.
        """
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")
        return value.astimezone(UTC)

    def _validate_fields(self) -> None:
        """Validate one self instance without constructing another record."""
        EventProvenance._require_text(self.schema_version, field_name="schema_version")
        if self.schema_version != "1":
            raise ValueError("schema_version must be '1'")
        EventProvenance._require_text(self.source_id, field_name="source_id")
        EventProvenance._require_text(self.event_id, field_name="event_id")
        for field_name, value in (
            ("source_revision", self.source_revision),
            ("source_sequence", self.source_sequence),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} must be nonnegative")
        EventProvenance._require_text(self.source_digest, field_name="source_digest")
        if len(self.source_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.source_digest
        ):
            raise ValueError("source_digest must be a lowercase SHA-256 digest")

        timestamps: dict[str, datetime] = {
            "ts_event": EventProvenance._normalize_utc(self.ts_event, field_name="ts_event"),
            "ts_received": EventProvenance._normalize_utc(
                self.ts_received, field_name="ts_received"
            ),
            "ts_ingested": EventProvenance._normalize_utc(
                self.ts_ingested, field_name="ts_ingested"
            ),
            "ts_knowledge": EventProvenance._normalize_utc(
                self.ts_knowledge, field_name="ts_knowledge"
            ),
        }
        source_received = self.ts_source_received
        if source_received is not None:
            timestamps["ts_source_received"] = EventProvenance._normalize_utc(
                source_received, field_name="ts_source_received"
            )
        timestamps["valid_from"] = EventProvenance._normalize_utc(
            self.valid_from, field_name="valid_from"
        )
        timestamps["valid_to"] = EventProvenance._normalize_utc(
            self.valid_to, field_name="valid_to"
        )

        correction_id = self.correction_id
        if correction_id is not None:
            EventProvenance._require_text(correction_id, field_name="correction_id")
        if not isinstance(self.knowledge_basis, str):
            raise TypeError("knowledge_basis must be a string")
        if self.knowledge_basis not in {
            "observed",
            "source_published",
            "source_capture",
            "assumed_delay",
        }:
            raise ValueError("knowledge_basis is unsupported")

        if timestamps["ts_received"] > timestamps["ts_ingested"]:
            raise ValueError("ts_received must be earlier than or equal to ts_ingested")
        if timestamps["valid_to"] <= timestamps["valid_from"]:
            raise ValueError("valid_to must be later than valid_from")
        if (
            self.knowledge_basis == "observed"
            and timestamps["ts_knowledge"] < timestamps["ts_ingested"]
        ):
            raise ValueError("observed ts_knowledge must be later than or equal to ts_ingested")
        if self.knowledge_basis == "source_capture":
            if source_received is None:
                raise ValueError("source_capture knowledge_basis requires ts_source_received")
            if timestamps["ts_knowledge"] < timestamps["ts_source_received"]:
                raise ValueError(
                    "source_capture ts_knowledge must be later than or equal to ts_source_received"
                )
