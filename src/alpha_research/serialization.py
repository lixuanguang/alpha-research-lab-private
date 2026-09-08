"""Encode P1 records with msgspec while preserving exact C01/C03 wire values."""

from __future__ import annotations

# standard library imports
from decimal import Decimal, InvalidOperation

# third party library imports
import msgspec

# project library imports
from alpha_research.financial_units import (
    Currency,
    Dimension,
    FXRate,
    Money,
    Price,
    Quantity,
    QuantityKind,
    Tick,
)
from alpha_research.instrument_identity import InstrumentId


class _IdentityWire(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Retain the existing nested C03 instrument UUID representation."""

    uuid_value: str


class _DimensionWire(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Pair a canonical listing with its native quantity unit on the wire."""

    instrument_id: _IdentityWire
    kind: QuantityKind


class _MoneyWire(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Carry an exact decimal string and explicit currency."""

    value: str
    currency: object


class _CurrencyWire(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Carry a complete currency definition with an exact decimal string quantum."""

    code: str
    minor_unit: str


class _PriceWire(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Carry a dimensioned price or tick without binary floating-point conversion."""

    value: str
    currency: object
    per: _DimensionWire


class _QuantityWire(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Carry a native amount and its complete instrument dimension."""

    value: str
    dimension: _DimensionWire


class _FXRateWire(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Carry an exact FX quote and both complete currency definitions."""

    value: str
    base: object
    quote: object


def _dimension_wire(value: Dimension) -> _DimensionWire:
    """Translate a validated C03 dimension without traversing Pydantic serialization."""
    return _DimensionWire(_IdentityWire(str(value.instrument_id)), value.kind)


def _dimension_value(value: _DimensionWire) -> Dimension:
    """Reconstruct a C03 dimension through its strict public constructor."""
    return Dimension(
        instrument_id=InstrumentId.from_canonical_text(value.instrument_id.uuid_value),
        kind=value.kind,
    )


def _decimal_value(value: str) -> Decimal:
    """Translate malformed decimal wire text into the decoder's value-error contract."""
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise ValueError("invalid decimal text") from error


def _currency_wire(value: Currency) -> _CurrencyWire:
    """Translate one validated currency to its self-contained wire definition."""
    value.validate_currency()
    return _CurrencyWire(value.code, format(value.minor_unit, "f"))


def _currency_value(value: object) -> Currency:
    """Decode one explicit currency object or a retained known legacy code."""
    if isinstance(value, str):
        return Currency.from_code(value)
    fields = msgspec.convert(value, type=dict[str, object], strict=True)
    if set(fields) != {"code", "minor_unit"}:
        raise ValueError("currency object must contain exactly code and minor_unit")
    code = fields["code"]
    minor_unit = fields["minor_unit"]
    if type(code) is not str or type(minor_unit) is not str:
        raise ValueError("currency code and minor_unit must be strings")
    wire = msgspec.convert(fields, type=_CurrencyWire, strict=True)
    return Currency(code=wire.code, minor_unit=_decimal_value(wire.minor_unit))


def encode_domain(value: object) -> object:
    """Translate supported validated domain values for the native msgspec encoder.

    Args:
        value: Immutable C01 identifier or C03 amount, dimension, price or tick.

    Returns:
        A msgspec-native wire value retaining decimal strings and explicit units.
        Encoding assumes validated objects; untrusted bytes enter through decoding.

    Raises:
        NotImplementedError: The object is outside the supported domain boundary.
    """
    if isinstance(value, InstrumentId):
        return str(value)
    if isinstance(value, Currency):
        return _currency_wire(value)
    if isinstance(value, Money):
        return _MoneyWire(str(value.value), value.currency)
    if isinstance(value, (Price, Tick)):
        return _PriceWire(str(value.value), value.currency, _dimension_wire(value.per))
    if isinstance(value, Quantity):
        return _QuantityWire(str(value.value), _dimension_wire(value.dimension))
    if isinstance(value, FXRate):
        return _FXRateWire(str(value.value), value.base, value.quote)
    if isinstance(value, Dimension):
        return _dimension_wire(value)
    raise NotImplementedError(f"unsupported serialized domain type: {type(value).__name__}")


def decode_domain(target: type[object], value: object) -> object:
    """Decode supported domain values through their strict C01/C03 constructors.

    Args:
        target: Domain type requested by the typed msgspec decoder.
        value: Untrusted JSON/MessagePack-compatible value supplied by msgspec.

    Returns:
        A validated domain object with exact Decimal and instrument/currency semantics.

    Raises:
        ValueError: The wire representation or domain invariants are invalid.
        NotImplementedError: The requested type is outside this adapter's scope.
    """
    if target is InstrumentId:
        if not isinstance(value, str):
            raise ValueError("instrument_id must be canonical UUID text")
        return InstrumentId.from_canonical_text(value)
    if target is Currency:
        return _currency_value(value)
    if target is Money:
        money = msgspec.convert(value, type=_MoneyWire, strict=True)
        return Money(value=_decimal_value(money.value), currency=_currency_value(money.currency))
    if target is Price or target is Tick:
        price = msgspec.convert(value, type=_PriceWire, strict=True)
        dimension = _dimension_value(price.per)
        currency = _currency_value(price.currency)
        if target is Tick:
            return Tick(value=_decimal_value(price.value), currency=currency, per=dimension)
        return Price(value=_decimal_value(price.value), currency=currency, per=dimension)
    if target is Quantity:
        quantity = msgspec.convert(value, type=_QuantityWire, strict=True)
        return Quantity(
            value=_decimal_value(quantity.value), dimension=_dimension_value(quantity.dimension)
        )
    if target is FXRate:
        rate = msgspec.convert(value, type=_FXRateWire, strict=True)
        return FXRate(
            value=_decimal_value(rate.value),
            base=_currency_value(rate.base),
            quote=_currency_value(rate.quote),
        )
    if target is Dimension:
        return _dimension_value(msgspec.convert(value, type=_DimensionWire, strict=True))
    raise NotImplementedError(f"unsupported serialized domain type: {target.__name__}")


_JSON_ENCODER = msgspec.json.Encoder(enc_hook=encode_domain, order="sorted")
_JSON_DECODERS: dict[type[object], msgspec.json.Decoder[object]] = {}
_JSON_VALUE_DECODER: msgspec.json.Decoder[object] = msgspec.json.Decoder(
    object,
    strict=True,
)


def _json_decoder(target: type[object]) -> msgspec.json.Decoder[object]:
    """Compile each caller-selected typed schema once for repeated decoding."""
    decoder = _JSON_DECODERS.get(target)
    if decoder is None:
        decoder = msgspec.json.Decoder(target, strict=True, dec_hook=decode_domain)
        _JSON_DECODERS[target] = decoder
    return decoder


def encode_json(value: object) -> bytes:
    """Encode validated records deterministically without Pydantic or JSON round-trips.

    Args:
        value: A msgspec record or supported immutable domain value.

    Returns:
        UTF-8 JSON with sorted object keys and lossless decimal strings.

    Raises:
        TypeError: A value cannot be encoded by msgspec or the domain hook.
    """
    return _JSON_ENCODER.encode(value)


def decode_json[T](data: bytes | str, target: type[T]) -> T:
    """Decode an untrusted JSON record with strict types and domain validation.

    Args:
        data: Complete UTF-8 JSON object or value.
        target: Exact expected type, including its closed msgspec schema.

    Returns:
        A typed value whose native and custom domain invariants have been checked.

    Raises:
        ValueError: JSON syntax, field types, unknown fields or domain values are invalid.
    """
    if target is Currency:
        raw = _JSON_VALUE_DECODER.decode(data)
        decoded: object = _currency_value(raw)
    else:
        decoded = _json_decoder(target).decode(data)
    if not isinstance(decoded, target):
        raise ValueError("decoded value does not match the requested schema")
    return decoded
