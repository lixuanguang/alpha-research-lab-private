"""Exercise installed shared portfolio admission with exact authored paper facts."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountSnapshot, Fill
from applications.execute.accounts import (
    AccountExecutionApplication,
    AccountExecutionRequest,
    AccountExecutionResult,
)
from configuration import AccountConfiguration, OpeningAccount
from execution import (
    AccountDecision,
    AccountObservation,
    AccountQuote,
    NetFeeCorrection,
    OrderDecision,
    OrderEvent,
    PortfolioBatch,
    PortfolioCommit,
    PortfolioContext,
    PortfolioDecision,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent, TargetIntent


class ReferenceTargetPolicy:
    """Produce a configured absolute inventory target for one strategy instance."""

    def __init__(self, target: Quantity) -> None:
        """Bind an exact target without holding journal or account authority."""
        target.model_copy()
        self.target = target

    def decide(self) -> TargetIntent:
        """Return the portable target consumed by independent risk admission."""
        return TargetIntent(quantity=self.target)


class ReferenceLimitPolicy:
    """Produce a configured spot order intent for a different active strategy."""

    def __init__(self, side: Literal["buy", "sell"], quantity: Quantity, limit: Price) -> None:
        """Bind explicit side, base quantity and quote-currency limit."""
        quantity.model_copy()
        limit.model_copy()
        self.side, self.quantity, self.limit = side, quantity, limit

    def decide(self) -> OrderIntent:
        """Return a portable IOC order with no submission privilege."""
        return OrderIntent(
            side=self.side,
            quantity=self.quantity,
            limit=self.limit,
            time_in_force="ioc",
        )


class PortfolioAccountConsumer:
    """Run one complete venue-labelled local paper account through installed APIs."""

    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)

    def __init__(self, output: Path, venue: Literal["okx", "bitfinex"]) -> None:
        """Select authored identity and currency parameters for the same public path."""
        self.output = output
        self.venue = "OKX" if venue == "okx" else "Bitfinex"
        currency_code = "USDT" if venue == "okx" else "USD"
        instrument_text = (
            "11111111-1111-4111-8111-111111111111"
            if venue == "okx"
            else "22222222-2222-4222-8222-222222222222"
        )
        self.currency = Currency.from_code(currency_code)
        self.dimension = Dimension(
            instrument_id=InstrumentId.from_canonical_text(instrument_text),
            kind=QuantityKind.BASE_UNIT,
        )
        self.codec = DomainCodec()
        self.application = AccountExecutionApplication()
        self.config_path = output / "configuration.json"
        self.journal_path = output / "portfolio.sqlite3"

    def _money(self, amount: str) -> Money:
        """Construct exact local quote-currency money."""
        return Money(value=Decimal(amount), currency=self.currency)

    def _quantity(self, amount: str) -> Quantity:
        """Construct exact spot base inventory."""
        return Quantity(value=Decimal(amount), dimension=self.dimension)

    def _price(self, amount: str = "100") -> Price:
        """Construct an exact cash-spot valuation or limit."""
        return Price(value=Decimal(amount), currency=self.currency, per=self.dimension)

    def _config(self) -> AccountConfiguration:
        """Fund a paper account with two distinct authorized strategy instances."""
        return AccountConfiguration(
            mode="paper",
            opening_at=self.opening_at,
            accounts=(OpeningAccount(account_id="shared", cash=(self._money("50000"),)),),
            instruments=(
                SpotLimits(
                    maximum=self._quantity("200"),
                    lot=self._quantity("1"),
                    tick=self._price("0.01"),
                    product="spot",
                ),
            ),
            budgets=BudgetPolicy(
                valuation_currency=self.currency,
                firm_maximum=self._money("10000"),
                accounts=(AccountLimit(account_id="shared", maximum=self._money("10000")),),
                instances=(
                    InstanceLimit(
                        instance_id="alpha",
                        account_id="shared",
                        maximum=self._money("9000"),
                        instruments=(self.dimension.instrument_id,),
                    ),
                    InstanceLimit(
                        instance_id="beta",
                        account_id="shared",
                        maximum=self._money("9000"),
                        instruments=(self.dimension.instrument_id,),
                    ),
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=100,
                max_order_notional=self._money("9000"),
            ),
        )

    def _snapshot(
        self,
        *,
        instance_id: str | None,
        cash: str,
        position: str | None,
        fees: str,
        transfers: str,
        fill_ids: tuple[str, ...],
        posting_ids: tuple[str, ...],
    ) -> AccountSnapshot:
        """State independently authored exact account or strategy expectations."""
        return AccountSnapshot(
            account_id="shared",
            instance_id=instance_id,
            cash=(self._money(cash),),
            positions=() if position is None else (self._quantity(position),),
            fees=(self._money(fees),),
            rebates=(self._money("0"),),
            transfers=(self._money(transfers),),
            fill_ids=fill_ids,
            posting_ids=posting_ids,
        )

    def _opening(self) -> AccountSnapshot:
        """Specify the cash-funded account before any strategy activity."""
        return self._snapshot(
            instance_id=None,
            cash="50000",
            position=None,
            fees="0",
            transfers="50000",
            fill_ids=(),
            posting_ids=(f"opening:{self.currency.code}",),
        )

    def _decision(
        self,
        *,
        instance_id: Literal["alpha", "beta"],
        identity: str,
        at: datetime,
        intent: TargetIntent | OrderIntent,
        bucket: str = "spot",
    ) -> PortfolioDecision:
        """Bind one policy intent to complete strategy and account ownership."""
        strategy_id = "inventory-target" if instance_id == "alpha" else "limit-order"
        return PortfolioDecision(
            request=AccountDecision(
                account_id="shared",
                instance_id=instance_id,
                decision=OrderDecision(identity=identity, at=at, intent=intent),
                quote=AccountQuote(price=self._price(), at=at),
                maximum_fee=self._money("1"),
                checkpoint=f"{strategy_id}:{identity}".encode(),
            ),
            context=PortfolioContext(
                portfolio_id="reference-portfolio",
                strategy_id=strategy_id,
                model_revision="reference-v1",
                config_revision="paper-v1",
                horizon="one-minute",
                reason="authored-fixture",
                venue=self.venue,
                settlement="spot-immediate",
                risk_bucket=bucket,
                authority_scope="paper",
            ),
        )

    def _batch(
        self,
        identity: str,
        at: datetime,
        decisions: tuple[PortfolioDecision, ...],
        crossing: Literal["reject", "internal_at_quote"],
    ) -> PortfolioBatch:
        """Give independently timed strategy decisions one atomic boundary."""
        return PortfolioBatch(
            identity=identity,
            at=at + timedelta(microseconds=1),
            decisions=decisions,
            crossing=crossing,
        )

    def _apply(self, label: str, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Retain typed installed request and result bytes after each durable operation."""
        request_path = self.output / "requests" / f"{label}.json"
        result_path = self.output / "results" / f"{label}.json"
        request_path.write_bytes(self.codec.encode_json(request))
        result = self.application.run(
            config_path=self.config_path,
            journal_path=self.journal_path,
            request_path=request_path,
        )
        assert not result.submission_attempted
        result_path.write_bytes(self.codec.encode_json(result))
        return result

    def _quote(self, label: str, at: datetime) -> None:
        """Persist an independent market valuation before either policy decides."""
        self._apply(
            label,
            AccountExecutionRequest(action="quote", quote=AccountQuote(price=self._price(), at=at)),
        )

    def _observe(
        self,
        label: str,
        at: datetime,
        snapshot: AccountSnapshot,
    ) -> bool:
        """Reconcile the physical account against an authored external-style record."""
        result = self._apply(
            label,
            AccountExecutionRequest(
                action="reconcile",
                observation=AccountObservation(
                    identity=label,
                    at=at,
                    snapshot=snapshot,
                    open_orders=(),
                ),
            ),
        )
        assert result.reconciled is not None
        return result.reconciled

    def _coordinate(self, label: str, batch: PortfolioBatch) -> AccountExecutionResult:
        """Submit a typed cohort and require a visible portfolio outcome."""
        result = self._apply(label, AccountExecutionRequest(action="coordinate", batch=batch))
        assert result.portfolio is not None
        return result

    def _physical_fill(
        self,
        *,
        identity: str,
        order_id: str,
        decision_at: datetime,
        at: datetime,
        quantity: str,
        fee: str,
    ) -> OrderEvent:
        """Supply one explicitly modeled physical paper fill and cost."""
        return OrderEvent(
            identity=f"receipt:{identity}",
            order_id=order_id,
            at=at,
            kind="fill",
            fill=Fill(
                identity=identity,
                decision_at=decision_at,
                filled_at=at,
                quantity=self._quantity(quantity),
                reference=self._price(),
                effective=self._price(),
                fee=self._money(fee),
            ),
        )

    def _net_event(self, label: str, event: OrderEvent) -> AccountExecutionResult:
        """Post one modeled physical event through the installed application."""
        return self._apply(label, AccountExecutionRequest(action="net_event", net_event=event))

    def _conflicting_receipt(self, original: OrderEvent, at: datetime) -> str:
        """Retain a contradictory receipt and verify durable independent admission protection."""
        before = self._apply("before-conflict", AccountExecutionRequest(action="inspect"))
        assert original.fill is not None
        conflicting = replace(
            original,
            at=at,
            fill=replace(original.fill, quantity=self._quantity("3")),
        )
        try:
            self._net_event("changed-event-retry", conflicting)
        except ValueError as error:
            assert "different content" in str(error)
        else:
            raise AssertionError("changed physical event identity was accepted")

        self.application = AccountExecutionApplication()
        blocked = self._apply("reopened-conflict", AccountExecutionRequest(action="inspect"))
        assert blocked.accounts[0].fault is not None
        assert blocked.accounts[0].ledger == before.accounts[0].ledger
        assert blocked.orders == before.orders and blocked.net_orders == before.net_orders
        assert blocked.failed_net_events == (conflicting,)
        self._cli_matches("reopened-conflict", blocked)
        assert self._net_event("original-after-conflict", original).accounts == blocked.accounts

        decision_at = at + timedelta(microseconds=1)
        self._quote("blocked-quote", decision_at)
        rejected = self._require_commit(
            self._coordinate(
                "blocked-admission",
                self._batch(
                    "blocked-admission",
                    decision_at,
                    (
                        self._decision(
                            instance_id="beta",
                            identity="blocked-beta-order",
                            at=decision_at,
                            intent=ReferenceLimitPolicy(
                                "buy", self._quantity("1"), self._price()
                            ).decide(),
                        ),
                    ),
                    "internal_at_quote",
                ),
            )
        )
        assert rejected.status == "rejected" and rejected.reason == blocked.accounts[0].fault
        assert not self._observe(
            "conflict-cannot-reconcile",
            decision_at + timedelta(microseconds=1),
            AccountLedger(before.accounts[0].ledger).snapshot(),
        )
        return rejected.reason

    def _allocated_fill_id(self, physical_id: str, child_id: str) -> str:
        """Derive the documented child lineage for an independent observation."""
        return hashlib.sha256(
            self.codec.encode_json(("allocated-physical-fill-v1", physical_id, child_id))
        ).hexdigest()

    def _cli_matches(self, label: str, expected: AccountExecutionResult) -> None:
        """Compare fresh installed command output with the typed application retry."""
        command = [
            str(Path(sys.executable).with_name("alpha-execute")),
            "account",
            "--config",
            str(self.config_path),
            "--journal",
            str(self.journal_path),
            "--request",
            str(self.output / "requests" / f"{label}.json"),
        ]
        completed = subprocess.run(command, check=True, capture_output=True, timeout=20)
        (self.output / "results" / f"cli-{label}.json").write_bytes(completed.stdout)
        actual = msgspec.json.decode(completed.stdout, type=dict[str, object])
        typed = msgspec.json.decode(self.codec.encode_json(expected), type=dict[str, object])
        assert actual == typed

    def _balances(
        self,
        result: AccountExecutionResult,
        *,
        physical_cash: str,
        physical_position: str | None,
        physical_fee: str,
        alpha_cash: str,
        alpha_position: str | None,
        alpha_fee: str,
        beta_cash: str,
        beta_position: str | None,
        beta_fee: str,
    ) -> None:
        """Compare all three exact balances to independently hand calculated values."""
        assert len(result.accounts) == 1
        ledger = AccountLedger(result.accounts[0].ledger)
        physical = ledger.snapshot()
        alpha = ledger.snapshot(instance_id="alpha")
        beta = ledger.snapshot(instance_id="beta")
        assert physical.cash == (self._money(physical_cash),)
        assert physical.positions == (
            () if physical_position is None else (self._quantity(physical_position),)
        )
        assert physical.fees == (self._money(physical_fee),)
        assert alpha.cash == (self._money(alpha_cash),)
        assert alpha.positions == (
            () if alpha_position is None else (self._quantity(alpha_position),)
        )
        assert alpha.fees == (self._money(alpha_fee),)
        assert beta.cash == (self._money(beta_cash),)
        assert beta.positions == (() if beta_position is None else (self._quantity(beta_position),))
        assert beta.fees == (self._money(beta_fee),)
        assert physical.transfers == (self._money("50000"),)
        assert alpha.transfers == beta.transfers == (self._money("0"),)
        assert physical.rebates == alpha.rebates == beta.rebates == (self._money("0"),)
        assert physical.cash[0] == self._money("50000") + alpha.cash[0] + beta.cash[0]
        assert physical.fees[0] == alpha.fees[0] + beta.fees[0]

    def _require_commit(self, result: AccountExecutionResult) -> PortfolioCommit:
        """Select the typed portfolio result after the application validates it."""
        if result.portfolio is None:
            raise ValueError("portfolio application omitted its outcome")
        return result.portfolio

    def run(self) -> dict[str, object]:
        """Qualify netting, residual ownership, crossing, controls and wire retries."""
        self.output.mkdir(parents=True, exist_ok=False)
        (self.output / "requests").mkdir()
        (self.output / "results").mkdir()
        self.config_path.write_bytes(self.codec.encode_json(self._config()))
        initial = self.application.run(config_path=self.config_path, journal_path=self.journal_path)
        (self.output / "results" / "initial.json").write_bytes(self.codec.encode_json(initial))
        assert self._observe("opening", self.opening_at, self._opening())

        budget_at = self.opening_at + timedelta(seconds=1)
        self._quote("budget-quote", budget_at)
        oversized = self._batch(
            "oversubscribed-cohort",
            budget_at,
            (
                self._decision(
                    instance_id="alpha",
                    identity="oversized-target",
                    at=budget_at,
                    intent=ReferenceTargetPolicy(self._quantity("80")).decide(),
                ),
                self._decision(
                    instance_id="beta",
                    identity="oversized-order",
                    at=budget_at,
                    intent=ReferenceLimitPolicy(
                        "buy", self._quantity("80"), self._price()
                    ).decide(),
                ),
            ),
            "internal_at_quote",
        )
        oversized_result = self._coordinate("oversubscribed", oversized)
        assert (
            self._require_commit(oversized_result).status,
            self._require_commit(oversized_result).reason,
        ) == ("rejected", "account_limit")
        assert oversized_result.orders == () and oversized_result.net_orders == ()

        decision_at = self.opening_at + timedelta(seconds=2)
        self._quote("shared-quote", decision_at)
        batch = self._batch(
            "shared-target-and-order",
            decision_at,
            (
                self._decision(
                    instance_id="alpha",
                    identity="alpha-target-two",
                    at=decision_at,
                    intent=ReferenceTargetPolicy(self._quantity("2")).decide(),
                ),
                self._decision(
                    instance_id="beta",
                    identity="beta-order-two",
                    at=decision_at,
                    intent=ReferenceLimitPolicy("buy", self._quantity("2"), self._price()).decide(),
                ),
            ),
            "internal_at_quote",
        )
        admitted = self._coordinate("shared-admission", batch)
        commit = self._require_commit(admitted)
        assert commit.status == "committed" and len(commit.children) == 2
        assert len(commit.net_orders) == 1 and len(admitted.net_orders) == 1
        parent = commit.net_orders[0]
        assert parent.order.intent.quantity == self._quantity("4")
        assert tuple(item.quantity for item in parent.allocations) == (
            self._quantity("2"),
            self._quantity("2"),
        )
        assert {
            child.instance_id: child.context.strategy_id
            for child in commit.children
            if child.context
        } == {"alpha": "inventory-target", "beta": "limit-order"}
        self._cli_matches("shared-admission", admitted)
        assert self._coordinate("shared-admission-retry", batch).portfolio == commit
        try:
            self._coordinate(
                "changed-batch-retry", replace(batch, at=batch.at + timedelta(microseconds=1))
            )
        except ValueError as error:
            assert "different content" in str(error)
        else:
            raise AssertionError("changed portfolio batch identity was accepted")

        partial_at = decision_at + timedelta(seconds=1)
        partial_event = self._physical_fill(
            identity="physical-partial",
            order_id=parent.order.identity,
            decision_at=parent.order.decision_at,
            at=partial_at,
            quantity="2",
            fee="0.02",
        )
        partial = self._net_event("physical-partial", partial_event)
        assert partial.net_orders[0].order.remaining == self._quantity("2")
        assert tuple(item.filled for item in partial.net_orders[0].allocations) == (
            self._quantity("1"),
            self._quantity("1"),
        )
        self._balances(
            partial,
            physical_cash="49799.98",
            physical_position="2",
            physical_fee="0.02",
            alpha_cash="-100.01",
            alpha_position="1",
            alpha_fee="0.01",
            beta_cash="-100.01",
            beta_position="1",
            beta_fee="0.01",
        )
        assert self._net_event("physical-partial-retry", partial_event).accounts == partial.accounts

        stop_at = partial_at + timedelta(seconds=1)
        stopped = self._apply(
            "stop-alpha",
            AccountExecutionRequest(action="stop_instance", instance_id="alpha", at=stop_at),
        )
        assert stopped.net_orders[0].order.status == "cancel_requested"
        assert stopped.net_orders[0].order.remaining == self._quantity("2")
        assert stopped.stopped_instances == ("alpha",)
        assert (
            self._apply(
                "stop-alpha-retry",
                AccountExecutionRequest(action="stop_instance", instance_id="alpha", at=stop_at),
            ).net_orders
            == stopped.net_orders
        )
        stopped_decision_at = stop_at + timedelta(microseconds=1)
        self._quote("stopped-quote", stopped_decision_at)
        stopped_batch = self._batch(
            "stopped-strategy-attempt",
            stopped_decision_at,
            (
                self._decision(
                    instance_id="alpha",
                    identity="stopped-target-attempt",
                    at=stopped_decision_at,
                    intent=ReferenceTargetPolicy(self._quantity("0")).decide(),
                ),
            ),
            "internal_at_quote",
        )
        stopped_rejection = self._require_commit(
            self._coordinate("stopped-strategy-attempt", stopped_batch)
        )
        assert (stopped_rejection.status, stopped_rejection.reason) == (
            "rejected",
            "instance_stopped",
        )
        cancel_ack_at = stop_at + timedelta(seconds=1)
        acknowledged = self._net_event(
            "cancel-acknowledged",
            OrderEvent(
                identity="physical-cancel-ack",
                order_id=parent.order.identity,
                at=cancel_ack_at,
                kind="cancel_ack",
            ),
        )
        assert acknowledged.net_orders[0].order.remaining == self._quantity("2")
        assert acknowledged.net_orders[0].order.status == "cancel_ack"
        try:
            self._apply(
                "restart-before-confirmation",
                AccountExecutionRequest(
                    action="restart_instance", instance_id="alpha", at=cancel_ack_at
                ),
            )
        except ValueError as error:
            assert "instance_restart_requires_reconciliation" in str(error)
        else:
            raise AssertionError("unconfirmed cancellation allowed strategy restart")

        cancel_at = cancel_ack_at + timedelta(seconds=1)
        cancelled = self._net_event(
            "cancel-confirmed",
            OrderEvent(
                identity="physical-cancelled",
                order_id=parent.order.identity,
                at=cancel_at,
                kind="cancelled",
            ),
        )
        assert cancelled.net_orders[0].order.status == "cancelled"
        assert {child.instance_id: child.order.status for child in cancelled.orders} == {
            "alpha": "cancelled",
            "beta": "partial",
        }
        assert next(
            child.order.remaining for child in cancelled.orders if child.instance_id == "beta"
        ) == self._quantity("1")
        alpha_id, beta_id = (child.order.identity for child in commit.children)
        alpha_fill_id = self._allocated_fill_id("physical-partial", alpha_id)
        beta_fill_id = self._allocated_fill_id("physical-partial", beta_id)
        partial_expected = self._snapshot(
            instance_id=None,
            cash="49799.98",
            position="2",
            fees="0.02",
            transfers="50000",
            fill_ids=(alpha_fill_id, beta_fill_id),
            posting_ids=(
                f"opening:{self.currency.code}",
                alpha_fill_id,
                f"fee:{alpha_fill_id}",
                beta_fill_id,
                f"fee:{beta_fill_id}",
            ),
        )
        assert AccountLedger(cancelled.accounts[0].ledger).snapshot() == partial_expected
        assert self._observe("physical-after-cancel", cancel_at, partial_expected)

        reissue_at = cancel_at + timedelta(microseconds=1)
        self._quote("reissue-quote", reissue_at)
        reissued = self._apply(
            "reissue-beta",
            AccountExecutionRequest(action="reissue_pending", account_id="shared", at=reissue_at),
        )
        assert len(reissued.net_orders) == 2
        beta_parent = reissued.net_orders[1]
        assert beta_parent.order.intent.quantity == self._quantity("1")
        assert beta_parent.allocations[0].child_order_id == beta_id
        try:
            self._apply(
                "reissue-without-new-observation",
                AccountExecutionRequest(
                    action="reissue_pending", account_id="shared", at=reissue_at
                ),
            )
        except ValueError as error:
            assert "reissue_requires_current_reconciliation" in str(error)
        else:
            raise AssertionError("physical reissue bypassed account reconciliation")
        assert (
            self._apply("after-reissue-guard", AccountExecutionRequest(action="inspect")).net_orders
            == reissued.net_orders
        )
        beta_fill_at = cancel_at + timedelta(seconds=1)
        settled = self._net_event(
            "beta-residual-fill",
            self._physical_fill(
                identity="beta-residual-physical",
                order_id=beta_parent.order.identity,
                decision_at=beta_parent.order.decision_at,
                at=beta_fill_at,
                quantity="1",
                fee="0.01",
            ),
        )
        self._balances(
            settled,
            physical_cash="49699.97",
            physical_position="3",
            physical_fee="0.03",
            alpha_cash="-100.01",
            alpha_position="1",
            alpha_fee="0.01",
            beta_cash="-200.02",
            beta_position="2",
            beta_fee="0.02",
        )
        beta_residual_fill_id = self._allocated_fill_id("beta-residual-physical", beta_id)
        settled_expected = self._snapshot(
            instance_id=None,
            cash="49699.97",
            position="3",
            fees="0.03",
            transfers="50000",
            fill_ids=(alpha_fill_id, beta_fill_id, beta_residual_fill_id),
            posting_ids=(
                f"opening:{self.currency.code}",
                alpha_fill_id,
                f"fee:{alpha_fill_id}",
                beta_fill_id,
                f"fee:{beta_fill_id}",
                beta_residual_fill_id,
                f"fee:{beta_residual_fill_id}",
            ),
        )
        assert AccountLedger(settled.accounts[0].ledger).snapshot() == settled_expected
        assert self._observe("physical-after-residual", beta_fill_at, settled_expected)
        restart_at = beta_fill_at + timedelta(seconds=1)
        self.application = AccountExecutionApplication()
        restarted = self._apply(
            "restart-alpha",
            AccountExecutionRequest(action="restart_instance", instance_id="alpha", at=restart_at),
        )
        assert restarted.accounts[0].fault is None
        assert restarted.stopped_instances == ()

        cross_at = restart_at + timedelta(seconds=1)
        self._quote("cross-quote", cross_at)
        cross_batch = self._batch(
            "owned-inventory-transfer",
            cross_at,
            (
                self._decision(
                    instance_id="alpha",
                    identity="alpha-target-flat",
                    at=cross_at,
                    intent=ReferenceTargetPolicy(self._quantity("0")).decide(),
                ),
                self._decision(
                    instance_id="beta",
                    identity="beta-buy-one",
                    at=cross_at,
                    intent=ReferenceLimitPolicy("buy", self._quantity("1"), self._price()).decide(),
                ),
            ),
            "internal_at_quote",
        )
        crossed = self._coordinate("internal-cross", cross_batch)
        cross_commit = self._require_commit(crossed)
        assert cross_commit.status == "committed" and cross_commit.reason == "internal_cross"
        assert cross_commit.net_orders == () and len(cross_commit.internal_fill_ids) == 2
        assert len(crossed.net_orders) == 2
        self._balances(
            crossed,
            physical_cash="49699.97",
            physical_position="3",
            physical_fee="0.03",
            alpha_cash="-0.01",
            alpha_position=None,
            alpha_fee="0.01",
            beta_cash="-300.02",
            beta_position="3",
            beta_fee="0.02",
        )
        assert self._coordinate("internal-cross-retry", cross_batch).portfolio == cross_commit
        assert self._observe(
            "physical-after-cross",
            cross_batch.at,
            AccountLedger(crossed.accounts[0].ledger).snapshot(),
        )

        conflict_at = cross_at + timedelta(seconds=1)
        self._quote("incompatible-quote", conflict_at)
        incompatible = self._batch(
            "incompatible-authority",
            conflict_at,
            (
                self._decision(
                    instance_id="beta",
                    identity="beta-sell-one",
                    at=conflict_at,
                    intent=ReferenceLimitPolicy(
                        "sell", self._quantity("1"), self._price()
                    ).decide(),
                ),
                self._decision(
                    instance_id="alpha",
                    identity="alpha-buy-one",
                    at=conflict_at,
                    intent=ReferenceTargetPolicy(self._quantity("1")).decide(),
                    bucket="other-risk-bucket",
                ),
            ),
            "internal_at_quote",
        )
        rejected = self._coordinate("incompatible-cross", incompatible)
        assert (self._require_commit(rejected).status, self._require_commit(rejected).reason) == (
            "rejected",
            "incompatible_crossing_scope",
        )
        assert rejected.accounts[0].ledger == crossed.accounts[0].ledger
        assert len(rejected.orders) == len(crossed.orders)

        try:
            PortfolioBatch(
                identity="invalid-clock",
                at=conflict_at,
                decisions=(
                    self._decision(
                        instance_id="beta",
                        identity="late-decision",
                        at=conflict_at,
                        intent=ReferenceLimitPolicy(
                            "buy", self._quantity("1"), self._price()
                        ).decide(),
                    ),
                ),
            )
        except ValueError as error:
            assert "follow each decision" in str(error)
        else:
            raise AssertionError("coordination at its decision time was accepted")
        malformed_path = self.output / "requests" / "malformed-coordinate.json"
        malformed_path.write_text('{"action":"coordinate"}', encoding="utf-8")
        malformed = subprocess.run(
            [
                str(Path(sys.executable).with_name("alpha-execute")),
                "account",
                "--config",
                str(self.config_path),
                "--journal",
                str(self.journal_path),
                "--request",
                str(malformed_path),
            ],
            capture_output=True,
            check=False,
            timeout=20,
        )
        assert malformed.returncode != 0
        after_malformed = self._apply("after-malformed", AccountExecutionRequest(action="inspect"))
        assert after_malformed.accounts == rejected.accounts
        assert after_malformed.orders == rejected.orders
        assert after_malformed.net_orders == rejected.net_orders

        correction = NetFeeCorrection(
            identity="physical-partial-fee-revision",
            physical_fill_id="physical-partial",
            corrected_fee=self._money("0.04"),
            known_at=conflict_at + timedelta(seconds=1),
        )
        corrected = self._apply(
            "physical-fee-correction",
            AccountExecutionRequest(action="net_cost", net_cost=correction),
        )
        assert corrected.accounts[0].fault == "posting_reconciliation"
        self._balances(
            corrected,
            physical_cash="49699.95",
            physical_position="3",
            physical_fee="0.05",
            alpha_cash="-0.02",
            alpha_position=None,
            alpha_fee="0.02",
            beta_cash="-300.03",
            beta_position="3",
            beta_fee="0.03",
        )
        assert tuple(parent.order.paid_fee for parent in corrected.net_orders) == (
            self._money("0.04"),
            self._money("0.01"),
        )
        assert {child.instance_id: child.order.paid_fee for child in corrected.orders[:2]} == {
            "alpha": self._money("0.02"),
            "beta": self._money("0.03"),
        }
        original_postings = after_malformed.accounts[0].ledger.postings
        revised_postings = corrected.accounts[0].ledger.postings
        assert revised_postings[: len(original_postings)] == original_postings
        assert len(revised_postings) == len(original_postings) + 2
        assert all(posting.kind == "correction" for posting in revised_postings[-2:])
        assert (
            self._apply(
                "physical-fee-correction-retry",
                AccountExecutionRequest(action="net_cost", net_cost=correction),
            ).accounts
            == corrected.accounts
        )
        assert (
            self._net_event("physical-event-after-cost-revision", partial_event).accounts
            == corrected.accounts
        )
        try:
            self._apply(
                "changed-fee-correction-retry",
                AccountExecutionRequest(
                    action="net_cost",
                    net_cost=replace(correction, corrected_fee=self._money("0.06")),
                ),
            )
        except ValueError as error:
            assert "physical fee correction identity reused" in str(error)
        else:
            raise AssertionError("changed physical fee revision identity was accepted")
        assert self._observe(
            "physical-after-fee-revision",
            correction.known_at,
            AccountLedger(corrected.accounts[0].ledger).snapshot(),
        )
        assert (
            self._apply("after-fee-reconciliation", AccountExecutionRequest(action="inspect"))
            .accounts[0]
            .fault
            is None
        )
        assert corrected.failed_net_events == ()
        conflicting_receipt_rejection = self._conflicting_receipt(
            partial_event, correction.known_at + timedelta(seconds=1)
        )

        self.journal_path = self.output / "reject-policy.sqlite3"
        assert self._observe("reject-opening", self.opening_at, self._opening())
        reject_seed_at = self.opening_at + timedelta(seconds=1)
        self._quote("reject-seed-quote", reject_seed_at)
        reject_seed = self._coordinate(
            "reject-seed",
            self._batch(
                "reject-seed",
                reject_seed_at,
                (
                    self._decision(
                        instance_id="alpha",
                        identity="reject-seed-target",
                        at=reject_seed_at,
                        intent=ReferenceTargetPolicy(self._quantity("1")).decide(),
                    ),
                ),
                "reject",
            ),
        )
        reject_parent = self._require_commit(reject_seed).net_orders[0]
        reject_fill_at = reject_seed_at + timedelta(seconds=1)
        reject_filled = self._net_event(
            "reject-seed-fill",
            self._physical_fill(
                identity="reject-seed-physical",
                order_id=reject_parent.order.identity,
                decision_at=reject_parent.order.decision_at,
                at=reject_fill_at,
                quantity="1",
                fee="0",
            ),
        )
        reject_snapshot = AccountLedger(reject_filled.accounts[0].ledger).snapshot()
        assert reject_snapshot.cash == (self._money("49900"),)
        assert reject_snapshot.positions == (self._quantity("1"),)
        assert self._observe("reject-seed-observed", reject_fill_at, reject_snapshot)
        reject_at = reject_fill_at + timedelta(seconds=1)
        self._quote("reject-conflict-quote", reject_at)
        crossing_rejected = self._coordinate(
            "opposing-rejected",
            self._batch(
                "opposing-rejected",
                reject_at,
                (
                    self._decision(
                        instance_id="alpha",
                        identity="alpha-sell-reject",
                        at=reject_at,
                        intent=ReferenceTargetPolicy(self._quantity("0")).decide(),
                    ),
                    self._decision(
                        instance_id="beta",
                        identity="beta-buy-reject",
                        at=reject_at,
                        intent=ReferenceLimitPolicy(
                            "buy", self._quantity("1"), self._price()
                        ).decide(),
                    ),
                ),
                "reject",
            ),
        )
        assert (
            self._require_commit(crossing_rejected).status,
            self._require_commit(crossing_rejected).reason,
        ) == ("rejected", "self_trade_conflict")
        assert crossing_rejected.accounts[0].ledger == reject_filled.accounts[0].ledger
        assert len(crossing_rejected.orders) == 1 and len(crossing_rejected.net_orders) == 1

        summary: dict[str, object] = {
            "qualification": "local-paper-fixture",
            "venue_label": self.venue,
            "currency": self.currency.code,
            "active_strategies": ["inventory-target", "limit-order"],
            "budget_rejection": self._require_commit(oversized_result).reason,
            "stopped_rejection": stopped_rejection.reason,
            "physical_order_quantity": "4",
            "partial_allocation": ["1", "1"],
            "partial_cash": "49799.98",
            "residual_owner": "beta",
            "settled_cash": "49699.97",
            "settled_position": "3",
            "settled_fees": "0.03",
            "corrected_cash": "49699.95",
            "corrected_fees": "0.05",
            "corrected_alpha_fee": "0.02",
            "corrected_beta_fee": "0.03",
            "crossed_alpha_cash": "-0.01",
            "crossed_beta_cash": "-300.02",
            "crossed_alpha_position": "0",
            "crossed_beta_position": "3",
            "internal_fill_count": len(cross_commit.internal_fill_ids),
            "incompatible_rejection": self._require_commit(rejected).reason,
            "crossing_rejection": self._require_commit(crossing_rejected).reason,
            "conflicting_receipt_rejection": conflicting_receipt_rejection,
            "malformed_request_rejected": malformed.returncode != 0,
            "submission_attempted": False,
            "physical_venue_evidence": False,
        }
        (self.output / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return summary


class ConsumerArguments(argparse.Namespace):
    """Hold the selected authored venue and fresh local evidence directory."""

    output: Path
    venue: Literal["okx", "bitfinex"]


def main() -> None:
    """Parse one selected paper configuration and retain installed evidence."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--venue", required=True, choices=("okx", "bitfinex"))
    arguments = parser.parse_args(namespace=ConsumerArguments())
    summary = PortfolioAccountConsumer(arguments.output, arguments.venue).run()
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
