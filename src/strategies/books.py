"""Select isolated, versioned book rules with no risk or execution authority."""

from __future__ import annotations

# standard library imports
from decimal import Decimal
from fractions import Fraction
from typing import Protocol

# project library imports
from financial_units import Quantity
from research.observations import BookFeature


class BookRule(Protocol):
    """Consume only a delivered feature and return an absolute long-only target."""

    def target(self, feature: BookFeature, quantity: Quantity, threshold: Decimal) -> Quantity:
        """Select a holding without access to exchange state or unacknowledged fills.

        Args:
            feature: Latest feature delivered before this decision.
            quantity: Configured long target in base units.
            threshold: Explicit nonnegative imbalance entry threshold.

        Returns:
            Absolute long or flat target.
        """
        ...


class BookImbalance:
    """Buy when selected bid depth exceeds ask depth by the configured normalized threshold."""

    def target(self, feature: BookFeature, quantity: Quantity, threshold: Decimal) -> Quantity:
        """Compare an exact delivered imbalance without fitting on the sample.

        Args:
            feature: Valid delivered L2 feature.
            quantity: Configured positive base-unit target.
            threshold: Long only when imbalance is strictly greater than this value.

        Returns:
            Long target on a positive signal, otherwise flat.
        """
        ratio = feature.imbalance
        long = ratio is not None and Fraction(
            int(ratio.numerator), int(ratio.denominator)
        ) > Fraction(threshold)
        return quantity if long else Quantity(value=Decimal(0), dimension=quantity.dimension)


class BookNoTrade:
    """Keep the control flat through the same decision, risk, execution and accounting path."""

    def target(self, feature: BookFeature, quantity: Quantity, threshold: Decimal) -> Quantity:
        """Request zero holdings independently of the observed signal.

        Args:
            feature: Delivered feature retained for control diagnostics.
            quantity: Explicit instrument dimension.
            threshold: Unused control parameter retained in configuration.

        Returns:
            Exact flat target.
        """
        return Quantity(value=Decimal(0), dimension=quantity.dimension)


class BookRules:
    """Resolve registered stateless rule classes into independent instances."""

    def __init__(self) -> None:
        """Install the bounded L2 rule and no-trade control."""
        self._types: dict[str, type[BookRule]] = {
            "book-imbalance-v1": BookImbalance,
            "book-no-trade-v1": BookNoTrade,
        }

    def register(self, identity: str, rule: type[BookRule]) -> None:
        """Add a reviewed implementation without edits to shared orchestration.

        Args:
            identity: New versioned rule identifier.
            rule: Class creating fresh stateless rule instances.

        Raises:
            ValueError: The identifier is empty or already registered.
        """
        if not identity.strip() or identity in self._types:
            raise ValueError("empty or duplicate book rule identity")
        self._types[identity] = rule

    def resolve(self, identity: str) -> BookRule:
        """Create an independent instance of an explicitly selected rule.

        Args:
            identity: Installed versioned rule identifier.

        Returns:
            Fresh rule instance with no shared account state.

        Raises:
            ValueError: An unsupported implementation was selected.
        """
        if identity not in self._types:
            raise ValueError(f"unsupported book rule: {identity}")
        return self._types[identity]()
