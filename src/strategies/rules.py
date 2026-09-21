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


class RuleFactory(Protocol):
    """Construct a fresh deterministic target-rule instance."""

    def __call__(self) -> TargetRule:
        """Construct one independent target-rule instance.

        Returns:
            Newly constructed target rule.
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


class Reversal:
    """Target the configured holding only after a strict fall between adjacent closes."""

    @property
    def identity(self) -> str:
        """Identify the fixed completed-price reversal formula.

        Returns:
            Versioned rule identity.
        """
        return "completed-price-reversal-v1"

    def target(
        self,
        previous: Observation | None,
        current: Observation,
        quantity: Quantity,
        cadence: timedelta,
    ) -> Quantity | None:
        """Compare frozen prices and buy after a strict fall.

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
            if current.point.price.value < previous.point.price.value
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


class RuleRegistry:
    """Resolve reviewed target-rule factories while isolating each consumer instance."""

    def __init__(self) -> None:
        """Register the built-in rules for the default research workflow."""
        self._factories: dict[str, RuleFactory] = {}
        self.register(Momentum)
        self.register(NoTrade)
        self.register(Reversal)

    @property
    def identities(self) -> tuple[str, ...]:
        """Return the registered identities in registration order.

        Returns:
            Stable identities available to this registry.
        """
        return tuple(self._factories)

    def register(self, factory: RuleFactory) -> None:
        """Register one zero-argument factory under its validated rule identity.

        Args:
            factory: Callable constructing a fresh target rule.

        Raises:
            ValueError: If the factory identity is invalid, duplicated or unstable,
                or if it returns the same instance during registration validation.
        """
        candidate = factory()
        identity = self._validate_identity(candidate.identity)
        if identity in self._factories:
            raise ValueError(f"duplicate target rule identity: {identity}")
        second = factory()
        if second is candidate:
            raise ValueError("target rule factory must return fresh instances")
        if self._validate_identity(second.identity) != identity:
            raise ValueError("target rule factory identity changed")
        self._factories[identity] = factory

    def resolve(self, identity: str) -> TargetRule:
        """Construct a fresh registered rule for one configured identity.

        Args:
            identity: Versioned target-rule identity from a backtest specification.

        Returns:
            New target-rule instance owned by the caller.

        Raises:
            ValueError: If the identity is invalid, unsupported or no longer stable.
        """
        self._validate_identity(identity)
        factory = self._factories.get(identity)
        if factory is None:
            raise ValueError(f"unsupported installed target rule: {identity}")
        rule = factory()
        if self._validate_identity(rule.identity) != identity:
            raise ValueError("target rule factory identity changed")
        return rule

    def supports(self, identity: str) -> bool:
        """Report whether a valid identity is registered.

        Args:
            identity: Candidate target-rule identity.

        Returns:
            Whether the identity resolves through this registry.
        """
        return type(identity) is str and bool(identity) and identity in self._factories

    @staticmethod
    def _validate_identity(identity: str) -> str:
        """Validate one stable nonempty rule identity.

        Args:
            identity: Candidate rule identity.

        Returns:
            The validated identity.

        Raises:
            ValueError: If the identity is empty or contains surrounding whitespace.
        """
        if type(identity) is not str or not identity or identity != identity.strip():
            raise ValueError("target rule identity must be a nonempty trimmed string")
        return identity
