"""Verify shared decision SDK continuation and exact paper application composition."""

from __future__ import annotations

# standard library imports
from dataclasses import replace as replace_binding
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountSnapshot, Fill
from applications.paper import SharedPaperDecision, run_shared_paper
from configuration import AccountConfiguration, OpeningAccount
from configuration.accounts import InstrumentFeeRate
from execution import (
    AccountJournal,
    AccountObservation,
    AccountQuote,
    MarketTouch,
    OrderEvent,
    PortfolioContext,
)
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from research.experiments import CandidateStateContract
from research.features import FeatureSchema, ProjectionFeature
from research.observations import DecisionInputs, InputRequirement, NamedObservation, NumericField
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import (
    AuthoredCandidates,
    LoadedCandidate,
    SharedCandidateCheckpoint,
    SharedDecisionRuntime,
    SharedStrategyBinding,
    SharedStrategyInput,
)
from serialization import DomainCodec
from strategies import (
    ConfirmedSignal,
    DecisionContext,
    DecisionPolicy,
    DecisionTransition,
    OrderIntent,
)


class _AccumulatingOrder:
    """Request an increasing IOC clip while retaining an explicit portable counter."""

    def __init__(self, quantity: Quantity, price: Price) -> None:
        """Bind independently authored instrument economics."""
        self.quantity, self.price = quantity, price

    @property
    def identity(self) -> str:
        """Pin this workload formula and its complete economic parameters."""
        return DomainCodec().encode_json(("accumulating-order", self.quantity, self.price)).hex()

    @property
    def output(self) -> Literal["order"]:
        """Use the portable order-intent extension point."""
        return "order"

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Reject a substituted feature signature or a learned input."""
        if fields != (NumericField(name="signal", units="score"),) or prediction is not None:
            raise ValueError("unexpected input signature")

    def initial_state(self) -> bytes:
        """Create an independent zero-count instance."""
        return b"0"

    def validate_state(self, state: bytes) -> None:
        """Keep the counter canonical and nonnegative."""
        if not state.isdigit() or str(int(state)).encode() != state:
            raise ValueError("invalid order counter")

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Increase the order clip by one unit after each retained decision."""
        count = int(state)
        return DecisionTransition(
            intent=OrderIntent(
                side="buy",
                quantity=self.quantity
                + Quantity(value=Decimal(count), dimension=self.quantity.dimension),
                limit=self.price,
                time_in_force="ioc",
            ),
            state=str(count + 1).encode(),
        )


