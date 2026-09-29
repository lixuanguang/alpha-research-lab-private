"""Share the exact return of adjacent frozen completed-price observations."""

from __future__ import annotations

# standard library imports
from datetime import timedelta
from fractions import Fraction
from typing import Literal

# project library imports
from financial_units import ExactRatio
from research.observations import Observation
from serialization import WireRecord


class CompletedReturn(WireRecord, frozen=True):
    """Version the P1 completed-close formula separately from observed-trade windows."""

    cadence_seconds: int
    schema_version: Literal["completed-price-return"] = "completed-price-return"

    def __post_init__(self) -> None:
        """Reject unsupported formula versions and nonpositive cadence."""
        if (
            self.schema_version != "completed-price-return"
            or type(self.cadence_seconds) is not int
            or self.cadence_seconds <= 0
        ):
            raise ValueError("completed return requires its version and positive cadence")

    def evaluate(self, previous: Observation | None, current: Observation) -> ExactRatio | None:
        """Calculate an exact dimensionless return without revising either endpoint.

        Args:
            previous: Frozen preceding close, or None during warm-up.
            current: Newly frozen close with explicit missingness.

        Returns:
            Exact current/previous minus one, or None for missing/nonadjacent endpoints.

        Raises:
            ValueError: Endpoint units differ or a supposedly valid price is nonpositive.
        """
        self.__post_init__()
        current.__post_init__()
        if previous is None:
            return None
        previous.__post_init__()
        if (
            previous.point is None
            or current.point is None
            or current.closed_at - previous.closed_at != timedelta(seconds=self.cadence_seconds)
        ):
            return None
        left, right = previous.point.price, current.point.price
        if left.currency != right.currency or left.per != right.per:
            raise ValueError("completed return endpoint units differ")
        if left.value <= 0 or right.value <= 0:
            raise ValueError("completed return requires positive endpoint prices")
        return ExactRatio.from_fraction(Fraction(right.value) / Fraction(left.value) - 1)
