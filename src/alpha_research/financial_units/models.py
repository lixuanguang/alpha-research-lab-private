"""Define bounded exact C03 financial values and explicit convention metadata."""

from __future__ import annotations

# standard library imports
from collections.abc import Mapping
from copy import deepcopy
from datetime import date
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from functools import partial
from typing import Annotated, ClassVar, Self

# third party library imports
from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError

# project library imports
from alpha_research.instrument_identity import InstrumentId


class UnitError(ValueError):
    """Reject invalid values, dimensions, conventions, or unsupported precision."""


class _FinancialUnitModel(BaseModel):
    """Keep strict frozen C03 construction and validated replacement in one boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
        strict=True,
        validate_default=True,
    )
    _validation_error_type: ClassVar[type[UnitError]] = UnitError

    def __init__(self, **data: object) -> None:
        try:
            super().__init__(**data)
        except ValidationError as error:
            messages: list[str] = []
            for detail in error.errors(include_input=False, include_url=False):
                location = ".".join(str(component) for component in detail["loc"])
                message = str(detail["msg"]).removeprefix("Value error, ")
                messages.append(f"{location}: {message}" if location else message)
            raise self._validation_error_type("\n".join(messages)) from error

    def model_copy(self, *, update: Mapping[str, object] | None = None, deep: bool = False) -> Self:
        """Reconstruct and validate every field, including updates and nested values."""
        values = {name: getattr(self, name) for name in type(self).model_fields}
        if update is not None:
            values.update(update)
        if deep:
            values = deepcopy(values)
        return type(self)(**values)


class Currency(StrEnum):
    """Enumerate supported currency units; this is not a currency registry or entitlement."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    CHF = "CHF"
    SGD = "SGD"
    AUD = "AUD"
    CAD = "CAD"
    HKD = "HKD"
    CNY = "CNY"

    @property
    def minor_unit(self) -> Decimal:
        """Return the supported currency's accounting quantum, not a cash-payment rule."""
        return Decimal("1") if self is Currency.JPY else Decimal("0.01")


class QuantityKind(StrEnum):
    """Distinguish native quantity dimensions even for the same instrument."""

    SHARE = "share"
    CONTRACT = "contract"
    BASE_UNIT = "base_unit"
    FACE_AMOUNT = "face_amount"


class Rounding(StrEnum):
    """Specify mathematical floor, ceiling, toward-zero, or nearest ties-to-even."""

    FLOOR = "floor"
    CEILING = "ceiling"
    TOWARD_ZERO = "toward_zero"
    HALF_EVEN = "half_even"


class DayCount(StrEnum):
    """Name the exact supported day-count variants; generic 30/360 is ambiguous."""

    ACTUAL_360 = "actual_360"
    ACTUAL_365_FIXED = "actual_365_fixed"
    ACTUAL_ACTUAL_ISDA = "actual_actual_isda"
    THIRTY_360_BOND_BASIS = "thirty_360_bond_basis"
    THIRTY_E_360 = "thirty_e_360"


class Compounding(StrEnum):
    """Describe a quoted annual rate without computing accruals or valuation."""

    SIMPLE = "simple"
    CONTINUOUS = "continuous"
    PERIODIC = "periodic"


def require_type[T](value: object, expected: type[T], name: str) -> T:
    """Reject coercion and unsupported subclasses at the owned construction boundary."""
    if not isinstance(value, expected) or type(value) is not expected:
        raise UnitError(f"{name} must be {expected.__name__}")
    return value


def require_decimal(value: object) -> Decimal:
    """Require finite Decimal values on the 10^-18 grid with magnitude below 10^18."""
    require_type(value, Decimal, "value")
    if not isinstance(value, Decimal) or not value.is_finite():
        raise UnitError("value must be finite")
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or not -18 <= exponent <= 18:
        raise UnitError("value exponent must be between -18 and 18")
    if value.copy_abs() >= Decimal("1e18"):
        raise UnitError("value magnitude must be below 1e18")
    return value


def exact_decimal(value: Fraction) -> Decimal:
    """Convert a rational exactly to the bounded grid, independently of Decimal context."""
    scaled = value * 10**18
    if scaled.denominator != 1:
        raise UnitError("result is not exactly representable on the 1e-18 grid")
    digits = str(abs(scaled.numerator))
    return require_decimal(Decimal((int(scaled < 0), tuple(map(int, digits)), -18)))