class TestSharedDecisions:
    """Exercise fresh candidate injection, retries, rejection state and incompatible restart."""

    at = datetime(2026, 9, 25, tzinfo=UTC)
    currency = Currency.from_code("USD")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("22222222-2222-4222-8222-222222222222"),
        kind=QuantityKind.BASE_UNIT,
    )
    field = NumericField(name="signal", units="score")
    signal = InputRequirement(
        name="signal", family="non-book", clock="authored", field=field, max_age_us=1_000_000
    )

    @classmethod
    def _money(cls, value: str) -> Money:
        """Author an exact cash value."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Author exact instrument units."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls) -> Price:
        """Author an independent unchanged execution price."""
        return Price(value=Decimal("100"), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _config(cls, maximum: str = "10000") -> AccountConfiguration:
        """Select two isolated policy instances under common cash and authority."""
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(
                maximum=cls._quantity("200"),
                lot=cls._quantity("1"),
                tick=Price(value=Decimal("0.01"), currency=cls.currency, per=cls.dimension),
                product="spot",
            ),
        )
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.at,
            accounts=(OpeningAccount(account_id="shared", cash=(cls._money("20000"),)),),
            instruments=spot_limits,
            fee_rates=tuple(
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal(0)
                )
                for limits in spot_limits
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.currency,
                firm_maximum=cls._money("20000"),
                accounts=(AccountLimit(account_id="shared", maximum=cls._money(maximum)),),
                instances=tuple(
                    InstanceLimit(
                        instance_id=instance,
                        account_id="shared",
                        maximum=cls._money("9000"),
                        instruments=(cls.dimension.instrument_id,),
                    )
                    for instance in ("target", "orders")
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_residual_age_us=86_400_000_000,
                max_price_deviation_bps=100,
                max_order_notional=cls._money("9000"),
            ),
        )

    @classmethod
    def _candidate(
        cls,
        name: str,
        policy: DecisionPolicy,
        *,
        warmup: int = 0,
        on_restart: Literal["reset", "restore"] = "restore",
    ) -> LoadedCandidate:
        """Wrap an authored policy over the projected signal as a one-second candidate."""
        return AuthoredCandidates(venue="fixture").load(
            name=f"shared-{name}",
            feature=ProjectionFeature(
                FeatureSchema(
                    implementation="named-projection",
                    inputs=(cls.signal,),
                    outputs=(cls.field,),
                    parameters=(),
                    mode="batch",
                    ttl_us=1_000_000,
                )
            ),
            policy=policy,
            instance=name,
            entity=str(cls.dimension.instrument_id),
            cadence_us=1_000_000,
            starts_at=cls.at,
            source_identity="reference-source",
            state=CandidateStateContract(
                feature_mode="batch",
                warmup_observations=warmup,
                checkpoint_schema="candidate-checkpoint" if on_restart == "restore" else None,
                on_gap="continue",
                on_restart=on_restart,
                policy_state_schema="reference-policy-state",
            ),
        )

    @classmethod
    def _bindings(cls) -> tuple[SharedStrategyBinding, ...]:
        """Select distinct target and order implementations through the public SDK."""
        return tuple(
            SharedStrategyBinding(
                instance_id=name,
                account_id="shared",
                entity=str(cls.dimension.instrument_id),
                candidate=cls._candidate(name, policy),
                context=PortfolioContext(
                    portfolio_id="cash-spot",
                    strategy_id=name,
                    model_revision="rule-only",
                    config_revision="reference",
                    horizon="short",
                    reason="reference-decision",
                    venue="fixture",
                    settlement="spot",
                    risk_bucket="cash",
                    authority_scope="paper",
                ),
                maximum_fee=cls._money("1"),
            )
            for name, policy in (
                (
                    "target",
                    ConfirmedSignal(field=cls.field, quantity=cls._quantity("2"), confirmations=1),
                ),
                ("orders", _AccumulatingOrder(cls._quantity("2"), cls._price())),
            )
        )

    @classmethod
    def _inputs(cls, at: datetime, signal: str = "1") -> tuple[SharedStrategyInput, ...]:
        """Supply one exact then-available signal and a 99.50/100 touch to each candidate."""
        inputs = DecisionInputs(
            entity=str(cls.dimension.instrument_id),
            decision_at=at,
            observations=(
                NamedObservation(
                    input=cls.signal,
                    entity=str(cls.dimension.instrument_id),
                    event_at=at,
                    available_at=at,
                    value=ExactRatio(numerator=signal, denominator="1"),
                    reason="authored",
                    lineage="reference-source",
                ),
            ),
        )
        return tuple(
            SharedStrategyInput(
                instance_id=name,
                inputs=inputs,
                quote=AccountQuote(price=cls._price(), at=at),
                touch=MarketTouch(
                    bid=Price(value=Decimal("99.50"), currency=cls.currency, per=cls.dimension),
                    ask=cls._price(),
                ),
            )
            for name in ("target", "orders")
        )

    @classmethod
    def _opening(cls) -> AccountObservation:
        """Declare opening balances independently of the journal output."""
        return AccountObservation(
            identity="opening",
            at=cls.at,
            snapshot=AccountSnapshot(
                account_id="shared",
                instance_id=None,
                cash=(cls._money("20000"),),
                positions=(),
                fees=(cls._money("0"),),
                rebates=(cls._money("0"),),
                transfers=(cls._money("20000"),),
                fill_ids=(),
                posting_ids=("opening:USD",),
            ),
            open_orders=(),
        )

    def test_public_workflow_restores_distinct_policies_and_exact_retry(
        self, tmp_path: Path
    ) -> None:
        """Reopen policy checkpoints and keep matched targets separate from new order clips."""
        config, bindings = self._config(), self._bindings()
        path = tmp_path / "account.sqlite3"
        at = self.at + timedelta(seconds=1)
        decision = SharedPaperDecision(
            identity="first", at=at + timedelta(microseconds=1), inputs=self._inputs(at)
        )
        result = run_shared_paper(
            config,
            bindings=bindings,
            journal_path=path,
            events=(self._opening(), AccountQuote(price=self._price(), at=at), decision),
        )
        assert result.decisions[0].status == "committed"
        assert len(result.net_orders) == 1
        parent = result.net_orders[0].order
        assert parent.intent.quantity == self._quantity("4")
        retry = run_shared_paper(config, bindings=bindings, journal_path=path, events=(decision,))
        assert retry.accounts == result.accounts and retry.net_orders == result.net_orders
        fill_at = at + timedelta(seconds=1)
        fill = OrderEvent(
            identity="filled",
            order_id=parent.identity,
            at=fill_at,
            kind="fill",
            fill=Fill(
                identity="physical-four",
                decision_at=parent.decision_at,
                filled_at=fill_at,
                quantity=self._quantity("4"),
                reference=self._price(),
                effective=self._price(),
                fee=self._money("0.4"),
            ),
        )
        settled = run_shared_paper(config, bindings=bindings, journal_path=path, events=(fill,))
        ledger = AccountLedger(settled.accounts[0].ledger)
        assert ledger.snapshot().cash == (self._money("19599.6"),)
        for name in ("target", "orders"):
            assert ledger.snapshot(name).positions == (self._quantity("2"),)
            assert ledger.snapshot(name).cash == (self._money("-200.2"),)
        later = fill_at + timedelta(seconds=1)
        continued = run_shared_paper(
            config,
            bindings=bindings,
            journal_path=path,
            events=(
                AccountQuote(price=self._price(), at=later),
                SharedPaperDecision(
                    identity="second",
                    at=later + timedelta(microseconds=1),
                    inputs=self._inputs(later),
                ),
            ),
        )
        assert continued.decisions[0].status == "committed"
        assert len(continued.decisions[0].children) == 1
        assert continued.decisions[0].children[0].instance_id == "orders"
        assert continued.decisions[0].net_orders[0].order.intent.quantity == self._quantity("3")
        assert not continued.submission_attempted
        journal = AccountJournal(path, config)
        saved = journal.checkpoint("orders")
        assert saved is not None
        continuation = DomainCodec().decode_json(saved, SharedCandidateCheckpoint)
        assert continuation.step.checkpoint.policy.state == b"2"
        old_retry = run_shared_paper(
            config, bindings=bindings, journal_path=path, events=(decision,)
        )
        assert old_retry.decisions == result.decisions
        assert old_retry.net_orders == continued.net_orders
        assert journal.checkpoint("orders") == saved
        with pytest.raises(ValueError, match="another candidate binding"):
            SharedDecisionRuntime(
                journal, (replace_binding(bindings[0], maximum_fee=self._money("2")), bindings[1])
            )

    def test_rejection_persists_state_but_changed_retry_and_future_input_fail(
        self, tmp_path: Path
    ) -> None:
        """Do not repeatedly evaluate rejected policies or retain partially evaluated inputs.

        Each 201 buy alone exceeds the 150 account ceiling, so both decisions are refused.
        """
        config, bindings = self._config("150"), self._bindings()
        path = tmp_path / "account.sqlite3"
        at = self.at + timedelta(seconds=1)
        decision = SharedPaperDecision(
            identity="over-budget", at=at + timedelta(microseconds=1), inputs=self._inputs(at)
        )
        result = run_shared_paper(
            config,
            bindings=bindings,
            journal_path=path,
            events=(self._opening(), AccountQuote(price=self._price(), at=at), decision),
        )
        assert (result.decisions[0].status, result.decisions[0].reason) == (
            "rejected",
            "account_limit",
        )
        assert not result.children
        journal = AccountJournal(path, config)
        before = journal.checkpoint("orders")
        assert before is not None
        continuation = DomainCodec().decode_json(before, SharedCandidateCheckpoint)
        assert continuation.step.checkpoint.policy.state == b"1"
        assert (
            run_shared_paper(
                config, bindings=bindings, journal_path=path, events=(decision,)
            ).decisions
            == result.decisions
        )
        changed = replace(decision, crossing="internal_at_quote")
        with pytest.raises(ValueError, match="retry"):
            run_shared_paper(config, bindings=bindings, journal_path=path, events=(changed,))
        late_quote = AccountQuote(price=self._price(), at=at + timedelta(seconds=1))
        late = replace(
            decision,
            identity="late-quote",
            inputs=(replace(decision.inputs[0], quote=late_quote),),
        )
        with pytest.raises(ValueError, match="precede their coordination"):
            run_shared_paper(config, bindings=bindings, journal_path=path, events=(late,))
        assert journal.checkpoint("orders") == before

    def test_warmup_commits_state_without_intent_and_reset_restart_starts_fresh(
        self, tmp_path: Path
    ) -> None:
        """A warming step reserves nothing; a reset candidate warms again after restart."""
        config = self._config()
        target, orders = self._bindings()
        warming = replace_binding(
            orders,
            candidate=self._candidate(
                "orders",
                _AccumulatingOrder(self._quantity("2"), self._price()),
                warmup=1,
                on_restart="reset",
            ),
        )
        bindings = (target, warming)
        path = tmp_path / "account.sqlite3"
        instants = tuple(self.at + timedelta(seconds=second) for second in (1, 2, 3))
        decisions = tuple(
            SharedPaperDecision(
                identity=f"orders-{index}",
                at=at + timedelta(microseconds=1),
                inputs=tuple(item for item in self._inputs(at) if item.instance_id == "orders"),
            )
            for index, at in enumerate(instants)
        )
        quotes = tuple(AccountQuote(price=self._price(), at=at) for at in instants)
        opened = run_shared_paper(
            config,
            bindings=bindings,
            journal_path=path,
            events=(self._opening(), quotes[0], decisions[0], quotes[1], decisions[1]),
        )
        warmed, decided = opened.decisions
        assert (warmed.status, warmed.reason) == ("committed", "no_intent")
        assert not warmed.children and not warmed.net_orders
        assert [child.instance_id for child in decided.children] == ["orders"]
        restarted = run_shared_paper(
            config, bindings=bindings, journal_path=path, events=(quotes[2], decisions[2])
        )
        assert (restarted.decisions[0].status, restarted.decisions[0].reason) == (
            "committed",
            "no_intent",
        )
        saved = AccountJournal(path, config).checkpoint("orders")
        assert saved is not None
        continuation = DomainCodec().decode_json(saved, SharedCandidateCheckpoint)
        assert continuation.step.status == "warming"
        assert continuation.step.decision is None
        assert continuation.step.checkpoint.observations == 1

    def test_a_flat_target_sells_its_holding_at_the_bid(self, tmp_path: Path) -> None:
        """After buying 2 at the 100 ask, a nonpositive signal sells both at the 99.50 bid."""
        config, bindings = self._config(), self._bindings()
        path = tmp_path / "flat.sqlite3"
        at = self.at + timedelta(seconds=1)
        entered = run_shared_paper(
            config,
            bindings=bindings,
            journal_path=path,
            events=(
                self._opening(),
                AccountQuote(price=self._price(), at=at),
                SharedPaperDecision(
                    identity="enter", at=at + timedelta(microseconds=1), inputs=self._inputs(at)[:1]
                ),
            ),
        )
        parent = entered.net_orders[0].order
        assert parent.intent == OrderIntent(
            side="buy", quantity=self._quantity("2"), limit=self._price(), time_in_force="ioc"
        )
        fill_at = at + timedelta(seconds=1)
        entry = Fill(
            identity="entry-fill",
            decision_at=parent.decision_at,
            filled_at=fill_at,
            quantity=self._quantity("2"),
            reference=self._price(),
            effective=self._price(),
            fee=self._money("0"),
        )
        later = fill_at + timedelta(seconds=1)
        exited = run_shared_paper(
            config,
            bindings=bindings,
            journal_path=path,
            events=(
                OrderEvent(
                    identity="entered",
                    order_id=parent.identity,
                    at=fill_at,
                    kind="fill",
                    fill=entry,
                ),
                AccountQuote(price=self._price(), at=later),
                SharedPaperDecision(
                    identity="exit",
                    at=later + timedelta(microseconds=1),
                    inputs=self._inputs(later, signal="0")[:1],
                ),
            ),
        )
        assert exited.decisions[0].net_orders[0].order.intent == OrderIntent(
            side="sell",
            quantity=self._quantity("2"),
            limit=Price(value=Decimal("99.50"), currency=self.currency, per=self.dimension),
            time_in_force="ioc",
        )
