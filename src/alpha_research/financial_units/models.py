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
from importlib import resources
from typing import Annotated, ClassVar, Protocol, Self, TypedDict

# third party library imports
import msgspec
from pydantic import BaseModel, BeforeValidator, ConfigDict, TypeAdapter, ValidationError

# project library imports
from alpha_research.instrument_identity import InstrumentId


class UnitError(ValueError):
    """Reject invalid values, dimensions, conventions, or unsupported precision."""


class _ValidationErrorDetail(TypedDict):
    """Capture the redacted, stable fields consumed from Pydantic error JSON."""

    loc: list[int | str]
    msg: str


class _AttributeReader(Protocol):
    """Expose reflective model attributes as raw values at a validation boundary."""

    def __getattribute__(self, name: str) -> object:
        """Read one named attribute without assuming its concrete runtime type."""
        ...


_VALIDATION_ERROR_DETAILS = TypeAdapter(list[_ValidationErrorDetail])


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

    @staticmethod
    def _read_attribute(model: _AttributeReader, name: str) -> object:
        """Read one model field as an unchecked value before reconstruction validation."""
        return model.__getattribute__(name)

    def __init__(self, **data: object) -> None:
        """Validate fields and translate construction failures to the owned error type.

        Args:
            **data: Declared model fields in their strict Python types; unknown fields
                and invalid nested instances are rejected.

        Raises:
            UnitError: Field or model validation fails. Subclasses may specialize this
                error through ``_validation_error_type``. Messages omit raw inputs.
        """
        try:
            super().__init__(**data)
        except ValidationError as error:
            messages: list[str] = []
            details = _VALIDATION_ERROR_DETAILS.validate_json(
                error.json(include_context=False, include_input=False, include_url=False),
                strict=True,
            )
            for detail in details:
                location = ".".join(str(component) for component in detail["loc"])
                message = str(detail["msg"]).removeprefix("Value error, ")
                messages.append(f"{location}: {message}" if location else message)
            raise self._validation_error_type("\n".join(messages)) from error

    def model_copy(self, *, update: Mapping[str, object] | None = None, deep: bool = False) -> Self:
        """Reconstruct and validate every field, including updates and nested values.

        Args:
            update: Field replacements to merge into the current values, or None to
                retain all values. Unknown fields and invalid replacements fail.
            deep: Whether to deep-copy the merged values before reconstruction.

        Returns:
            A newly validated instance of the same concrete type; this instance and
            the update mapping are not mutated.

        Raises:
            UnitError: Reconstruction violates the concrete model's contract, using
                its specialized validation error type where applicable.
        """
        values = {name: self._read_attribute(self, name) for name in type(self).model_fields}
        if update is not None:
            values.update(update)
        if deep:
            values = deepcopy(values)
        return type(self)(**values)


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
    """Reject coercion and unsupported subclasses at the owned construction boundary.

    Args:
        value: Raw value to check without conversion.
        expected: Required exact concrete type; subclasses are also rejected.
        name: Field label used in a failure message.

    Returns:
        The original value narrowed to the required type.

    Raises:
        UnitError: The value's concrete type differs from ``expected``.
    """
    if not isinstance(value, expected) or type(value) is not expected:
        raise UnitError(f"{name} must be {expected.__name__}")
    return value


def require_currency(value: object) -> Currency:
    """Require and revalidate one exact immutable currency value.

    Args:
        value: Candidate currency value received at a public boundary.

    Returns:
        The same validated currency instance.

    Raises:
        UnitError: The value is not an exact Currency or contains unsafe fields.
    """
    currency = require_type(value, Currency, "currency")
    currency.validate_currency()
    return currency


def require_decimal(value: object) -> Decimal:
    """Require finite Decimal values on the 10^-18 grid with magnitude below 10^18.

    The stored Decimal exponent must lie between -18 and 18 inclusive. Equivalent
    values with finer stored exponents are rejected rather than normalized.

    Args:
        value: Raw value; must be an exact Decimal, not a float or decimal string.

    Returns:
        The original finite Decimal, without rounding or context-dependent arithmetic.

    Raises:
        UnitError: The type, finiteness, stored exponent, or magnitude is unsupported.
    """
    require_type(value, Decimal, "value")
    if not isinstance(value, Decimal) or not value.is_finite():
        raise UnitError("value must be finite")
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or not -18 <= exponent <= 18:
        raise UnitError("value exponent must be between -18 and 18")
    if value.copy_abs() >= Decimal("1e18"):
        raise UnitError("value magnitude must be below 1e18")
    return value


