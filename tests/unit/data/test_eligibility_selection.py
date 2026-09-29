"""Protect bitemporal membership and explicit, append-only listing corrections."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

# third party library imports
import msgspec
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import EligibilityAssertion, EligibilityAssertions
from reference_data.instruments import InstrumentId
from serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_START = datetime(2024, 6, 1, tzinfo=UTC)
_TICK = timedelta(microseconds=1)


class TestEligibilitySelection:
    """Exercise selection through retained serialized history and unsafe boundaries."""

    @staticmethod
    def _history() -> EligibilityAssertions:
        """Read the explicit synthetic correction scenario against its authored catalog."""
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        return EligibilityAssertions.read(
            _ROOT / "tests/fixtures/eligibility/membership-corrections.json", catalog=catalog
        )

    def test_future_corrections_preserve_earlier_universe_and_exact_round_trip(self) -> None:
        """Compare the actual selector before and after appending future information."""
        history = self._history()
        original, _, _, correction = history.assertions
        before = replace(history, assertions=history.assertions[:-1])
        before_bytes = _CODEC.encode_json(before)
        rebuilt = before.append(correction)
        assert rebuilt == history and _CODEC.encode_json(before) == before_bytes
        assert _CODEC.decode_json(_CODEC.encode_json(rebuilt), EligibilityAssertions) == rebuilt
        reordered = replace(history, assertions=history.assertions[::-1])
        for valid_at in (original.valid_from, correction.valid_from, original.valid_to - _TICK):
            for known_at in (_START - _TICK, _START, correction.ts_knowledge - _TICK):
                for member in history.catalog.instruments:
                    expected = before.select(
                        member.instrument_id, valid_at=valid_at, known_at=known_at
                    )
                    assert (
                        rebuilt.select(member.instrument_id, valid_at=valid_at, known_at=known_at)
                        == expected
                    )
                    assert (
                        reordered.select(member.instrument_id, valid_at=valid_at, known_at=known_at)
                        == expected
                    )
        with pytest.raises(AttributeError):
            setattr(original, "state", "excluded")

    def test_explicit_wire_fields_and_numbered_schema_rejection(self) -> None:
        """Encode every field explicitly and refuse any other eligibility schema."""
        history = self._history()
        path = _ROOT / "tests/fixtures/eligibility/assumptions-and-membership.json"
        membership = EligibilityAssertions.read(path, catalog=history.catalog)
        assert b'"supersedes":null' in _CODEC.encode_json(membership)
        payload = _CODEC.encode_json(history)
        assert payload.endswith(b',"schema_version":"1"}')
        with pytest.raises(ValueError, match="unsupported eligibility schema"):
            _CODEC.decode_json(
                payload.removesuffix(b',"schema_version":"1"}') + b',"schema_version":"2"}',
                EligibilityAssertions,
            )

    @pytest.mark.parametrize("offset", (-1, 0))
    def test_knowledge_boundary_is_inclusive(self, offset: int) -> None:
        """Expose the old or corrected assertion exactly at the decision cutoff."""
        history = self._history()
        original, _, _, correction = history.assertions
        assert history.select(
            original.instrument_id,
            valid_at=correction.valid_from,
            known_at=correction.ts_knowledge + offset * _TICK,
        ) == (original if offset < 0 else correction)
        assert history.select(
            original.instrument_id,
            valid_at=original.valid_from,
            known_at=original.ts_knowledge + offset * _TICK,
        ) == ("unknown" if offset < 0 else original)

    @pytest.mark.parametrize(
        ("boundary", "offset", "is_selected"),
        [
            ("valid_from", -1, False),
            ("valid_from", 0, True),
            ("valid_to", -1, True),
            ("valid_to", 0, False),
        ],
    )
    def test_corrected_validity_is_half_open_without_predecessor_fallback(
        self, boundary: str, offset: int, is_selected: bool
    ) -> None:
        """Withdraw the entire predecessor, including dates removed by a listing correction."""
        history = self._history()
        correction = history.assertions[-1]
        instant = correction.valid_from if boundary == "valid_from" else correction.valid_to
        assert history.select(
            correction.instrument_id,
            valid_at=instant + offset * _TICK,
            known_at=correction.ts_knowledge,
        ) == (correction if is_selected else "unknown")

    def test_unknown_unsupported_assumptions_and_exclusions_remain_distinct(self) -> None:
        """Never infer inclusion from catalog presence, late assumptions or missing history."""
        history = self._history()
        member = history.catalog.instruments[0].instrument_id
        missing = InstrumentId.from_canonical_text("33333333-3333-4333-8333-333333333333")
        assert history.select(missing, valid_at=_START, known_at=_START) == "unsupported"
        assert (
            replace(history, assertions=()).select(member, valid_at=_START, known_at=_START)
            == "unknown"
        )
        authored = EligibilityAssertions.read(
            _ROOT / "tests/fixtures/eligibility/assumptions-and-membership.json",
            catalog=history.catalog,
        ).assertions[0]
        assert (
            replace(history, assertions=(authored,)).select(
                member, valid_at=_START, known_at=_START
            )
            == "unknown"
        )
        excluded = history.assertions[2]
        assert (
            history.select(excluded.instrument_id, valid_at=excluded.valid_from, known_at=_START)
            == excluded
        )
        assert (
            history.select(
                excluded.instrument_id,
                valid_at=history.catalog.instruments[1].valid_to,
                known_at=_START,
            )
            == excluded
        )

    def test_correction_chain_can_restore_membership_without_rewriting_history(self) -> None:
        """Keep two earlier decisions stable when a third evidenced version is appended."""
        history = self._history()
        original, _, _, correction = history.assertions
        restored = replace(
            original,
            ts_knowledge=correction.ts_knowledge + timedelta(hours=1),
            supersedes=correction.identity,
            evidence=replace(correction.evidence, identity="synthetic:mr12:restored"),
        )
        latest = history.append(restored)
        for cutoff, expected in (
            (original.ts_knowledge, original),
            (correction.ts_knowledge, correction),
            (restored.ts_knowledge, restored),
        ):
            assert (
                latest.select(
                    original.instrument_id, valid_at=correction.valid_from, known_at=cutoff
                )
                == expected
            )
        assert history.assertions[-1] == correction

    @pytest.mark.parametrize(
        "defect",
        (
            "dangling",
            "same-time",
            "same-evidence",
            "other-member",
            "branch",
            "unlinked",
            "removed-parent",
        ),
    )
    def test_invalid_corrections_fail_in_construction_and_decoding(self, defect: str) -> None:
        """Reject ambiguous, unevidenced and incomplete replacement histories as a whole."""
        history = self._history()
        original, included, excluded, correction = history.assertions
        assertions = history.assertions
        if defect == "dangling":
            assertions = (*assertions[:-1], replace(correction, supersedes="0" * 64))
        elif defect == "same-time":
            assertions = (
                *assertions[:-1],
                replace(
                    correction,
                    ts_knowledge=_START,
                    evidence=replace(correction.evidence, available_at=_START),
                ),
            )
        elif defect == "same-evidence":
            assertions = (*assertions[:-1], replace(correction, evidence=original.evidence))
        elif defect == "other-member":
            assertions = (
                *assertions[:-1],
                replace(correction, instrument_id=included.instrument_id),
            )
        elif defect == "branch":
            assertions = (*assertions, replace(correction, reason="Another branch"))
        elif defect == "unlinked":
            assertions = (*assertions[:-1], replace(correction, supersedes=None))
        elif defect == "removed-parent":
            assertions = (included, excluded, correction)
        with pytest.raises(ValueError):
            replace(history, assertions=assertions)
        force_setattr(history, "assertions", assertions)
        with pytest.raises(msgspec.ValidationError):
            _CODEC.decode_json(_CODEC.encode_json(history), EligibilityAssertions)
        with pytest.raises(ValueError):
            history.select(original.instrument_id, valid_at=_START, known_at=_START)

    @pytest.mark.parametrize("link", ("", "A" * 64, "g" * 64, True))
    def test_invalid_link_is_rejected_at_assertion_boundary(self, link: object) -> None:
        """Retain strict hash syntax in both direct construction and cached decoding."""
        correction = self._history().assertions[-1]
        with pytest.raises(ValueError, match="SHA-256"):
            replace(correction, supersedes=link)
        force_setattr(correction, "supersedes", link)
        with pytest.raises(msgspec.ValidationError):
            _CODEC.decode_json(_CODEC.encode_json(correction), EligibilityAssertion)

    @pytest.mark.parametrize(
        ("field", "instant"),
        [
            ("valid_at", datetime(2024, 6, 1)),
            ("known_at", datetime(2024, 6, 1, tzinfo=timezone(timedelta(hours=8)))),
        ],
    )
    def test_invalid_query_clocks_fail_and_recover(self, field: str, instant: datetime) -> None:
        """Reject ambiguous clocks without retaining selection state after failure."""
        history = self._history()
        original = history.assertions[0]
        clocks = {"valid_at": _START, "known_at": _START, field: instant}
        with pytest.raises((TypeError, ValueError)):
            history.select(original.instrument_id, **clocks)
        assert history.select(original.instrument_id, valid_at=_START, known_at=_START) == original

    def test_agreement_ties_have_stable_identity_order_and_unsafe_history_fails(self) -> None:
        """Choose deterministic evidence without silently tolerating mutated input objects."""
        history = self._history()
        original = history.assertions[0]
        alternate = replace(original, reason="Independent agreeing assertion")
        expected = original if original.identity > alternate.identity else alternate
        for assertions in ((original, alternate), (alternate, original)):
            assert (
                replace(history, assertions=assertions).select(
                    original.instrument_id, valid_at=_START, known_at=_START
                )
                == expected
            )
        force_setattr(original.evidence, "identity", "")
        with pytest.raises(ValueError, match="evidence identity"):
            history.select(original.instrument_id, valid_at=_START, known_at=_START)
