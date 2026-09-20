"""Retain exact dimensionless returns without ambient Decimal rounding."""

from __future__ import annotations

# standard library imports
import re
from fractions import Fraction

# third party library imports
import msgspec


class ExactRatio(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Encode a reduced rational as canonical base-10 integer strings."""

    numerator: str
    denominator: str

    def __post_init__(self) -> None:
        """Reject noncanonical integers, negative denominators and unreduced fractions."""
        if (
            type(self.numerator) is not str
            or re.fullmatch(r"0|-?[1-9][0-9]*", self.numerator) is None
            or type(self.denominator) is not str
            or re.fullmatch(r"[1-9][0-9]*", self.denominator) is None
        ):
            raise ValueError("ratio requires canonical integer strings and positive denominator")
        value = Fraction(int(self.numerator), int(self.denominator))
        if (str(value.numerator), str(value.denominator)) != (self.numerator, self.denominator):
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
