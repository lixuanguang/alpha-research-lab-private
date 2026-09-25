"""Bind dedicated paper accounts to explicit spot mechanics and independent limits."""

from __future__ import annotations

# standard library imports
import hashlib
from decimal import Decimal
from typing import Literal

# project library imports
from financial_units import DecimalGrid, Money, Price, Quantity, QuantityKind
from serialization import DomainCodec, WireRecord


class PaperConfiguration(WireRecord, frozen=True):
    """Select a non-executable account and a declared top-of-book fill scenario.

    Limits, tick and lot are authored simulation assumptions, not venue
    qualification. Initial cash starts a flat dedicated account. Maximum fee is
    reserved per child order; actual fees use the explicit rate and half-even
    quote-currency rounding. Only one instance/instrument can own this account.
    """

    account: str
    mode: Literal["paper", "shadow"]
    initial_cash: Money
    maximum: Quantity
    lot: Quantity
    tick: Price
    maximum_fee: Money
    fee_rate: Decimal
    market_max_age_us: int
    schema_version: Literal["paper-runtime-v1"] = "paper-runtime-v1"

    def __post_init__(self) -> None:
        """Reject executable modes, incompatible units and unbounded market freshness."""
        if (
            self.schema_version != "paper-runtime-v1"
            or self.mode not in ("paper", "shadow")
            or type(self.account) is not str
            or not self.account.strip()
        ):
            raise ValueError("invalid paper account or schema")
        for value in (self.initial_cash, self.maximum, self.lot, self.tick, self.maximum_fee):
            value.model_copy()
        DecimalGrid.require_decimal(self.fee_rate)
        if (
            self.initial_cash.value < 0
            or self.maximum.value <= 0
            or self.lot.value <= 0
            or self.tick.value <= 0
            or self.maximum_fee.value < 0
            or not Decimal(0) <= self.fee_rate < Decimal(1)
            or self.maximum.dimension.kind != QuantityKind.BASE_UNIT
            or self.maximum.dimension != self.lot.dimension
            or self.tick.per != self.maximum.dimension
            or self.tick.currency != self.initial_cash.currency
            or self.maximum_fee.currency != self.initial_cash.currency
            or type(self.market_max_age_us) is not int
            or not 0 < self.market_max_age_us <= 86_400_000_000
        ):
            raise ValueError("invalid paper economics or freshness")

    @property
    def identity(self) -> str:
        """Bind the full non-secret resolved operating scenario to durable state."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()
