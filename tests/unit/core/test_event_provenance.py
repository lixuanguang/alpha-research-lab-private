"""Test the P1 immutable event-provenance boundary."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta, timezone

# third party library imports
import msgspec
import pytest

# project library imports
from alpha_research.core import EventProvenance, KnowledgeBasis

_BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64


def _payload(**overrides: object) -> dict[str, object]:
    """Return one valid observed provenance payload with selected replacements."""
    payload: dict[str, object] = {
        "source_id": "source",
        "event_id": "event",
        "source_revision": 0,
        "source_sequence": 0,
        "source_digest": _DIGEST_A,
        "ts_event": _BASE_TIME,
        "ts_received": _BASE_TIME + timedelta(seconds=1),
        "ts_ingested": _BASE_TIME + timedelta(seconds=2),
        "ts_knowledge": _BASE_TIME + timedelta(seconds=2),
        "valid_from": _BASE_TIME,
        "valid_to": _BASE_TIME + timedelta(hours=1),
        "knowledge_basis": "observed",
    }
    payload.update(overrides)
    return payload


def _event(**overrides: object) -> EventProvenance:
    """Construct a provenance event from a deliberately untyped test payload."""
    payload = _payload(**overrides)
    source_id = payload["source_id"]
    event_id = payload["event_id"]
    source_digest = payload["source_digest"]
    if not isinstance(source_id, str) or not isinstance(event_id, str):
        raise TypeError("source identifiers must be strings")
    if not isinstance(source_digest, str):
        raise TypeError("source_digest must be a string")
    revision = payload["source_revision"]
    sequence = payload["source_sequence"]
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise TypeError("source_revision must be an integer")
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise TypeError("source_sequence must be an integer")

    def _datetime_value(field_name: str) -> datetime:
        """Read one test timestamp with its concrete runtime type."""
        value = payload[field_name]
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime")
        return value

    ts_event = _datetime_value("ts_event")
    ts_received = _datetime_value("ts_received")
    ts_ingested = _datetime_value("ts_ingested")
    ts_knowledge = _datetime_value("ts_knowledge")
    valid_from = _datetime_value("valid_from")
    valid_to = _datetime_value("valid_to")
    source_received = payload.get("ts_source_received")
    if source_received is not None and not isinstance(source_received, datetime):
        raise TypeError("ts_source_received must be a datetime")
    basis_value = payload["knowledge_basis"]
    if basis_value == "observed":
        basis: KnowledgeBasis = "observed"
    elif basis_value == "source_capture":
        basis = "source_capture"
    else:
        raise ValueError("unsupported test knowledge basis")
    correction_id = payload.get("correction_id")
    if correction_id is not None and not isinstance(correction_id, str):
        raise TypeError("correction_id must be a string")
    return EventProvenance(
        source_id=source_id,
        event_id=event_id,
        source_revision=revision,
        source_sequence=sequence,
        source_digest=source_digest,
        ts_event=ts_event,
        ts_received=ts_received,
        ts_ingested=ts_ingested,
        ts_knowledge=ts_knowledge,
        ts_source_received=source_received,
        valid_from=valid_from,
        valid_to=valid_to,
        correction_id=correction_id,
        knowledge_basis=basis,
    )


def test_offsets_are_normalized_and_serialization_round_trips() -> None:
    """Normalize every supplied offset to UTC and preserve it through JSON."""
    offset = timezone(timedelta(hours=8))
    event = _event(
        ts_event=_BASE_TIME.astimezone(offset),
        ts_received=(_BASE_TIME + timedelta(seconds=1)).astimezone(offset),
        ts_ingested=(_BASE_TIME + timedelta(seconds=2)).astimezone(offset),
        ts_knowledge=(_BASE_TIME + timedelta(seconds=2)).astimezone(offset),
        valid_from=_BASE_TIME.astimezone(offset),
        valid_to=(_BASE_TIME + timedelta(hours=1)).astimezone(offset),
    )

    assert event.ts_event == _BASE_TIME
    assert event.ts_event.tzinfo is UTC
    assert event.ts_received == _BASE_TIME + timedelta(seconds=1)
    assert event.ts_ingested == _BASE_TIME + timedelta(seconds=2)
    assert event.ts_knowledge == _BASE_TIME + timedelta(seconds=2)
    assert event.valid_from == _BASE_TIME
    assert event.valid_to == _BASE_TIME + timedelta(hours=1)
    encoded = msgspec.json.encode(event)
    assert msgspec.json.decode(encoded, type=EventProvenance) == event


@pytest.mark.parametrize(
    "field_name",
    (
        "ts_event",
        "ts_received",
        "ts_ingested",
        "ts_knowledge",
        "valid_from",
        "valid_to",
    ),
)
def test_naive_timestamps_are_rejected(field_name: str) -> None:
    """Reject a naive datetime at each timestamp boundary."""
    with pytest.raises((TypeError, ValueError), match=field_name):
        _event(**{field_name: _BASE_TIME.replace(tzinfo=None)})


def test_source_capture_preserves_historical_vendor_capture_time() -> None:
    """Allow historical source knowledge while keeping local receipt distinct."""
    source_capture = _event(
        knowledge_basis="source_capture",
        ts_source_received=_BASE_TIME + timedelta(seconds=3),
        ts_knowledge=_BASE_TIME + timedelta(seconds=3),
        ts_received=_BASE_TIME + timedelta(hours=2),
        ts_ingested=_BASE_TIME + timedelta(hours=2, seconds=1),
    )

    assert source_capture.ts_source_received == _BASE_TIME + timedelta(seconds=3)
    assert source_capture.is_available(
        _BASE_TIME + timedelta(seconds=3), _BASE_TIME + timedelta(minutes=30)
    )


def test_source_capture_requires_source_timestamp_and_knowledge_cutoff() -> None:
    """Require source capture metadata and prevent knowledge before that capture."""
    with pytest.raises((TypeError, ValueError), match="ts_source_received"):
        _event(knowledge_basis="source_capture")

    with pytest.raises((TypeError, ValueError), match="ts_knowledge"):
        _event(
            knowledge_basis="source_capture",
            ts_source_received=_BASE_TIME + timedelta(seconds=3),
            ts_knowledge=_BASE_TIME + timedelta(seconds=2),
        )


def test_future_reference_event_can_have_current_validity() -> None:
    """Do not require event time to lie inside the business-validity interval."""
    event = _event(
        ts_event=_BASE_TIME + timedelta(days=30),
        valid_from=_BASE_TIME,
        valid_to=_BASE_TIME + timedelta(days=1),
    )

    assert event.is_available(_BASE_TIME + timedelta(seconds=2), _BASE_TIME)


def test_availability_uses_knowledge_cutoff_and_half_open_validity() -> None:
    """Apply inclusive knowledge and valid-start boundaries and exclusive valid-end."""
    event = _event()
    knowledge_time = _BASE_TIME + timedelta(seconds=2)
    valid_end = _BASE_TIME + timedelta(hours=1)

    assert event.is_available(knowledge_time, _BASE_TIME)
    assert not event.is_available(knowledge_time - timedelta(microseconds=1), _BASE_TIME)
    assert event.is_available(knowledge_time, valid_end - timedelta(microseconds=1))
    assert not event.is_available(knowledge_time, valid_end)


def test_repeated_timestamp_ordering_is_deterministic() -> None:
    """Order equal-knowledge revisions by sequence, revision, then digest."""
    events = [
        _event(source_sequence=2, source_revision=0, source_digest=_DIGEST_A),
        _event(source_sequence=1, source_revision=1, source_digest=_DIGEST_A),
        _event(source_sequence=1, source_revision=0, source_digest=_DIGEST_B),
        _event(source_sequence=1, source_revision=0, source_digest=_DIGEST_A),
    ]

    ordered = sorted(events, key=_ordering_key)
    assert [
        (event.source_sequence, event.source_revision, event.source_digest) for event in ordered
    ] == [
        (1, 0, _DIGEST_A),
        (1, 0, _DIGEST_B),
        (1, 1, _DIGEST_A),
        (2, 0, _DIGEST_A),
    ]


def _ordering_key(event: EventProvenance) -> tuple[datetime, int, int, str]:
    """Return an event's typed deterministic ordering key for sorting."""
    return event.ordering_key


