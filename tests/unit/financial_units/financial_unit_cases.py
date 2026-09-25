"""Shared authored financial-unit inputs and strict golden-case loading."""

from __future__ import annotations

# standard library imports
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TypedDict
from uuid import UUID

# third party library imports
from pydantic import TypeAdapter

# project library imports
from financial_units import (
    Compounding,
    DayCount,
    Dimension,
    EvaluationContext,
    QuantityKind,
    RateConvention,
)
from reference_data.calendars import SettlementCalendar
from reference_data.instruments import InstrumentId

D = Decimal
SHARES = Dimension(instrument_id=InstrumentId(UUID(int=1)), kind=QuantityKind.SHARE)
CONTRACTS = Dimension(instrument_id=InstrumentId(UUID(int=2)), kind=QuantityKind.CONTRACT)
CONTEXT = EvaluationContext(evaluation_date=date(2024, 1, 1), convention_revision="c03-v1")
CONVENTION = RateConvention(day_count=DayCount.ACTUAL_360, compounding=Compounding.SIMPLE)
FIXTURE = Path(__file__).parents[2] / "golden/financial_units/c03_units.json"


class _Tolerance(TypedDict):
    """Retain decimal-string year tolerances and their numerical justification."""

    absolute_years: str
    relative: str
    rationale: str


class _DayCountCase(TypedDict):
    """Describe an ISO-date interval and its hand-calculated rational year count."""

    basis: str
    start: str
    end: str
    numerator: int
    denominator: int


class _RoundingCase(TypedDict):
    """Retain exact decimal strings for a rounding input, grid and expected result."""

    value: str
    tick: str
    mode: str
    expected: str


class _FinancialFixture(TypedDict):
    """Bind synthetic golden cases to their convention, native version and tolerances."""

    fixture_kind: str
    convention_revision: str
    quantlib_version: str
    tolerance: _Tolerance
    day_counts: list[_DayCountCase]
    rounding: list[_RoundingCase]


class FinancialUnitCases:
    """Own synthetic input construction and validated independent golden values."""

    @staticmethod
    def fixture() -> _FinancialFixture:
        """Read golden inputs and validate every consumed field without coercion.

        Returns:
            Typed cases preserving decimal strings and integer rational components.

        Raises:
            OSError: The golden file cannot be read.
            ValidationError: The JSON or a required field has an invalid shape or type.
        """
        return TypeAdapter(_FinancialFixture).validate_json(FIXTURE.read_bytes(), strict=True)

    @staticmethod
    def calendar() -> SettlementCalendar:
        """Build the synthetic holiday gap used by settlement and coverage tests.

        Returns:
            A UTC calendar covering August 29 through September 5, 2024, inclusively.
        """
        return SettlementCalendar(
            calendar_id="synthetic",
            calendar_version="v1",
            timezone_name="UTC",
            covered_from=date(2024, 8, 29),
            covered_through=date(2024, 9, 5),
            settlement_dates=(
                date(2024, 8, 29),
                date(2024, 8, 30),
                date(2024, 9, 3),
                date(2024, 9, 4),
                date(2024, 9, 5),
            ),
            source="synthetic",
            source_revision="v1",
        )
