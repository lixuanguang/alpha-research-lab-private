"""Describe portable strategy intents without research or executable authority."""

from __future__ import annotations

# standard library imports
from typing import Literal

# project library imports
from financial_units import Money, Price, Quantity
from serialization import WireRecord


class TargetIntent(WireRecord, frozen=True, tag="target"):
    """Request an absolute position in explicit instrument units, subject to independent risk."""

    quantity: Quantity

    def __post_init__(self) -> None:
        """Retain the complete validated quantity dimension without float conversion."""
        if type(self.quantity) is not Quantity:
            raise TypeError("target requires Quantity")
        self.quantity.model_copy()


class ExposureIntent(WireRecord, frozen=True, tag="exposure"):
    """Request instrument exposure in a declared currency; valuation/allocation remains external."""

    exposure: Money

    def __post_init__(self) -> None:
        """Validate exact exposure currency and amount."""
        if type(self.exposure) is not Money:
            raise TypeError("exposure requires Money")
        self.exposure.model_copy()


class OrderIntent(WireRecord, frozen=True, tag="order"):
    """Request a positive limit order; no client ID, submission or account authority is implied."""

    side: Literal["buy", "sell"]
    quantity: Quantity
    limit: Price
    time_in_force: Literal["ioc", "gtc", "post-only"]

    def __post_init__(self) -> None:
        """Reject wrong units, nonpositive economics and unsupported order semantics."""
        if type(self.quantity) is not Quantity or type(self.limit) is not Price:
            raise TypeError("order requires Quantity and Price")
        self.quantity.model_copy()
        self.limit.model_copy()
        if (
            self.side not in ("buy", "sell")
            or self.time_in_force not in ("ioc", "gtc", "post-only")
            or self.quantity.value <= 0
            or self.limit.value <= 0
            or self.quantity.dimension != self.limit.per
        ):
            raise ValueError("invalid limit order intent")


class QuoteIntent(WireRecord, frozen=True, tag="quote"):
    """Request a two-sided quote whose independent orders still require portfolio/OMS admission."""

    bid: OrderIntent
    ask: OrderIntent

    def __post_init__(self) -> None:
        """Require compatible noncrossing buy/sell limits with resting semantics."""
        self.bid.__post_init__()
        self.ask.__post_init__()
        if (
            self.bid.side != "buy"
            or self.ask.side != "sell"
            or self.bid.limit.currency != self.ask.limit.currency
            or self.bid.limit.per != self.ask.limit.per
            or self.bid.limit.value >= self.ask.limit.value
            or self.bid.time_in_force == "ioc"
            or self.ask.time_in_force == "ioc"
        ):
            raise ValueError("invalid two-sided quote intent")


type DecisionIntent = TargetIntent | ExposureIntent | OrderIntent | QuoteIntent
