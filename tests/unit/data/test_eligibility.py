"""Protect evidence-backed eligibility reading without introducing an as-of selector."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# third party library imports
import msgspec
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from alpha_research.data.eligibility import (
    EligibilityAssertion,
    EligibilityAssertions,
    EligibilityEvidence,
)
from alpha_research.financial_units import Currency
from alpha_research.instrument_identity import InstrumentId
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_FIXTURE = _ROOT / "tests/fixtures/mr11/eligibility.json"
_CODEC = DomainCodec()
_START = datetime(2024, 6, 1, tzinfo=UTC)


class _Fixture:
    """Load retained synthetic history and make invalid boundary inputs."""

    @staticmethod
    def catalog() -> CatalogSnapshot:
        """Read the unchanged archive-bound authored catalog."""
        return _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )

    @staticmethod
    def history() -> EligibilityAssertions:
        """Read the file through the public catalog-linked boundary."""
        return EligibilityAssertions.read(_FIXTURE, catalog=_Fixture.catalog())


def test_read_preserves_assumption_evidence_units_and_delisted_members() -> None:
    """Separate historical validity from evidenced knowledge and keep every exclusion."""
    catalog = _Fixture.catalog()
    original = _CODEC.encode_json(catalog)
    history = EligibilityAssertions.read(_FIXTURE, catalog=catalog)
    assumption, evidenced, included, excluded = history.assertions
    assert assumption.valid_from == evidenced.valid_from == _START
    assert assumption.ts_knowledge == datetime(2026, 9, 16, tzinfo=UTC)
    assert evidenced.ts_knowledge == _START
    assert assumption.evidence.basis == "research_assumption"
    assert evidenced.evidence.basis == "synthetic"
    assert included.instrument_id == excluded.instrument_id
    assert included.valid_to == excluded.valid_from
    assert excluded.state == "excluded" and "delisting" in excluded.reason
    assert excluded.valid_to > catalog.instruments[1].valid_to
    assert history.catalog.instruments[0].quote_currency == Currency.from_code("USDT")
    assert _CODEC.encode_json(catalog) == original == _CODEC.encode_json(history.catalog)
    assert _CODEC.decode_json(_CODEC.encode_json(history), EligibilityAssertions) == history
    assert EligibilityAssertions.read(_FIXTURE, catalog=catalog) == history
    with pytest.raises(AttributeError):
        setattr(evidenced, "state", "excluded")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("identity", "", "evidence identity"),
        ("identity", " padded ", "whitespace"),
        ("identity", "line\nbreak", "printable"),
        ("identity", "x" * 257, "256"),
        ("basis", "invented", "basis"),
        ("recorded_at", datetime(2026, 9, 16), "timezone-aware"),
        ("available_at", datetime(2024, 6, 1, tzinfo=timezone(timedelta(hours=8))), "UTC"),
        ("available_at", datetime(2027, 1, 1, tzinfo=UTC), "follow its recording"),
    ],
)
def test_evidence_rejects_invalid_fields(field: str, value: object, message: str) -> None:
    """Reject unsafe evidence through both direct construction and strict decoding."""
    evidence = _Fixture.history().assertions[1].evidence
    with pytest.raises((TypeError, ValueError), match=message):
        replace(evidence, **{field: value})
    force_setattr(evidence, field, value)
    with pytest.raises(msgspec.ValidationError):
        _CODEC.decode_json(_CODEC.encode_json(evidence), EligibilityEvidence)


def test_assumption_cannot_be_backdated_or_relabel_catalog() -> None:
    """Reject knowledge before evidence and preserve the authored catalog's meaning."""
    history = _Fixture.history()
    assumption = history.assertions[0]
    with pytest.raises(ValueError, match="authored recording"):
        replace(assumption.evidence, available_at=_START)
    with pytest.raises(ValueError, match="precede evidenced"):
        replace(assumption, ts_knowledge=_START)
    # Separate attested source evidence may predate its later recording; the
    # synthetic unit fixture does not authenticate an actual historical source.
    source = replace(history.assertions[1].evidence, basis="source_evidence")
    assert source.available_at < source.recorded_at
    assert all(item.metadata_basis == "research_assumption" for item in history.catalog.instruments)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("instrument_id", "BTCUSDT", "canonical"),
        ("state", True, "state"),
        ("state", "unknown", "state"),
        ("reason", "", "reason"),
        ("evidence", None, "EligibilityEvidence"),
        ("valid_from", _START + timedelta(days=1), "nonempty"),
        ("valid_to", _START - timedelta(seconds=1), "nonempty"),
        ("ts_knowledge", _START - timedelta(microseconds=1), "precede evidenced"),
        ("ts_knowledge", datetime(2024, 6, 1), "timezone-aware"),
    ],
)
def test_assertion_rejects_invalid_fields(field: str, value: object, message: str) -> None:
    """Protect explicit construction and decoding against malformed membership."""
    assertion = _Fixture.history().assertions[1]
    with pytest.raises((TypeError, ValueError), match=message):
        replace(assertion, **{field: value})
    force_setattr(assertion, field, value)
    with pytest.raises(msgspec.ValidationError):
        _CODEC.decode_json(_CODEC.encode_json(assertion), EligibilityAssertion)


