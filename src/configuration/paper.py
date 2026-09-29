"""Bind dedicated paper accounts to explicit spot mechanics and independent limits."""

from __future__ import annotations

# standard library imports
import hashlib
from decimal import Decimal
from fractions import Fraction
from typing import Literal

# project library imports
from financial_units import DecimalGrid, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from serialization import DomainCodec, WireRecord


class PaperExecutionScenario(WireRecord, frozen=True):
    """Declare authored spot paper economics without implying venue execution fidelity."""

    venue: Literal["okx", "bitfinex"]
    instrument_id: InstrumentId
    entry_delay_us: int
    cancel_delay_us: int
    adverse: Price
    fee_rate: Decimal
    take_fraction: Decimal
    gas_inapplicable_reason: str
    schema_version: Literal["paper-execution"] = "paper-execution"

    def __post_init__(self) -> None:
        """Require exact supported off-chain costs and bounded modeled delays."""
        self.adverse.model_copy()
        DecimalGrid.require_decimal(self.fee_rate)
        DecimalGrid.require_decimal(self.take_fraction)
        if (
            self.schema_version != "paper-execution"
            or self.venue not in ("okx", "bitfinex")
            or type(self.instrument_id) is not InstrumentId
            or self.adverse.per.instrument_id != self.instrument_id
            or self.adverse.value < 0
            or not Decimal(0) <= self.fee_rate < Decimal(1)
            or not Decimal(0) < self.take_fraction <= Decimal(1)
            or type(self.entry_delay_us) is not int
            or type(self.cancel_delay_us) is not int
            or not 0 <= self.entry_delay_us <= 86_400_000_000
            or not 0 <= self.cancel_delay_us <= 86_400_000_000
            or type(self.gas_inapplicable_reason) is not str
            or not self.gas_inapplicable_reason.strip()
        ):
            raise ValueError("invalid paper execution scenario")

    @property
    def identity(self) -> str:
        """Pin every non-secret authored cost and delay to retained paper state."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


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
    execution: PaperExecutionScenario
    schema_version: Literal["paper-runtime"] = "paper-runtime"

    def __post_init__(self) -> None:
        """Reject executable modes, incompatible units and unbounded market freshness."""
        if (
            self.schema_version != "paper-runtime"
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
        if type(self.execution) is not PaperExecutionScenario:
            raise TypeError("paper configuration requires an execution scenario")
        self.execution.__post_init__()
        if (
            self.execution.instrument_id != self.maximum.dimension.instrument_id
            or self.execution.adverse.per != self.maximum.dimension
            or self.execution.adverse.currency != self.tick.currency
            or self.execution.fee_rate != self.fee_rate
            or (Fraction(self.execution.adverse.value) / Fraction(self.tick.value)).denominator != 1
        ):
            raise ValueError("paper execution scenario has incompatible units")

    @property
    def identity(self) -> str:
        """Bind the full non-secret resolved operating scenario to durable state."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()
