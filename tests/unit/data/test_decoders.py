"""Test the shared immutable decode context contract."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256

# third party library imports
import pytest

# project library imports
from market_data.contracts import DecodeContext


class TestDecodeContext:
    """Normalize receipt times and hash raw lines in the decode context."""

    def test_decode_context_normalizes_receipt_times_and_hashes_raw_line(self) -> None:
        """Normalize aware times and derive stable provenance from the raw line."""
        raw_line = '2024-06-01T00:00:00Z {"value":1}'
        context = DecodeContext(
            capture_text="2024-06-01T00:00:00Z",
            capture_time=datetime(2024, 6, 1, 8, tzinfo=timezone(timedelta(hours=8))),
            raw_line=raw_line,
            source_sequence=2,
            local_received=datetime(2024, 6, 2, 8, tzinfo=timezone(timedelta(hours=8))),
            local_ingested=datetime(2024, 6, 2, 8, 0, 1, tzinfo=timezone(timedelta(hours=8))),
            source_digest=None,
            source_id="source.test",
        )

        provenance = context.provenance(
            event_time=datetime(2024, 6, 1, 0, 0, 1, tzinfo=UTC),
            event_id_suffix="event:1",
        )

        assert context.capture_time == datetime(2024, 6, 1, tzinfo=UTC)
        assert context.local_received == datetime(2024, 6, 2, tzinfo=UTC)
        assert provenance.source_digest == sha256(raw_line.encode()).hexdigest()
        assert provenance.valid_to == provenance.valid_from + timedelta(microseconds=1)

    def test_decode_context_rejects_invalid_source_digest(self) -> None:
        """Reject source digests that cannot identify a SHA-256 object."""
        with pytest.raises(ValueError, match="lowercase SHA-256 digest"):
            DecodeContext(
                capture_text="2024-06-01T00:00:00Z",
                capture_time=datetime(2024, 6, 1, tzinfo=UTC),
                raw_line="2024-06-01T00:00:00Z {}",
                source_sequence=0,
                local_received=datetime(2024, 6, 1, tzinfo=UTC),
                local_ingested=None,
                source_digest="not-a-digest",
                source_id="source.test",
            )
