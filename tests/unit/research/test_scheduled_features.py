"""Reconcile scheduled frozen features against independent clock and exact-value examples."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace
from test_features import TestPriceDiagnostics as _Prices

# project library imports
from financial_units import Currency, Dimension, ExactRatio, Price, QuantityKind
from market_data.contracts import Occurrence
from market_data.query import QueryReader
from market_data.validation import Correction, TradeRevision
from research.features import (
    CompletedReturn,
    ScheduledFeatureCheckpoint,
    ScheduledFeatures,
    ScheduledFeatureSpec,
)
from serialization import DomainCodec


class TestScheduledFeatures:
    """Exercise batch admission, frozen corrections, restart and independent instance state."""

    @staticmethod
    def _definition(instrument: int = 0) -> ScheduledFeatureSpec:
        """Use explicit spot units and a three-close synthetic schedule."""
        request = _Prices._request(instrument)
        return ScheduledFeatureSpec(
            instance=f"scheduled-{instrument}",
            binding=_Prices._binding(request),
            tick=Price(
                value=Decimal("0.01"),
                currency=request.instrument.quote_currency,
                per=Dimension(
                    instrument_id=request.instrument.instrument_id, kind=QuantityKind.BASE_UNIT
                ),
            ),
            start=request.start,
            end=request.start + timedelta(seconds=40),
            cadence_seconds=10,
            max_age_seconds=5,
        )

    @staticmethod
    def _reader(instrument: int = 0, *, correction_at: int = 25) -> QueryReader:
        """Retain a price revision which becomes knowable after its original frozen close."""
        request = _Prices._request(instrument)
        first = _Prices._item(request, 9, 9, "100.03", 1, 0)
        second = _Prices._item(request, 19, 19, "100.04", 2, 1)
        revision = _Prices._item(request, 19, 19, "999", 2, 2)
        correction = Correction(
            supersedes=TradeRevision(occurrences=(second,)).identity,
            replacement=TradeRevision(occurrences=(revision,)).identity,
            ts_published=request.start + timedelta(seconds=correction_at),
            ts_available=request.start + timedelta(seconds=correction_at),
            evidence_reference="synthetic:scheduled-correction",
        )
        third = _Prices._item(request, 29, 29, "101", 3, 3)
        return _Prices._reader(request, (first, second, revision, third), (correction,))

    def test_exact_frozen_correction_and_serialized_restart(self) -> None:
        """Keep 1/10003 and 24/2501 after a late revision under a tiny Decimal context."""
        codec = DomainCodec()
        for instrument in (0, 1):
            definition, reader = self._definition(instrument), self._reader(instrument)
            running = ScheduledFeatures(reader, definition, batch_size=1)
            with localcontext() as context:
                context.prec = 2
                first = running.evaluate(definition.start + timedelta(seconds=10))
                second = running.evaluate(definition.start + timedelta(seconds=20))
                assert first.value is None and first.observation.reason == "valid"
                assert second.value == ExactRatio(numerator="1", denominator="10003")
                state = codec.decode_json(
                    codec.encode_json(running.checkpoint), ScheduledFeatureCheckpoint
                )
                restarted = ScheduledFeatures(reader, definition, checkpoint=state, batch_size=9)
                third = restarted.evaluate(definition.start + timedelta(seconds=30))
                assert third.value == ExactRatio.from_fraction(Fraction(24, 2501))
                assert running.evaluate(third.observation.closed_at) == third
                assert restarted.checkpoint == running.checkpoint
                assert restarted.checkpoint.values[1] == second
            other = ScheduledFeatures(reader, replace(definition, instance="independent"))
            assert other.checkpoint.values == ()

    def test_equal_clock_correction_is_available_but_later_revision_is_not(self) -> None:
        """Admit inclusive knowledge at the close while preserving the half-open event window."""
        definition = self._definition()
        known = ScheduledFeatures(self._reader(correction_at=20), definition)
        late = ScheduledFeatures(self._reader(correction_at=21), definition)
        for batch in (known, late):
            batch.evaluate(definition.start + timedelta(seconds=10))
        assert known.evaluate(
            definition.start + timedelta(seconds=20)
        ).value == ExactRatio.from_fraction(Fraction(89897, 10003))
        assert late.evaluate(definition.start + timedelta(seconds=20)).value == ExactRatio(
            numerator="1", denominator="10003"
        )

    def test_gap_missing_stale_ties_and_recovery(self) -> None:
        """Keep explicit missingness and recover only after fresh adjacent complete windows."""
        request, definition = _Prices._request(), self._definition()
        rows: tuple[Occurrence, ...] = (
            _Prices._item(request, 1, 1, "100", 1, 0),
            _Prices._item(request, 19, 19, "110", 2, 1),
            _Prices._item(request, 19, 19, "120", 3, 2),
            _Prices._item(request, 20, 20, "0", 4, 3, disconnect=True),
            _Prices._item(request, 29, 29, "130", 5, 4),
            _Prices._item(request, 39, 39, "140", 6, 5),
            _Prices._item(request, 49, 49, "154", 7, 6),
        )
        definition = replace(definition, end=request.start + timedelta(seconds=60))
        batch = ScheduledFeatures(_Prices._reader(request, rows), definition)
        values = tuple(
            batch.evaluate(request.start + timedelta(seconds=i)) for i in (10, 20, 30, 40, 50)
        )
        assert tuple(v.observation.reason for v in values) == (
            "stale",
            "valid",
            "known_gap",
            "valid",
            "valid",
        )
        assert values[1].observation.point is not None
        assert values[1].observation.point.price.value == Decimal("120")
        assert values[1].has_current_gap and values[1].value is None
        assert all(v.value is None for v in values[:4])
        assert values[4].value == ExactRatio(numerator="1", denominator="10")
        missing = ScheduledFeatures(_Prices._reader(request, rows[1:]), definition)
        assert (
            missing.evaluate(request.start + timedelta(seconds=10)).observation.reason == "missing"
        )

    def test_schedule_compatibility_and_failure_atomicity(self) -> None:
        """Refuse skipped/repeated closes and altered state without advancing a prior checkpoint."""
        codec = DomainCodec()
        definition, reader = self._definition(), self._reader()
        batch = ScheduledFeatures(reader, definition)
        batch.evaluate(definition.start + timedelta(seconds=10))
        before = batch.checkpoint
        for second in (10, 30, 40):
            with pytest.raises(ValueError, match="next close"):
                batch.evaluate(definition.start + timedelta(seconds=second))
        with patch.object(QueryReader, "batches", side_effect=ValueError("source failure")):
            with pytest.raises(ValueError, match="source failure"):
                batch.evaluate(definition.start + timedelta(seconds=20))
        assert before == batch.checkpoint
        for changed in (
            replace(definition, instance="other"),
            replace(definition, max_age_seconds=4),
            replace(definition, cadence_seconds=20),
        ):
            with pytest.raises(ValueError, match="definition or source changed"):
                ScheduledFeatures(reader, changed, checkpoint=before)
        with pytest.raises(ValueError, match="definition or source changed"):
            ScheduledFeatures(self._reader(correction_at=24), definition, checkpoint=before)
        with pytest.raises(ValueError, match="digest"):
            replace(before, values_sha256="0" * 64)
        malformed = codec.decode_json(codec.encode_json(before), ScheduledFeatureCheckpoint)
        force_setattr(malformed, "schema_version", "future-version")
        with pytest.raises(ValueError, match="version"):
            ScheduledFeatures(reader, definition, checkpoint=malformed)
        inconsistent = replace(before.values[0], value=ExactRatio(numerator="0", denominator="1"))
        values = (inconsistent,)
        with pytest.raises(ValueError, match="frozen endpoints"):
            replace(
                before,
                values=values,
                values_sha256=hashlib.sha256(codec.encode_json(values)).hexdigest(),
            )

    def test_nonadjacent_and_wrong_unit_formula_inputs(self) -> None:
        """Keep a missing return for nonadjacent closes and reject cross-instrument arithmetic."""
        values = []
        for instrument in (0, 1):
            batch = ScheduledFeatures(self._reader(instrument), self._definition(instrument))
            values.append(
                batch.evaluate(batch.definition.start + timedelta(seconds=10)).observation
            )
        current = replace(values[0], closed_at=values[0].closed_at + timedelta(seconds=20))
        assert CompletedReturn(10).evaluate(values[0], current) is None
        current = replace(values[1], closed_at=values[1].closed_at + timedelta(seconds=10))
        with pytest.raises(ValueError, match="units differ"):
            CompletedReturn(10).evaluate(values[0], current)

    def test_source_quote_and_spot_dimension_cannot_be_reinterpreted(self) -> None:
        """Refuse quote-currency and quantity-kind mismatches before committing a close."""
        definition, reader = self._definition(), self._reader()
        quote = replace(
            definition,
            tick=definition.tick.model_copy(update={"currency": Currency.from_code("USD")}),
        )
        batch = ScheduledFeatures(reader, quote)
        before = batch.checkpoint
        with pytest.raises(ValueError, match="quote currency"):
            batch.evaluate(definition.start + timedelta(seconds=10))
        assert batch.checkpoint == before
        with pytest.raises(ValueError, match="binding or units"):
            replace(
                definition,
                tick=definition.tick.model_copy(
                    update={
                        "per": definition.tick.per.model_copy(
                            update={"kind": QuantityKind.CONTRACT}
                        )
                    }
                ),
            )
