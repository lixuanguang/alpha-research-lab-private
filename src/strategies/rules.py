"""Produce absolute spot targets from two adjacent frozen completed observations."""

from __future__ import annotations

# standard library imports
from datetime import timedelta
from decimal import Decimal
from typing import Protocol

# project library imports
from financial_units import Quantity
from research.observations import Observation


class TargetRule(Protocol):
    """Require an explicit versioned rule identity and deterministic target operation."""

    @property
    def identity(self) -> str:
        """Identify formula/version independent of run or attempt.

        Returns:
            Stable reviewed implementation identifier.
        """
        ...

    def target(
        self,
        previous: Observation | None,
        current: Observation,
        quantity: Quantity,
        cadence: timedelta,
    ) -> Quantity | None:
        """Select a target or refuse an unavailable signal.

        Args:
            previous: Frozen previous close, absent during warm-up.
            current: Newly completed observation.
            quantity: Explicit positive strategy size.
            cadence: Required adjacency interval.

        Returns:
            Absolute target, or None for invalid input/warm-up.
        """
        ...


class Momentum:
    """Target the configured holding only after a strict rise between adjacent valid closes."""

    @property
    def identity(self) -> str:
        """Identify the fixed completed-price momentum formula.

        Returns:
            Versioned rule identity.
        """
        return "completed-price-momentum-v1"

    def target(
        self,
        previous: Observation | None,
        current: Observation,
        quantity: Quantity,
        cadence: timedelta,
    ) -> Quantity | None:
        """Compare frozen prices without approximating their exact return.

        Args:
            previous: Previous frozen observation, or None for warm-up.
            current: Current completed observation.
            quantity: Explicit positive long target.
            cadence: Required adjacent close interval.

        Returns:
            Long or flat target, or None for missing/nonadjacent observations.
        """
        if (
            previous is None
            or previous.point is None
            or current.point is None
            or current.closed_at - previous.closed_at != cadence
        ):
            return None
        return (
            quantity
            if current.point.price.value > previous.point.price.value
            else Quantity(value=Decimal(0), dimension=quantity.dimension)
        )


class NoTrade:
    """Provide the zero-target control through the identical independent risk and ledger path."""

    @property
    def identity(self) -> str:
        """Identify the deterministic flat control.

        Returns:
            Versioned control identity.
        """
        return "no-trade-v1"

    def target(
        self,
        previous: Observation | None,
        current: Observation,
        quantity: Quantity,
        cadence: timedelta,
    ) -> Quantity | None:
        """Request zero holdings while retaining observation diagnostics externally.

        Args:
            previous: Unused previous observation, retained by the shared consumer.
            current: Current completed observation.
            quantity: Dimension from explicit strategy configuration.
            cadence: Unused observation cadence shared with momentum.

        Returns:
            Exact zero target in the selected dimension.
        """
        return Quantity(value=Decimal(0), dimension=quantity.dimension)
