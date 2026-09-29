"""Post identified spot fills exactly and reconcile two independent P&L attributions."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from decimal import Decimal
from fractions import Fraction

# third party library imports
from msgspec.structs import force_setattr

# project library imports
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity
from serialization import WireRecord


class RationalMoney(WireRecord, frozen=True):
    """Retain exact proportional attribution in an explicit currency."""

    amount: ExactRatio
    currency: Currency

    def __post_init__(self) -> None:
        """Reject malformed rational or currency values."""
        if type(self.amount) is not ExactRatio or type(self.currency) is not Currency:
            raise TypeError("rational money requires exact ratio and currency")
        self.amount.__post_init__()
        self.currency.validate_currency()

    @classmethod
    def create(cls, value: Fraction, currency: Currency) -> RationalMoney:
        """Bind an exact attribution to its currency.

        Args:
            value: Unrounded rational amount.
            currency: Complete quote currency, including quantum.

        Returns:
            Canonical currency-bearing attribution.
        """
        return cls(amount=ExactRatio.from_fraction(value), currency=currency)

    @property
    def value(self) -> Fraction:
        """Return the exact amount for reconciliation.

        Returns:
            Reduced rational, never a Decimal approximation.
        """
        return Fraction(int(self.amount.numerator), int(self.amount.denominator))


class Fill(WireRecord, frozen=True):
    """Identify one complete signed spot fill, with reference and effective prices."""

    identity: str
    decision_at: datetime
    filled_at: datetime
    quantity: Quantity
    reference: Price
    effective: Price
    fee: Money

    def __post_init__(self) -> None:
        """Reject invalid clocks, dimensions, costs and nonpositive execution prices."""
        self._require_utc(self.decision_at, field_name="decision_at")
        self._require_utc(self.filled_at, field_name="filled_at")
        if (
            type(self.identity) is not str
            or not self.identity
            or self.filled_at <= self.decision_at
        ):
            raise ValueError("fill requires identity and strictly positive decision delay")
        for value, kind in (
            (self.quantity, Quantity),
            (self.reference, Price),
            (self.effective, Price),
            (self.fee, Money),
        ):
            if type(value) is not kind:
                raise TypeError("fill requires exact financial values")
            value.model_copy()
        if (
            self.quantity.value == 0
            or self.reference.value <= 0
            or self.effective.value <= 0
            or self.fee.value < 0
            or self.reference.per != self.quantity.dimension
            or self.effective.per != self.quantity.dimension
            or self.reference.currency != self.effective.currency
            or self.fee.currency != self.reference.currency
            or (Fraction(self.effective.value) - Fraction(self.reference.value))
            * Fraction(self.quantity.value)
            < 0
        ):
            raise ValueError("fill has incompatible dimensions or unsupported favorable cost")


class LedgerState(WireRecord, frozen=True):
    """Retain initial capital and every applied identity for deterministic ledger recovery."""

    initial_cash: Money
    dimension: Dimension
    fills: tuple[Fill, ...] = ()
    schema_version: str = "spot-ledger"

    def __post_init__(self) -> None:
        """Reject invalid initial state or duplicate applied identities."""
        if self.schema_version != "spot-ledger" or type(self.initial_cash) is not Money:
            raise ValueError("unsupported spot ledger state")
        self.initial_cash.model_copy()
        if type(self.dimension) is not Dimension or type(self.fills) is not tuple:
            raise TypeError("ledger requires a dimension and immutable fills")
        self.dimension.model_copy()
        if self.initial_cash.value < 0:
            raise ValueError("initial cash cannot be negative")
        identities: set[str] = set()
        for fill in self.fills:
            if type(fill) is not Fill:
                raise TypeError("ledger requires Fill records")
            fill.__post_init__()
            if fill.identity in identities:
                raise ValueError("duplicate applied fill identity")
            identities.add(fill.identity)


class LedgerBalance(WireRecord, frozen=True):
    """Expose exact holdings and costs, with instrument-bound rational basis."""

    cash: Money
    holding: Quantity
    basis: RationalMoney
    realized: RationalMoney
    reference_basis: RationalMoney
    reference_realized: RationalMoney
    fees: Money
    slippage: Money
    turnover: Money

    def __post_init__(self) -> None:
        """Keep cash, quantities and attribution in one consistent nonnegative spot state."""
        if type(self.holding) is not Quantity:
            raise TypeError("balance requires exact holdings")
        self.holding.model_copy()
        for value in (self.cash, self.fees, self.slippage, self.turnover):
            if type(value) is not Money:
                raise TypeError("balance requires exact money")
            value.model_copy()
            if value.currency != self.cash.currency or value.value < 0:
                raise ValueError("balance has incompatible or negative cash/costs")
        for attribution in (
            self.basis,
            self.realized,
            self.reference_basis,
            self.reference_realized,
        ):
            if type(attribution) is not RationalMoney:
                raise TypeError("balance requires currency-bearing rational attribution")
            attribution.__post_init__()
            if attribution.currency != self.cash.currency:
                raise ValueError("balance attribution currency mismatch")
        if self.holding.value < 0 or self.basis.value < 0 or self.reference_basis.value < 0:
            raise ValueError("short holdings or negative basis are unsupported")
        if self.holding.value == 0 and (self.basis.value or self.reference_basis.value):
            raise ValueError("flat holdings must have zero basis")


class LedgerMark(WireRecord, frozen=True):
    """Retain reconciled NAV and effective-price and reference-price attribution."""

    nav: Money
    unrealized: RationalMoney
    gross: RationalMoney
    net: Money

    def __post_init__(self) -> None:
        """Require finite exact valuation and common attribution currency."""
        for money in (self.nav, self.net):
            if type(money) is not Money:
                raise TypeError("ledger mark requires exact money")
            money.model_copy()
        for ratio in (self.unrealized, self.gross):
            if type(ratio) is not RationalMoney:
                raise TypeError("ledger mark requires rational attribution")
            ratio.__post_init__()
        if self.nav.value < 0 or any(
            value.currency != self.nav.currency for value in (self.net, self.unrealized, self.gross)
        ):
            raise ValueError("inconsistent ledger mark currencies or negative NAV")


class Ledger:
    """Own atomic postings; rejected fills cannot change cash, holdings or applied IDs."""

    def __init__(self, state: LedgerState) -> None:
        """Reconstruct the exact ledger from its complete validated posting history.

        Args:
            state: Initial capital, position dimension and ordered applied fills.

        Raises:
            ValueError: State is inconsistent, disallowed or unreconciled.
        """
        state.__post_init__()
        self._initial = state.initial_cash.model_copy()
        self._dimension = state.dimension.model_copy()
        # Applied fills in order, their identities for constant-time duplicate
        # refusal, and the last state built from them (cleared on every apply).
        self._fills: list[Fill] = []
        self._fill_ids: set[str] = set()
        self._state: LedgerState | None = None
        zero = Money(value=Decimal(0), currency=self._initial.currency)
        ratio = RationalMoney.create(Fraction(0), self._initial.currency)
        self._balance = LedgerBalance(
            cash=self._initial,
            holding=Quantity(value=Decimal(0), dimension=self._dimension),
            basis=ratio,
            realized=ratio,
            reference_basis=ratio,
            reference_realized=ratio,
            fees=zero,
            slippage=zero,
            turnover=zero,
        )
        for fill in state.fills:
            self.apply(fill)

    @property
    def state(self) -> LedgerState:
        """Return complete economic restart state.

        Every fill was validated, and its identity and order checked, when it was
        applied, so the state attaches them without validating each fill again;
        that repeated check made every read linear in the retained fill count.

        Returns:
            Immutable capital, dimension and applied postings.
        """
        if self._state is None:
            state = LedgerState(initial_cash=self._initial, dimension=self._dimension)
            fills: tuple[Fill, ...] = tuple(self._fills)
            force_setattr(state, "fills", fills)
            self._state = state
        return self._state

    def copy(self) -> Ledger:
        """Return an independent ledger with the same validated postings, without replay.

        Returns:
            A ledger whose later postings do not affect this one.
        """
        duplicate = Ledger.__new__(Ledger)
        duplicate._initial, duplicate._dimension = self._initial, self._dimension
        duplicate._fills, duplicate._fill_ids = list(self._fills), set(self._fill_ids)
        duplicate._state, duplicate._balance = self._state, self._balance
        return duplicate

    @property
    def balance(self) -> LedgerBalance:
        """Expose immutable current balances.

        Returns:
            Cash, holdings, attribution and accumulated costs.
        """
        return self._balance

    def apply(self, fill: Fill) -> LedgerBalance:
        """Apply one accepted fill atomically without borrowing, shorting or duplicate posting.

        Args:
            fill: Complete positive-delay fill in this ledger's dimension and currency.

        Returns:
            New exact balances after successful posting.

        Raises:
            ValueError: A duplicate, incompatible, out-of-order or unaffordable fill is refused.
        """
        fill.__post_init__()
        before = self._balance
        if (
            fill.quantity.dimension != self._dimension
            or fill.fee.currency != self._initial.currency
            or fill.identity in self._fill_ids
            or (self._fills and fill.filled_at < self._fills[-1].filled_at)
        ):
            raise ValueError("duplicate, incompatible or out-of-order fill")
        notional = fill.effective.amount(fill.quantity)
        reference = fill.reference.amount(fill.quantity)
        cash = before.cash - notional - fill.fee
        holding = before.holding + fill.quantity
        if cash.value < 0 or holding.value < 0:
            raise ValueError("insufficient cash or overselling")
        basis, realized = self._attribute(
            before.basis.value, before.realized.value, fill.quantity, before.holding, notional
        )
        ref_basis, ref_realized = self._attribute(
            before.reference_basis.value,
            before.reference_realized.value,
            fill.quantity,
            before.holding,
            reference,
        )
        currency = cash.currency
        after = LedgerBalance(
            cash=cash,
            holding=holding,
            basis=RationalMoney.create(basis, currency),
            realized=RationalMoney.create(realized, currency),
            reference_basis=RationalMoney.create(ref_basis, currency),
            reference_realized=RationalMoney.create(ref_realized, currency),
            fees=before.fees + fill.fee,
            slippage=before.slippage + notional - reference,
            turnover=before.turnover + Money(value=notional.value.copy_abs(), currency=currency),
        )
        self._balance = after
        self._fills.append(fill)
        self._fill_ids.add(fill.identity)
        self._state = None
        return after

    @staticmethod
    def _attribute(
        basis: Fraction, realized: Fraction, delta: Quantity, previous: Quantity, notional: Money
    ) -> tuple[Fraction, Fraction]:
        """Release proportional basis exactly; fees never enter purchase basis."""
        if delta.value > 0:
            return basis + Fraction(notional.value), realized
        released = basis * -Fraction(delta.value) / Fraction(previous.value)
        return basis - released, realized - Fraction(notional.value) - released

    def mark(self, price: Price | None) -> LedgerMark:
        """Reconcile terminal or intermediate NAV without inventing liquidation.

        Args:
            price: Eligible fresh positive quote, required only for an open position.

        Returns:
            Exact NAV, net change and two reconciled attributions.

        Raises:
            ValueError: Required valuation is missing, incompatible or fails reconciliation.
        """
        balance = self._balance
        value = Money(value=Decimal(0), currency=self._initial.currency)
        if balance.holding.value:
            if price is None or price.value <= 0:
                raise ValueError("open position requires a valid valuation price")
            value = price.amount(balance.holding)
        nav = balance.cash + value
        net = nav - self._initial
        unrealized = Fraction(value.value) - balance.basis.value
        gross = (
            balance.reference_realized.value + Fraction(value.value) - balance.reference_basis.value
        )
        if balance.realized.value + unrealized - Fraction(balance.fees.value) != Fraction(
            net.value
        ) or gross - Fraction(balance.slippage.value) - Fraction(balance.fees.value) != Fraction(
            net.value
        ):
            raise ValueError("spot NAV attribution does not reconcile")
        return LedgerMark(
            nav=nav,
            net=net,
            unrealized=RationalMoney.create(unrealized, nav.currency),
            gross=RationalMoney.create(gross, nav.currency),
        )