def test_overlaps_are_checked_across_all_retained_assertions() -> None:
    """Reject contradictions even across different knowledge times and nested intervals."""
    history = _Fixture.history()
    original = history.assertions[1]
    contrary = replace(
        original,
        state="excluded",
        valid_from=_START + timedelta(hours=1),
        valid_to=_START + timedelta(hours=2),
        ts_knowledge=_START + timedelta(days=2),
    )
    for assertions in ((original, contrary), (contrary, original)):
        with pytest.raises(ValueError, match="contradictory eligibility overlap"):
            replace(history, assertions=assertions)
    same_state = replace(original, valid_to=_START + timedelta(minutes=1))
    adjacent = replace(
        contrary, valid_from=original.valid_to, valid_to=original.valid_to + timedelta(days=1)
    )
    assert replace(history, assertions=(original, same_state, adjacent)).assertions[-1] == adjacent
    assert replace(history, assertions=()).assertions == ()


def test_evidence_identity_cannot_hide_changed_dates_or_basis() -> None:
    """Reject two incompatible descriptions under one retained evidence identity."""
    history = _Fixture.history()
    assertion = history.assertions[1]
    changed = replace(assertion, evidence=replace(assertion.evidence, basis="source_evidence"))
    with pytest.raises(ValueError, match="conflicting metadata"):
        replace(history, assertions=(assertion, changed))


def test_catalog_linkage_rejects_unknown_ids_and_changed_units(tmp_path: Path) -> None:
    """Bind the complete selected catalog, including exact unit grids and authored meaning."""
    history = _Fixture.history()
    unknown = replace(
        history.assertions[0],
        instrument_id=InstrumentId.from_canonical_text("33333333-3333-4333-8333-333333333333"),
    )
    with pytest.raises(ValueError, match="absent from the selected catalog"):
        replace(history, assertions=(unknown,))
    first, second = history.catalog.instruments
    for changed_catalog in (
        replace(history.catalog, evidence="Changed authored meaning"),
        replace(history.catalog, instruments=(replace(first, price_tick=Decimal("0.02")), second)),
        replace(
            history.catalog,
            instruments=(
                replace(first, quote_currency=Currency(code="USDT", minor_unit=Decimal("0.01"))),
                second,
            ),
        ),
    ):
        with pytest.raises(ValueError, match="selected catalog/units"):
            EligibilityAssertions.read(_FIXTURE, catalog=changed_catalog)
    bad = tmp_path / "unsafe.json"
    force_setattr(first, "price_tick", Decimal("NaN"))
    with pytest.raises(ValueError, match="finite and positive"):
        EligibilityAssertions(catalog=history.catalog, assertions=history.assertions)
    bad.write_bytes(_CODEC.encode_json(history))
    with pytest.raises(msgspec.ValidationError):
        EligibilityAssertions.read(bad, catalog=_Fixture.catalog())


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b"null",
        b"{",
        b'{"schema_version":"2"}',
        _FIXTURE.read_bytes().replace(
            b'"state": "included"', b'"state": "included", "extra": true', 1
        ),
        _FIXTURE.read_bytes().replace(
            b'"basis": "synthetic"', b'"basis": "synthetic", "extra": true', 1
        ),
        _FIXTURE.read_bytes().replace(
            b'"schema_version": "1"', b'"schema_version": "1", "extra": true', 1
        ),
        b" " * 1_048_577,
    ],
    ids=[
        "missing",
        "null",
        "malformed",
        "version",
        "assertion-extra",
        "evidence-extra",
        "file-extra",
        "oversize",
    ],
)
def test_file_failures_do_not_poison_subsequent_reads(tmp_path: Path, payload: bytes) -> None:
    """Reject the entire invalid file then read a valid file with the same cached codec."""
    path = tmp_path / "eligibility.json"
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        EligibilityAssertions.read(path, catalog=_Fixture.catalog())
    path.write_bytes(_FIXTURE.read_bytes())
    assert len(EligibilityAssertions.read(path, catalog=_Fixture.catalog()).assertions) == 4


def test_missing_file_and_unsafe_nested_records_fail(tmp_path: Path) -> None:
    """Reject absent files and unsafe copies at the owning immutable boundary."""
    with pytest.raises(FileNotFoundError):
        EligibilityAssertions.read(tmp_path / "absent", catalog=_Fixture.catalog())
    history = _Fixture.history()
    force_setattr(history.assertions[0].evidence, "available_at", _START)
    with pytest.raises(ValueError, match="authored recording"):
        replace(history)
