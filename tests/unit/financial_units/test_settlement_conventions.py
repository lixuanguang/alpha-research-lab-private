"""Bounded settlement adjustment, lag and calendar ownership contracts."""

from __future__ import annotations

# standard library imports
from collections.abc import Mapping
from datetime import date, datetime

# third party library imports
import pytest
from financial_unit_cases import FinancialUnitCases
from pydantic import ValidationError

# project library imports
from financial_units import BusinessDayConvention as BDC
from financial_units import (
    ConventionError,
    SettlementConventions,
    UnitError,
)
from reference_data.calendars import SettlementCalendar


class TestSettlementConventions:
    """Exercise bounded settlement adjustment, lag and calendar ownership contracts."""

    @pytest.mark.parametrize(
        ("convention", "candidate", "expected"),
        [
            (BDC.UNADJUSTED, date(2024, 8, 31), date(2024, 8, 31)),
            (BDC.FOLLOWING, date(2024, 8, 31), date(2024, 9, 3)),
            (BDC.MODIFIED_FOLLOWING, date(2024, 8, 31), date(2024, 8, 30)),
            (BDC.PRECEDING, date(2024, 9, 1), date(2024, 8, 30)),
            (BDC.MODIFIED_PRECEDING, date(2024, 9, 1), date(2024, 9, 3)),
        ],
    )
    def test_business_day_and_settlement_goldens(
        self, convention: BDC, candidate: date, expected: date
    ) -> None:
        """Match business-day adjustments and settlement lags across the holiday gap."""
        service = SettlementConventions(FinancialUnitCases.calendar())
        assert service.adjust_business_day(candidate, convention=convention) == expected
        assert (
            service.settlement_date(candidate, business_day_lag=0, convention=convention)
            == expected
        )
        expected_lagged = date(2024, 9, 4)
        assert (
            service.settlement_date(date(2024, 8, 30), business_day_lag=2, convention=BDC.FOLLOWING)
            == expected_lagged
        )

    @pytest.mark.parametrize("lag", [-1, 367, True, 1.0])
    def test_bad_settlement_lag_rejects(self, lag: object) -> None:
        """Reject out-of-range and non-integer lags through the settlement service."""
        service = SettlementConventions(FinancialUnitCases.calendar())
        with pytest.raises(ConventionError, match="lag"):
            service.settlement_date(
                date(2024, 8, 30),
                business_day_lag=lag,  # type: ignore[arg-type]  # [owner=platform; rationale=exercise typed settlement lag rejection; expires=2027-03-01]
                convention=BDC.FOLLOWING,
            )

    def test_calendar_coverage_and_unknown_conventions_fail_closed(self) -> None:
        """Reject uncovered dates, empty calendars and untyped convention strings."""
        service = SettlementConventions(FinancialUnitCases.calendar())
        for candidate in (date(2024, 8, 28), date(2024, 9, 6)):
            with pytest.raises(ConventionError, match="coverage"):
                service.adjust_business_day(candidate, convention=BDC.UNADJUSTED)
        with pytest.raises(ConventionError, match="coverage"):
            service.settlement_date(date(2024, 9, 5), business_day_lag=1, convention=BDC.FOLLOWING)
        calendar_update: dict[str, tuple[date, ...]] = {"settlement_dates": ()}
        empty = FinancialUnitCases.calendar().model_copy(update=calendar_update)
        with pytest.raises(ConventionError, match="coverage"):
            service_with_empty_calendar = SettlementConventions(empty)
            service_with_empty_calendar.adjust_business_day(
                date(2024, 8, 31), convention=BDC.FOLLOWING
            )
        with pytest.raises(UnitError):
            service.adjust_business_day(
                date(2024, 8, 31),
                convention="following",  # type: ignore[arg-type]  # [owner=platform; rationale=exercise typed convention rejection on SettlementConventions; expires=2027-03-01]
            )

    @pytest.mark.parametrize(
        ("candidate", "convention"),
        [
            (date(2024, 8, 28), BDC.MODIFIED_FOLLOWING),
            (date(2024, 9, 6), BDC.MODIFIED_PRECEDING),
        ],
    )
    def test_coverage_is_checked_before_modified_search(
        self, candidate: date, convention: BDC
    ) -> None:
        """Reject uncovered dates before a modified search can use the reverse direction."""
        service = SettlementConventions(FinancialUnitCases.calendar())
        with pytest.raises(ConventionError, match="coverage"):
            service.adjust_business_day(candidate, convention=convention)

    @pytest.mark.parametrize(
        ("candidate", "convention", "settlement_dates"),
        [
            (date(2024, 8, 31), BDC.FOLLOWING, (date(2024, 8, 30),)),
            (date(2024, 8, 31), BDC.MODIFIED_FOLLOWING, (date(2024, 8, 30),)),
            (date(2024, 8, 31), BDC.MODIFIED_FOLLOWING, (date(2024, 9, 3),)),
            (date(2024, 9, 1), BDC.PRECEDING, (date(2024, 9, 3),)),
            (date(2024, 9, 1), BDC.MODIFIED_PRECEDING, (date(2024, 9, 3),)),
            (date(2024, 9, 1), BDC.MODIFIED_PRECEDING, (date(2024, 8, 30),)),
        ],
    )
    def test_adjustment_stays_bounded_when_directional_date_is_missing(
        self,
        candidate: date,
        convention: BDC,
        settlement_dates: tuple[date, ...],
    ) -> None:
        """Reject missing primary or modified reverse dates within otherwise valid coverage."""
        calendar_update: dict[str, tuple[date, ...]] = {"settlement_dates": settlement_dates}
        bounded = FinancialUnitCases.calendar().model_copy(update=calendar_update)
        service = SettlementConventions(bounded)
        with pytest.raises(ConventionError, match="cannot determine"):
            service.adjust_business_day(candidate, convention=convention)

    @pytest.mark.parametrize(
        ("business_day_lag", "expected"),
        [
            (0, date(2024, 8, 31)),
            (1, date(2024, 9, 3)),
            (2, date(2024, 9, 4)),
        ],
    )
    def test_unadjusted_nonsettlement_anchor_counts_only_later_eligible_dates(
        self, business_day_lag: int, expected: date
    ) -> None:
        """Return an unadjusted anchor at zero lag and count later eligible dates thereafter."""
        service = SettlementConventions(FinancialUnitCases.calendar())
        trade_date = date(2024, 8, 31)
        assert service.adjust_business_day(trade_date, convention=BDC.UNADJUSTED) == trade_date
        assert (
            service.settlement_date(
                trade_date, business_day_lag=business_day_lag, convention=BDC.UNADJUSTED
            )
            == expected
        )

    @pytest.mark.parametrize("lag", [-1, 367])
    def test_constructor_validation_precedes_calls_and_lag_precedes_trade_date(
        self, lag: int
    ) -> None:
        """Validate calendars at construction, then reject lag before checking trade dates."""
        service = SettlementConventions(FinancialUnitCases.calendar())
        with pytest.raises(ConventionError, match="lag"):
            service.settlement_date(
                date(2024, 8, 28), business_day_lag=lag, convention=BDC.FOLLOWING
            )
        invalid_update: dict[str, tuple[date, ...]] = {
            "settlement_dates": (date(2024, 9, 3), date(2024, 8, 30))
        }
        invalid_calendar = FinancialUnitCases.calendar().model_copy(update=invalid_update)
        with pytest.raises(ConventionError, match="invalid settlement") as caught:
            SettlementConventions(invalid_calendar).settlement_date(
                date(2024, 8, 28), business_day_lag=lag, convention=BDC.FOLLOWING
            )
        assert isinstance(caught.value.__cause__, ValidationError)

    @pytest.mark.parametrize(
        ("candidate", "expected_message"),
        [
            (datetime(2024, 8, 31), "candidate must be date"),
            (date(2024, 8, 31), "business-day convention must be BusinessDayConvention"),
        ],
    )
    def test_calendar_construction_precedes_invalid_call_arguments(
        self, candidate: date, expected_message: str
    ) -> None:
        """Reject the calendar first, retaining candidate-before-convention method order."""
        invalid_update: Mapping[str, object] = {"settlement_dates": (date(2024, 1, 1),)}
        invalid = FinancialUnitCases.calendar().model_copy(update=invalid_update)
        with pytest.raises(ConventionError) as constructor_error:
            SettlementConventions(invalid).adjust_business_day(
                candidate,
                convention="following",  # type: ignore[arg-type]  # [owner=platform; rationale=verify constructor precedence over multiple invalid operation inputs; expires=2027-03-01]
            )
        assert str(constructor_error.value) == "invalid settlement calendar"
        assert isinstance(constructor_error.value.__cause__, ValidationError)
        service = SettlementConventions(FinancialUnitCases.calendar())
        with pytest.raises(UnitError) as method_error:
            service.adjust_business_day(
                candidate,
                convention="following",  # type: ignore[arg-type]  # [owner=platform; rationale=preserve candidate-before-convention method validation ordering; expires=2027-03-01]
            )
        assert str(method_error.value) == expected_message

    def test_repeated_failures_do_not_contaminate_snapshot_or_caller_calendar(self) -> None:
        """Keep one service usable after repeated failures and preserve the caller calendar."""
        caller_calendar = FinancialUnitCases.calendar()
        original_dates = caller_calendar.settlement_dates
        service = SettlementConventions(caller_calendar)
        for _ in range(2):
            with pytest.raises(ConventionError, match="coverage"):
                service.adjust_business_day(date(2024, 9, 6), convention=BDC.FOLLOWING)
        assert caller_calendar.settlement_dates == original_dates
        assert service.adjust_business_day(date(2024, 8, 31), convention=BDC.FOLLOWING) == date(
            2024, 9, 3
        )
        for _ in range(2):
            with pytest.raises(ConventionError, match="lag exceeds"):
                service.settlement_date(
                    date(2024, 9, 5), business_day_lag=1, convention=BDC.FOLLOWING
                )
        assert service.settlement_date(
            date(2024, 8, 30), business_day_lag=2, convention=BDC.FOLLOWING
        ) == date(2024, 9, 4)
        assert caller_calendar.settlement_dates == original_dates

    def test_strict_date_contract_rejects_datetime_candidates(self) -> None:
        """Reject datetime subclasses at both service operation boundaries."""
        candidate = datetime(2024, 8, 31)
        service = SettlementConventions(FinancialUnitCases.calendar())
        with pytest.raises(UnitError, match="candidate"):
            service.adjust_business_day(candidate, convention=BDC.UNADJUSTED)
        with pytest.raises(UnitError, match="candidate"):
            service.settlement_date(candidate, business_day_lag=0, convention=BDC.UNADJUSTED)

    def test_modified_adjustment_compares_year_as_well_as_month(self) -> None:
        """Treat same-month dates in different years as crossing an adjustment boundary."""
        bounded = SettlementCalendar(
            calendar_id="synthetic-sparse",
            calendar_version="v1",
            timezone_name="UTC",
            covered_from=date(2024, 1, 1),
            covered_through=date(2025, 1, 31),
            settlement_dates=(date(2024, 1, 1), date(2025, 1, 31)),
            source="synthetic",
            source_revision="v1",
        )
        service = SettlementConventions(bounded)
        assert service.adjust_business_day(
            date(2024, 1, 30), convention=BDC.MODIFIED_FOLLOWING
        ) == date(2024, 1, 1)
        assert service.adjust_business_day(
            date(2025, 1, 2), convention=BDC.MODIFIED_PRECEDING
        ) == date(2025, 1, 31)
