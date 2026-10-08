"""Verify managed paper authority, recovery fencing and exact retained economics."""

from __future__ import annotations

# standard library imports
import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

# third party library imports
import pytest
from msgspec.structs import replace
from paper_books import PaperBooks

# project library imports
from accounting import AccountLedger, AccountPosting, AccountSnapshot, Fill
from configuration import (
    AccountConfiguration,
    OpeningAccount,
    PaperAuthorization,
    PaperDeployment,
    PaperExecutionScenario,
    PaperStrategyIdentity,
)
from configuration.accounts import InstrumentFeeRate
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
    PaperReductionRequest,
    PortfolioBatch,
    PortfolioContext,
    PortfolioDecision,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent


class _PaperClock:
    """Supply an operator clock that can advance independently of request history."""

    def __init__(self, at: datetime) -> None:
        """Start the explicit UTC test clock."""
        self.at = at

    def __call__(self) -> datetime:
        """Return current time at each journal economic boundary."""
        return self.at


class TestPaperActivation:
    """Exercise the managed public journal without installation or feed adapters."""

    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)
    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    first_release = "a" * 64
    rollback_release = "b" * 64

    @classmethod
    def _at(cls, seconds: int) -> datetime:
        """Use exact event and wall-clock points within one bounded session."""
        return cls.opening_at + timedelta(seconds=seconds)

    @classmethod
    def _money(cls, value: str) -> Money:
        """Construct exact quote-currency cash or cost."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Construct exact base units with the configured instrument identity."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Construct an exact on-tick price."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Give two strategies independent ceilings on a shared paper account."""
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(
                maximum=cls._quantity("20"),
                lot=cls._quantity("1"),
                tick=cls._price("0.01"),
                product="spot",
            ),
        )
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.opening_at,
            accounts=(OpeningAccount(account_id="shared", cash=(cls._money("1000"),)),),
            instruments=spot_limits,
            fee_rates=tuple(
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal("0.01")
                )
                for limits in spot_limits
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.currency,
                firm_maximum=cls._money("1000"),
                accounts=(AccountLimit(account_id="shared", maximum=cls._money("1000")),),
                instances=tuple(
                    InstanceLimit(
                        instance_id=instance,
                        account_id="shared",
                        maximum=cls._money("1000"),
                        instruments=(cls.dimension.instrument_id,),
                    )
                    for instance in ("alpha", "beta")
                ),
                max_quote_age_us=10_000_000,
                max_state_age_us=60_000_000,
                max_residual_age_us=86_400_000_000,
                max_price_deviation_bps=200,
                max_order_notional=cls._money("1000"),
            ),
        )

    @classmethod
    def _scenario(cls) -> PaperExecutionScenario:
        """Pin finite public-book liquidity and explicit modeled costs."""
        return PaperExecutionScenario(
            venue="okx",
            instrument_id=cls.dimension.instrument_id,
            entry_delay_us=0,
            cancel_delay_us=0,
            adverse=cls._price("0.01"),
            fee_rate=Decimal("0.01"),
            take_fraction=Decimal(1),
            gas_inapplicable_reason="off-chain spot matching",
        )

    @classmethod
    def _opening(cls) -> AccountSnapshot:
        """Supply complete opening facts independently of journal projection."""
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
    def _deployment(cls, config: AccountConfiguration) -> PaperDeployment:
        """Bind two compatible release digests to one disabled strategy deployment."""
        return PaperDeployment(
            account_id="shared",
            configuration_sha256=hashlib.sha256(DomainCodec().encode_json(config)).hexdigest(),
            releases=(cls.first_release, cls.rollback_release),
            strategies=(
                PaperStrategyIdentity(
                    instance_id="alpha",
                    policy_identity="policy-alpha",
                    candidate_identity="candidate-alpha",
                    model_identity="no-model",
                    feature_identity="feature-alpha",
                ),
            ),
            input_identity="public-okx-book",
            scenario=cls._scenario(),
            state_identity="paper-account-state",
        )

    @classmethod
    def _authorization(
        cls,
        deployment: PaperDeployment,
        *,
        identity: str = "bounded-paper-session",
        quantity: str = "5",
        maximum_notional: str = "100",
        maximum_orders: int = 5,
    ) -> PaperAuthorization:
        """Make one exact finite grant for the immutable deployment."""
        return PaperAuthorization(
            identity=identity,
            deployment_sha256=deployment.identity,
            valid_from=cls._at(11),
            expires_at=cls._at(30),
            quantities=(cls._quantity(quantity),),
            maximum_order_notional=cls._money(maximum_notional),
            maximum_orders=maximum_orders,
        )

    @classmethod
    def _quote(cls, at: datetime) -> AccountQuote:
        """Use a separately observed mid valuation for independent risk."""
        return AccountQuote(price=cls._price("10"), at=at)

    @classmethod
    def _market(
        cls,
        identity: str,
        at: datetime,
        *,
        bid_quantity: str = "2",
        ask_quantity: str = "2",
    ) -> PaperMarket:
        """Supply a finite uncrossed quote whose bid can execute a reduction."""
        return PaperMarket(
            identity=identity,
            at=at,
            bid=cls._price("9.95"),
            ask=cls._price("10"),
            bid_quantity=cls._quantity(bid_quantity),
            ask_quantity=cls._quantity(ask_quantity),
        )

    @classmethod
    def _decision(
        cls,
        identity: str,
        at: datetime,
        quote: AccountQuote,
        *,
        instance_id: str = "alpha",
        quantity: str = "1",
    ) -> AccountDecision:
        """Build one portable buy checked against actual wall time and durable scope."""
        return AccountDecision(
            account_id="shared",
            instance_id=instance_id,
            decision=OrderDecision(
                identity=identity,
                at=at,
                intent=OrderIntent(
                    side="buy",
                    quantity=cls._quantity(quantity),
                    limit=cls._price("10.10"),
                    time_in_force="gtc",
                ),
            ),
            quote=quote,
            maximum_fee=cls._money("1"),
        )

    @classmethod
    def _reduction(cls, identity: str, at: datetime, quote: AccountQuote) -> PaperReductionRequest:
        """Request one owned sale at a minimum executable paper price."""
        return PaperReductionRequest(
            identity=identity,
            account_id="shared",
            instance_id="alpha",
            quantity=cls._quantity("1"),
            quote=quote,
            limit=cls._price("9.90"),
            maximum_fee=cls._money("1"),
            at=at,
        )

    @classmethod
    def _bootstrap(
        cls,
        path: Path,
        *,
        quantity: str = "5",
        maximum_notional: str = "100",
        maximum_orders: int = 5,
    ) -> tuple[
        AccountJournal,
        AccountJournal,
        _PaperClock,
        PaperDeployment,
        PaperAuthorization,
        PaperOwner,
    ]:
        """Install, grant, reconcile and claim one current managed owner."""
        config = cls._config()
        clock = _PaperClock(cls._at(10))
        admin = AccountJournal(path, config, clock=clock)
        assert admin.reconcile(
            AccountObservation(
                identity="opening",
                at=cls._at(1),
                snapshot=cls._opening(),
                open_orders=(),
            )
        )
        deployment = cls._deployment(config)
        admin.install_paper(deployment)
        clock.at = cls._at(11)
        authorization = cls._authorization(
            deployment,
            quantity=quantity,
            maximum_notional=maximum_notional,
            maximum_orders=maximum_orders,
        )
        admin.authorize_paper(authorization)
        assert admin.reconcile(
            AccountObservation(
                identity="after-install",
                at=cls._at(12),
                snapshot=cls._opening(),
                open_orders=(),
            )
        )
        quote = cls._quote(cls._at(12))
        admin.observe(quote)
        clock.at = cls._at(13)
        owner = admin.claim_paper(
            "shared",
            "worker-first",
            cls.first_release,
            AccountControl(
                identity="claim-first",
                account_id="shared",
                kind="restart",
                at=cls._at(13),
                expected_control_identity=f"paper-deployment:{deployment.identity}",
            ),
        )
        worker = AccountJournal(path, config, paper_owner=owner, clock=clock)
        return admin, worker, clock, deployment, authorization, owner

    def test_disabled_install_and_claim_require_exact_fresh_grant(self, tmp_path: Path) -> None:
        """Installation stays stopped; permission and current state precede owner claim."""
        path = tmp_path / "activation.sqlite3"
        config = self._config()
        clock = _PaperClock(self._at(10))
        admin = AccountJournal(path, config, clock=clock)
        assert admin.reconcile(
            AccountObservation(
                identity="opening",
                at=self._at(1),
                snapshot=self._opening(),
                open_orders=(),
            )
        )
        deployment = self._deployment(config)
        with pytest.raises(ValueError, match="disabled"):
            replace(deployment, enabled=True)
        admin.install_paper(deployment)
        admin.install_paper(deployment)
        assert admin.accounts()[0].phase == "stopped"
        activation = admin.paper_activations()[0]
        assert activation.deployment == deployment
        assert activation.authorization is None
        assert activation.owner is None
        with closing(sqlite3.connect(path)) as connection:
            row = cast(
                tuple[str] | None,
                connection.execute(
                    "SELECT json_extract(payload, '$.schema_version') FROM firm WHERE id=1"
                ).fetchone(),
            )
        assert row == ("account-journal",)
        assert AccountJournal.verify(path, config) == admin.accounts()
        assert AccountJournal(path, config, clock=clock).paper_activations() == (activation,)
        restart = AccountControl(
            identity="claim-without-grant",
            account_id="shared",
            kind="restart",
            at=self._at(13),
            expected_control_identity=f"paper-deployment:{deployment.identity}",
        )
        clock.at = self._at(13)
        with pytest.raises(ValueError, match="paper_authorization_absent"):
            admin.claim_paper("shared", "worker", self.first_release, restart)
        with pytest.raises(ValueError, match="managed_paper_restart_requires_owner_claim"):
            admin.control(restart)
        wrong = replace(
            self._authorization(deployment),
            deployment_sha256="c" * 64,
        )
        with pytest.raises(ValueError, match="paper_deployment_absent_or_mismatched"):
            admin.authorize_paper(wrong)
        clock.at = self._at(31)
        with pytest.raises(ValueError, match="expired_or_not_yet_valid"):
            admin.authorize_paper(self._authorization(deployment))
        clock.at = self._at(11)
        admin.authorize_paper(self._authorization(deployment))
        clock.at = self._at(13)
        with pytest.raises(ValueError, match="account_recovery_requires_fresh_reconciliation"):
            admin.claim_paper("shared", "worker", self.first_release, restart)
        assert admin.reconcile(
            AccountObservation(
                identity="fresh-after-install",
                at=self._at(12),
                snapshot=self._opening(),
                open_orders=(),
            )
        )
        admin.observe(self._quote(self._at(12)))
        clock.at = self._at(13)
        with pytest.raises(ValueError, match="paper_release_incompatible"):
            admin.claim_paper("shared", "worker", "c" * 64, restart)
        owner = admin.claim_paper("shared", "worker", self.first_release, restart)
        assert owner.generation == 1
        assert admin.accounts()[0].phase == "running"
        assert admin.paper_activations()[0].owner == owner

    @pytest.mark.parametrize(
        ("quantity_limit", "notional_limit", "requested", "reason"),
        (
            ("5", "15", "2", "paper_authorization_notional_limit"),
            ("1", "100", "2", "paper_authorization_quantity_limit"),
        ),
    )
    def test_scoped_size_caps_reject_before_any_new_order(
        self,
        tmp_path: Path,
        quantity_limit: str,
        notional_limit: str,
        requested: str,
        reason: str,
    ) -> None:
        """Managed bounds survive the independent account admission check."""
        admin, worker, clock, _, _, _ = self._bootstrap(
            tmp_path / "sized.sqlite3",
            quantity=quantity_limit,
            maximum_notional=notional_limit,
        )
        clock.at = self._at(14)
        quote = self._quote(self._at(12))
        with pytest.raises(ValueError, match="paper_authorization_scope_differs"):
            worker.admit(
                self._decision("beta-outside-deployment", self._at(14), quote, instance_id="beta")
            )
        result = worker.admit(
            self._decision("oversize-buy", self._at(14), quote, quantity=requested)
        )
        assert (result.status, result.reason, result.orders) == ("rejected", reason, ())
        assert worker.orders() == ()
        assert admin.accounts()[0].ledger == worker.accounts()[0].ledger
        assert (
            worker.admit(self._decision("oversize-buy", self._at(14), quote, quantity=requested))
            == result
        )

    def test_order_count_and_current_wall_clock_fence_historical_decisions(
        self, tmp_path: Path
    ) -> None:
        """A later wall clock defeats a historically valid request; count stays finite."""
        _, worker, clock, _, _, _ = self._bootstrap(tmp_path / "count.sqlite3", maximum_orders=1)
        quote = self._quote(self._at(12))
        clock.at = self._at(14)
        first = worker.admit(self._decision("first-buy", self._at(14), quote))
        assert first.status == "committed"
        clock.at = self._at(15)
        second = worker.admit(self._decision("second-buy", self._at(15), quote))
        assert (second.status, second.reason) == ("rejected", "paper_authorization_order_limit")
        assert len(worker.orders()) == 1
        clock.at = self._at(31)
        with pytest.raises(ValueError, match="paper_authorization_expired_or_not_yet_valid"):
            worker.admit(self._decision("historical-but-late", self._at(14), quote))
        assert len(worker.orders()) == 1

    def test_current_clock_rejects_stale_direct_inputs_and_future_market(
        self, tmp_path: Path
    ) -> None:
        """A still-valid grant cannot launder stale quotes or future paper books."""
        _, worker, clock, _, _, _ = self._bootstrap(tmp_path / "current-input.sqlite3")
        quote = self._quote(self._at(12))
        clock.at = self._at(25)
        with pytest.raises(ValueError, match="paper_input_stale_or_future"):
            worker.admit(self._decision("stale-direct-buy", self._at(14), quote))
        assert worker.orders() == ()
        with pytest.raises(ValueError, match="paper_market_stale_or_future"):
            PaperBooks.apply(
                worker, "shared", self._market("stale-book", self._at(14)), self._scenario()
            )
        assert tuple(worker.iter_paper_traces("shared")) == ()
        clock.at = self._at(14)
        with pytest.raises(ValueError, match="paper_input_stale_or_future"):
            worker.admit(self._decision("future-direct-buy", self._at(15), quote))
        with pytest.raises(ValueError, match="paper_market_stale_or_future"):
            PaperBooks.apply(
                worker, "shared", self._market("future-book", self._at(15)), self._scenario()
            )
        assert worker.orders() == ()
        assert tuple(worker.iter_paper_traces("shared")) == ()

    def test_managed_portfolio_context_matches_deployment_before_mutation(
        self, tmp_path: Path
    ) -> None:
        """Model, venue and paper authority are pinned before batch or checkpoint writes."""
        _, worker, clock, _, _, _ = self._bootstrap(tmp_path / "managed-portfolio.sqlite3")
        decision_at = self._at(14)
        batch_at = decision_at + timedelta(microseconds=1)
        clock.at = batch_at
        quote = self._quote(self._at(12))
        valid_context = PortfolioContext(
            portfolio_id="managed-portfolio",
            strategy_id="alpha",
            model_revision="no-model",
            config_revision="config",
            horizon="one-minute",
            reason="bounded-paper-order",
            venue="okx",
            settlement="spot-immediate",
            risk_bucket="spot",
            authority_scope="paper",
        )
        baseline = AccountLedger(worker.accounts()[0].ledger).snapshot()
        assert baseline == self._opening()
        invalid_contexts = (
            ("other-model", replace(valid_context, model_revision="uninstalled-model")),
            ("other-venue", replace(valid_context, venue="other-venue")),
            ("production", replace(valid_context, authority_scope="production")),
        )
        for identity, context in invalid_contexts:
            request = replace(
                self._decision(identity, decision_at, quote),
                checkpoint=f"checkpoint-{identity}".encode(),
            )
            batch = PortfolioBatch(
                identity=f"invalid-{identity}",
                at=batch_at,
                decisions=(PortfolioDecision(request=request, context=context),),
            )
            with pytest.raises(ValueError, match="paper_deployment_context_differs"):
                worker.coordinate(batch)
            assert worker.portfolio_batch(batch.identity) is None
            assert worker.checkpoint("alpha") is None
            assert worker.orders() == ()
            assert worker.net_orders() == ()
            assert AccountLedger(worker.accounts()[0].ledger).snapshot() == baseline

        valid_request = replace(
            self._decision("valid-managed-portfolio", decision_at, quote),
            checkpoint=b"candidate-valid-managed-portfolio",
        )
        valid_batch = PortfolioBatch(
            identity="valid-managed-portfolio",
            at=batch_at,
            decisions=(PortfolioDecision(request=valid_request, context=valid_context),),
        )
        committed = worker.coordinate(valid_batch)
        assert committed.status == "committed"
        assert len(committed.children) == 1
        assert len(committed.net_orders) == 1
        assert worker.portfolio_batch(valid_batch.identity) == valid_batch
        assert worker.checkpoint("alpha") == valid_request.checkpoint
        assert AccountLedger(worker.accounts()[0].ledger).snapshot() == baseline

    def test_stopped_grant_replacement_fences_old_owner_without_replenishing_limits(
        self, tmp_path: Path
    ) -> None:
        """A new finite grant changes authority, not lifetime deployment economics."""
        admin, worker, clock, deployment, first_grant, first_owner = self._bootstrap(
            tmp_path / "renewal.sqlite3", maximum_orders=1
        )
        clock.at = self._at(14)
        quote = self._quote(self._at(12))
        assert (
            worker.admit(
                self._decision("first-before-renewal", self._at(14), quote, quantity="2")
            ).status
            == "committed"
        )
        renewed = self._authorization(deployment, identity="renewed-session", maximum_orders=1)
        with pytest.raises(ValueError, match="paper_reauthorization_requires_stop"):
            admin.authorize_paper(renewed)
        clock.at = self._at(15)
        assert (
            len(
                PaperBooks.apply(
                    worker,
                    "shared",
                    self._market("first-renewal-fill", self._at(15), ask_quantity="1"),
                    self._scenario(),
                ).child_fill_events
            )
            == 1
        )
        partial = AccountLedger(worker.accounts()[0].ledger).snapshot()
        clock.at = self._at(16)
        assert (
            admin.control(
                AccountControl(
                    identity="stop-for-renewal",
                    account_id="shared",
                    kind="stop",
                    at=self._at(16),
                    reason="replace finite grant",
                )
            ).status
            == "applied"
        )
        clock.at = self._at(17)
        admin.authorize_paper(renewed)
        admin.authorize_paper(renewed)
        activation = admin.paper_activations()[0]
        assert activation.authorization == renewed
        assert activation.authorizations == (first_grant, renewed)
        assert activation.owner is None
        with pytest.raises(ValueError, match="paper_owner_stale_or_absent"):
            worker.admit(
                self._decision("old-owner-after-renewal", self._at(17), self._quote(self._at(12)))
            )
        with pytest.raises(ValueError, match="paper_authorization_identity_reused"):
            admin.authorize_paper(replace(first_grant, maximum_orders=2))
        with pytest.raises(ValueError, match="paper_authorization_identity_reused"):
            admin.authorize_paper(replace(renewed, maximum_orders=2))
        clock.at = self._at(18)
        assert admin.reconcile(
            AccountObservation(
                identity="reconciled-for-renewal",
                at=self._at(18),
                snapshot=partial,
                open_orders=(worker.orders()[0].order,),
            )
        )
        current_quote = self._quote(self._at(18))
        admin.observe(current_quote)
        clock.at = self._at(19)
        replacement = admin.claim_paper(
            "shared",
            "worker-renewed",
            self.rollback_release,
            AccountControl(
                identity="claim-renewal",
                account_id="shared",
                kind="restart",
                at=self._at(19),
                expected_control_identity="stop-for-renewal",
            ),
        )
        assert replacement.generation == first_owner.generation + 1
        assert replacement.authorization_id == renewed.identity
        current_worker = AccountJournal(
            admin.path, self._config(), paper_owner=replacement, clock=clock
        )
        after = current_worker.admit(
            self._decision("second-after-renewal", self._at(19), current_quote)
        )
        assert (after.status, after.reason) == ("rejected", "paper_authorization_order_limit")
        assert len(current_worker.orders()) == 1

    @pytest.mark.parametrize("barrier", ("expired", "revoked"))
    def test_unsettled_renewal_preserves_owner_until_matcher_confirms_cancel(
        self, tmp_path: Path, barrier: Literal["expired", "revoked"]
    ) -> None:
        """A rejected replacement cannot strand an old owner's pending obligations."""
        admin, worker, clock, deployment, first_grant, first_owner = self._bootstrap(
            tmp_path / f"unsettled-{barrier}.sqlite3"
        )
        clock.at = self._at(14)
        admitted = worker.admit(
            self._decision("resting-before-renewal", self._at(14), self._quote(self._at(12)))
        )
        assert admitted.status == "committed"
        assert worker.orders()[0].order.status == "intent"
        clock.at = self._at(15)
        assert (
            admin.control(
                AccountControl(
                    identity="stop-unsettled-renewal",
                    account_id="shared",
                    kind="stop",
                    at=self._at(15),
                    reason="replace authority only after settlement",
                )
            ).status
            == "applied"
        )
        renewed = replace(
            self._authorization(deployment, identity="renew-after-settlement"),
            valid_from=self._at(16),
            expires_at=self._at(60),
        )
        clock.at = self._at(16)
        with pytest.raises(
            ValueError, match="paper_reauthorization_requires_settled_order_outcomes"
        ):
            admin.authorize_paper(renewed)
        assert admin.paper_activations()[0].owner == first_owner
        assert admin.paper_activations()[0].authorization == first_grant

        no_liquidity = PaperBooks.apply(
            worker,
            "shared",
            self._market(f"resting-{barrier}", self._at(16), ask_quantity="0"),
            self._scenario(),
        )
        assert no_liquidity.child_fill_events == ()
        assert worker.orders()[0].order.status == "accepted"
        clock.at = self._at(17)
        cancel = admin.control(
            AccountControl(
                identity="cancel-unsettled-renewal",
                account_id="shared",
                kind="cancel",
                at=self._at(17),
                reason="protective pending cancel",
            )
        )
        assert cancel.cancel_order_ids == (admitted.orders[0].identity,)
        assert worker.orders()[0].order.status == "cancel_requested"
        if barrier == "revoked":
            clock.at = self._at(18)
            admin.revoke_paper("shared", first_grant.identity, self._at(18))
            now = self._at(19)
        else:
            now = self._at(31)
        clock.at = now
        with pytest.raises(
            ValueError, match="paper_reauthorization_requires_settled_order_outcomes"
        ):
            admin.authorize_paper(renewed)
        assert admin.paper_activations()[0].owner == first_owner
        assert admin.paper_activations()[0].authorization == first_grant
        assert AccountLedger(worker.accounts()[0].ledger).snapshot() == self._opening()

        due = now + timedelta(seconds=1)
        clock.at = due
        settled = PaperBooks.apply(
            worker,
            "shared",
            self._market(f"cancel-confirmed-{barrier}", due, ask_quantity="0"),
            self._scenario(),
        )
        assert tuple(event.kind for event in settled.physical_events) == ("cancelled_on_request",)
        assert worker.orders()[0].order.status == "cancelled"
        assert AccountLedger(worker.accounts()[0].ledger).snapshot() == self._opening()
        clock.at = due + timedelta(seconds=1)
        admin.authorize_paper(renewed)
        activation = admin.paper_activations()[0]
        assert activation.authorization == renewed
        assert activation.authorizations == (first_grant, renewed)
        assert activation.owner is None
        with pytest.raises(ValueError, match="paper_owner_stale_or_absent"):
            PaperBooks.apply(
                worker,
                "shared",
                self._market(f"old-token-{barrier}", clock.at, ask_quantity="0"),
                self._scenario(),
            )

    @pytest.mark.parametrize("expired", (False, True))
    def test_managed_owner_cannot_inject_fill_or_transfer(
        self, tmp_path: Path, expired: bool
    ) -> None:
        """Current and expired owners derive economics only from public-book matching."""
        _, worker, clock, _, _, _ = self._bootstrap(tmp_path / f"manual-{expired}.sqlite3")
        clock.at = self._at(14)
        admitted = worker.admit(
            self._decision("pending-two", self._at(14), self._quote(self._at(12)), quantity="2")
        )
        assert admitted.status == "committed"
        order_id = admitted.orders[0].identity
        clock.at = self._at(15)
        no_liquidity = PaperBooks.apply(
            worker,
            "shared",
            self._market("empty-book", self._at(15), ask_quantity="0"),
            self._scenario(),
        )
        assert no_liquidity.child_fill_events == ()
        accepted = worker.orders()[0].order
        assert accepted.status == "accepted"
        now = self._at(31 if expired else 16)
        clock.at = now
        assert worker.reconcile(
            AccountObservation(
                identity=f"fresh-before-manual-{expired}",
                at=now,
                snapshot=self._opening(),
                open_orders=(accepted,),
            )
        )
        worker.observe(self._quote(now))
        manual_fill = Fill(
            identity=f"manual-fill-{expired}",
            decision_at=self._at(14),
            filled_at=now,
            quantity=self._quantity("2"),
            reference=self._price("10"),
            effective=self._price("10.01"),
            fee=self._money("0.2002"),
        )
        with pytest.raises(ValueError, match="managed_paper"):
            worker.apply_event(
                OrderEvent(
                    identity=f"manual-receipt-{expired}",
                    order_id=order_id,
                    at=now,
                    kind="fill",
                    fill=manual_fill,
                )
            )
        with pytest.raises(ValueError, match="managed_paper_events_require_public_matching"):
            worker.apply_event(
                OrderEvent(
                    identity=f"fabricated-cancel-{expired}",
                    order_id=order_id,
                    at=now,
                    kind="cancelled",
                )
            )
        with pytest.raises(ValueError, match="managed_paper"):
            worker.post(
                AccountPosting(
                    identity=f"manual-cash-{expired}",
                    account_id="shared",
                    kind="transfer",
                    event_at=now,
                    known_at=now,
                    cash=self._money("100"),
                )
            )
        assert AccountLedger(worker.accounts()[0].ledger).snapshot() == self._opening()
        assert worker.orders()[0].order.status == "accepted"
        later = now + timedelta(seconds=1)
        clock.at = later
        matched = PaperBooks.apply(
            worker, "shared", self._market(f"actual-book-{expired}", later), self._scenario()
        )
        assert len(matched.child_fill_events) == 1
        after = AccountLedger(worker.accounts()[0].ledger).snapshot()
        assert after.cash == (self._money("979.7798"),)
        assert after.positions == (self._quantity("2"),)
        assert after.fees == (self._money("0.2002"),)

    def test_restart_and_compatible_release_retry_preserve_exact_economics(
        self, tmp_path: Path
    ) -> None:
        """A new owner and compatible release resume one pending buy exactly once."""
        path = tmp_path / "recovery.sqlite3"
        admin, worker, clock, _, _, first_owner = self._bootstrap(path)
        clock.at = self._at(14)
        quote = self._quote(self._at(12))
        request = self._decision("two-unit-buy", self._at(14), quote, quantity="2")
        admitted = worker.admit(request)
        assert admitted.status == "committed"
        assert len(admitted.orders) == 1
        clock.at = self._at(15)
        first_market = self._market("partial-book", self._at(15), ask_quantity="1")
        first_trace = PaperBooks.apply(worker, "shared", first_market, self._scenario())
        assert worker.paper_trace("shared", first_market.identity) is not None
        assert len(first_trace.child_fill_events) == 1
        first_fill = first_trace.child_fill_events[0].fill
        assert first_fill is not None
        assert (first_fill.quantity, first_fill.effective, first_fill.fee) == (
            self._quantity("1"),
            self._price("10.01"),
            self._money("0.1001"),
        )
        partial = AccountLedger(worker.accounts()[0].ledger).snapshot()
        assert partial.cash == (self._money("989.8899"),)
        assert partial.positions == (self._quantity("1"),)
        assert partial.fees == (self._money("0.1001"),)
        assert PaperBooks.apply(worker, "shared", first_market, self._scenario()) == first_trace
        assert AccountLedger(worker.accounts()[0].ledger).snapshot() == partial

        clock.at = self._at(16)
        stop = admin.control(
            AccountControl(
                identity="pause-for-recovery",
                account_id="shared",
                kind="stop",
                at=self._at(16),
                reason="operator restart drill",
            )
        )
        assert stop.status == "applied"
        clock.at = self._at(17)
        open_order = worker.orders()[0].order
        assert open_order.status == "partial"
        assert worker.reconcile(
            AccountObservation(
                identity="after-partial-and-stop",
                at=self._at(17),
                snapshot=partial,
                open_orders=(open_order,),
            )
        )
        worker.observe(self._quote(self._at(17)))
        clock.at = self._at(18)
        rollback_owner = admin.claim_paper(
            "shared",
            "worker-rollback",
            self.rollback_release,
            AccountControl(
                identity="claim-rollback",
                account_id="shared",
                kind="restart",
                at=self._at(18),
                expected_control_identity="pause-for-recovery",
            ),
        )
        assert rollback_owner.generation == first_owner.generation + 1
        assert rollback_owner.release_identity == self.rollback_release
        with pytest.raises(ValueError, match="paper_owner_stale_or_absent"):
            worker.apply_public_market("shared", first_market, self._scenario())
        with pytest.raises(ValueError, match="paper_owner_stale_or_absent"):
            worker.admit(self._decision("stale-owner-buy", self._at(18), self._quote(self._at(17))))
        with pytest.raises(ValueError, match="paper_owner_stale_or_absent"):
            PaperBooks.apply(
                worker, "shared", self._market("stale-owner-book", self._at(19)), self._scenario()
            )
        with pytest.raises(ValueError, match="paper_owner_stale_or_absent"):
            worker.reduce_paper(
                self._reduction("stale-owner-reduction", self._at(18), self._quote(self._at(17)))
            )

        rollback = AccountJournal(path, self._config(), paper_owner=rollback_owner, clock=clock)
        # The new owner's exact retry of the first book returns its saved trace and
        # leaves the later valuation, ledger and liquidity as they are.
        valued = rollback.valuation(self.dimension)
        with closing(sqlite3.connect(path)) as connection:
            head_before = cast(
                tuple[bytes], connection.execute("SELECT payload FROM firm").fetchone()
            )
        assert PaperBooks.apply(rollback, "shared", first_market, self._scenario()) == first_trace
        assert rollback.valuation(self.dimension) == valued == self._quote(self._at(17))
        with closing(sqlite3.connect(path)) as connection:
            head_after = cast(
                tuple[bytes], connection.execute("SELECT payload FROM firm").fetchone()
            )
        assert head_after == head_before
        clock.at = self._at(19)
        second_market = self._market("remaining-book", self._at(19), ask_quantity="2")
        assert rollback.paper_trace("shared", second_market.identity) is None
        final_trace = PaperBooks.apply(rollback, "shared", second_market, self._scenario())
        assert rollback.paper_trace("shared", second_market.identity) is not None
        assert len(final_trace.child_fill_events) == 1
        final_fill = final_trace.child_fill_events[0].fill
        assert final_fill is not None
        assert (final_fill.quantity, final_fill.effective, final_fill.fee) == (
            self._quantity("1"),
            self._price("10.01"),
            self._money("0.1001"),
        )
        finished = AccountLedger(rollback.accounts()[0].ledger).snapshot()
        assert finished.cash == (self._money("979.7798"),)
        assert finished.positions == (self._quantity("2"),)
        assert finished.fees == (self._money("0.2002"),)
        assert rollback.orders()[0].order.status == "filled"
        assert PaperBooks.apply(rollback, "shared", second_market, self._scenario()) == final_trace
        reopened = AccountJournal(path, self._config(), paper_owner=rollback_owner, clock=clock)
        assert AccountLedger(reopened.accounts()[0].ledger).snapshot() == finished
        assert PaperBooks.apply(reopened, "shared", second_market, self._scenario()) == final_trace
        assert len(tuple(reopened.iter_paper_traces("shared"))) == 2
        assert reopened.paper_trace("shared", first_market.identity) is not None
        assert reopened.paper_trace("shared", second_market.identity) is not None

    @pytest.mark.parametrize("barrier", ("revoked", "expired"))
    def test_stopped_owner_can_reduce_after_authority_ends(
        self, tmp_path: Path, barrier: Literal["revoked", "expired"]
    ) -> None:
        """End new exposure while allowing an exact owned paper sell and later fill."""
        admin, worker, clock, _, grant, _ = self._bootstrap(tmp_path / f"{barrier}.sqlite3")
        clock.at = self._at(14)
        admitted = worker.admit(
            self._decision("owned-buy", self._at(14), self._quote(self._at(12)), quantity="2")
        )
        assert admitted.status == "committed"
        clock.at = self._at(15)
        buy_trace = PaperBooks.apply(
            worker, "shared", self._market("buy-two", self._at(15)), self._scenario()
        )
        assert len(buy_trace.child_fill_events) == 1
        owned = AccountLedger(worker.accounts()[0].ledger).snapshot()
        assert owned.cash == (self._money("979.7798"),)
        assert owned.positions == (self._quantity("2"),)
        clock.at = self._at(16)
        assert (
            admin.control(
                AccountControl(
                    identity="stop-new-exposure",
                    account_id="shared",
                    kind="stop",
                    at=self._at(16),
                    reason="operator protective stop",
                )
            ).status
            == "applied"
        )
        if barrier == "revoked":
            clock.at = self._at(18)
            admin.revoke_paper("shared", grant.identity, self._at(18))
            now = self._at(19)
            blocked_reason = "paper_authorization_revoked"
        else:
            now = self._at(31)
            blocked_reason = "paper_authorization_expired_or_not_yet_valid"
        clock.at = now
        with pytest.raises(ValueError, match=blocked_reason):
            worker.admit(
                self._decision(f"blocked-{barrier}", self._at(14), self._quote(self._at(12)))
            )
        with pytest.raises(ValueError, match=blocked_reason):
            admin.claim_paper(
                "shared",
                "blocked-replacement",
                self.first_release,
                AccountControl(
                    identity=f"blocked-claim-{barrier}",
                    account_id="shared",
                    kind="restart",
                    at=now,
                    expected_control_identity="stop-new-exposure",
                ),
            )
        assert worker.reconcile(
            AccountObservation(
                identity=f"after-{barrier}",
                at=now,
                snapshot=owned,
                open_orders=(),
            )
        )
        current_quote = self._quote(now)
        worker.observe(current_quote)
        PaperBooks.apply(
            worker, "shared", self._market(f"connected-{barrier}", now), self._scenario()
        )
        request = self._reduction(f"protective-{barrier}", now, current_quote)
        result = worker.reduce_paper(request)
        assert (result.status, result.reason) == ("accepted", "reserved")
        assert AccountLedger(worker.accounts()[0].ledger).snapshot() == owned
        later = now + timedelta(seconds=1)
        clock.at = later
        sold_trace = PaperBooks.apply(
            worker,
            "shared",
            self._market(f"sell-after-{barrier}", later, bid_quantity="1"),
            self._scenario(),
        )
        assert len(sold_trace.child_fill_events) == 1
        sale = sold_trace.child_fill_events[0].fill
        assert sale is not None
        assert (sale.quantity, sale.effective, sale.fee) == (
            self._quantity("-1"),
            self._price("9.94"),
            self._money("0.0994"),
        )
        after = AccountLedger(worker.accounts()[0].ledger).snapshot()
        assert after.cash == (self._money("989.6204"),)
        assert after.positions == (self._quantity("1"),)
        assert after.fees == (self._money("0.2996"),)
        assert worker.reduce_paper(request) == result

    @staticmethod
    def _journal_rows(path: Path) -> tuple[bytes, tuple[tuple[str, int], ...], tuple[str, ...]]:
        """Read the committed head payload, every table's row count and every row."""
        with closing(sqlite3.connect(path)) as connection:
            (head,) = cast(
                tuple[bytes | str],
                connection.execute("SELECT payload FROM firm WHERE id=1").fetchone(),
            )
            tables = cast(
                list[tuple[str]],
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall(),
            )
            counts = tuple(
                (
                    table,
                    cast(
                        tuple[int],
                        connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone(),
                    )[0],
                )
                for (table,) in tables
            )
            rows = tuple(connection.iterdump())
        return head if isinstance(head, bytes) else head.encode(), counts, rows

    @classmethod
    def _context(cls) -> PortfolioContext:
        """Bind a batch decision to the installed model, venue and paper authority."""
        return PortfolioContext(
            portfolio_id="managed-portfolio",
            strategy_id="alpha",
            model_revision="no-model",
            config_revision="config",
            horizon="one-minute",
            reason="bounded-paper-order",
            venue="okx",
            settlement="spot-immediate",
            risk_bucket="spot",
            authority_scope="paper",
        )

    @classmethod
    def _batch(cls, identity: str, decision_at: datetime, quote: AccountQuote) -> PortfolioBatch:
        """Coordinate one checkpointed alpha buy one microsecond after its cutoff."""
        request = replace(
            cls._decision(identity, decision_at, quote),
            checkpoint=f"checkpoint-{identity}".encode(),
        )
        return PortfolioBatch(
            identity=identity,
            at=decision_at + timedelta(microseconds=1),
            decisions=(PortfolioDecision(request=request, context=cls._context()),),
        )

    @classmethod
    def _end_authority(
        cls,
        barrier: Literal["stale_input", "expired", "revoked"],
        admin: AccountJournal,
        grant: PaperAuthorization,
        clock: _PaperClock,
    ) -> str:
        """Age the original inputs or end the grant; return the refusal of new content."""
        if barrier == "stale_input":
            clock.at = cls._at(25)
            return "paper_input_stale_or_future"
        if barrier == "expired":
            clock.at = cls._at(31)
            return "paper_authorization_expired_or_not_yet_valid"
        revoked_at = clock.at + timedelta(seconds=1)
        clock.at = revoked_at
        admin.revoke_paper("shared", grant.identity, revoked_at)
        clock.at = revoked_at + timedelta(seconds=1)
        return "paper_authorization_revoked"

    @pytest.mark.parametrize("barrier", ("stale_input", "expired", "revoked"))
    def test_exact_decision_retry_returns_saved_result_after_authority_ends(
        self, tmp_path: Path, barrier: Literal["stale_input", "expired", "revoked"]
    ) -> None:
        """Ageing, expiry and revocation fence new content, never the saved outcome."""
        path = tmp_path / f"admit-{barrier}.sqlite3"
        admin, worker, clock, _, grant, _ = self._bootstrap(path)
        quote = self._quote(self._at(12))
        request = self._decision("retried-buy", self._at(14), quote)
        clock.at = self._at(14)
        admitted = worker.admit(request)
        assert (admitted.status, admitted.reason, len(admitted.orders)) == (
            "committed",
            "reserved",
            1,
        )
        new_content_refusal = self._end_authority(barrier, admin, grant, clock)
        journal = self._journal_rows(path)

        assert worker.admit(request) == admitted
        assert self._journal_rows(path) == journal
        with pytest.raises(ValueError, match="decision identity reused with different content"):
            worker.admit(replace(request, checkpoint=b"changed-continuation"))
        with pytest.raises(ValueError, match=new_content_refusal):
            worker.admit(self._decision("new-buy", self._at(14), quote))
        assert self._journal_rows(path) == journal
        assert worker.admit(request) == admitted
        assert [item.order for item in worker.orders()] == list(admitted.orders)

    @pytest.mark.parametrize("barrier", ("stale_input", "expired", "revoked"))
    def test_exact_batch_retry_returns_saved_result_after_authority_ends(
        self, tmp_path: Path, barrier: Literal["stale_input", "expired", "revoked"]
    ) -> None:
        """Ageing, expiry and revocation fence a new batch, never the saved batch."""
        path = tmp_path / f"coordinate-{barrier}.sqlite3"
        admin, worker, clock, _, grant, _ = self._bootstrap(path, maximum_orders=2)
        quote = self._quote(self._at(12))
        batch = self._batch("retried-batch", self._at(14), quote)
        clock.at = batch.at
        committed = worker.coordinate(batch)
        assert (committed.status, committed.reason) == ("committed", "reserved")
        assert (len(committed.children), len(committed.net_orders)) == (1, 1)
        # A later order uses the grant's last order, so new content is refused on limits.
        clock.at = self._at(15)
        later = worker.admit(self._decision("later-buy", self._at(15), quote))
        assert later.status == "committed"
        clock.at = self._at(16)
        with pytest.raises(ValueError, match="paper_authorization_order_limit"):
            worker.coordinate(self._batch("over-limit-batch", self._at(16), quote))
        assert worker.portfolio_batch("over-limit-batch") is None
        new_content_refusal = self._end_authority(barrier, admin, grant, clock)
        journal = self._journal_rows(path)

        assert worker.coordinate(batch) == committed
        assert self._journal_rows(path) == journal
        changed_request = replace(batch.decisions[0].request, checkpoint=b"changed-continuation")
        changed = replace(batch, decisions=(replace(batch.decisions[0], request=changed_request),))
        with pytest.raises(
            ValueError, match="portfolio batch identity reused with different content"
        ):
            worker.coordinate(changed)
        with pytest.raises(ValueError, match=new_content_refusal):
            worker.coordinate(self._batch("new-batch", self._at(14), quote))
        assert worker.portfolio_batch("new-batch") is None
        assert self._journal_rows(path) == journal
        assert worker.coordinate(batch) == committed
        assert worker.portfolio_batch(batch.identity) == batch

    def test_exact_retries_return_saved_results_after_replacement_grant_lowers_limit(
        self, tmp_path: Path
    ) -> None:
        """A lower replacement cap refuses new content but not the saved outcomes."""
        path = tmp_path / "lower-cap.sqlite3"
        admin, worker, clock, deployment, _, _ = self._bootstrap(path, maximum_orders=2)
        quote = self._quote(self._at(12))
        batch = self._batch("capped-batch", self._at(14), quote)
        clock.at = batch.at
        committed = worker.coordinate(batch)
        assert committed.status == "committed"
        clock.at = self._at(15)
        later_request = self._decision("later-buy", self._at(15), quote)
        later = worker.admit(later_request)
        assert later.status == "committed"
        # The later decision replaced the batch's order: the first book confirms that
        # cancellation and the next one fills the later order.
        PaperBooks.apply(worker, "shared", self._market("cancel", self._at(15)), self._scenario())
        clock.at = self._at(16)
        PaperBooks.apply(worker, "shared", self._market("fill", self._at(16)), self._scenario())
        assert sorted(item.order.status for item in worker.orders()) == ["cancelled", "filled"]
        settled = AccountLedger(worker.accounts()[0].ledger).snapshot()
        assert settled.positions == (self._quantity("1"),)
        assert (
            admin.control(
                AccountControl(
                    identity="stop-for-lower-cap",
                    account_id="shared",
                    kind="stop",
                    at=self._at(16),
                    reason="operator grant replacement",
                )
            ).status
            == "applied"
        )
        clock.at = self._at(17)
        admin.authorize_paper(
            self._authorization(deployment, identity="lower-cap-session", maximum_orders=1)
        )
        assert admin.reconcile(
            AccountObservation(
                identity="settled-for-lower-cap", at=self._at(17), snapshot=settled, open_orders=()
            )
        )
        current_quote = self._quote(self._at(17))
        admin.observe(current_quote)
        clock.at = self._at(18)
        successor_owner = admin.claim_paper(
            "shared",
            "worker-lower-cap",
            self.first_release,
            AccountControl(
                identity="claim-lower-cap",
                account_id="shared",
                kind="restart",
                at=self._at(18),
                expected_control_identity="stop-for-lower-cap",
            ),
        )
        successor = AccountJournal(path, self._config(), paper_owner=successor_owner, clock=clock)
        journal = self._journal_rows(path)

        assert successor.coordinate(batch) == committed
        assert successor.admit(later_request) == later
        assert self._journal_rows(path) == journal
        with pytest.raises(ValueError, match="paper_authorization_order_limit"):
            successor.coordinate(self._batch("over-lower-cap", self._at(18), current_quote))
        assert successor.portfolio_batch("over-lower-cap") is None
        assert self._journal_rows(path) == journal

    def test_exact_retries_still_require_current_owner_clock_and_retained_journal(
        self, tmp_path: Path
    ) -> None:
        """A replaced owner, a regressed clock or a quarantined restore refuses retries."""
        path = tmp_path / "fenced-retries.sqlite3"
        admin, worker, clock, _, _, _ = self._bootstrap(path)
        quote = self._quote(self._at(12))
        request = self._decision("fenced-buy", self._at(14), quote)
        clock.at = self._at(14)
        admitted = worker.admit(request)
        assert admitted.status == "committed"
        batch = self._batch("fenced-batch", self._at(14), quote)
        clock.at = batch.at
        committed = worker.coordinate(batch)
        assert committed.status == "committed"
        clock.at = self._at(15)
        PaperBooks.apply(
            worker, "shared", self._market("fill-both", self._at(15)), self._scenario()
        )
        # The batch replaced the direct order; one book cancels it and fills the batch.
        assert [item.order.status for item in worker.orders()] == ["cancelled", "filled"]
        filled = AccountLedger(worker.accounts()[0].ledger).snapshot()
        assert filled.positions == (self._quantity("1"),)
        clock.at = self._at(16)
        assert (
            admin.control(
                AccountControl(
                    identity="stop-for-claim",
                    account_id="shared",
                    kind="stop",
                    at=self._at(16),
                    reason="operator replacement drill",
                )
            ).status
            == "applied"
        )
        clock.at = self._at(17)
        assert worker.reconcile(
            AccountObservation(
                identity="before-replacement", at=self._at(17), snapshot=filled, open_orders=()
            )
        )
        worker.observe(self._quote(self._at(17)))
        clock.at = self._at(18)
        successor_owner = admin.claim_paper(
            "shared",
            "worker-successor",
            self.first_release,
            AccountControl(
                identity="claim-successor",
                account_id="shared",
                kind="restart",
                at=self._at(18),
                expected_control_identity="stop-for-claim",
            ),
        )
        successor = AccountJournal(path, self._config(), paper_owner=successor_owner, clock=clock)
        journal = self._journal_rows(path)

        with pytest.raises(ValueError, match="paper_owner_stale_or_absent"):
            worker.admit(request)
        with pytest.raises(ValueError, match="paper_owner_stale_or_absent"):
            worker.coordinate(batch)
        assert successor.admit(request) == admitted
        assert successor.coordinate(batch) == committed
        clock.at = self._at(17)
        with pytest.raises(ValueError, match="paper_owner_clock_regressed"):
            successor.admit(request)
        with pytest.raises(ValueError, match="paper_owner_clock_regressed"):
            successor.coordinate(batch)
        assert self._journal_rows(path) == journal
        clock.at = self._at(19)
        admin.quarantine_paper_restore()
        quarantined = self._journal_rows(path)
        with pytest.raises(ValueError, match="paper_restore_requires_current_retained_journal"):
            successor.admit(request)
        with pytest.raises(ValueError, match="paper_restore_requires_current_retained_journal"):
            successor.coordinate(batch)
        assert self._journal_rows(path) == quarantined

    def test_unmanaged_retries_return_saved_results_without_wall_clock_checks(
        self, tmp_path: Path
    ) -> None:
        """Without an installed deployment, retries keep their exact-content contract."""
        path = tmp_path / "unmanaged.sqlite3"
        clock = _PaperClock(self._at(14))
        journal = AccountJournal(path, self._config(), clock=clock)
        assert journal.reconcile(
            AccountObservation(
                identity="opening", at=self._at(1), snapshot=self._opening(), open_orders=()
            )
        )
        quote = self._quote(self._at(12))
        journal.observe(quote)
        request = self._decision("unmanaged-buy", self._at(14), quote)
        admitted = journal.admit(request)
        assert admitted.status == "committed"
        batch = self._batch("unmanaged-batch", self._at(14), quote)
        clock.at = batch.at
        committed = journal.coordinate(batch)
        assert committed.status == "committed"
        clock.at = self._at(31)
        rows = self._journal_rows(path)
        assert journal.admit(request) == admitted
        assert journal.coordinate(batch) == committed
        assert self._journal_rows(path) == rows
        with pytest.raises(ValueError, match="decision identity reused with different content"):
            journal.admit(replace(request, checkpoint=b"changed-continuation"))
        changed_request = replace(batch.decisions[0].request, checkpoint=b"changed-continuation")
        with pytest.raises(
            ValueError, match="portfolio batch identity reused with different content"
        ):
            journal.coordinate(
                replace(batch, decisions=(replace(batch.decisions[0], request=changed_request),))
            )
