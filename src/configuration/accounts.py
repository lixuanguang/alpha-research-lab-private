"""Configure shared non-executable spot accounts and independent risk authority."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from typing import Literal

# project library imports
from financial_units import Money
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