@pytest.mark.parametrize("digest", ("A" * 64, "0" * 63, "g" * 64, ""))
def test_invalid_digest_is_rejected(digest: str) -> None:
    """Require exactly 64 lowercase hexadecimal digest characters."""
    with pytest.raises((TypeError, ValueError), match="source_digest"):
        _event(source_digest=digest)


@pytest.mark.parametrize("field_name", ("source_revision", "source_sequence"))
def test_negative_revision_and_sequence_are_rejected(field_name: str) -> None:
    """Require nonnegative source revision and sequence numbers."""
    with pytest.raises((TypeError, ValueError), match=field_name):
        _event(**{field_name: -1})


def test_schema_version_is_fixed() -> None:
    """Reject an unsupported serialized schema version."""
    event = _event()
    msgspec.structs.force_setattr(event, "schema_version", "2")
    with pytest.raises(ValueError, match="schema_version"):
        event.validate()


def test_temporal_ordering_is_validated() -> None:
    """Reject reversed local times, empty validity, and early observed knowledge."""
    with pytest.raises((TypeError, ValueError), match="ts_received"):
        _event(
            ts_received=_BASE_TIME + timedelta(seconds=3),
            ts_ingested=_BASE_TIME + timedelta(seconds=2),
        )
    with pytest.raises((TypeError, ValueError), match="valid_to"):
        _event(valid_to=_BASE_TIME)
    with pytest.raises((TypeError, ValueError), match="ts_knowledge"):
        _event(ts_knowledge=_BASE_TIME + timedelta(seconds=1))


def test_consuming_methods_revalidate_unsafe_copies() -> None:
    """Reject invalid values inserted through msgspec's unsafe mutation hook."""
    event = _event()
    unsafe_copy = msgspec.structs.replace(event)
    msgspec.structs.force_setattr(unsafe_copy, "source_digest", "invalid")

    with pytest.raises(ValueError, match="source_digest"):
        unsafe_copy.validate()
    with pytest.raises(ValueError, match="source_digest"):
        _ = unsafe_copy.ordering_key
    with pytest.raises(ValueError, match="source_digest"):
        unsafe_copy.is_available(_BASE_TIME + timedelta(seconds=2), _BASE_TIME)


def test_struct_is_immutable() -> None:
    """Reject assignment after a provenance value has been constructed."""
    event = _event()

    with pytest.raises(AttributeError):
        event.source_sequence = 1  # type: ignore[misc]  # [owner=platform; rationale=exercise frozen-field runtime rejection at the original assignment; expires=2027-03-01]
