"""Define the bounded, authored Binance spot reference catalog."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import ClassVar, Literal, Self

# third party library imports
import msgspec

# project library imports
from alpha_research.financial_units import Currency
from alpha_research.financial_units.models import _DecimalArithmetic
from alpha_research.instrument_identity import InstrumentId
from alpha_research.serialization import DomainCodec

Venue = Literal["binance"]
Product = Literal["spot"]
Source = Literal["tardis.binance.spot", "binance.archive.spot"]
MetadataBasis = Literal["research_assumption"]

_SYMBOL_PATTERN = re.compile(r"[A-Z0-9]+")
_SOURCE: Source = "tardis.binance.spot"


class _ReferenceRecord(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Keep authored reference timestamps strictly UTC without normalization."""

    @staticmethod
    def _require_utc(value: object, *, field_name: str) -> datetime:
        """Require an aware datetime whose offset is exactly UTC."""
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TypeError(f"{field_name} must be a timezone-aware datetime")
        if value.utcoffset() != timedelta(0):
            raise ValueError(f"{field_name} must use UTC")
        return value


class SpotInstrument(_ReferenceRecord, frozen=True, kw_only=True):
    """Describe one authored Binance spot listing for local research metadata.

    The validity interval is scenario metadata used to select an instrument for a
    bounded replay. It does not assert historical exchange filters or point-in-time
    venue truth. Exact Decimal values are emitted as strings by ``DomainCodec.encode_json``;
    strict JSON decoding follows msgspec's Decimal contract, while Python
    constructors require Decimal instances.
    """

    instrument_id: InstrumentId
    symbol: str
    quote_currency: Currency
    price_tick: Decimal
    valid_from: datetime
    valid_to: datetime
    venue: Venue = "binance"
    product: Product = "spot"
    source: Source = _SOURCE
    metadata_basis: MetadataBasis = "research_assumption"

    def __post_init__(self) -> None:
        """Validate the closed record and its explicit UTC validity interval.

        Raises:
            TypeError: A field has an unsafe Python type.
            ValueError: A symbol, tick, interval or fixed metadata value is invalid.
        """
        if type(self.instrument_id) is not InstrumentId:
            raise TypeError("instrument_id must be an InstrumentId")
        if not isinstance(self.symbol, str) or _SYMBOL_PATTERN.fullmatch(self.symbol) is None:
            raise ValueError("symbol must be uppercase ASCII alphanumeric Binance text")
        if len(self.symbol) > 64:
            raise ValueError("symbol exceeds the bounded Binance symbol length")
        if type(self.quote_currency) is not Currency:
            raise TypeError("quote_currency must be a Currency")
        Currency._require(self.quote_currency)
        SpotInstrument._require_decimal(self.price_tick, field_name="price_tick")
        valid_from = self._require_utc(self.valid_from, field_name="valid_from")
        valid_to = self._require_utc(self.valid_to, field_name="valid_to")
        if valid_to <= valid_from:
            raise ValueError("valid_to must be later than valid_from")
        if self.venue != "binance":
            raise ValueError("unsupported instrument venue")
        if self.product != "spot":
            raise ValueError("unsupported instrument product")
        if self.source not in (_SOURCE, "binance.archive.spot"):
            raise ValueError("unsupported instrument source")
        if self.metadata_basis != "research_assumption":
            raise ValueError("unsupported instrument metadata basis")

    def validate(self) -> Self:
        """Revalidate a record received through a trusted Python boundary.

        Returns:
            This immutable instrument after all field and interval checks succeed.

        Raises:
            TypeError: A field has an unsafe Python type.
            ValueError: A field or invariant is invalid.
        """
        self.__post_init__()
        return self

    @staticmethod
    def _require_decimal(value: object, *, field_name: str) -> Decimal:
        """Require one finite, strictly positive exact C03-bounded decimal value."""
        if not isinstance(value, Decimal):
            raise TypeError(f"{field_name} must be a Decimal")
        if not value.is_finite() or value <= 0:
            raise ValueError(f"{field_name} must be finite and positive")
        return _DecimalArithmetic.require_decimal(value)


