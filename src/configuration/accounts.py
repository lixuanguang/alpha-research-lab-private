"""Configure shared non-executable spot accounts and independent risk authority."""

from __future__ import annotations

# standard library imports
import math
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal

# project library imports
from financial_units import DecimalGrid, Money, Price, Quantity
from reference_data.instruments import InstrumentId
from risk import BudgetPolicy, SpotLimits
from serialization import WireRecord


class OpeningAccount(WireRecord, frozen=True):
    """Declare independently funded initial currency balances for one paper account."""

    account_id: str
    cash: tuple[Money, ...]

    def __post_init__(self) -> None:
        """Require unique exact currencies and nonnegative initial funding."""
        if (
            type(self.account_id) is not str
            or not self.account_id
            or type(self.cash) is not tuple
            or not self.cash
        ):
            raise ValueError("opening account requires identity and currency balances")
        for cash in self.cash:
            if type(cash) is not Money:
                raise TypeError("opening cash requires exact Money")
            cash.model_copy()
            if cash.value < 0:
                raise ValueError("opening account cannot borrow")
        if len({cash.currency.code for cash in self.cash}) != len(self.cash):
            raise ValueError("opening currencies must be unique")


class InstrumentFeeRate(WireRecord, frozen=True):
    """Declare one instrument's worst-case proportional fee rate, such as the taker rate.

    Admission refuses an order whose fee reservation cannot pay this rate on its
    whole quantity at its limit, so a reserve is never sized below the fee the
    venue or paper model can charge at the order's own price.
    """

    instrument_id: InstrumentId
    rate: Decimal

    def __post_init__(self) -> None:
        """Require an exact rate in [0, 1)."""
        DecimalGrid.require_decimal(self.rate)
        if type(self.instrument_id) is not InstrumentId or not Decimal(0) <= self.rate < 1:
            raise ValueError("invalid instrument fee rate")

    def minimum_reserve(self, quantity: Quantity, limit: Price, lot: Quantity) -> Fraction:
        """Return the smallest fee reservation for ``quantity`` at ``limit``.

        The fee on the whole quantity at the limit, plus one minor unit per lot for
        the rounding of each possible fill. A sell filling above its limit can
        still cost more; the paper model then cancels a remainder it cannot pay.
        """
        exact = Fraction(quantity.value) * Fraction(limit.value) * Fraction(self.rate)
        if not self.rate:
            return exact
        lots = Fraction(quantity.value) / Fraction(lot.value)
        return exact + lots * Fraction(limit.currency.minor_unit)

    def paper_minimum_reserve(self, quantity: Quantity, limit: Price, lot: Quantity) -> Fraction:
        """Return the smallest reservation for fees the paper model rounds per fill.

        The paper model rounds each fill's fee half-even, so a fill adds at most half
        a minor unit, and only a fill whose own fee reaches half a minor unit can
        round up. Those fills' fees sum to at most the exact fee at the limit, so at
        most ``2 * exact / minor`` of them, and never more than one per lot, exist.
        A venue's own rounding is unknown, so venue accounts use ``minimum_reserve``.
        """
        exact = Fraction(quantity.value) * Fraction(limit.value) * Fraction(self.rate)
        if not self.rate:
            return exact
        minor = Fraction(limit.currency.minor_unit)
        lots = Fraction(quantity.value) / Fraction(lot.value)
        rounding_fills = min(math.floor(lots), math.floor(2 * exact / minor))
        return exact + rounding_fills * minor / 2


class AccountConfiguration(WireRecord, frozen=True):
    """Pin account state, spot mechanics and one explicit firm valuation currency.

    This authority controls local software admission only. ``venue_test`` provides
    a distinct state identity for a separately authorized test-venue gateway; it
    grants no physical access by itself. Other cash currencies can reconcile,
    but trading without a configured common valuation is rejected.
    """

    mode: Literal["paper", "shadow", "venue_test"]
    opening_at: datetime
    accounts: tuple[OpeningAccount, ...]
    instruments: tuple[SpotLimits, ...]
    budgets: BudgetPolicy
    # One worst-case fee rate for each configured instrument.
    fee_rates: tuple[InstrumentFeeRate, ...]
    schema_version: Literal["account-runtime"] = "account-runtime"

    def __post_init__(self) -> None:
        """Reject ambiguous ownership, incompatible funding and unsupported products."""
        self._require_utc(self.opening_at, field_name="opening account time")
        if type(self.budgets) is not BudgetPolicy:
            raise TypeError("account configuration requires BudgetPolicy")
        self.budgets.__post_init__()
        if (
            self.mode not in ("paper", "shadow", "venue_test")
            or self.schema_version != "account-runtime"
        ):
            raise ValueError("unsupported account runtime mode or schema")
        if (
            type(self.accounts) is not tuple
            or type(self.instruments) is not tuple
            or not self.accounts
            or not self.instruments
        ):
            raise ValueError("account runtime requires accounts and spot instruments")
        for account in self.accounts:
            if type(account) is not OpeningAccount:
                raise TypeError("account configuration requires OpeningAccount")
            account.__post_init__()
        for limits in self.instruments:
            if type(limits) is not SpotLimits:
                raise TypeError("account instruments require SpotLimits")
            limits.__post_init__()
            if limits.tick.currency != self.budgets.valuation_currency:
                raise ValueError("spot trading requires the explicit firm valuation currency")
        account_ids = {account.account_id for account in self.accounts}
        instrument_ids = {limits.maximum.dimension.instrument_id for limits in self.instruments}
        if type(self.fee_rates) is not tuple:
            raise ValueError("account runtime requires instrument fee rates")
        for fee_rate in self.fee_rates:
            if type(fee_rate) is not InstrumentFeeRate:
                raise TypeError("account fee rates require InstrumentFeeRate")
            fee_rate.__post_init__()
        if sorted(str(item.instrument_id) for item in self.fee_rates) != sorted(
            str(item) for item in instrument_ids
        ):
            raise ValueError("account runtime requires exactly one fee rate per instrument")
        if (
            len(account_ids) != len(self.accounts)
            or len(instrument_ids) != len(self.instruments)
            or account_ids != {account.account_id for account in self.budgets.accounts}
            or any(
                not set(instance.instruments).issubset(instrument_ids)
                for instance in self.budgets.instances
            )
            or any(
                self.budgets.valuation_currency not in tuple(c.currency for c in account.cash)
                for account in self.accounts
            )
        ):
            raise ValueError("account budget ownership, funding or instruments differ")

    def fee_rate(self, instrument_id: InstrumentId) -> InstrumentFeeRate:
        """Return the configured worst-case fee rate for one instrument."""
        for item in self.fee_rates:
            if item.instrument_id == instrument_id:
                return item
        raise ValueError("instrument has no configured fee rate")
