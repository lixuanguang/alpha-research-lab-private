"""Evaluate independent owner budgets against exact, authoritative exposure snapshots."""

from __future__ import annotations

# standard library imports
import re
from datetime import datetime, timedelta
from fractions import Fraction

# project library imports
from financial_units import Currency, Money, Price
from reference_data.instruments import InstrumentId
from serialization import WireRecord
from strategies import OrderIntent


class AccountLimit(WireRecord, frozen=True):
    """Cap marked and reserved exposure for one physical account."""

    account_id: str
    maximum: Money

    def __post_init__(self) -> None:
        """Require a stable account identity and positive exact currency limit."""
        BudgetPolicy._require_id(self.account_id, field_name="account_id")
        if type(self.maximum) is not Money:
            raise TypeError("account maximum must be Money")
        self.maximum.model_copy()
        if self.maximum.value <= 0:
            raise ValueError("account maximum must be positive")


class InstanceLimit(WireRecord, frozen=True):
    """Cap one strategy instance and declare its permitted instrument identities."""

    instance_id: str
    account_id: str
    maximum: Money
    instruments: tuple[InstrumentId, ...]

    def __post_init__(self) -> None:
        """Require an owned account, positive limit and unique authorized instruments."""
        BudgetPolicy._require_id(self.instance_id, field_name="instance_id")
        BudgetPolicy._require_id(self.account_id, field_name="account_id")
        if type(self.maximum) is not Money:
            raise TypeError("instance maximum must be Money")
        self.maximum.model_copy()
        if self.maximum.value <= 0:
            raise ValueError("instance maximum must be positive")
        if type(self.instruments) is not tuple or not self.instruments:
            raise ValueError("instance instruments must be a nonempty tuple")
        for instrument in self.instruments:
            if type(instrument) is not InstrumentId:
                raise TypeError("instance instruments must contain InstrumentId")
            InstrumentId(instrument.uuid_value)
        if len(set(self.instruments)) != len(self.instruments):
            raise ValueError("instance instruments must be unique")


class BudgetPolicy(WireRecord, frozen=True):
    """Bind firm, account and instance ceilings to one explicit valuation currency.

    The initial cash spot implementation requires all marked exposure and orders
    to use this currency. A different quote currency needs an evidenced FX and
    valuation policy before it can be admitted; no implicit conversion exists.
    ``max_residual_age_us`` bounds how long after its decision a waiting order may
    still be sent; an older one is retired instead.
    """

    valuation_currency: Currency
    firm_maximum: Money
    accounts: tuple[AccountLimit, ...]
    instances: tuple[InstanceLimit, ...]
    max_quote_age_us: int
    max_state_age_us: int
    max_residual_age_us: int
    max_price_deviation_bps: int
    max_order_notional: Money

    def __post_init__(self) -> None:
        """Reject incomplete ownership, mismatched currencies and invalid ceilings."""
        if type(self.valuation_currency) is not Currency:
            raise TypeError("valuation_currency must be Currency")
        self.valuation_currency.validate_currency()
        for maximum in (self.firm_maximum, self.max_order_notional):
            if type(maximum) is not Money:
                raise TypeError("policy maxima must be Money")
            maximum.model_copy()
            if maximum.currency != self.valuation_currency or maximum.value <= 0:
                raise ValueError("policy maxima need positive valuation-currency amounts")
        if type(self.accounts) is not tuple or not self.accounts:
            raise ValueError("accounts must be a nonempty tuple")
        if type(self.instances) is not tuple or not self.instances:
            raise ValueError("instances must be a nonempty tuple")
        account_ids: set[str] = set()
        for account in self.accounts:
            if type(account) is not AccountLimit:
                raise TypeError("accounts must contain AccountLimit")
            account.__post_init__()
            if (
                account.account_id in account_ids
                or account.maximum.currency != self.valuation_currency
            ):
                raise ValueError("duplicate account or incompatible account currency")
            account_ids.add(account.account_id)
        instance_ids: set[str] = set()
        for instance in self.instances:
            if type(instance) is not InstanceLimit:
                raise TypeError("instances must contain InstanceLimit")
            instance.__post_init__()
            if (
                instance.instance_id in instance_ids
                or instance.account_id not in account_ids
                or instance.maximum.currency != self.valuation_currency
            ):
                raise ValueError("duplicate, unowned or incompatible instance")
            instance_ids.add(instance.instance_id)
        for age in (self.max_quote_age_us, self.max_state_age_us, self.max_residual_age_us):
            if type(age) is not int or not 0 < age <= 86_400_000_000:
                raise ValueError("risk freshness ages must be positive and at most one day")
        if (
            type(self.max_price_deviation_bps) is not int
            or not 0 <= self.max_price_deviation_bps <= 10_000
        ):
            raise ValueError("price deviation must be between zero and 10000 basis points")

    @staticmethod
    def _require_id(value: object, *, field_name: str) -> str:
        """Require a bounded identity suitable for stable journal ownership."""
        if (
            type(value) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", value) is None
        ):
            raise ValueError(f"{field_name} must be a bounded identity")
        return value