class CatalogSnapshot(_ReferenceRecord, frozen=True, kw_only=True):
    """Capture the complete authored instrument metadata used by one research run."""

    _codec: ClassVar[DomainCodec] = DomainCodec()

    schema_version: Literal["1"] = "1"
    recorded_at: datetime
    evidence: str
    instruments: tuple[SpotInstrument, ...]

    def __post_init__(self) -> None:
        """Validate snapshot metadata, nested records and identifier uniqueness.

        Raises:
            TypeError: A field or nested record has an unsafe Python type.
            ValueError: The snapshot, nested metadata or uniqueness invariant is invalid.
        """
        if self.schema_version != "1":
            raise ValueError("unsupported catalog schema version")
        self._require_utc(self.recorded_at, field_name="recorded_at")
        CatalogSnapshot._require_text(self.evidence, field_name="evidence")
        if type(self.instruments) is not tuple or not self.instruments:
            raise TypeError("instruments must be a nonempty tuple")
        seen_ids: set[InstrumentId] = set()
        seen_symbols: set[str] = set()
        for instrument in self.instruments:
            if type(instrument) is not SpotInstrument:
                raise TypeError("catalog instruments must be SpotInstrument records")
            instrument.validate()
            if instrument.instrument_id in seen_ids:
                raise ValueError("catalog contains duplicate instrument IDs")
            if instrument.symbol in seen_symbols:
                raise ValueError("catalog contains duplicate instrument symbols")
            seen_ids.add(instrument.instrument_id)
            seen_symbols.add(instrument.symbol)

    def validate(self) -> Self:
        """Revalidate this complete immutable snapshot before resolution or hashing.

        Returns:
            This catalog snapshot after nested records and uniqueness checks succeed.

        Raises:
            TypeError: A field or nested record has an unsafe Python type.
            ValueError: The snapshot or one nested instrument violates its contract.
        """
        self.__post_init__()
        return self

    def resolve(
        self,
        instrument_id: InstrumentId,
        start: datetime,
        end: datetime,
    ) -> SpotInstrument:
        """Resolve an instrument only when its authored interval fully covers a request.

        Args:
            instrument_id: Canonical C01 identifier to resolve.
            start: Inclusive UTC start of the requested interval.
            end: Exclusive UTC end of the requested interval.

        Returns:
            The catalog instrument whose interval contains ``[start, end)``.

        Raises:
            TypeError: An identifier or timestamp has the wrong type.
            ValueError: The interval is invalid, the ID is absent, or coverage is incomplete.
        """
        self.validate()
        if type(instrument_id) is not InstrumentId:
            raise TypeError("instrument_id must be an InstrumentId")
        requested_start = self._require_utc(start, field_name="requested start")
        requested_end = self._require_utc(end, field_name="requested end")
        if requested_end <= requested_start:
            raise ValueError("requested interval must be nonempty")
        for instrument in self.instruments:
            if instrument.instrument_id != instrument_id:
                continue
            if instrument.valid_from <= requested_start and requested_end <= instrument.valid_to:
                return instrument
            raise ValueError("instrument does not cover the complete requested interval")
        raise ValueError("instrument ID is absent from the catalog")

    @property
    def identity(self) -> str:
        """Return the SHA-256 identity of the canonical encoded catalog snapshot.

        Returns:
            Lowercase SHA-256 digest of the complete canonical catalog encoding.
        """
        self.validate()
        return hashlib.sha256(self._codec.encode_json(self)).hexdigest()

    @staticmethod
    def _require_text(value: object, *, field_name: str) -> str:
        """Require bounded nonempty text without silently coercing scalar values."""
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")
        if not value or value != value.strip():
            raise ValueError(f"{field_name} must be nonempty without surrounding whitespace")
        return value


__all__ = ["CatalogSnapshot", "MetadataBasis", "Product", "Source", "SpotInstrument", "Venue"]
