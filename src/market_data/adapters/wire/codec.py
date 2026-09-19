"""Exact vendor JSON boundaries and bounded visible-order state."""

from __future__ import annotations

# standard library imports
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast

# third party library imports
import msgspec

# project library imports


class Wire:
    """Decode JSON numbers exactly and validate only explicitly understood fields."""

    _decoder: msgspec.json.Decoder[object] = msgspec.json.Decoder(object, float_hook=Decimal)

    @classmethod
    def decode(cls, raw: bytes) -> object:
        """Parse vendor bytes without passing decimal tokens through binary floats.

        Args:
            raw: Original received JSON bytes, before any numeric conversion.

        Returns:
            JSON value with decimal tokens parsed directly to Decimal.
        """
        return cls._decoder.decode(raw)

    @staticmethod
    def mapping(value: object) -> dict[str, object]:
        """Require a JSON object at the current protocol boundary.

        Args:
            value: Untrusted decoded source value at this field boundary.

        Returns:
            Validated source object without coercion.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
            raise ValueError("expected JSON object")
        return cast(dict[str, object], value)

    @staticmethod
    def array(value: object) -> list[object]:
        """Require a JSON array at the current protocol boundary.

        Args:
            value: Untrusted decoded source value at this field boundary.

        Returns:
            Validated source array without coercion.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if not isinstance(value, list):
            raise ValueError("expected JSON array")
        return cast(list[object], value)

    @staticmethod
    def text(value: object) -> str:
        """Require nonempty source text without coercing unknown identities.

        Args:
            value: Untrusted decoded source value at this field boundary.

        Returns:
            Original nonempty source text.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if not isinstance(value, str) or not value:
            raise ValueError("expected source text")
        return value

    @staticmethod
    def integer(value: object) -> int:
        """Read nonnegative source sequence/order IDs, including Coinbase numeric text.

        Args:
            value: Untrusted decoded source value at this field boundary.

        Returns:
            Exact nonnegative integer from the source.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if type(value) is int and value >= 0:
            return value
        if isinstance(value, str) and value.isascii() and value.isdigit():
            return int(value)
        raise ValueError("expected nonnegative integer")

    @staticmethod
    def decimal(value: object) -> Decimal:
        """Require a finite exact number; floats and booleans are never admitted.

        Args:
            value: Untrusted decoded source value at this field boundary.

        Returns:
            Finite Decimal within the supported precision and magnitude limits.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if not isinstance(value, (str, Decimal, int)) or isinstance(value, bool):
            raise ValueError("expected exact decimal")
        try:
            result = Decimal(value)
        except InvalidOperation:
            raise ValueError("invalid decimal") from None
        if (
            not result.is_finite()
            or len(result.as_tuple().digits) > 40
            or abs(result.adjusted()) > 30
        ):
            raise ValueError("nonfinite decimal")
        return result

    @staticmethod
    def source_time(value: object) -> str | None:
        """Validate supplied UTC source text while retaining its original fractional precision.

        Args:
            value: Untrusted decoded source value at this field boundary.

        Returns:
            Original UTC timestamp text, or None when the source omitted it.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if value is None:
            return None
        text = Wire.text(value)
        timestamp = datetime.fromisoformat(text)
        if timestamp.utcoffset() != timedelta(0):
            raise ValueError("source timestamp must be UTC")
        return text

    @staticmethod
    def source_nanoseconds(source_time: str) -> int:
        """Project validated UTC source text to the exact replay nanosecond clock.

        Args:
            source_time: UTC timestamp text retained at the wire boundary.

        Returns:
            Unix nanoseconds, preserving the first nine fractional digits.

        Raises:
            ValueError: The source timestamp cannot be parsed as an ISO instant.
        """
        instant = datetime.fromisoformat(source_time)
        seconds = instant.replace(microsecond=0) - datetime(1970, 1, 1, tzinfo=UTC)
        fraction: re.Match[str] | None = re.search(r"[.,](\d+)", source_time)
        digits = "" if fraction is None else source_time[fraction.start() + 1 : fraction.end()]
        nanos = 0 if not digits else int((digits + "000000000")[:9])
        return (seconds.days * 86400 + seconds.seconds) * 1_000_000_000 + nanos
