"""Check independent exact account, instance and firm budget admission."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk.budgets import (
    AccountLimit,
    BudgetEngine,
    BudgetPolicy,
    BudgetRequest,
    ExposureCommitment,
    InstanceLimit,
)
from serialization import DomainCodec
from strategies import OrderIntent


class TestBudgetEngine:
    """Exercise scope, valuation and time boundaries with independent amounts."""

    @staticmethod
    def _money(amount: str, *, currency: Currency | None = None) -> Money:
        """Construct one exact amount in the declared policy currency by default."""
        return Money(value=Decimal(amount), currency=currency or Currency.from_code("USDT"))

    @staticmethod
    def _instrument(number: int) -> InstrumentId:
        """Give each test listing a stable opaque instrument identity."""
        return InstrumentId.from_canonical_text(f"00000000-0000-4000-8000-{number:012d}")

    @classmethod
    def _policy(cls) -> BudgetPolicy:
        """Give two instances one account so the account ceiling is the race boundary."""
        instrument = cls._instrument(1)
        return BudgetPolicy(
            valuation_currency=Currency.from_code("USDT"),
            firm_maximum=cls._money("20000"),
            accounts=(AccountLimit(account_id="shared", maximum=cls._money("10000")),),
            instances=(
                InstanceLimit(
                    instance_id="alpha",
                    account_id="shared",
                    maximum=cls._money("9000"),
                    instruments=(instrument,),
                ),
                InstanceLimit(
                    instance_id="beta",
                    account_id="shared",
                    maximum=cls._money("9000"),
                    instruments=(instrument,),
                ),
            ),
            max_quote_age_us=1_000_000,
            max_state_age_us=1_000_000,
            max_price_deviation_bps=100,
            max_order_notional=cls._money("9000"),
        )

    @classmethod
    def _request(
        cls,
        *,
        instance_id: str = "alpha",
        quantity: str = "80",
        limit: str = "100",
        side: str = "buy",
    ) -> BudgetRequest:
        """Request an 8,000 USDT spot order from an exactly current quote."""
        currency = Currency.from_code("USDT")
        dimension = Dimension(instrument_id=cls._instrument(1), kind=QuantityKind.BASE_UNIT)
        observed_at = datetime(2026, 9, 25, 12, tzinfo=UTC)
        return BudgetRequest(
            account_id="shared",
            instance_id=instance_id,
            intent=OrderIntent(
                side="buy" if side == "buy" else "sell",
                quantity=Quantity(value=Decimal(quantity), dimension=dimension),
                limit=Price(value=Decimal(limit), currency=currency, per=dimension),
                time_in_force="ioc",
            ),
            decision_at=observed_at,
            quote=Price(value=Decimal("100"), currency=currency, per=dimension),
            quote_at=observed_at,
            state_at=observed_at,
            maximum_fee=cls._money("0"),
        )

    @classmethod
    def _zero_commitments(cls, policy: BudgetPolicy) -> tuple[ExposureCommitment, ...]:
        """Supply every configured owner explicitly with no starting exposure."""
        return tuple(
            ExposureCommitment(
                account_id=owner.account_id,
                instance_id=owner.instance_id,
                held_exposure=cls._money("0"),
                reserved_exposure=cls._money("0"),
            )
            for owner in policy.instances
        )

    def test_exact_shared_account_race_keeps_unknown_reservation(self) -> None:
        """The second 8,000 request exceeds the 10,000 account ceiling after the first reserves."""
        policy = self._policy()
        engine = BudgetEngine()
        first = self._request()
        second = self._request(instance_id="beta")
        assert engine.evaluate(policy, first, self._zero_commitments(policy)) is None
        uncertain_first = ExposureCommitment(
            account_id="shared",
            instance_id="alpha",
            held_exposure=self._money("0"),
            reserved_exposure=self._money("8000"),
        )
        second_snapshot = (uncertain_first, self._zero_commitments(policy)[1])
        assert engine.evaluate(policy, second, second_snapshot) == "account_limit"
        assert engine.evaluate(policy, second, second_snapshot) == "account_limit"

    def test_limits_are_inclusive_and_fee_caps_consume_budget(self) -> None:
        """An exactly 9,000 order fits the instance; a 0.01 fee makes it exceed."""
        policy = self._policy()
        request = self._request(quantity="90")
        engine = BudgetEngine()
        snapshot = self._zero_commitments(policy)
        assert engine.evaluate(policy, request, snapshot) is None
        assert (
            engine.evaluate(policy, replace(request, maximum_fee=self._money("0.01")), snapshot)
            == "instance_limit"
        )
        assert (
            engine.evaluate(policy, self._request(quantity="90.000000000000000001"), snapshot)
            == "order_notional_limit"
        )

    def test_firm_limit_counts_distinct_accounts_and_instances(self) -> None:
        """Exposure in another account still consumes the common firm ceiling."""
        policy = self._policy()
        second_account = AccountLimit(account_id="other", maximum=self._money("15000"))
        second_instance = InstanceLimit(
            instance_id="gamma",
            account_id="other",
            maximum=self._money("15000"),
            instruments=(self._instrument(1),),
        )
        policy = replace(
            policy,
            accounts=(
                AccountLimit(account_id="shared", maximum=self._money("10000")),
                second_account,
            ),
            instances=(
                InstanceLimit(
                    instance_id="alpha",
                    account_id="shared",
                    maximum=self._money("9000"),
                    instruments=(self._instrument(1),),
                ),
                second_instance,
            ),
            firm_maximum=self._money("10000"),
        )
        prior = ExposureCommitment(
            account_id="other",
            instance_id="gamma",
            held_exposure=self._money("2500"),
            reserved_exposure=self._money("0"),
        )
        snapshot = (self._zero_commitments(policy)[0], prior)
        assert BudgetEngine().evaluate(policy, self._request(), snapshot) == "firm_limit"

    def test_no_ceiling_refuses_a_sell_but_held_exposure_stays_until_its_fill(self) -> None:
        """Marks above every ceiling still admit a sell; a buy beside it is still refused."""
        policy = replace(
            self._policy(),
            firm_maximum=self._money("1000"),
            accounts=(AccountLimit(account_id="shared", maximum=self._money("1000")),),
            instances=(
                InstanceLimit(
                    instance_id="alpha",
                    account_id="shared",
                    maximum=self._money("1000"),
                    instruments=(self._instrument(1),),
                ),
            ),
        )
        rallied = ExposureCommitment(
            account_id="shared",
            instance_id="alpha",
            held_exposure=self._money("1200"),
            reserved_exposure=self._money("0"),
        )
        sell = replace(self._request(side="sell", quantity="10"), maximum_fee=self._money("0.01"))
        engine = BudgetEngine()
        assert engine.evaluate(policy, sell, (rallied,)) is None
        stale = replace(sell, quote_at=sell.decision_at - timedelta(microseconds=1_000_001))
        assert engine.evaluate(policy, stale, (rallied,)) == "stale_quote"
        # The pending sell's fee joins held exposure, which stays counted until a fill.
        pending = replace(rallied, reserved_exposure=self._money("0.01"))
        assert engine.evaluate(policy, self._request(quantity="1"), (pending,)) == "instance_limit"

    def test_recheck_holds_back_only_buyers_over_a_ceiling(self) -> None:
        """Marks over alpha's 6,000 stop alpha's buys; beta's in-limit buys still go."""
        policy = replace(
            self._policy(),
            instances=(
                InstanceLimit(
                    instance_id="alpha",
                    account_id="shared",
                    maximum=self._money("6000"),
                    instruments=(self._instrument(1),),
                ),
                InstanceLimit(
                    instance_id="beta",
                    account_id="shared",
                    maximum=self._money("9000"),
                    instruments=(self._instrument(1),),
                ),
            ),
        )
        alpha = ExposureCommitment(
            account_id="shared",
            instance_id="alpha",
            held_exposure=self._money("6600"),
            reserved_exposure=self._money("0"),
        )
        beta = ExposureCommitment(
            account_id="shared",
            instance_id="beta",
            held_exposure=self._money("0"),
            reserved_exposure=self._money("1200"),
        )
        engine = BudgetEngine()
        assert engine.recheck(policy, (alpha, beta), ()) is None
        assert engine.recheck(policy, (alpha, beta), ("beta",)) is None
        assert engine.recheck(policy, (alpha, beta), ("alpha",)) == "instance_limit"
        # 6,600 + 3,401 exceeds the 10,000 account ceiling though beta is within its own.
        crowded = replace(beta, reserved_exposure=self._money("3401"))
        assert engine.recheck(policy, (alpha, crowded), ("beta",)) == "account_limit"
        assert engine.recheck(policy, (alpha,), ("beta",)) == "incomplete_exposure_state"
        assert engine.recheck(policy, (alpha, beta), ("gamma",)) == "unauthorized_instance"

    def test_authority_and_missing_fx_fail_closed(self) -> None:
        """An account, instance, instrument or currency mismatch cannot enter a budget."""
        policy = self._policy()
        request = self._request()
        engine = BudgetEngine()
        assert (
            engine.evaluate(policy, replace(request, account_id="foreign"), ())
            == "unauthorized_account"
        )
        assert (
            engine.evaluate(policy, replace(request, instance_id="unknown"), ())
            == "unauthorized_instance"
        )
        other_dimension = Dimension(instrument_id=self._instrument(2), kind=QuantityKind.BASE_UNIT)
        foreign_order = replace(
            request.intent,
            quantity=Quantity(value=Decimal("80"), dimension=other_dimension),
            limit=Price(
                value=Decimal("100"), currency=Currency.from_code("USDT"), per=other_dimension
            ),
        )
        assert (
            engine.evaluate(policy, replace(request, intent=foreign_order), ())
            == "unauthorized_instrument"
        )
        other_currency = Currency.from_code("USD")
        assert (
            engine.evaluate(
                policy,
                replace(
                    request,
                    quote=Price(
                        value=Decimal("100"), currency=other_currency, per=request.quote.per
                    ),
                ),
                (),
            )
            == "currency_mismatch"
        )

    def test_freshness_future_and_price_deviation_are_exact(self) -> None:
        """Exact age and bps boundaries pass; the next microsecond or tick fails."""
        policy = self._policy()
        request = self._request(quantity="1", limit="101")
        engine = BudgetEngine()
        at_boundary = replace(
            request,
            quote_at=request.decision_at - timedelta(microseconds=1_000_000),
            state_at=request.decision_at - timedelta(microseconds=1_000_000),
        )
        snapshot = self._zero_commitments(policy)
        assert engine.evaluate(policy, at_boundary, snapshot) is None
        assert (
            engine.evaluate(
                policy,
                replace(at_boundary, quote_at=at_boundary.quote_at - timedelta(microseconds=1)),
                snapshot,
            )
            == "stale_quote"
        )
        assert (
            engine.evaluate(
                policy,
                replace(at_boundary, state_at=at_boundary.state_at - timedelta(microseconds=1)),
                snapshot,
            )
            == "stale_state"
        )
        assert (
            engine.evaluate(
                policy,
                replace(request, quote_at=request.decision_at + timedelta(microseconds=1)),
                snapshot,
            )
            == "future_quote"
        )
        assert (
            engine.evaluate(
                policy,
                replace(request, state_at=request.decision_at + timedelta(microseconds=1)),
                snapshot,
            )
            == "future_state"
        )
        assert (
            engine.evaluate(
                policy, self._request(quantity="1", limit="101.000000000000000001"), snapshot
            )
            == "price_deviation"
        )

    def test_exposure_snapshot_must_be_owned_unique_and_in_currency(self) -> None:
        """Unknown, duplicated or cross-currency exposure cannot be silently ignored."""
        policy = self._policy()
        request = self._request(quantity="1")
        engine = BudgetEngine()
        prior = ExposureCommitment(
            account_id="shared",
            instance_id="alpha",
            held_exposure=self._money("1"),
            reserved_exposure=self._money("0"),
        )
        assert engine.evaluate(policy, request, ()) == "incomplete_exposure_state"
        assert engine.evaluate(policy, request, (prior, prior)) == "duplicate_exposure_owner"
        assert (
            engine.evaluate(policy, request, (replace(prior, instance_id="unknown"),))
            == "unattributed_exposure"
        )
        eur = Currency.from_code("EUR")
        assert (
            engine.evaluate(
                policy,
                request,
                (
                    replace(
                        prior,
                        held_exposure=self._money("1", currency=eur),
                        reserved_exposure=self._money("0", currency=eur),
                    ),
                ),
            )
            == "currency_mismatch"
        )

    def test_policy_and_request_validate_round_trip_and_invalid_values(self) -> None:
        """Wire decoding keeps exact values; authored limits cannot lose ownership or UTC."""
        policy = self._policy()
        request = self._request()
        codec = DomainCodec()
        assert codec.decode_json(codec.encode_json(policy), BudgetPolicy) == policy
        assert codec.decode_json(codec.encode_json(request), BudgetRequest) == request
        with pytest.raises(ValueError, match="duplicate account"):
            replace(policy, accounts=(policy.accounts[0], policy.accounts[0]))
        with pytest.raises(ValueError, match="unowned"):
            replace(policy, instances=(replace(policy.instances[0], account_id="missing"),))
        with pytest.raises(ValueError, match="nonnegative"):
            ExposureCommitment(
                account_id="shared",
                instance_id="alpha",
                held_exposure=self._money("-1"),
                reserved_exposure=self._money("0"),
            )
        with pytest.raises(TypeError, match="timezone-aware"):
            replace(request, decision_at=request.decision_at.replace(tzinfo=None))
