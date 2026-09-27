"""Value complete paper spot accounts with explicit marks and cost provenance."""

from __future__ import annotations

# standard library imports
from datetime import datetime, timedelta
from fractions import Fraction

# project library imports
from accounting.accounts import (
    AccountLedger,
    AccountSnapshot,
    AccountState,
    EffectiveAccountPosting,
)
from accounting.ledger import Fill
from financial_units import Currency, DecimalGrid, Dimension, Money, Price, Quantity
from serialization import WireRecord


class PaperPositionMark(WireRecord, frozen=True):
    """Identify a price at its effective availability time for one spot holding."""

    identity: str
    available_at: datetime
    price: Price

    def __post_init__(self) -> None:
        """Require a positive dimensioned price and a UTC availability clock."""
        self._require_utc(self.available_at, field_name="mark availability")
        if type(self.identity) is not str or not self.identity or type(self.price) is not Price:
            raise ValueError("paper mark requires identity and exact price")
        self.price.model_copy()
        if self.price.value <= 0:
            raise ValueError("paper mark price must be positive")


class AttributedPaperFill(WireRecord, frozen=True):
    """Bind a retained direct or child fill to its strategy and account order."""

    instance_id: str
    order_id: str
    fill: Fill

    def __post_init__(self) -> None:
        """Require stable attribution and a complete exact fill."""
        if (
            type(self.instance_id) is not str
            or not self.instance_id
            or type(self.order_id) is not str
            or not self.order_id
            or type(self.fill) is not Fill
        ):
            raise ValueError("paper fill requires instance, order and retained Fill")
        self.fill.__post_init__()


class PaperCostEvidence(WireRecord, frozen=True):
    """Name one positive charge or negative rebate, or an explicit zero-cost fill."""

    source_fill_id: str
    posting_id: str | None
    amount: Money

    def __post_init__(self) -> None:
        """Require a signed native amount and an ID for every nonzero cost."""
        if (
            type(self.source_fill_id) is not str
            or not self.source_fill_id
            or type(self.amount) is not Money
        ):
            raise ValueError("paper cost requires source fill and exact amount")
        self.amount.model_copy()
        if self.posting_id is None:
            if self.amount.value != 0:
                raise ValueError("nonzero paper cost requires a posting identity")
        elif type(self.posting_id) is not str or not self.posting_id or self.amount.value == 0:
            raise ValueError("paper cost posting requires a nonzero amount and identity")


class PaperGasPolicy(WireRecord, frozen=True):
    """Record the scenario's explicit off-chain gas inapplicability decision."""

    scenario_id: str
    applicable: bool
    reason: str

    def __post_init__(self) -> None:
        """Refuse unbooked on-chain gas under the bounded spot paper contract."""
        if (
            type(self.scenario_id) is not str
            or not self.scenario_id
            or type(self.applicable) is not bool
            or type(self.reason) is not str
            or not self.reason.strip()
        ):
            raise ValueError("paper gas policy requires scenario and explicit reason")
        if self.applicable:
            raise ValueError("applicable gas requires an implemented activity and posting contract")


class PaperMarkedPosition(WireRecord, frozen=True):
    """Retain an exact holding value and the eligible mark used to obtain it."""

    position: Quantity
    mark: PaperPositionMark
    value: Money

    def __post_init__(self) -> None:
        """Require one positive position valued at its own dimensioned mark."""
        if (
            type(self.position) is not Quantity
            or type(self.mark) is not PaperPositionMark
            or type(self.value) is not Money
        ):
            raise TypeError("marked paper position requires exact values")
        self.position.model_copy()
        self.mark.__post_init__()
        self.value.model_copy()
        if (
            self.position.value <= 0
            or self.mark.price.per != self.position.dimension
            or self.value != self.mark.price.amount(self.position)
        ):
            raise ValueError("marked paper position has incompatible or inexact value")


