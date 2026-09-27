"""Verify signed source scopes across instruments and non-filling shadow accounts."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountSnapshot, Fill
from configuration import (
    AccountConfiguration,
    OpeningAccount,
    PaperAuthorization,
    PaperDeployment,
    PaperExecutionScenario,
    PaperSourceBinding,
    PaperStrategyIdentity,
)
from execution import (
    AccountControl,
    AccountDecision,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    OrderDecision,
    OrderEvent,
    PaperMarket,
    PaperOwner,
    PortfolioBatch,
    PortfolioContext,
    PortfolioDecision,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent


class _Clock:
    """Hold the managed boundary's independently advancing UTC time."""

    def __init__(self, at: datetime) -> None:
        """Begin at the requested wall time."""
        self.at = at

    def __call__(self) -> datetime:
        """Read current operation time."""
        return self.at


class TestPaperSourceScopes:
    """Exercise two same-currency instruments under one signed account owner."""

    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)
    currency = Currency.from_code("USDT")
    first = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    second = Dimension(
        instrument_id=InstrumentId.from_canonical_text("22222222-2222-4222-8222-222222222222"),
        kind=QuantityKind.BASE_UNIT,
    )

    @classmethod
    def _at(cls, seconds: int) -> datetime:
        """Use one bounded session timeline."""
        return cls.opening_at + timedelta(seconds=seconds)

    @classmethod
    def _money(cls, value: str) -> Money:
        """Use the configured common quote currency."""
        return Money(value=Decimal(value), currency=cls.currency)

    @staticmethod
    def _quantity(value: str, dimension: Dimension) -> Quantity:
        """Keep instrument dimensions explicit at every boundary."""
        return Quantity(value=Decimal(value), dimension=dimension)

    @classmethod
    def _price(cls, value: str, dimension: Dimension) -> Price:
        """Use one quote currency across independent instruments."""
        return Price(value=Decimal(value), currency=cls.currency, per=dimension)

    @classmethod
    def _scenario(
        cls, dimension: Dimension, venue: Literal["okx", "bitfinex"]
    ) -> PaperExecutionScenario:
        """Declare one immutable public-book matching profile."""
        return PaperExecutionScenario(
            venue=venue,
            instrument_id=dimension.instrument_id,
            entry_delay_us=0,
            cancel_delay_us=0,
            adverse=cls._price("0.01", dimension),
            fee_rate=Decimal("0.001"),
            take_fraction=Decimal(1),
            gas_inapplicable_reason="off-chain spot scenario",
        )

    @classmethod
    def _config(cls, mode: Literal["paper", "shadow"] = "paper") -> AccountConfiguration:
        """Provision both owners and both instruments before activating either."""
        return AccountConfiguration(
            mode=mode,
            opening_at=cls.opening_at,
            accounts=(OpeningAccount(account_id="shared", cash=(cls._money("1000"),)),),
            instruments=tuple(
                SpotLimits(
                    maximum=cls._quantity("10", dimension),
                    lot=cls._quantity("1", dimension),
                    tick=cls._price("0.01", dimension),
                    product="spot",
                )
                for dimension in (cls.first, cls.second)
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.currency,
                firm_maximum=cls._money("1000"),
                accounts=(AccountLimit(account_id="shared", maximum=cls._money("1000")),),
                instances=tuple(
                    InstanceLimit(
                        instance_id=instance,
                        account_id="shared",
                        maximum=cls._money("500"),
                        instruments=(dimension.instrument_id,),
                    )
                    for instance, dimension in (("alpha", cls.first), ("beta", cls.second))
                ),
                max_quote_age_us=10_000_000,
                max_state_age_us=60_000_000,
                max_price_deviation_bps=200,
                max_order_notional=cls._money("100"),
            ),
        )

    @staticmethod
    def _strategy(instance_id: str) -> PaperStrategyIdentity:
        """Pin exact policy/model identities for one strategy owner."""
        return PaperStrategyIdentity(
            instance_id=instance_id,
            policy_identity=f"policy-{instance_id}",
            candidate_identity=f"candidate-{instance_id}",
            model_identity="no-model",
            feature_identity=f"feature-{instance_id}",
        )

    @classmethod
    def _deployment(cls, config: AccountConfiguration) -> PaperDeployment:
        """Bind distinct public sources beneath one durable account owner."""
        return PaperDeployment(
            account_id="shared",
            configuration_sha256=hashlib.sha256(DomainCodec().encode_json(config)).hexdigest(),
            releases=("a" * 64,),
            strategies=(cls._strategy("alpha"), cls._strategy("beta")),
            input_identity="okx-first-book",
            scenario=cls._scenario(cls.first, "okx"),
            state_identity="paper-account-state-v1",
            submission_authority="shadow" if config.mode == "shadow" else "paper",
            additional_sources=(
                PaperSourceBinding(
                    instance_id="beta",
                    input_identity="bitfinex-second-book",
                    scenario=cls._scenario(cls.second, "bitfinex"),
                ),
            ),
        )

    @classmethod
    def _authorization(cls, deployment: PaperDeployment) -> PaperAuthorization:
        """Authorize both exact dimensions under one finite quote-currency cap."""
        return PaperAuthorization(
            identity="finite-session",
            deployment_sha256=deployment.identity,
            valid_from=cls._at(11),
            expires_at=cls._at(30),
            quantities=(
                cls._quantity("5", cls.first),
                cls._quantity("5", cls.second),
            ),
            maximum_order_notional=cls._money("100"),
            maximum_orders=5,
            submission_authority=deployment.submission_authority,
        )

    @classmethod
    def _opening(cls) -> AccountSnapshot:
        """Supply independent flat opening facts."""
        return AccountSnapshot(
            account_id="shared",
            instance_id=None,
            cash=(cls._money("1000"),),
            positions=(),
            fees=(cls._money("0"),),
            rebates=(cls._money("0"),),
            transfers=(cls._money("1000"),),
            fill_ids=(),
            posting_ids=("opening:USDT",),
        )

    @classmethod
    def _start(
        cls, path: Path, mode: Literal["paper", "shadow"] = "paper"
    ) -> tuple[AccountJournal, AccountJournal, _Clock, PaperDeployment, PaperOwner]:
        """Install, reconcile, authorize and claim one managed worker."""
        config = cls._config(mode)
        clock = _Clock(cls._at(10))
        admin = AccountJournal(path, config, clock=clock)
        assert admin.reconcile(
            AccountObservation(
                identity="opening", at=cls._at(1), snapshot=cls._opening(), open_orders=()
            )
        )
        deployment = cls._deployment(config)
        admin.install_paper(deployment)
        clock.at = cls._at(11)
        admin.authorize_paper(cls._authorization(deployment))
        assert admin.reconcile(
            AccountObservation(
                identity="after-install", at=cls._at(12), snapshot=cls._opening(), open_orders=()
            )
        )
        for dimension in (cls.first, cls.second):
            admin.observe(AccountQuote(price=cls._price("10", dimension), at=cls._at(12)))
        clock.at = cls._at(13)
        owner = admin.claim_paper(
            "shared",
            "worker-one",
            deployment.releases[0],
            AccountControl(
                identity="claim-one",
                account_id="shared",
                kind="restart",
                at=cls._at(13),
                expected_control_identity=f"paper-deployment:{deployment.identity}",
            ),
        )
        return (
            admin,
            AccountJournal(path, config, paper_owner=owner, clock=clock),
            clock,
            deployment,
            owner,
        )

    @classmethod
    def _decision(
        cls, instance_id: str, dimension: Dimension, identity: str, at: datetime
    ) -> AccountDecision:
        """Create one buy owned by an exact strategy and instrument."""
        return AccountDecision(
            account_id="shared",
            instance_id=instance_id,
            decision=OrderDecision(
                identity=identity,
                at=at,
                intent=OrderIntent(
                    side="buy",
                    quantity=cls._quantity("1", dimension),
                    limit=cls._price("10.10", dimension),
                    time_in_force="gtc",
                ),
            ),
            quote=AccountQuote(price=cls._price("10", dimension), at=at),
            maximum_fee=cls._money("1"),
        )

    @classmethod
    def _market(cls, dimension: Dimension, identity: str, at: datetime) -> PaperMarket:
        """Provide a finite public touch for one instrument only."""
        return PaperMarket(
            identity=identity,
            at=at,
            bid=cls._price("9.95", dimension),
            ask=cls._price("10", dimension),
            bid_quantity=cls._quantity("2", dimension),
            ask_quantity=cls._quantity("2", dimension),
        )

    @classmethod
    def _net_batch(
        cls, request: AccountDecision, authority_scope: Literal["paper", "shadow"]
    ) -> PortfolioBatch:
        """Reserve a physical parent under one signed strategy context."""
        return PortfolioBatch(
            identity=f"batch-{request.decision.identity}",
            at=request.decision.at + timedelta(microseconds=1),
            decisions=(
                PortfolioDecision(
                    request=request,
                    context=PortfolioContext(
                        portfolio_id="reference",
                        strategy_id=request.instance_id,
                        model_revision="no-model",
                        config_revision="v1",
                        horizon="one-minute",
                        reason="unsent-shadow-test",
                        venue="okx",
                        settlement="spot-immediate",
                        risk_bucket="spot",
                        authority_scope=authority_scope,
                    ),
                ),
            ),
        )

    def test_distinct_instruments_match_under_exact_source_and_owner_scope(
        self, tmp_path: Path
    ) -> None:
        """One account grants and matches both signed instrument profiles."""
        admin, worker, clock, deployment, owner = self._start(tmp_path / "sources.sqlite3")
        assert tuple(scenario.instrument_id for scenario in deployment.scenarios) == (
            self.first.instrument_id,
            self.second.instrument_id,
        )
        assert deployment.scope_for("beta").input_identity == "bitfinex-second-book"
        with pytest.raises(ValueError, match="instance differs"):
            deployment.scope_for("unknown")
        with pytest.raises(ValueError, match="instrument_or_currency_differs"):
            deployment.require_authorization(
                replace(
                    self._authorization(deployment), quantities=(self._quantity("5", self.first),)
                )
            )
        with pytest.raises(ValueError, match="incompatible"):
            admin.install_paper(
                replace(
                    deployment,
                    additional_sources=(
                        replace(deployment.source_bindings[1], input_identity="other-book"),
                    ),
                )
            )
        first = self._decision("alpha", self.first, "first", self._at(13))
        second = self._decision("beta", self.second, "second", self._at(13))
        worker.observe(first.quote)
        worker.observe(second.quote)
        assert worker.admit(first).status == "committed"
        assert worker.admit(second).status == "committed"
        with pytest.raises(ValueError, match="scope_differs"):
            worker.admit(self._decision("alpha", self.second, "wrong-instrument", self._at(13)))
        with pytest.raises(ValueError, match="scope_differs"):
            worker.admit(self._decision("unknown", self.first, "wrong-owner", self._at(13)))
        clock.at = self._at(14)
        first_trace = worker.match_public_market(
            "shared", self._market(self.first, "first-book", self._at(14)), deployment.scenarios[0]
        )
        second_trace = worker.match_public_market(
            "shared",
            self._market(self.second, "second-book", self._at(14)),
            deployment.scenarios[1],
        )
        assert any(event.fill is not None for event in first_trace.child_fill_events)
        assert any(event.fill is not None for event in second_trace.child_fill_events)
        assert {
            position.dimension
            for position in AccountLedger(worker.accounts()[0].ledger).snapshot().positions
        } == {
            self.first,
            self.second,
        }
        stale = AccountJournal(
            worker.path,
            worker.config,
            paper_owner=replace(owner, generation=owner.generation + 1),
            clock=clock,
        )
        with pytest.raises(ValueError, match="stale_or_absent"):
            stale.bind_paper_scenario("shared", deployment.scenarios[0])

    def test_context_venue_and_shadow_fill_paths_remain_fenced(self, tmp_path: Path) -> None:
        """Per-instance venue checks and shadow mode prohibit modeled economics."""
        _, worker, _, _, _ = self._start(tmp_path / "venue.sqlite3")
        request = self._decision("beta", self.second, "wrong-venue", self._at(13))
        worker.observe(request.quote)
        context = PortfolioContext(
            portfolio_id="reference",
            strategy_id="beta",
            model_revision="no-model",
            config_revision="v1",
            horizon="one-minute",
            reason="source-scope-test",
            venue="okx",
            settlement="spot-immediate",
            risk_bucket="spot",
            authority_scope="paper",
        )
        with pytest.raises(ValueError, match="context_differs"):
            worker.coordinate(
                PortfolioBatch(
                    identity="wrong-venue-batch",
                    at=self._at(13) + timedelta(microseconds=1),
                    decisions=(PortfolioDecision(request=request, context=context),),
                )
            )
        _, shadow, shadow_clock, shadow_deployment, _ = self._start(
            tmp_path / "shadow.sqlite3", "shadow"
        )
        assert shadow_deployment.submission_authority == "shadow"
        shadow_request = self._decision("alpha", self.first, "shadow-order", self._at(13))
        shadow.observe(shadow_request.quote)
        assert shadow.admit(shadow_request).status == "committed"
        shadow_clock.at = self._at(14)
        with pytest.raises(ValueError, match="automatic matching requires paper"):
            shadow.match_public_market(
                "shared",
                self._market(self.first, "shadow-book", self._at(14)),
                shadow_deployment.scenarios[0],
            )
        with pytest.raises(ValueError, match="cannot internally match"):
            shadow.coordinate(
                PortfolioBatch(
                    identity="shadow-cross",
                    at=self._at(14) + timedelta(microseconds=1),
                    decisions=(
                        PortfolioDecision(
                            request=shadow_request,
                            context=replace(context, venue="okx", authority_scope="shadow"),
                        ),
                    ),
                    crossing="internal_at_quote",
                )
            )
        assert AccountLedger(shadow.accounts()[0].ledger).snapshot().positions == ()
        assert shadow.paper_traces() == ()

    @pytest.mark.parametrize("cancel_before_reject", (False, True))
    def test_stopped_shadow_rejects_only_unsent_net_parent_and_reclaims(
        self, tmp_path: Path, cancel_before_reject: bool
    ) -> None:
        """A fenced local rejection settles an unsent parent before owner replacement."""
        admin, worker, clock, deployment, owner = self._start(
            tmp_path / "shadow-recovery.sqlite3", "shadow"
        )
        request = replace(
            self._decision("alpha", self.first, "shadow-net", self._at(13)),
            checkpoint=b"shadow-checkpoint",
        )
        worker.observe(request.quote)
        committed = worker.coordinate(self._net_batch(request, "shadow"))
        assert committed.status == "committed" and len(committed.net_orders) == 1
        parent = committed.net_orders[0]
        assert parent.order.status == "intent"
        assert not parent.order.accepted and parent.order.filled.value == 0
        rejected = OrderEvent(
            identity="local-unsent-shadow-rejection",
            order_id=parent.order.identity,
            at=self._at(16),
            kind="rejected",
        )
        clock.at = self._at(14)
        with pytest.raises(ValueError, match="managed_paper_events_require_public_matching"):
            worker.apply_net_event(replace(rejected, at=clock.at))
        if cancel_before_reject:
            worker.stop_instance("alpha", clock.at)
            assert worker.net_orders()[0].order.status == "cancel_requested"
        stop = AccountControl(
            identity="shadow-stop",
            account_id="shared",
            kind="stop",
            at=self._at(15),
            reason="settle unsent shadow reservation",
        )
        clock.at = stop.at
        assert worker.control(stop).status == "applied"
        clock.at = rejected.at
        stale = AccountJournal(
            worker.path,
            worker.config,
            paper_owner=replace(owner, generation=owner.generation + 1),
            clock=clock,
        )
        with pytest.raises(ValueError, match="paper_owner_stale_or_absent"):
            stale.apply_net_event(rejected)
        for kind in ("accepted", "cancelled"):
            with pytest.raises(ValueError, match="managed_paper_events_require_public_matching"):
                worker.apply_net_event(replace(rejected, identity=f"manual-{kind}", kind=kind))
        physical_fill = Fill(
            identity="prohibited-shadow-fill",
            decision_at=parent.order.decision_at,
            filled_at=clock.at,
            quantity=self._quantity("1", self.first),
            reference=self._price("10", self.first),
            effective=self._price("10", self.first),
            fee=self._money("0"),
        )
        with pytest.raises(ValueError, match="managed_paper_events_require_public_matching"):
            worker.apply_net_event(
                replace(rejected, identity="manual-fill", kind="fill", fill=physical_fill)
            )
        with pytest.raises(ValueError, match="managed_paper_events_require_public_matching"):
            worker.apply_net_event(replace(rejected, at=self._at(17)))
        before = (
            worker.accounts()[0].ledger,
            worker.paper_report_facts("shared"),
            worker.checkpoint("alpha"),
        )
        settled = worker.apply_net_event(rejected)
        assert settled.order.status == "rejected"
        assert worker.apply_net_event(rejected) == settled
        assert worker.physical_open_orders("shared") == ()
        if cancel_before_reject:
            assert worker.orders()[0].order.status == "cancelled"
        else:
            worker.stop_instance("alpha", clock.at)
            assert worker.orders()[0].order.status == "cancelled"
        assert (
            worker.accounts()[0].ledger,
            worker.paper_report_facts("shared"),
            worker.checkpoint("alpha"),
        ) == before
        with pytest.raises(ValueError, match="managed_paper_events_require_public_matching"):
            worker.apply_net_event(replace(rejected, identity="second-local-rejection"))

        clock.at = self._at(17)
        for dimension in (self.first, self.second):
            worker.observe(AccountQuote(price=self._price("10", dimension), at=clock.at))
        assert worker.reconcile(
            AccountObservation(
                identity="flat-after-unsent-rejection",
                at=clock.at,
                snapshot=self._opening(),
                open_orders=(),
            )
        )
        clock.at = self._at(18)
        successor = admin.claim_paper(
            "shared",
            "worker-two",
            deployment.releases[0],
            AccountControl(
                identity="shadow-claim-two",
                account_id="shared",
                kind="restart",
                at=clock.at,
                expected_control_identity=stop.identity,
            ),
        )
        assert successor.generation == owner.generation + 1
        resumed = AccountJournal(worker.path, worker.config, paper_owner=successor, clock=clock)
        with pytest.raises(ValueError, match="paper_owner_stale_or_absent"):
            worker.apply_net_event(rejected)
        assert resumed.apply_net_event(rejected) == settled
        assert resumed.accounts()[0].ledger == before[0]
        assert resumed.checkpoint("alpha") == before[2]
        with pytest.raises(ValueError, match="managed_paper_events_require_public_matching"):
            resumed.apply_net_event(replace(rejected, identity="running-rejection"))

    def test_managed_paper_net_rejection_stays_matching_only(self, tmp_path: Path) -> None:
        """A stopped paper deployment cannot use shadow's local rejection path."""
        _, worker, clock, _, _ = self._start(tmp_path / "paper-net.sqlite3")
        request = self._decision("alpha", self.first, "paper-net", self._at(13))
        worker.observe(request.quote)
        committed = worker.coordinate(self._net_batch(request, "paper"))
        assert committed.status == "committed" and len(committed.net_orders) == 1
        clock.at = self._at(14)
        assert (
            worker.control(
                AccountControl(
                    identity="paper-stop",
                    account_id="shared",
                    kind="stop",
                    at=clock.at,
                    reason="paper matching remains exclusive",
                )
            ).status
            == "applied"
        )
        with pytest.raises(ValueError, match="managed_paper_events_require_public_matching"):
            worker.apply_net_event(
                OrderEvent(
                    identity="paper-manual-rejection",
                    order_id=committed.net_orders[0].order.identity,
                    at=clock.at,
                    kind="rejected",
                )
            )

    def test_legacy_wire_bytes_and_conflicting_sources(self) -> None:
        """An absent extension preserves v1 JSON and rejects ambiguous overrides."""
        config = self._config()
        extended = self._deployment(config)
        legacy = replace(extended, additional_sources=msgspec.UNSET)
        codec = DomainCodec()
        expected = codec.encode_json(
            {
                "account_id": legacy.account_id,
                "configuration_sha256": legacy.configuration_sha256,
                "releases": legacy.releases,
                "strategies": legacy.strategies,
                "input_identity": legacy.input_identity,
                "scenario": legacy.scenario,
                "state_identity": legacy.state_identity,
                "enabled": legacy.enabled,
                "submission_authority": legacy.submission_authority,
                "state_schema": legacy.state_schema,
                "schema_version": legacy.schema_version,
            }
        )
        assert codec.encode_json(legacy) == expected
        assert legacy.identity == hashlib.sha256(expected).hexdigest()
        assert codec.decode_json(expected, PaperDeployment) == legacy
        with pytest.raises(ValueError, match="omits empty source overrides"):
            replace(legacy, additional_sources=())
        with pytest.raises(ValueError, match="source instance differs"):
            replace(
                extended,
                additional_sources=(extended.source_bindings[1], extended.source_bindings[1]),
            )
        with pytest.raises(ValueError, match="override is redundant"):
            replace(
                extended,
                additional_sources=(
                    replace(
                        extended.source_bindings[1],
                        input_identity=extended.input_identity,
                        scenario=extended.scenario,
                    ),
                ),
            )
        with pytest.raises(ValueError, match="instrument source differs"):
            replace(
                extended,
                additional_sources=(
                    replace(extended.source_bindings[1], scenario=extended.scenario),
                ),
            )
