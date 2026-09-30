"""Exercise the installed shared-account application with independent paper goldens."""

from __future__ import annotations

# standard library imports
import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec

# project library imports
from accounting import Fill
from accounting.accounts import AccountLedger, AccountPosting, AccountSnapshot
from applications.execute.accounts import (
    AccountExecutionApplication,
    AccountExecutionRequest,
    AccountExecutionResult,
)
from configuration.accounts import AccountConfiguration, InstrumentFeeRate, OpeningAccount
from execution.accounts import AccountDecision, AccountObservation, AccountQuote
from execution.records import OrderDecision, OrderEvent, OrderState, StepCommit
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk.budgets import AccountLimit, BudgetPolicy, InstanceLimit
from risk.spot import SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent, TargetIntent


class SharedAccountConsumer:
    """Retain every installed request and result for one non-submitting shared account."""

    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)

    def __init__(self, output: Path) -> None:
        """Bind one new local evidence directory, never an executable venue."""
        self.output = output
        self.codec = DomainCodec()
        self.application = AccountExecutionApplication()
        self.config_path = output / "configuration.json"
        self.journal_path = output / "account.sqlite3"

    @classmethod
    def _money(cls, amount: str) -> Money:
        """Construct an exact USDT amount without binary floating arithmetic."""
        return Money(value=Decimal(amount), currency=cls.currency)

    @classmethod
    def _quantity(cls, amount: str) -> Quantity:
        """Construct an exact spot base quantity."""
        return Quantity(value=Decimal(amount), dimension=cls.dimension)

    @classmethod
    def _price(cls, amount: str) -> Price:
        """Construct an exact spot limit or quote."""
        return Price(value=Decimal(amount), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Declare two active 9,000 instances sharing one 10,000 account budget."""
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(
                maximum=cls._quantity("200"),
                lot=cls._quantity("1"),
                tick=cls._price("0.01"),
                product="spot",
            ),
        )
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.opening_at,
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
                accounts=(AccountLimit(account_id="shared", maximum=cls._money("10000")),),
                instances=(
                    InstanceLimit(
                        instance_id="alpha",
                        account_id="shared",
                        maximum=cls._money("9000"),
                        instruments=(cls.dimension.instrument_id,),
                    ),
                    InstanceLimit(
                        instance_id="beta",
                        account_id="shared",
                        maximum=cls._money("9000"),
                        instruments=(cls.dimension.instrument_id,),
                    ),
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=100,
                max_order_notional=cls._money("9000"),
            ),
        )

    @classmethod
    def _snapshot(
        cls,
        *,
        cash: str,
        position: str | None = None,
        fees: str = "0",
        rebates: str = "0",
        transfers: str = "20000",
        fill_ids: tuple[str, ...] = (),
        posting_ids: tuple[str, ...] = ("opening:USDT",),
    ) -> AccountSnapshot:
        """Provide literal independent physical-account expectations."""
        return AccountSnapshot(
            account_id="shared",
            instance_id=None,
            cash=(cls._money(cash),),
            positions=() if position is None else (cls._quantity(position),),
            fees=(cls._money(fees),),
            rebates=(cls._money(rebates),),
            transfers=(cls._money(transfers),),
            fill_ids=fill_ids,
            posting_ids=posting_ids,
        )

    @classmethod
    def _decision(
        cls,
        identity: str,
        instance_id: str,
        at: datetime,
        *,
        limit: str = "100",
        quote_at: datetime | None = None,
        fee: str = "0",
        checkpoint: bytes = b"reference-candidate",
        form: Literal["order", "target"] = "order",
    ) -> AccountDecision:
        """Submit one portable order intent through independent account authority."""
        intent = (
            TargetIntent(quantity=cls._quantity("80"))
            if form == "target"
            else OrderIntent(
                side="buy",
                quantity=cls._quantity("80"),
                limit=cls._price(limit),
                time_in_force="gtc",
            )
        )
        return AccountDecision(
            account_id="shared",
            instance_id=instance_id,
            decision=OrderDecision(
                identity=identity,
                at=at,
                intent=intent,
            ),
            quote=AccountQuote(price=cls._price("100"), at=quote_at or at),
            maximum_fee=cls._money(fee),
            checkpoint=checkpoint,
        )

    @staticmethod
    def _admission(result: AccountExecutionResult) -> StepCommit:
        """Require an application admission outcome for an admission request."""
        if result.admission is None:
            raise ValueError("installed application omitted admission outcome")
        return result.admission

    @staticmethod
    def _event(
        identity: str,
        order_id: str,
        at: datetime,
        kind: str,
        fill: Fill | None = None,
    ) -> OrderEvent:
        """Create an identified normalized order event for the installed command."""
        if kind == "fill":
            return OrderEvent(identity=identity, order_id=order_id, at=at, kind="fill", fill=fill)
        if kind == "unknown":
            return OrderEvent(identity=identity, order_id=order_id, at=at, kind="unknown")
        if kind == "reconcile_open":
            return OrderEvent(identity=identity, order_id=order_id, at=at, kind="reconcile_open")
        if kind == "cancel_requested":
            return OrderEvent(identity=identity, order_id=order_id, at=at, kind="cancel_requested")
        if kind == "cancel_ack":
            return OrderEvent(identity=identity, order_id=order_id, at=at, kind="cancel_ack")
        if kind == "cancelled":
            return OrderEvent(identity=identity, order_id=order_id, at=at, kind="cancelled")
        if kind == "accepted":
            return OrderEvent(identity=identity, order_id=order_id, at=at, kind="accepted")
        raise ValueError("unsupported reference event")

    def _apply(self, label: str, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Write exact input bytes and retain the actual application result bytes."""
        request_path = self.output / "requests" / f"{label}.json"
        result_path = self.output / "results" / f"{label}.json"
        request_path.write_bytes(self.codec.encode_json(request))
        result = self.application.run(
            config_path=self.config_path,
            journal_path=self.journal_path,
            request_path=request_path,
        )
        if result.submission_attempted:
            raise ValueError("account application attempted an executable submission")
        result_path.write_bytes(self.codec.encode_json(result))
        return result

    def _observe(
        self,
        identity: str,
        at: datetime,
        snapshot: AccountSnapshot,
        orders: tuple[OrderState, ...] = (),
    ) -> bool:
        """Supply a complete independently calculated account observation."""
        result = self._apply(
            identity,
            AccountExecutionRequest(
                action="reconcile",
                observation=AccountObservation(
                    identity=identity,
                    at=at,
                    snapshot=snapshot,
                    open_orders=orders,
                ),
            ),
        )
        if result.reconciled is None:
            raise ValueError("installed application omitted reconciliation outcome")
        return result.reconciled

    def _mark_quote(self, label: str, at: datetime) -> None:
        """Supply an independent valuation fact before a candidate requests admission."""
        self._apply(
            label,
            AccountExecutionRequest(
                action="quote", quote=AccountQuote(price=self._price("100"), at=at)
            ),
        )

    def _cli(
        self,
        label: str,
        expected: AccountExecutionResult,
        request_path: Path | None = None,
    ) -> None:
        """Compare parsed installed-command JSON with the typed application result."""
        command = [
            str(Path(sys.executable).with_name("alpha-execute")),
            "account",
            "--config",
            str(self.config_path),
            "--journal",
            str(self.journal_path),
        ]
        if request_path is not None:
            command.extend(("--request", str(request_path)))
        completed = subprocess.run(command, capture_output=True, check=True, timeout=20)
        (self.output / "results" / f"{label}.json").write_bytes(completed.stdout)
        actual = msgspec.json.decode(completed.stdout, type=dict[str, object])
        expected_json = msgspec.json.decode(
            self.codec.encode_json(expected), type=dict[str, object]
        )
        if actual != expected_json:
            raise ValueError("installed account command differs from application result")

    def run(self) -> dict[str, object]:
        """Run restart, uncertainty, exact economics and safe-response scenarios."""
        self.output.mkdir(parents=True, exist_ok=False)
        (self.output / "requests").mkdir()
        (self.output / "results").mkdir()
        self.config_path.write_bytes(self.codec.encode_json(self._config()))
        initial = self.application.run(
            config_path=self.config_path,
            journal_path=self.journal_path,
        )
        (self.output / "results" / "initial.json").write_bytes(self.codec.encode_json(initial))
        self._cli("cli-initial-inspect", initial)
        opening = self._snapshot(cash="20000")
        assert self._observe("opening", self.opening_at, opening)
        at = self.opening_at + timedelta(seconds=1)
        old_quote_at = at - timedelta(seconds=2)
        self._mark_quote("old-market-quote", old_quote_at)
        stale = self._admission(
            self._apply(
                "stale-quote",
                AccountExecutionRequest(
                    action="admit",
                    decision=self._decision("stale-quote", "alpha", at, quote_at=old_quote_at),
                ),
            )
        )
        assert (stale.status, stale.reason) == ("rejected", "stale_quote")
        self._mark_quote("fresh-market-quote", at)
        rejected = (
            (
                "unauthorized",
                self._decision("unauthorized", "rogue", at),
                "unauthorized_instance_or_instrument",
            ),
            ("price", self._decision("bad-price", "alpha", at, limit="105"), "price_deviation"),
            (
                "unobserved-quote",
                self._decision("unobserved-quote", "alpha", at + timedelta(seconds=1)),
                "unobserved_quote",
            ),
        )
        for label, decision, reason in rejected:
            outcome = self._admission(
                self._apply(
                    label,
                    AccountExecutionRequest(
                        action="admit",
                        decision=decision,
                    ),
                )
            )
            assert (outcome.status, outcome.reason) == ("rejected", reason)
        assert (
            self.application.run(
                config_path=self.config_path,
                journal_path=self.journal_path,
            ).orders
            == ()
        )

        alpha = self._decision("alpha-first", "alpha", at, form="target")
        alpha_result = self._apply(
            "alpha-admit", AccountExecutionRequest(action="admit", decision=alpha)
        )
        accepted = self._admission(alpha_result)
        assert accepted.status == "committed" and len(accepted.orders) == 1
        self._cli(
            "cli-alpha-retry",
            alpha_result,
            self.output / "requests" / "alpha-admit.json",
        )
        alpha_order = accepted.orders[0]
        competing = self._admission(
            self._apply(
                "beta-race",
                AccountExecutionRequest(
                    action="admit",
                    decision=self._decision("beta-race", "beta", at),
                ),
            )
        )
        assert (competing.status, competing.reason) == ("rejected", "account_limit")
        self.application = AccountExecutionApplication()
        assert (
            self._admission(
                self._apply("alpha-retry", AccountExecutionRequest(action="admit", decision=alpha))
            )
            == accepted
        )

        unknown_at = at + timedelta(seconds=1)
        uncertain = self._apply(
            "unknown",
            AccountExecutionRequest(
                action="event",
                event=self._event("unknown-event", alpha_order.identity, unknown_at, "unknown"),
            ),
        )
        assert uncertain.orders[0].order.status == "unknown"
        self._mark_quote("market-quote-uncertain", unknown_at + timedelta(seconds=1))
        blocked = self._admission(
            self._apply(
                "beta-uncertain",
                AccountExecutionRequest(
                    action="admit",
                    decision=self._decision(
                        "beta-uncertain", "beta", unknown_at + timedelta(seconds=1)
                    ),
                ),
            )
        )
        assert (blocked.status, blocked.reason) == ("rejected", "order_outcome_unknown")
        assert not self._observe(
            "unknown-observation",
            unknown_at + timedelta(seconds=1),
            opening,
            (uncertain.orders[0].order,),
        )
        opened = self._apply(
            "reconcile-open",
            AccountExecutionRequest(
                action="event",
                event=self._event(
                    "open-event",
                    alpha_order.identity,
                    unknown_at + timedelta(seconds=2),
                    "reconcile_open",
                ),
            ),
        )
        assert opened.order is not None
        assert self._observe(
            "open-observation",
            unknown_at + timedelta(seconds=2),
            opening,
            (opened.order,),
        )
        self._apply(
            "cancel-request",
            AccountExecutionRequest(
                action="event",
                event=self._event(
                    "cancel-request",
                    alpha_order.identity,
                    unknown_at + timedelta(seconds=3),
                    "cancel_requested",
                ),
            ),
        )
        acknowledged = self._apply(
            "cancel-ack",
            AccountExecutionRequest(
                action="event",
                event=self._event(
                    "cancel-ack",
                    alpha_order.identity,
                    unknown_at + timedelta(seconds=4),
                    "cancel_ack",
                ),
            ),
        )
        assert acknowledged.order is not None
        assert acknowledged.order.remaining == self._quantity("80")
        self._mark_quote("market-quote-cancel-ack", unknown_at + timedelta(seconds=5))
        reserved = self._admission(
            self._apply(
                "beta-cancel-ack",
                AccountExecutionRequest(
                    action="admit",
                    decision=self._decision(
                        "beta-after-ack", "beta", unknown_at + timedelta(seconds=5)
                    ),
                ),
            )
        )
        assert (reserved.status, reserved.reason) == ("rejected", "account_limit")
        self._apply(
            "cancelled",
            AccountExecutionRequest(
                action="event",
                event=self._event(
                    "cancel-final",
                    alpha_order.identity,
                    unknown_at + timedelta(seconds=6),
                    "cancelled",
                ),
            ),
        )
        beta_at = unknown_at + timedelta(seconds=7)
        self._mark_quote("market-quote-beta", beta_at)
        beta = self._admission(
            self._apply(
                "beta-admit",
                AccountExecutionRequest(
                    action="admit",
                    decision=self._decision("beta-after-final", "beta", beta_at, fee="1"),
                ),
            )
        )
        assert beta.status == "committed" and len(beta.orders) == 1
        beta_order = beta.orders[0]
        self._apply(
            "beta-accepted",
            AccountExecutionRequest(
                action="event",
                event=self._event(
                    "beta-accepted",
                    beta_order.identity,
                    beta_at + timedelta(seconds=1),
                    "accepted",
                ),
            ),
        )

        partial_at = beta_at + timedelta(seconds=2)
        partial_fill = Fill(
            identity="fill-two",
            decision_at=beta_at,
            filled_at=partial_at,
            quantity=self._quantity("2"),
            reference=self._price("100"),
            effective=self._price("100"),
            fee=self._money("0.20"),
        )
        partial_event = self._event(
            "partial-receipt", beta_order.identity, partial_at, "fill", partial_fill
        )
        partial_result = self._apply(
            "partial-fill",
            AccountExecutionRequest(
                action="event",
                event=partial_event,
            ),
        )
        assert partial_result.order is not None
        assert partial_result.order.remaining == self._quantity("78")
        partial_expected = self._snapshot(
            cash="19799.80",
            position="2",
            fees="0.20",
            fill_ids=("fill-two",),
            posting_ids=("opening:USDT", "fill-two", "fee:fill-two"),
        )
        assert AccountLedger(partial_result.accounts[0].ledger).snapshot() == partial_expected
        assert (
            self._apply(
                "partial-retry",
                AccountExecutionRequest(
                    action="event",
                    event=partial_event,
                ),
            ).accounts
            == partial_result.accounts
        )

        final_fill_at = partial_at + timedelta(seconds=1)
        full = self._apply(
            "full-fill",
            AccountExecutionRequest(
                action="event",
                event=self._event(
                    "full-receipt",
                    beta_order.identity,
                    final_fill_at,
                    "fill",
                    Fill(
                        identity="fill-seventy-eight",
                        decision_at=beta_at,
                        filled_at=final_fill_at,
                        quantity=self._quantity("78"),
                        reference=self._price("100"),
                        effective=self._price("100"),
                        fee=self._money("0.80"),
                    ),
                ),
            ),
        )
        assert full.order is not None and full.order.status == "filled"
        transfer_at = final_fill_at + timedelta(seconds=1)
        self._apply(
            "withdrawal",
            AccountExecutionRequest(
                action="post",
                posting=AccountPosting(
                    identity="withdrawal",
                    account_id="shared",
                    kind="transfer",
                    event_at=transfer_at,
                    known_at=transfer_at,
                    cash=self._money("-100"),
                ),
            ),
        )
        rebate_at = transfer_at + timedelta(seconds=1)
        self._apply(
            "rebate",
            AccountExecutionRequest(
                action="post",
                posting=AccountPosting(
                    identity="rebate-one",
                    account_id="shared",
                    instance_id="beta",
                    order_id=beta_order.identity,
                    kind="rebate",
                    event_at=rebate_at,
                    known_at=rebate_at,
                    cash=self._money("1"),
                ),
            ),
        )
        correction_at = rebate_at + timedelta(seconds=1)
        revised = self._apply(
            "rebate-correction",
            AccountExecutionRequest(
                action="post",
                posting=AccountPosting(
                    identity="rebate-correction",
                    account_id="shared",
                    instance_id="beta",
                    order_id=beta_order.identity,
                    kind="correction",
                    corrects="rebate-one",
                    replacement_kind="rebate",
                    event_at=rebate_at,
                    known_at=correction_at,
                    cash=self._money("1.50"),
                ),
            ),
        )
        final_expected = self._snapshot(
            cash="11900.50",
            position="80",
            fees="1",
            rebates="1.50",
            transfers="19900",
            fill_ids=("fill-two", "fill-seventy-eight"),
            posting_ids=(
                "opening:USDT",
                "fill-two",
                "fee:fill-two",
                "fill-seventy-eight",
                "fee:fill-seventy-eight",
                "withdrawal",
                "rebate-one",
                "rebate-correction",
            ),
        )
        assert AccountLedger(revised.accounts[0].ledger).snapshot() == final_expected
        assert self._observe("settled", correction_at + timedelta(seconds=1), final_expected)
        self.application = AccountExecutionApplication()
        inspected = self.application.run(
            config_path=self.config_path,
            journal_path=self.journal_path,
        )
        assert AccountLedger(inspected.accounts[0].ledger).snapshot() == final_expected
        assert tuple(tagged.order.status for tagged in inspected.orders) == ("cancelled", "filled")

        self._apply(
            "operator-stop",
            AccountExecutionRequest(
                action="block",
                account_id="shared",
                reason="operator-stop",
            ),
        )
        mismatch = self._snapshot(
            cash="11900.49",
            position="80",
            fees="1",
            rebates="1.50",
            transfers="19900",
            fill_ids=("fill-two", "fill-seventy-eight"),
            posting_ids=final_expected.posting_ids,
        )
        assert not self._observe("mismatch", correction_at + timedelta(seconds=2), mismatch)
        assert not self._observe("stale", correction_at - timedelta(seconds=1), final_expected)
        assert self._observe("recovered", correction_at + timedelta(seconds=3), final_expected)
        stopped = self._admission(
            self._apply(
                "stopped-admission",
                AccountExecutionRequest(
                    action="admit",
                    decision=self._decision(
                        "after-stop", "alpha", correction_at + timedelta(seconds=4)
                    ),
                ),
            )
        )
        assert (stopped.status, stopped.reason) == ("rejected", "operator-stop")
        assert inspected.submission_attempted is False
        state = self.application.run(
            config_path=self.config_path,
            journal_path=self.journal_path,
        )
        assert state.accounts[0].fault is None
        assert state.accounts[0].operator_block == "operator-stop"
        summary: dict[str, object] = {
            "qualification": "local-paper-fixture",
            "submission_attempted": False,
            "account_id": "shared",
            "active_instances": ["alpha", "beta"],
            "shared_budget": "10000",
            "first_admission": accepted.status,
            "competing_admission": competing.reason,
            "unknown_admission": blocked.reason,
            "cancel_ack_admission": reserved.reason,
            "partial_cash": "19799.80",
            "partial_position": "2",
            "final_cash": "11900.50",
            "final_position": "80",
            "final_fees": "1",
            "final_rebates": "1.50",
            "final_transfers": "19900",
            "order_statuses": [tagged.order.status for tagged in state.orders],
            "operator_block": state.accounts[0].operator_block,
            "posting_ids": list(final_expected.posting_ids),
        }
        (self.output / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return summary


class ConsumerArguments(argparse.Namespace):
    """Hold the single required local evidence-directory argument."""

    output: Path


def main() -> None:
    """Run the installed, non-submitting shared-account reference workload."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(namespace=ConsumerArguments())
    print(json.dumps(SharedAccountConsumer(arguments.output).run(), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