def round_fraction(value: Fraction, quantum: Decimal, mode: Rounding) -> Decimal:
    """Round an exact rational once to an arbitrary positive grid, including 0.05 ticks."""
    step = require_decimal(quantum)
    require_type(mode, Rounding, "rounding")
    if step <= 0:
        raise UnitError("quantum must be positive")
    ratio = value / Fraction(step)
    lower, remainder = divmod(ratio.numerator, ratio.denominator)
    match mode:
        case Rounding.FLOOR:
            count = lower
        case Rounding.CEILING:
            count = lower + bool(remainder)
        case Rounding.TOWARD_ZERO:
            count = lower + (ratio < 0 and bool(remainder))
        case Rounding.HALF_EVEN:
            count = lower + (
                2 * remainder > ratio.denominator
                or (2 * remainder == ratio.denominator and lower % 2 != 0)
            )
    return exact_decimal(Fraction(count) * Fraction(step))


class Dimension(_FinancialUnitModel):
    """Bind a native quantity kind to a stable C01 instrument identity."""

    instrument_id: Annotated[
        InstrumentId,
        BeforeValidator(partial(require_type, expected=InstrumentId, name="instrument_id")),
    ]
    kind: QuantityKind

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        require_type(self.instrument_id, InstrumentId, "instrument_id")
        try:
            InstrumentId(self.instrument_id.uuid_value)
        except ValueError as error:
            raise UnitError("invalid instrument identity") from error
        require_type(self.kind, QuantityKind, "quantity kind")


class RateConvention(_FinancialUnitModel):
    """State an annual quote's day count and compounding frequency explicitly."""

    day_count: DayCount
    compounding: Compounding
    payments_per_year: int | None = None

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        require_type(self.day_count, DayCount, "day count")
        require_type(self.compounding, Compounding, "compounding")
        if self.compounding is Compounding.PERIODIC:
            if type(self.payments_per_year) is not int or self.payments_per_year not in (
                1,
                2,
                4,
                12,
            ):
                raise UnitError("periodic compounding requires 1, 2, 4, or 12 payments per year")
        elif self.payments_per_year is not None:
            raise UnitError("only periodic compounding permits payments_per_year")


class _Value(_FinancialUnitModel):
    """Share exact same-dimension addition and subtraction across owned value types."""

    value: Annotated[Decimal, BeforeValidator(require_decimal)]

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        require_decimal(self.value)

    def _combine(self, other: Self, sign: int) -> Self:
        if type(other) is not type(self) or any(
            getattr(self, name) != getattr(other, name)
            for name in type(self).model_fields
            if name != "value"
        ):
            raise UnitError("arithmetic requires identical types and dimensions")
        return self.model_copy(
            update={"value": exact_decimal(Fraction(self.value) + sign * Fraction(other.value))}
        )

    def __add__(self, other: Self) -> Self:
        return self._combine(other, 1)

    def __sub__(self, other: Self) -> Self:
        return self._combine(other, -1)


class Money(_Value):
    """Represent a signed currency amount; conversion and rounding are always explicit."""

    currency: Currency

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        _Value.model_post_init(self, _context)
        require_type(self.currency, Currency, "currency")

    def rounded(self, *, mode: Rounding) -> Money:
        """Round once to this currency's accounting minor unit."""
        return self.model_copy(
            update={"value": round_fraction(Fraction(self.value), self.currency.minor_unit, mode)}
        )


class Quantity(_Value):
    """Represent a signed quantity in one instrument's native dimension."""

    dimension: Annotated[
        Dimension, BeforeValidator(partial(require_type, expected=Dimension, name="dimension"))
    ]

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        _Value.model_post_init(self, _context)
        require_type(self.dimension, Dimension, "dimension")

    def rounded(self, lot: Lot, *, mode: Rounding) -> Quantity:
        """Round to an explicitly matching lot, without order-side inference."""
        require_type(lot, Lot, "lot")
        if lot.dimension != self.dimension:
            raise UnitError("lot dimension mismatch")
        return self.model_copy(
            update={"value": round_fraction(Fraction(self.value), lot.value, mode)}
        )


class Price(_Value):
    """Represent signed currency per native unit; negative prices remain representable."""

    currency: Currency
    per: Annotated[
        Dimension, BeforeValidator(partial(require_type, expected=Dimension, name="per"))
    ]

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        _Value.model_post_init(self, _context)
        require_type(self.currency, Currency, "currency")
        require_type(self.per, Dimension, "price denominator")

    def rounded(self, tick: Tick, *, mode: Rounding) -> Price:
        """Round to an explicitly matching price tick."""
        require_type(tick, Tick, "tick")
        if tick.currency != self.currency or tick.per != self.per:
            raise UnitError("tick dimension mismatch")
        return self.model_copy(
            update={"value": round_fraction(Fraction(self.value), tick.value, mode)}
        )

    def amount(self, quantity: Quantity) -> Money:
        """Multiply matching dimensions exactly, without creating accounting state."""
        require_type(quantity, Quantity, "quantity")
        if quantity.dimension != self.per:
            raise UnitError("price and quantity dimension mismatch")
        return Money(
            value=exact_decimal(Fraction(self.value) * Fraction(quantity.value)),
            currency=self.currency,
        )