class ExposureCommitment(WireRecord, frozen=True):
    """State one instance's marked holdings and still-unresolved reservations.

    The caller obtains both amounts from authoritative account state inside the
    same transaction as admission. Pending and uncertain orders remain in
    ``reserved_exposure`` until their terminal outcome is established.
    """

    account_id: str
    instance_id: str
    held_exposure: Money
    reserved_exposure: Money

    def __post_init__(self) -> None:
        """Reject negative, untyped or mixed-currency exposure components."""
        BudgetPolicy._require_id(self.account_id, field_name="account_id")
        BudgetPolicy._require_id(self.instance_id, field_name="instance_id")
        if type(self.held_exposure) is not Money or type(self.reserved_exposure) is not Money:
            raise TypeError("exposure components must be Money")
        self.held_exposure.model_copy()
        self.reserved_exposure.model_copy()
        if (
            self.held_exposure.value < 0
            or self.reserved_exposure.value < 0
            or self.held_exposure.currency != self.reserved_exposure.currency
        ):
            raise ValueError("exposure components must be nonnegative in one currency")


class BudgetRequest(WireRecord, frozen=True):
    """Carry one order and the quote/account observation times used for admission."""

    account_id: str
    instance_id: str
    intent: OrderIntent
    decision_at: datetime
    quote: Price
    quote_at: datetime
    state_at: datetime
    maximum_fee: Money

    def __post_init__(self) -> None:
        """Require valid typed values and UTC timestamps without granting authority."""
        BudgetPolicy._require_id(self.account_id, field_name="account_id")
        BudgetPolicy._require_id(self.instance_id, field_name="instance_id")
        if type(self.intent) is not OrderIntent or type(self.quote) is not Price:
            raise TypeError("budget request needs OrderIntent and Price")
        self.intent.__post_init__()
        self.quote.model_copy()
        if type(self.maximum_fee) is not Money:
            raise TypeError("maximum_fee must be Money")
        self.maximum_fee.model_copy()
        if self.maximum_fee.value < 0:
            raise ValueError("maximum_fee must be nonnegative")
        self._require_utc(self.decision_at, field_name="decision_at")
        self._require_utc(self.quote_at, field_name="quote_at")
        self._require_utc(self.state_at, field_name="state_at")


class _ExposureTotals:
    """Sum one complete exposure snapshot by instance, account and firm."""

    def __init__(self, policy: BudgetPolicy) -> None:
        """Start with nothing counted under the policy's ceilings."""
        self.policy = policy
        self.by_instance: dict[str, Fraction] = {}
        self.by_account: dict[str, Fraction] = {}
        self.firm = Fraction(0)

    def count(self, commitments: tuple[ExposureCommitment, ...]) -> str | None:
        """Count each configured owner exactly once, or name why the snapshot is unusable."""
        instances = {instance.instance_id: instance for instance in self.policy.instances}
        for commitment in commitments:
            if type(commitment) is not ExposureCommitment:
                raise TypeError("commitments must contain ExposureCommitment")
            commitment.__post_init__()
            owner = instances.get(commitment.instance_id)
            if owner is None or owner.account_id != commitment.account_id:
                return "unattributed_exposure"
            if commitment.instance_id in self.by_instance:
                return "duplicate_exposure_owner"
            if commitment.held_exposure.currency != self.policy.valuation_currency:
                return "currency_mismatch"
            exposure = Fraction(commitment.held_exposure.value) + Fraction(
                commitment.reserved_exposure.value
            )
            self.by_instance[commitment.instance_id] = exposure
            self.by_account[commitment.account_id] = (
                self.by_account.get(commitment.account_id, Fraction(0)) + exposure
            )
            self.firm += exposure
        if set(self.by_instance) != set(instances):
            return "incomplete_exposure_state"
        return None

    def exceeded(self, instance: InstanceLimit, addition: Fraction) -> str | None:
        """Name the first instance, account or firm ceiling that the addition exceeds."""
        account = next(
            item for item in self.policy.accounts if item.account_id == instance.account_id
        )
        if self.by_instance[instance.instance_id] + addition > Fraction(instance.maximum.value):
            return "instance_limit"
        if self.by_account[instance.account_id] + addition > Fraction(account.maximum.value):
            return "account_limit"
        if self.firm + addition > Fraction(self.policy.firm_maximum.value):
            return "firm_limit"
        return None


