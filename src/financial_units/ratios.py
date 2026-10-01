"""Retain exact dimensionless returns without ambient Decimal rounding."""

from __future__ import annotations

# standard library imports
import re
from fractions import Fraction
from math import gcd

# third party library imports
import msgspec

_NUMERATOR = re.compile(r"0|-?[1-9][0-9]*")
_DENOMINATOR = re.compile(r"[1-9][0-9]*")


class ExactRatio(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Encode a reduced rational as canonical base-10 integer strings."""

    numerator: str
    denominator: str

    def __post_init__(self) -> None:
        """Reject noncanonical integers, negative denominators and unreduced fractions."""
        if (
            type(self.numerator) is not str
            or _NUMERATOR.fullmatch(self.numerator) is None
            or type(self.denominator) is not str
            or _DENOMINATOR.fullmatch(self.denominator) is None
        ):
            raise ValueError("ratio requires canonical integer strings and positive denominator")
        # Canonical strings with a positive denominator are reduced exactly when coprime;
        # gcd(0, d) is d, so zero must be 0/1.
        if gcd(int(self.numerator), int(self.denominator)) != 1:
            raise ValueError("ratio must be reduced; zero is 0/1")

    @classmethod
    def from_fraction(cls, value: Fraction) -> ExactRatio:
        """Retain an already exact calculation in canonical wire form.

        Args:
            value: Exact dimensionless result, without prior float or Decimal division.

        Returns:
            Reduced numerator and denominator strings.

        Raises:
            TypeError: The caller supplies an approximate or unsupported value.
        """
        if type(value) is not Fraction:
            raise TypeError("ratio requires Fraction")
        return cls(numerator=str(value.numerator), denominator=str(value.denominator))