class Currency(_FinancialUnitModel):
    """Identify one currency-like unit and its exact accounting quantum.

    ``Currency`` is an immutable C03 value object.  Configured currencies are resolved
    with :meth:`from_code`; callers may construct any valid authored unit directly.
    """

    code: str
    minor_unit: Annotated[Decimal, BeforeValidator(require_decimal)]

    def model_post_init(self, _context: object, /) -> None:
        """Validate the bounded code and strictly positive accounting quantum.

        Args:
            _context: Pydantic validation context, unused by this invariant check.

        Raises:
            UnitError: The code or accounting quantum violates the C03 contract.
        """
        _validate_currency_code(self.code)
        _validate_currency_quantum(self.minor_unit)

    def validate_currency(self) -> Currency:
        """Revalidate this value after a trusted boundary or unsafe operation.

        Returns:
            This unchanged currency value.

        Raises:
            UnitError: A field has an unsafe Python type or violates currency bounds.
        """
        _validate_currency_code(self.code)
        _validate_currency_quantum(self.minor_unit)
        return self

    @staticmethod
    def from_code(code: str) -> Currency:
        """Resolve a configured currency code through immutable default presets.

        Args:
            code: Uppercase currency code whose quantum is defined by a packaged preset.

        Returns:
            The matching default currency value.

        Raises:
            TypeError: The currency code is not a string.
            ValueError: The code is not a configured default currency.
        """
        if type(code) is not str:
            raise TypeError("currency code must be a string")
        for currency in _DEFAULT_CURRENCIES:
            if currency.code == code:
                return currency
        raise ValueError("unknown currency code")


_DEFAULT_CURRENCIES: tuple[Currency, ...]


def _validate_currency_code(value: object) -> str:
    """Require a bounded uppercase ASCII alphanumeric currency code."""
    if (
        type(value) is not str
        or not 1 <= len(value) <= 16
        or not value.isascii()
        or not value.isalnum()
        or value != value.upper()
    ):
        raise UnitError("currency code must be bounded uppercase ASCII alphanumeric text")
    return value


def _validate_currency_quantum(value: object) -> Decimal:
    """Require a positive finite C03-bounded currency accounting quantum."""
    quantum = require_decimal(value)
    if quantum <= 0:
        raise UnitError("currency minor_unit must be positive")
    return quantum