class BudgetEngine:
    """Reject unsafe new risk without holding mutable accounting or strategy state.

    Ceilings bound buys only. Owned inventory bounds a cash spot sell, so a sell
    can only lower exposure, and no ceiling refuses it, even after marks alone
    have taken its owner over one. Every other check still applies to a sell.
    """

    def evaluate(
        self,
        policy: BudgetPolicy,
        request: BudgetRequest,
        commitments: tuple[ExposureCommitment, ...],
    ) -> str | None:
        """Return a stable rejection reason, or ``None`` for this snapshot.

        The caller must read commitments and persist the admitted reservation in
        one serialized account transaction. An accepted buy consumes its exact
        limit notional plus fee cap. For the supported cash spot path, a sell
        reserves its fee cap but faces no ceiling, and existing held exposure
        stays counted until a confirmed fill. Inventory and product mechanics
        remain independently enforced by the owning execution and spot-risk
        boundaries.

        Args:
            policy: Validated firm, account and instance risk ceilings.
            request: Candidate order with market and account observation times.
            commitments: One authoritative marked/reserved snapshot per instance.

        Returns:
            A stable rejection reason, or ``None`` for an admissible request.
        """
        if type(policy) is not BudgetPolicy or type(request) is not BudgetRequest:
            raise TypeError("budget admission requires typed policy and request")
        policy.__post_init__()
        request.__post_init__()
        if type(commitments) is not tuple:
            raise TypeError("commitments must be a tuple")

        accounts = {account.account_id: account for account in policy.accounts}
        instances = {instance.instance_id: instance for instance in policy.instances}
        if request.account_id not in accounts:
            return "unauthorized_account"
        instance = instances.get(request.instance_id)
        if instance is None or instance.account_id != request.account_id:
            return "unauthorized_instance"
        if request.intent.quantity.dimension.instrument_id not in instance.instruments:
            return "unauthorized_instrument"
        if (
            request.intent.limit.currency != policy.valuation_currency
            or request.quote.currency != policy.valuation_currency
            or request.maximum_fee.currency != policy.valuation_currency
        ):
            return "currency_mismatch"
        if request.quote.per != request.intent.quantity.dimension:
            return "incompatible_quote"
        if request.quote.value <= 0:
            return "invalid_quote"
        if request.quote_at > request.decision_at:
            return "future_quote"
        if request.state_at > request.decision_at:
            return "future_state"
        if request.decision_at - request.quote_at > timedelta(microseconds=policy.max_quote_age_us):
            return "stale_quote"
        if request.decision_at - request.state_at > timedelta(microseconds=policy.max_state_age_us):
            return "stale_state"

        quote = Fraction(request.quote.value)
        limit = Fraction(request.intent.limit.value)
        if abs(limit - quote) * 10_000 > quote * policy.max_price_deviation_bps:
            return "price_deviation"
        notional = limit * Fraction(request.intent.quantity.value)
        if notional > Fraction(policy.max_order_notional.value):
            return "order_notional_limit"

        totals = _ExposureTotals(policy)
        reason = totals.count(commitments)
        if reason is not None or request.intent.side == "sell":
            return reason
        return totals.exceeded(instance, notional + Fraction(request.maximum_fee.value))

    def recheck(
        self,
        policy: BudgetPolicy,
        commitments: tuple[ExposureCommitment, ...],
        buyers: tuple[str, ...],
    ) -> str | None:
        """Return the ceiling a buying owner now exceeds at current marks, or ``None``.

        Before a physical send the caller names the owners of the buys it would
        send. Marks can take any owner over a ceiling with no new order. An
        owner, account or firm over its ceiling then holds back the buys that
        would add to it; a sell or another owner's in-limit buy still goes.

        Args:
            policy: Validated firm, account and instance risk ceilings.
            commitments: One authoritative marked/reserved snapshot per instance.
            buyers: Instance identities whose buys the caller would send.

        Returns:
            A stable rejection reason, or ``None`` when every buyer is within limits.
        """
        if type(policy) is not BudgetPolicy:
            raise TypeError("budget recheck requires a typed policy")
        policy.__post_init__()
        if type(commitments) is not tuple or type(buyers) is not tuple:
            raise TypeError("commitments and buyers must be tuples")
        totals = _ExposureTotals(policy)
        reason = totals.count(commitments)
        if reason is not None:
            return reason
        instances = {instance.instance_id: instance for instance in policy.instances}
        for buyer in buyers:
            instance = instances.get(buyer)
            if instance is None:
                return "unauthorized_instance"
            reason = totals.exceeded(instance, Fraction(0))
            if reason is not None:
                return reason
        return None
