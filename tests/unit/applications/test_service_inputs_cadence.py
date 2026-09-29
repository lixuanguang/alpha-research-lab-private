"""Keep the selected book cadence in deployed feature identity."""

from __future__ import annotations

# standard library imports
import hashlib

# third party library imports
import pytest

# project library imports
from applications.execute.service_inputs import ServiceBookInputs
from serialization import DomainCodec


def test_zero_cadence_is_part_of_feature_identity() -> None:
    """Admitting every book is an explicit cadence bound into the definition digest."""
    every_book = ServiceBookInputs(("first",), 30_000_000, 0)
    assert (
        every_book.identity
        == hashlib.sha256(
            DomainCodec().encode_json(
                ("service-book-features-v1", ServiceBookInputs.fields, 30_000_000, 0)
            )
        ).hexdigest()
    )
    assert ServiceBookInputs((), 30_000_000, 0).identity == every_book.identity


def test_nonzero_cadence_changes_identity_without_consumer_selection() -> None:
    """An installed policy cannot silently change how often books admit effects."""
    first = ServiceBookInputs(("first",), 30_000_000, 3_000_000)
    another_cohort = ServiceBookInputs(("second",), 30_000_000, 3_000_000)
    faster = ServiceBookInputs(("first",), 30_000_000, 1_000_000)
    assert first.identity == another_cohort.identity
    assert first.identity != faster.identity
    assert first.identity != ServiceBookInputs(("first",), 30_000_000, 0).identity
    for interval in (-1, 30_000_001):
        with pytest.raises(ValueError, match="market interval"):
            ServiceBookInputs((), 30_000_000, interval)