class _CurrencyDefinition(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Represent one packaged default currency definition."""

    code: str
    minor_unit: str


def _load_default_currencies() -> tuple[Currency, ...]:
    """Load and validate immutable compatibility presets from packaged JSON."""
    payload = resources.files(__package__).joinpath("default_currencies.json").read_bytes()
    definitions = msgspec.json.decode(
        payload,
        type=tuple[_CurrencyDefinition, ...],
        strict=True,
    )
    currencies = tuple(
        Currency(code=definition.code, minor_unit=Decimal(definition.minor_unit))
        for definition in definitions
    )
    if len({currency.code for currency in currencies}) != len(currencies):
        raise ValueError("default currency definitions contain duplicate codes")
    return currencies


def exact_decimal(value: Fraction) -> Decimal:
    """Convert a rational exactly to the bounded grid, independently of Decimal context.

    Args:
        value: Exact rational result to represent on the 1e-18 grid.

    Returns:
        An equal Decimal with stored exponent -18 and magnitude below 1e18.

    Raises:
        UnitError: The rational is not exactly representable on the grid or its
            magnitude reaches the bound. No implicit rounding is performed.
    """
    scaled = value * 10**18
    if scaled.denominator != 1:
        raise UnitError("result is not exactly representable on the 1e-18 grid")
    digits = str(abs(scaled.numerator))
    return require_decimal(Decimal((int(scaled < 0), tuple(map(int, digits)), -18)))


def round_fraction(value: Fraction, quantum: Decimal, mode: Rounding) -> Decimal:
    """Round an exact rational once to an arbitrary positive grid, including 0.05 ticks.

    Args:
        value: Exact rational to round; negative values are supported.
        quantum: Positive bounded Decimal grid step in the same units as ``value``.
        mode: Mathematical floor, ceiling, toward-zero, or nearest ties-to-even.

    Returns:
        A bounded Decimal multiple of the quantum, independent of Decimal context.

    Raises:
        UnitError: The quantum or mode is invalid, or the rounded result exceeds
            the bounded Decimal representation.
    """
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
        """Validate the instrument identity and native quantity kind.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: The identity is invalid or either field has an unexpected concrete type.
        """
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
        """Validate the day count and the compounding frequency relationship.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: An enum has the wrong concrete type, periodic frequency is not 1, 2,
                4, or 12, or a nonperiodic convention supplies a frequency.
        """
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
        """Validate the finite bounded Decimal value.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: The value is not an exact finite Decimal within the exponent
                and magnitude bounds.
        """
        require_decimal(self.value)

    def _combine(self, other: Self, sign: int) -> Self:
        """Combine signed values exactly after checking concrete type and every dimension."""
        if type(other) is not type(self) or any(
            self._read_attribute(self, name) != self._read_attribute(other, name)
            for name in type(self).model_fields
            if name != "value"
        ):
            raise UnitError("arithmetic requires identical types and dimensions")
        return self.model_copy(
            update={"value": exact_decimal(Fraction(self.value) + sign * Fraction(other.value))}
        )

    def __add__(self, other: Self) -> Self:
        """Return an exact same-type, same-dimension sum or raise UnitError."""
        return self._combine(other, 1)

    def __sub__(self, other: Self) -> Self:
        """Return an exact same-type, same-dimension difference or raise UnitError."""
        return self._combine(other, -1)


class Money(_Value):
    """Represent a signed currency amount; conversion and rounding are always explicit."""

    currency: Annotated[Currency, BeforeValidator(require_currency)]

    def model_post_init(self, _context: object, /) -> None:
        """Validate the bounded amount and explicit currency definition.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: The amount violates the Decimal bounds or the currency has the wrong type.
        """
        _Value.model_post_init(self, _context)
        require_currency(self.currency)

    def rounded(self, *, mode: Rounding) -> Money:
        """Round once to this currency's accounting minor unit.

        Args:
            mode: Explicit rounding direction or ties-to-even rule.

        Returns:
            New money in the same currency, rounded to its accounting quantum.

        Raises:
            UnitError: The mode is invalid or the rounded amount exceeds the Decimal bounds.
        """
        return self.model_copy(
            update={"value": round_fraction(Fraction(self.value), self.currency.minor_unit, mode)}
        )


class Quantity(_Value):
    """Represent a signed quantity in one instrument's native dimension."""

    dimension: Annotated[
        Dimension, BeforeValidator(partial(require_type, expected=Dimension, name="dimension"))
    ]

    def model_post_init(self, _context: object, /) -> None:
        """Validate the bounded quantity and explicit native dimension.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: The value violates the Decimal bounds or the dimension has the wrong type.
        """
        _Value.model_post_init(self, _context)
        require_type(self.dimension, Dimension, "dimension")

    def rounded(self, lot: Lot, *, mode: Rounding) -> Quantity:
        """Round to an explicitly matching lot, without order-side inference.

        Args:
            lot: Positive lot with exactly the same instrument and quantity kind.
            mode: Explicit rounding rule, also applied to negative quantities.

        Returns:
            A new quantity in this dimension, rounded to a multiple of the lot size.

        Raises:
            UnitError: The lot type, dimension, or mode is invalid, or the result
                exceeds the bounded Decimal representation. A Lot receiver also
                rejects rounding its positive value to zero.
        """
        require_type(lot, Lot, "lot")
        if lot.dimension != self.dimension:
            raise UnitError("lot dimension mismatch")
        return self.model_copy(
            update={"value": round_fraction(Fraction(self.value), lot.value, mode)}
        )


class Price(_Value):
    """Represent signed currency per native unit; negative prices remain representable."""

    currency: Annotated[Currency, BeforeValidator(require_currency)]
    per: Annotated[
        Dimension, BeforeValidator(partial(require_type, expected=Dimension, name="per"))
    ]

    def model_post_init(self, _context: object, /) -> None:
        """Validate the bounded price, currency, and native-unit denominator.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: The value violates the Decimal bounds or currency or denominator
                has the wrong type.
        """
        _Value.model_post_init(self, _context)
        require_currency(self.currency)
        require_type(self.per, Dimension, "price denominator")

    def rounded(self, tick: Tick, *, mode: Rounding) -> Price:
        """Round to an explicitly matching price tick.

        Args:
            tick: Positive increment with the same currency and native-unit denominator.
            mode: Explicit rounding rule, also applied to negative prices.

        Returns:
            A new price with the same dimensions and a value on the tick grid.

        Raises:
            UnitError: The tick type, dimensions, or mode is invalid, or the result
                exceeds the bounded Decimal representation. A Tick receiver also
                rejects rounding its positive value to zero.
        """
        require_type(tick, Tick, "tick")
        if tick.currency != self.currency or tick.per != self.per:
            raise UnitError("tick dimension mismatch")
        return self.model_copy(
            update={"value": round_fraction(Fraction(self.value), tick.value, mode)}
        )

    def amount(self, quantity: Quantity) -> Money:
        """Multiply matching dimensions exactly, without creating accounting state.

        Args:
            quantity: Signed quantity whose dimension exactly matches this price's denominator.

        Returns:
            New money in this price's currency; the product is not rounded to minor units.

        Raises:
            UnitError: Quantity type or dimension mismatches, or the exact product
                cannot be represented within the bounded Decimal grid.
        """
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
        """Require a positive price increment with valid currency and dimension.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: Price validation fails or the increment is zero or negative.
        """
        Price.model_post_init(self, _context)
        if self.value <= 0:
            raise UnitError("tick must be positive")


class Lot(Quantity):
    """Declare a strictly positive native quantity increment."""

    def model_post_init(self, _context: object, /) -> None:
        """Require a positive quantity increment in an explicit native dimension.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: Quantity validation fails or the increment is zero or negative.
        """
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
        """Require a positive bounded factor and exact input and output dimensions.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: The factor is invalid or nonpositive, or a dimension has the wrong type.
        """
        _Value.model_post_init(self, _context)
        require_type(self.input_dimension, Dimension, "input dimension")
        require_type(self.output_dimension, Dimension, "output dimension")
        if self.value <= 0:
            raise UnitError("multiplier must be positive")

    def apply(self, quantity: Quantity) -> Quantity:
        """Apply the declared factor once to the exact input dimension.

        Args:
            quantity: Signed quantity in the multiplier's input dimension.

        Returns:
            New quantity in the output dimension with the exact scaled value; no
            lot-size rounding is inferred.

        Raises:
            UnitError: Quantity type or dimension mismatches, or the exact product
                cannot be represented within the bounded Decimal grid.
        """
        require_type(quantity, Quantity, "quantity")
        if quantity.dimension != self.input_dimension:
            raise UnitError("multiplier input dimension mismatch")
        return Quantity(
            value=exact_decimal(Fraction(self.value) * Fraction(quantity.value)),
            dimension=self.output_dimension,
        )


class FXRate(_Value):
    """Quote positive units of quote currency for one unit of base currency."""

    base: Annotated[Currency, BeforeValidator(require_currency)]
    quote: Annotated[Currency, BeforeValidator(require_currency)]

    def model_post_init(self, _context: object, /) -> None:
        """Require a positive bounded quote for two distinct currencies.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: The value is invalid or nonpositive, currencies have the wrong type,
                or base and quote use the same currency code.
        """
        _Value.model_post_init(self, _context)
        require_currency(self.base)
        require_currency(self.quote)
        if self.base.code == self.quote.code or self.value <= 0:
            raise UnitError("FX requires distinct currencies and a positive rate")

    def convert(self, money: Money, *, target: Currency, mode: Rounding) -> Money:
        """Convert either direction at this explicit rate and round once to target minor units.

        Args:
            money: Signed amount in either currency of this rate's pair.
            target: The other currency in the pair; same-currency conversion is rejected.
            mode: Explicit rounding rule for the target currency's accounting quantum.

        Returns:
            New money in the target currency. Base-to-quote conversion multiplies;
            quote-to-base conversion divides using exact rational arithmetic before rounding.

        Raises:
            UnitError: An argument type or pair direction is invalid, or the rounded
                result exceeds the bounded Decimal representation.
        """
        require_type(money, Money, "money")
        require_currency(target)
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
        """Validate the bounded annual rate and its explicit quotation convention.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: The value violates the Decimal bounds or the convention has the wrong type.
        """
        _Value.model_post_init(self, _context)
        require_type(self.convention, RateConvention, "rate convention")


class Yield(Rate):
    """Represent a quoted annual yield, distinct from an interest-rate value."""


class Volatility(_Value):
    """Represent nonnegative annualized volatility as a fraction per square-root year."""

    day_count: DayCount

    def model_post_init(self, _context: object, /) -> None:
        """Require a nonnegative bounded annualized volatility and explicit year basis.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: The value is invalid or negative, or the day-count enum has the wrong type.
        """
        _Value.model_post_init(self, _context)
        require_type(self.day_count, DayCount, "volatility year basis")
        if self.value < 0:
            raise UnitError("volatility cannot be negative")


class Duration(_Value):
    """Represent a nonnegative elapsed year fraction, not a bond sensitivity."""

    day_count: DayCount

    def model_post_init(self, _context: object, /) -> None:
        """Require a nonnegative bounded year fraction and explicit day count.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: The value is invalid or negative, or the day-count enum has the wrong type.
        """
        _Value.model_post_init(self, _context)
        require_type(self.day_count, DayCount, "duration year basis")
        if self.value < 0:
            raise UnitError("duration cannot be negative")


class EvaluationContext(_FinancialUnitModel):
    """Carry the caller's evaluation date and convention revision, without library Settings."""

    evaluation_date: date
    convention_revision: str

    def model_post_init(self, _context: object, /) -> None:
        """Validate the exact evaluation date and bounded convention revision.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: The date has the wrong concrete type, or the revision is not a
                1-128 character ASCII token containing only letters, digits, dots,
                underscores, or hyphens.
        """
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


_DEFAULT_CURRENCIES = _load_default_currencies()