class Tick(Price):
    """Declare a strictly positive price increment for a matching currency and dimension."""

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        Price.model_post_init(self, _context)
        if self.value <= 0:
            raise UnitError("tick must be positive")


class Lot(Quantity):
    """Declare a strictly positive native quantity increment."""

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        Quantity.model_post_init(self, _context)
        if self.value <= 0:
            raise UnitError("lot must be positive")


class Multiplier(_Value):
    """Convert quantities between two explicitly identified native dimensions."""

    input_dimension: Annotated[
        Dimension,
        BeforeValidator(partial(require_type, expected=Dimension, name="input_dimension")),
    ]
    output_dimension: Annotated[
        Dimension,
        BeforeValidator(partial(require_type, expected=Dimension, name="output_dimension")),
    ]

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        _Value.model_post_init(self, _context)
        require_type(self.input_dimension, Dimension, "input dimension")
        require_type(self.output_dimension, Dimension, "output dimension")
        if self.value <= 0:
            raise UnitError("multiplier must be positive")

    def apply(self, quantity: Quantity) -> Quantity:
        """Apply the declared factor once to the exact input dimension."""
        require_type(quantity, Quantity, "quantity")
        if quantity.dimension != self.input_dimension:
            raise UnitError("multiplier input dimension mismatch")
        return Quantity(
            value=exact_decimal(Fraction(self.value) * Fraction(quantity.value)),
            dimension=self.output_dimension,
        )


class FXRate(_Value):
    """Quote positive units of quote currency for one unit of base currency."""

    base: Currency
    quote: Currency

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        _Value.model_post_init(self, _context)
        require_type(self.base, Currency, "base currency")
        require_type(self.quote, Currency, "quote currency")
        if self.base == self.quote or self.value <= 0:
            raise UnitError("FX requires distinct currencies and a positive rate")

    def convert(self, money: Money, *, target: Currency, mode: Rounding) -> Money:
        """Convert either direction at this explicit rate and round once to target minor units."""
        require_type(money, Money, "money")
        require_type(target, Currency, "target currency")
        if money.currency == self.base and target == self.quote:
            result = Fraction(money.value) * Fraction(self.value)
        elif money.currency == self.quote and target == self.base:
            result = Fraction(money.value) / Fraction(self.value)
        else:
            raise UnitError("FX currency pair or direction mismatch")
        return Money(value=round_fraction(result, target.minor_unit, mode), currency=target)


class Rate(_Value):
    """Represent a signed annual rate as a fraction, with explicit quotation conventions."""

    convention: Annotated[
        RateConvention,
        BeforeValidator(partial(require_type, expected=RateConvention, name="convention")),
    ]

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        _Value.model_post_init(self, _context)
        require_type(self.convention, RateConvention, "rate convention")


class Yield(Rate):
    """Represent a quoted annual yield, distinct from an interest-rate value."""


class Volatility(_Value):
    """Represent nonnegative annualized volatility as a fraction per square-root year."""

    day_count: DayCount

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        _Value.model_post_init(self, _context)
        require_type(self.day_count, DayCount, "volatility year basis")
        if self.value < 0:
            raise UnitError("volatility cannot be negative")


class Duration(_Value):
    """Represent a nonnegative elapsed year fraction, not a bond sensitivity."""

    day_count: DayCount

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        _Value.model_post_init(self, _context)
        require_type(self.day_count, DayCount, "duration year basis")
        if self.value < 0:
            raise UnitError("duration cannot be negative")


class EvaluationContext(_FinancialUnitModel):
    """Carry the caller's evaluation date and convention revision, without library Settings."""

    evaluation_date: date
    convention_revision: str

    def model_post_init(self, _context: object, /) -> None:
        """Enforce owned financial invariants after strict field validation."""
        require_type(self.evaluation_date, date, "evaluation date")
        revision = self.convention_revision
        if (
            type(revision) is not str
            or not 1 <= len(revision) <= 128
            or not all(
                character.isascii() and (character.isalnum() or character in "._-")
                for character in revision
            )
        ):
            raise UnitError("convention revision must be an explicit bounded ASCII token")