class PaperCurrencyResult(WireRecord, frozen=True):
    """Expose exact NAV change and separately disclosed execution slippage."""

    currency: Currency
    position_value: Money
    nav: Money
    net_pnl: Money
    slippage: Money

    def __post_init__(self) -> None:
        """Require exact same-currency values and nonnegative marked inventory."""
        if type(self.currency) is not Currency:
            raise TypeError("paper currency result requires exact currency")
        self.currency.validate_currency()
        for amount in (self.position_value, self.nav, self.net_pnl, self.slippage):
            if type(amount) is not Money:
                raise TypeError("paper currency result requires exact money")
            amount.model_copy()
            if amount.currency != self.currency:
                raise ValueError("paper currency result has mixed currencies")
        if self.position_value.value < 0 or self.slippage.value < 0:
            raise ValueError("paper marked value or adverse slippage cannot be negative")


class PaperScopeReport(WireRecord, frozen=True):
    """Retain one account or strategy's owned postings and marked economics."""

    snapshot: AccountSnapshot
    positions: tuple[PaperMarkedPosition, ...]
    currencies: tuple[PaperCurrencyResult, ...]

    def __post_init__(self) -> None:
        """Require one result per declared cash currency and open holding."""
        if (
            type(self.snapshot) is not AccountSnapshot
            or type(self.positions) is not tuple
            or type(self.currencies) is not tuple
        ):
            raise TypeError("paper scope requires account snapshot and immutable results")
        self.snapshot.__post_init__()
        if len(self.positions) != len(self.snapshot.positions) or len(self.currencies) != len(
            self.snapshot.cash
        ):
            raise ValueError("paper scope omits a holding or currency")
        for position, held in zip(self.positions, self.snapshot.positions, strict=True):
            if type(position) is not PaperMarkedPosition:
                raise TypeError("paper scope requires marked position values")
            position.__post_init__()
            if position.position != held:
                raise ValueError("paper scope holding differs from account snapshot")
        for result, cash, transfer in zip(
            self.currencies, self.snapshot.cash, self.snapshot.transfers, strict=True
        ):
            if type(result) is not PaperCurrencyResult:
                raise TypeError("paper scope requires currency results")
            result.__post_init__()
            if (
                result.currency != cash.currency
                or Fraction(result.position_value.value)
                != sum(
                    (
                        Fraction(position.value.value)
                        for position in self.positions
                        if position.value.currency == cash.currency
                    ),
                    Fraction(0),
                )
                or result.nav != cash + result.position_value
                or result.net_pnl != result.nav - transfer
            ):
                raise ValueError("paper scope NAV does not reconcile to account postings")


class PaperAccountReport(WireRecord, frozen=True):
    """Version a complete current account report for query and metric consumers."""

    cutoff: datetime
    max_mark_age_us: int
    gas_policy: PaperGasPolicy
    account: PaperScopeReport
    instances: tuple[PaperScopeReport, ...]
    schema_version: str = "paper-account-report-v1"

    def __post_init__(self) -> None:
        """Require a versioned cutoff and account-scoped immutable projections."""
        self._require_utc(self.cutoff, field_name="paper report cutoff")
        if (
            self.schema_version != "paper-account-report-v1"
            or type(self.max_mark_age_us) is not int
            or self.max_mark_age_us < 0
            or self.max_mark_age_us > 2**63 - 1
            or type(self.gas_policy) is not PaperGasPolicy
            or type(self.account) is not PaperScopeReport
            or type(self.instances) is not tuple
        ):
            raise ValueError("invalid paper account report contract")
        self.gas_policy.__post_init__()
        self.account.__post_init__()
        if self.account.snapshot.instance_id is not None:
            raise ValueError("paper account report requires a physical account scope")
        marks = {position.position.dimension: position.mark for position in self.account.positions}
        max_age = timedelta(microseconds=self.max_mark_age_us)
        if any(
            mark.available_at > self.cutoff or self.cutoff - mark.available_at > max_age
            for mark in marks.values()
        ):
            raise ValueError("paper report contains a future or stale mark")
        instance_ids: set[str] = set()
        for instance in self.instances:
            if type(instance) is not PaperScopeReport:
                raise TypeError("paper report requires instance scopes")
            instance.__post_init__()
            identity = instance.snapshot.instance_id
            if (
                identity is None
                or identity in instance_ids
                or instance.snapshot.account_id != self.account.snapshot.account_id
                or any(
                    marks.get(position.position.dimension) != position.mark
                    for position in instance.positions
                )
            ):
                raise ValueError("paper report has duplicate or mismatched instance")
            instance_ids.add(identity)
        PaperAccountReporter._reconcile_scopes(self.account, self.instances)


