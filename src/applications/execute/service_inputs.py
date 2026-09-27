"""Construct causal reference features for independently selected service instances."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import timedelta
from fractions import Fraction

# project library imports
from execution import AccountQuote, PaperMarket
from financial_units import ExactRatio
from research.features import FeatureVector
from research.observations import DecisionInputs, InputRequirement, NumericField
from runtime import SharedStrategyInput
from serialization import DomainCodec
from strategies import DecisionContext


class ServiceBookInputs:
    """Keep feature lineage stable when a controlled restart selects another instance."""

    fields = (
        NumericField(name="ask", units="quote/base"),
        NumericField(name="bid", units="quote/base"),
        NumericField(name="ask_size", units="base"),
    )

    def __init__(
        self, instances: tuple[str, ...], freshness_us: int, market_interval_us: int = 0
    ) -> None:
        """Bind selected consumers, source freshness and optional admission cadence."""
        if (
            type(freshness_us) is not int
            or freshness_us <= 0
            or type(market_interval_us) is not int
            or not 0 <= market_interval_us <= freshness_us
        ):
            raise ValueError("invalid service book freshness or market interval")
        self.instances, self.freshness_us = instances, freshness_us
        self.market_interval_us = market_interval_us

    @property
    def identity(self) -> str:
        """Identify the pure feature formula independently of active consumers."""
        definition: tuple[object, ...] = (
            "service-book-features-v1",
            self.fields,
            self.freshness_us,
        )
        if self.market_interval_us:
            definition = (*definition, self.market_interval_us)
        return hashlib.sha256(DomainCodec().encode_json(definition)).hexdigest()

    @property
    def requirement(self) -> InputRequirement:
        """Select the existing receipt-clock native-book projection."""
        return InputRequirement(
            name="book",
            family="book",
            field=NumericField(name="imbalance", units="dimensionless"),
            clock="receipt",
            max_age_us=self.freshness_us,
        )

    def build(self, inputs: DecisionInputs, market: PaperMarket) -> tuple[SharedStrategyInput, ...]:
        """Preserve native input identity and exact touch prices without inventing predictions."""
        at = inputs.decision_at
        vector = FeatureVector(
            entity=inputs.entity,
            decision_at=at,
            event_at=at,
            information_start=at,
            available_at=at,
            expires_at=at + timedelta(microseconds=self.freshness_us),
            definition=self.identity,
            fields=self.fields,
            values=tuple(
                ExactRatio.from_fraction(Fraction(value))
                for value in (
                    market.ask.value,
                    market.bid.value,
                    market.ask_quantity.value,
                )
            ),
            reasons=("native-touch",) * 3,
            input_identity=inputs.identity,
        )
        return tuple(
            SharedStrategyInput(
                instance_id=name,
                context=DecisionContext(features=vector, prediction=None),
                quote=AccountQuote(price=market.ask, at=at),
            )
            for name in self.instances
        )
