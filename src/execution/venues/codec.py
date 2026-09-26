"""Validate venue JSON without binary floating-point conversion."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from json import JSONDecodeError, dumps, loads
from typing import cast

# project library imports
from execution.venues.contracts import VenueProtocolError


class VenueJson:
    """Narrow untrusted JSON values into exact venue protocol fields."""

    @staticmethod
    def parse(raw: bytes) -> object:
        """Decode JSON floats directly into Decimal before validation."""
        try:
            return cast(object, loads(raw, parse_float=Decimal))
        except (UnicodeDecodeError, JSONDecodeError, ValueError) as error:
            raise VenueProtocolError("invalid venue JSON") from error

    @staticmethod
    def encode(value: object) -> bytes:
        """Emit compact UTF-8 JSON from already validated request fields."""
        return dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")

    @staticmethod
    def mapping(value: object) -> dict[str, object]:
        """Require a string-keyed JSON object."""
        if not isinstance(value, dict):
            raise VenueProtocolError("expected venue object")
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise VenueProtocolError("venue object key must be text")
            result[key] = item
        return result

    @staticmethod
    def array(value: object) -> list[object]:
        """Require a JSON array."""
        if not isinstance(value, list):
            raise VenueProtocolError("expected venue array")
        return list(value)

    @staticmethod
    def text(value: object, *, allow_empty: bool = False) -> str:
        """Require a textual protocol field."""
        if not isinstance(value, str) or (not allow_empty and not value):
            raise VenueProtocolError("expected venue text")
        return value

    @staticmethod
    def integer(value: object) -> int:
        """Require an integer without accepting bool or fractional JSON."""
        if type(value) is not int:
            raise VenueProtocolError("expected venue integer")
        return value

    @staticmethod
    def decimal(value: object) -> Decimal:
        """Accept native decimal strings and exact JSON numeric lexemes."""
        if isinstance(value, Decimal):
            result = value
        elif type(value) is int or isinstance(value, str):
            try:
                result = Decimal(value)
            except InvalidOperation as error:
                raise VenueProtocolError("invalid venue decimal") from error
        else:
            raise VenueProtocolError("expected venue decimal")
        if not result.is_finite():
            raise VenueProtocolError("non-finite venue decimal")
        return result

    @staticmethod
    def milliseconds(value: object) -> datetime:
        """Convert an integer millisecond epoch to UTC."""
        try:
            milliseconds = (
                int(VenueJson.text(value)) if isinstance(value, str) else VenueJson.integer(value)
            )
            return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=milliseconds)
        except (OverflowError, OSError, ValueError) as error:
            raise VenueProtocolError("invalid venue timestamp") from error

    @staticmethod
    def epoch_milliseconds(value: datetime) -> int:
        """Convert a UTC clock to integer milliseconds without float rounding."""
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("venue clock must be UTC")
        delta = value - datetime(1970, 1, 1, tzinfo=UTC)
        return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000

    @staticmethod
    def field(value: dict[str, object], key: str) -> object:
        """Require presence so absent fields cannot become zero or empty."""
        if key not in value:
            raise VenueProtocolError(f"missing venue field: {key}")
        return value[key]

    @staticmethod
    def indexed(value: list[object], index: int) -> object:
        """Require a documented positional field."""
        if index >= len(value):
            raise VenueProtocolError("truncated venue array")
        return value[index]