class PaperAccountReporter:
    """Reconcile exact current postings, retained fills, costs and fresh marks."""

    def build(
        self,
        state: AccountState,
        *,
        cutoff: datetime,
        max_mark_age: timedelta,
        marks: tuple[PaperPositionMark, ...],
        fills: tuple[AttributedPaperFill, ...],
        costs: tuple[PaperCostEvidence, ...],
        gas_policy: PaperGasPolicy,
    ) -> PaperAccountReport:
        """Return marked account and strategy NAV changes in native currencies.

        Net P&L is cash plus marked inventory less explicit transfers. Posted
        fees and rebates are already in cash or inventory; execution slippage
        is an attribution from reference to effective fill price and is not
        subtracted again. No currency conversion or source-time freshness is
        inferred from availability timestamps.

        Args:
            state: Complete current account history, with no facts after cutoff.
            cutoff: UTC knowledge cutoff for postings, fills and marks.
            max_mark_age: Largest accepted age since mark availability.
            marks: Exactly one current eligible mark per open dimension.
            fills: Every current direct or child Fill with its owner.
            costs: Complete current fee/rebate posting evidence and zero-fee fills.
            gas_policy: Explicit off-chain scenario applicability decision.

        Returns:
            Exact versioned account and per-instance report.

        Raises:
            ValueError: A mark, fill, cost or time is incomplete or inconsistent.
        """
        if type(state) is not AccountState or type(gas_policy) is not PaperGasPolicy:
            raise TypeError("paper report requires account state and gas policy")
        state.__post_init__()
        gas_policy.__post_init__()
        PaperAccountReport._require_utc(cutoff, field_name="paper report cutoff")
        if type(max_mark_age) is not timedelta or max_mark_age < timedelta(0):
            raise ValueError("paper mark maximum age must be a nonnegative duration")
        if max_mark_age // timedelta(microseconds=1) > 2**63 - 1:
            raise ValueError("paper mark maximum age exceeds the report wire range")
        if any(type(values) is not tuple for values in (marks, fills, costs)):
            raise TypeError("paper report inputs must be immutable tuples")
        ledger = AccountLedger(state)
        effective = ledger.effective_postings()
        if any(posting.known_at > cutoff for posting in state.postings):
            raise ValueError("paper report state contains knowledge after cutoff")
        fill_by_id = self._validate_fills(state, effective, fills, cutoff)
        self._validate_costs(state, effective, costs, fill_by_id)
        eligible_marks = self._validate_marks(
            ledger.snapshot(), effective, marks, cutoff, max_mark_age, state.currencies
        )
        account = self._scope(ledger.snapshot(), eligible_marks, fill_by_id)
        instance_ids = sorted(
            {posting.instance_id for posting in state.postings if posting.instance_id is not None}
        )
        instances = tuple(
            self._scope(ledger.snapshot(instance_id), eligible_marks, fill_by_id)
            for instance_id in instance_ids
        )
        return PaperAccountReport(
            cutoff=cutoff,
            max_mark_age_us=max_mark_age // timedelta(microseconds=1),
            gas_policy=gas_policy,
            account=account,
            instances=instances,
        )

    @staticmethod
    def _validate_fills(
        state: AccountState,
        effective: tuple[EffectiveAccountPosting, ...],
        fills: tuple[AttributedPaperFill, ...],
        cutoff: datetime,
    ) -> dict[str, AttributedPaperFill]:
        """Match each retained fill to exactly one current account posting."""
        postings = {item.identity: item for item in effective if item.kind == "fill"}
        fill_by_id: dict[str, AttributedPaperFill] = {}
        for attributed in fills:
            if type(attributed) is not AttributedPaperFill:
                raise TypeError("paper report requires attributed Fill records")
            attributed.__post_init__()
            fill = attributed.fill
            posting = postings.get(fill.identity)
            if (
                fill.identity in fill_by_id
                or posting is None
                or posting.account_id != state.account_id
                or posting.instance_id != attributed.instance_id
                or posting.order_id != attributed.order_id
                or posting.event_at != fill.filled_at
                or posting.quantity != fill.quantity
                or posting.price != fill.effective
                or fill.filled_at > cutoff
            ):
                raise ValueError("retained paper fill disagrees with current account posting")
            fill_by_id[fill.identity] = attributed
            if fill.fee.value:
                original_fee = next(
                    (item for item in state.postings if item.identity == f"fee:{fill.identity}"),
                    None,
                )
                if (
                    original_fee is None
                    or original_fee.effective_kind != "fee"
                    or original_fee.cash.currency != fill.fee.currency
                    or original_fee.cash.value != -fill.fee.value
                ):
                    raise ValueError("retained paper fill lacks its original posted fee")
        if set(fill_by_id) != set(postings):
            raise ValueError("paper report requires every current direct or child fill")
        return fill_by_id

    @staticmethod
    def _validate_costs(
        state: AccountState,
        effective: tuple[EffectiveAccountPosting, ...],
        costs: tuple[PaperCostEvidence, ...],
        fills: dict[str, AttributedPaperFill],
    ) -> None:
        """Require explicit one-to-one coverage of current native fee economics."""
        postings = {item.identity: item for item in effective if item.kind in ("fee", "rebate")}
        seen: set[str] = set()
        covered_fills: set[str] = set()
        declared_currencies = set(state.currencies)
        for evidence in costs:
            if type(evidence) is not PaperCostEvidence:
                raise TypeError("paper report requires cost evidence records")
            evidence.__post_init__()
            if evidence.amount.currency not in declared_currencies:
                raise ValueError("paper cost currency is not declared by account")
            if evidence.source_fill_id in fills:
                covered_fills.add(evidence.source_fill_id)
            if evidence.posting_id is None:
                if evidence.source_fill_id not in fills:
                    raise ValueError("zero paper cost requires a retained child or direct fill")
                continue
            posting = postings.get(evidence.posting_id)
            if (
                evidence.posting_id in seen
                or posting is None
                or posting.cash.currency != evidence.amount.currency
                or posting.cash.value != -evidence.amount.value
                or posting.instance_id is None
                or posting.order_id is None
            ):
                raise ValueError("paper cost evidence disagrees with current owned posting")
            attributed = fills.get(evidence.source_fill_id)
            if attributed is not None and (
                posting.instance_id != attributed.instance_id
                or posting.order_id != attributed.order_id
            ):
                raise ValueError("paper cost and source fill owners disagree")
            seen.add(evidence.posting_id)
        if seen != set(postings):
            raise ValueError("paper report requires every current fee and rebate")
        if covered_fills != set(fills):
            raise ValueError("paper report requires explicit cost evidence for every fill")

    @staticmethod
    def _validate_marks(
        snapshot: AccountSnapshot,
        effective: tuple[EffectiveAccountPosting, ...],
        marks: tuple[PaperPositionMark, ...],
        cutoff: datetime,
        max_mark_age: timedelta,
        currencies: tuple[Currency, ...],
    ) -> dict[Dimension, PaperPositionMark]:
        """Require exactly the current open dimensions at eligible known prices."""
        open_dimensions = {position.dimension for position in snapshot.positions}
        quote_by_dimension: dict[Dimension, Currency] = {}
        latest_effect: dict[Dimension, datetime] = {}
        for posting in effective:
            dimension = (
                posting.quantity.dimension
                if posting.quantity is not None
                else posting.asset_change.dimension
                if posting.asset_change is not None
                else None
            )
            if dimension not in open_dimensions:
                continue
            if dimension is None:
                raise AssertionError("open paper effect lacks a dimension")
            latest_effect[dimension] = max(
                posting.known_at, latest_effect.get(dimension, posting.known_at)
            )
            if posting.kind == "fill":
                if posting.price is None:
                    raise AssertionError("effective paper fill lacks a price")
                prior = quote_by_dimension.setdefault(dimension, posting.price.currency)
                if prior != posting.price.currency:
                    raise ValueError("one open dimension traded in multiple quote currencies")
        by_dimension: dict[Dimension, PaperPositionMark] = {}
        identities: set[str] = set()
        for mark in marks:
            if type(mark) is not PaperPositionMark:
                raise TypeError("paper report requires identified position marks")
            mark.__post_init__()
            dimension = mark.price.per
            if (
                mark.identity in identities
                or dimension in by_dimension
                or dimension not in open_dimensions
                or mark.price.currency not in currencies
                or (
                    dimension in quote_by_dimension
                    and mark.price.currency != quote_by_dimension[dimension]
                )
                or mark.available_at > cutoff
                or cutoff - mark.available_at > max_mark_age
                or mark.available_at < latest_effect.get(dimension, mark.available_at)
            ):
                raise ValueError("paper mark is missing, stale, future or incompatible")
            identities.add(mark.identity)
            by_dimension[dimension] = mark
        if set(by_dimension) != open_dimensions:
            raise ValueError("paper report requires complete current position marks")
        return by_dimension

    @staticmethod
    def _scope(
        snapshot: AccountSnapshot,
        marks: dict[Dimension, PaperPositionMark],
        fills: dict[str, AttributedPaperFill],
    ) -> PaperScopeReport:
        """Value one existing account projection without changing its postings."""
        positions = tuple(
            PaperMarkedPosition(
                position=position,
                mark=marks[position.dimension],
                value=marks[position.dimension].price.amount(position),
            )
            for position in snapshot.positions
        )
        value_by_currency: dict[Currency, Fraction] = {
            amount.currency: Fraction(0) for amount in snapshot.cash
        }
        slip_by_currency = value_by_currency.copy()
        for position in positions:
            value_by_currency[position.value.currency] += Fraction(position.value.value)
        for fill_id in snapshot.fill_ids:
            fill = fills[fill_id].fill
            slip_by_currency[fill.effective.currency] += (
                Fraction(fill.effective.value) - Fraction(fill.reference.value)
            ) * Fraction(fill.quantity.value)
        currencies = tuple(
            PaperAccountReporter._currency_result(
                cash,
                transfer,
                value_by_currency[cash.currency],
                slip_by_currency[cash.currency],
            )
            for cash, transfer in zip(snapshot.cash, snapshot.transfers, strict=True)
        )
        return PaperScopeReport(snapshot=snapshot, positions=positions, currencies=currencies)

    @staticmethod
    def _currency_result(
        cash: Money, transfer: Money, position_value: Fraction, slippage: Fraction
    ) -> PaperCurrencyResult:
        """Reconcile one native-currency NAV change without a second cost debit."""
        currency = cash.currency
        value = Money(value=DecimalGrid.exact_decimal(position_value), currency=currency)
        slip = Money(value=DecimalGrid.exact_decimal(slippage), currency=currency)
        nav = cash + value
        return PaperCurrencyResult(
            currency=currency,
            position_value=value,
            nav=nav,
            net_pnl=nav - transfer,
            slippage=slip,
        )

    @staticmethod
    def _reconcile_scopes(
        account: PaperScopeReport, instances: tuple[PaperScopeReport, ...]
    ) -> None:
        """Prove attributed trading P&L sums to physical P&L by currency."""
        for index, account_currency in enumerate(account.currencies):
            instance_net = sum(
                (Fraction(item.currencies[index].net_pnl.value) for item in instances),
                Fraction(0),
            )
            instance_slippage = sum(
                (Fraction(item.currencies[index].slippage.value) for item in instances),
                Fraction(0),
            )
            if instance_net != Fraction(
                account_currency.net_pnl.value
            ) or instance_slippage != Fraction(account_currency.slippage.value):
                raise ValueError("paper strategy and account economics do not reconcile")
