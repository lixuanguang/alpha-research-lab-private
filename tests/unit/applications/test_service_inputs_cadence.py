"""Keep the selected book cadence in deployed feature identity."""

from __future__ import annotations

# standard library imports
import hashlib

# third party library imports
import pytest

# project library imports
from applications.execute.service_inputs import ServiceBookInputs
from serialization import DomainCodec


def test_legacy_zero_cadence_keeps_original_feature_identity() -> None:
    """Existing non-service callers retain their exact feature definition digest."""
    legacy = ServiceBookInputs(("first",), 30_000_000)
    original = hashlib.sha256(
        DomainCodec().encode_json(
            ("service-book-features-v1", ServiceBookInputs.fields, 30_000_000)
        )
    ).hexdigest()
    assert legacy.market_interval_us == 0
    assert legacy.identity == original
    assert ServiceBookInputs((), 30_000_000).identity == original


def test_nonzero_cadence_changes_identity_without_consumer_selection() -> None:
    """An installed policy cannot silently change how often books admit effects."""
    first = ServiceBookInputs(("first",), 30_000_000, 3_000_000)
    another_cohort = ServiceBookInputs(("second",), 30_000_000, 3_000_000)
    faster = ServiceBookInputs(("first",), 30_000_000, 1_000_000)
    assert first.identity == another_cohort.identity
    assert first.identity != faster.identity
    assert first.identity != ServiceBookInputs(("first",), 30_000_000).identity
    for interval in (-1, 30_000_001):
        with pytest.raises(ValueError, match="market interval"):
            ServiceBookInputs((), 30_000_000, interval)
