"""Prove shared account admission, exact postings and independent recovery."""

from __future__ import annotations

# standard library imports
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import Fill
from accounting.accounts import AccountLedger, AccountPosting, AccountSnapshot
from applications.execute.accounts import AccountExecutionResult
from configuration.accounts import AccountConfiguration, OpeningAccount
from execution.accounts import AccountDecision, AccountJournal, AccountObservation, AccountQuote
from execution.records import OrderDecision, OrderEvent, OrderState
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk.budgets import AccountLimit, BudgetPolicy, InstanceLimit
from risk.spot import SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent


class TestAccountJournal:
    """Exercise one cash account shared by two active strategy identities."""

    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)

    @classmethod
    def _money(cls, amount: str) -> Money:
        """Construct an exact account-currency amount."""
        return Money(value=Decimal(amount), currency=cls.currency)

    @classmethod
    def _quantity(cls, amount: str) -> Quantity:
        """Construct an exact base-unit amount."""
        return Quantity(value=Decimal(amount), dimension=cls.dimension)

    @classmethod
    def _price(cls, amount: str) -> Price:
        """Construct an exact account-currency price."""
        return Price(value=Decimal(amount), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Put two 9,000 instance ceilings under one 10,000 account ceiling."""
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.opening_at,
            accounts=(OpeningAccount(account_id="shared", cash=(cls._money("20000"),)),),
            instruments=(
                SpotLimits(
                    maximum=cls._quantity("200"),
                    lot=cls._quantity("1"),
                    tick=cls._price("0.01"),
                    product="spot",
                ),
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
    def _opening_snapshot(cls) -> AccountSnapshot:
        """Describe the independently expected opening transfer."""
        return AccountSnapshot(
            account_id="shared",
            instance_id=None,
            cash=(cls._money("20000"),),
            positions=(),
            fees=(cls._money("0"),),
            rebates=(cls._money("0"),),
            transfers=(cls._money("20000"),),
            fill_ids=(),
            posting_ids=("opening:USDT",),
        )

    @classmethod
    def _observation(
        cls,
        identity: str,
        at: datetime,
        snapshot: AccountSnapshot,
        orders: tuple[OrderState, ...] = (),
    ) -> AccountObservation:
        """Construct an external whole-account fact with explicit open orders."""
        return AccountObservation(
            identity=identity,
            at=at,
            snapshot=snapshot,
            open_orders=orders,
        )

    @classmethod
    def _decision(
        cls,
        identity: str,
        instance_id: str,
        at: datetime,
        *,
        quantity: str = "80",
        limit: str = "100",
        quote_at: datetime | None = None,
        maximum_fee: str = "0",
        checkpoint: bytes = b"candidate-state",
    ) -> AccountDecision:
        """Build a portable order and independently timed valuation observation."""
        return AccountDecision(
            account_id="shared",
            instance_id=instance_id,
            decision=OrderDecision(
                identity=identity,
                at=at,
                intent=OrderIntent(
                    side="buy",
                    quantity=cls._quantity(quantity),
                    limit=cls._price(limit),
                    time_in_force="gtc",
                ),
            ),
            quote=AccountQuote(price=cls._price("100"), at=quote_at or at),
            maximum_fee=cls._money(maximum_fee),
            checkpoint=checkpoint,
        )

    @classmethod
    def _event(
        cls,
        identity: str,
        order_id: str,
        at: datetime,
        kind: str,
        fill: Fill | None = None,
    ) -> OrderEvent:
        """Create a separately identified normalized order fact."""
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
        raise ValueError("unsupported test event")

    def test_atomic_shared_budget_survives_restart_unknown_and_cancel_ack(
        self, tmp_path: Path
    ) -> None:
        """Two clients cannot admit 16,000 against 10,000 or release uncertain risk."""
        path = tmp_path / "shared.sqlite3"
        config = self._config()
        first = AccountJournal(path, config)
        second = AccountJournal(path, config)
        assert first.reconcile(
            self._observation("opening", self.opening_at, self._opening_snapshot())
        )
        at = self.opening_at + timedelta(seconds=1)
        first.observe(AccountQuote(price=self._price("100"), at=at))
        requests = (
            self._decision("alpha-first", "alpha", at),
            self._decision("beta-first", "beta", at),
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = (
                pool.submit(first.admit, requests[0]),
                pool.submit(second.admit, requests[1]),
            )
            outcomes = tuple(result.result() for result in results)
        assert sorted(result.status for result in outcomes) == ["committed", "rejected"]
        assert (
            next(result.reason for result in outcomes if result.status == "rejected")
            == "account_limit"
        )
        admitted_index = next(index for index, result in enumerate(outcomes) if result.orders)
        winner = requests[admitted_index]
        loser_instance = "beta" if winner.instance_id == "alpha" else "alpha"
        order = outcomes[admitted_index].orders[0]
        reopened = AccountJournal(path, config)
        assert reopened.admit(winner) == outcomes[admitted_index]
        assert reopened.checkpoint(winner.instance_id) == b"candidate-state"
        assert len(reopened.orders()) == 1
        with pytest.raises(ValueError, match="different content"):
            reopened.admit(replace(winner, checkpoint=b"changed"))

        reopened.apply_event(
            self._event("unknown-ack", order.identity, at + timedelta(seconds=1), "unknown")
        )
        uncertain = AccountJournal(path, config)
        uncertain.observe(AccountQuote(price=self._price("100"), at=at + timedelta(seconds=2)))
        blocked = uncertain.admit(
            self._decision("loser-unknown", loser_instance, at + timedelta(seconds=2))
        )
        assert (blocked.status, blocked.reason) == ("rejected", "order_outcome_unknown")
        assert not uncertain.reconcile(
            self._observation(
                "unknown-observation",
                at + timedelta(seconds=2),
                self._opening_snapshot(),
                (uncertain.orders()[0].order,),
            )
        )
        resolved = uncertain.apply_event(
            self._event(
                "open-resolution", order.identity, at + timedelta(seconds=3), "reconcile_open"
            )
        )
        assert uncertain.reconcile(
            self._observation(
                "open-observation",
                at + timedelta(seconds=3),
                self._opening_snapshot(),
                (resolved,),
            )
        )
        uncertain.apply_event(
            self._event(
                "cancel-request", order.identity, at + timedelta(seconds=4), "cancel_requested"
            )
        )
        acknowledged = uncertain.apply_event(
            self._event("cancel-ack", order.identity, at + timedelta(seconds=5), "cancel_ack")
        )
        assert acknowledged.remaining == self._quantity("80")
        uncertain.observe(AccountQuote(price=self._price("100"), at=at + timedelta(seconds=6)))
        still_reserved = uncertain.admit(
            self._decision("loser-after-cancel-ack", loser_instance, at + timedelta(seconds=6))
        )
        assert (still_reserved.status, still_reserved.reason) == ("rejected", "account_limit")
        uncertain.apply_event(
            self._event("cancel-final", order.identity, at + timedelta(seconds=7), "cancelled")
        )
        stale_at = at + timedelta(seconds=6, microseconds=500_000)
        stale_decision = uncertain.admit(
            self._decision("decision-before-cancel", loser_instance, stale_at)
        )
        assert (stale_decision.status, stale_decision.reason) == (
            "rejected",
            "decision_precedes_account_state",
        )
        assert not uncertain.reconcile(
            self._observation("observation-before-cancel", stale_at, self._opening_snapshot())
        )
        assert uncertain.reconcile(
            self._observation(
                "observation-after-cancel", at + timedelta(seconds=7), self._opening_snapshot()
            )
        )
        uncertain.observe(AccountQuote(price=self._price("100"), at=at + timedelta(seconds=8)))
        admitted = AccountJournal(path, config).admit(
            self._decision("loser-after-cancel-final", loser_instance, at + timedelta(seconds=8))
        )
        assert admitted.status == "committed"
        assert len(admitted.orders) == 1
        assert {tagged.instance_id for tagged in uncertain.orders()} == {"alpha", "beta"}

    def test_partial_fills_fees_transfers_rebates_and_corrections(self, tmp_path: Path) -> None:
        """Independent cash goldens survive retries, append-only revisions and restart."""
        path = tmp_path / "postings.sqlite3"
        journal = AccountJournal(path, self._config())
        assert journal.reconcile(
            self._observation("opening", self.opening_at, self._opening_snapshot())
        )
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("100"), at=decision_at))
        admitted = journal.admit(self._decision("beta-buy", "beta", decision_at, maximum_fee="1"))
        assert admitted.status == "committed"
        order_id = admitted.orders[0].identity
        journal.apply_event(
            self._event("accepted", order_id, decision_at + timedelta(seconds=1), "accepted")
        )
        first_fill_at = decision_at + timedelta(seconds=2)
        partial = Fill(
            identity="fill-two",
            decision_at=decision_at,
            filled_at=first_fill_at,
            quantity=self._quantity("2"),
            reference=self._price("100"),
            effective=self._price("100"),
            fee=self._money("0.20"),
        )
        partial_event = self._event("partial-receipt", order_id, first_fill_at, "fill", partial)
        partial_order = journal.apply_event(partial_event)
        assert partial_order.status == "partial"
        assert partial_order.remaining == self._quantity("78")
        partial_snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert partial_snapshot.cash == (self._money("19799.80"),)
        assert partial_snapshot.positions == (self._quantity("2"),)
        assert partial_snapshot.fees == (self._money("0.20"),)
        assert partial_snapshot.fill_ids == ("fill-two",)
        assert journal.apply_event(partial_event) == partial_order
        with pytest.raises(ValueError, match="different content"):
            journal.apply_event(
                replace(partial_event, at=first_fill_at + timedelta(microseconds=1))
            )
        assert (
            AccountLedger(AccountJournal(path, self._config()).accounts()[0].ledger).snapshot()
            == partial_snapshot
        )

        final_fill_at = first_fill_at + timedelta(seconds=1)
        final_fill = Fill(
            identity="fill-seventy-eight",
            decision_at=decision_at,
            filled_at=final_fill_at,
            quantity=self._quantity("78"),
            reference=self._price("100"),
            effective=self._price("100"),
            fee=self._money("0.80"),
        )
        assert (
            journal.apply_event(
                self._event("full-receipt", order_id, final_fill_at, "fill", final_fill)
            ).status
            == "filled"
        )
        transfer_at = final_fill_at + timedelta(seconds=1)
        journal.post(
            AccountPosting(
                identity="withdrawal",
                account_id="shared",
                kind="transfer",
                event_at=transfer_at,
                known_at=transfer_at,
                cash=self._money("-100"),
            )
        )
        rebate_at = transfer_at + timedelta(seconds=1)
        rebate = AccountPosting(
            identity="rebate-one",
            account_id="shared",
            instance_id="beta",
            order_id=order_id,
            kind="rebate",
            event_at=rebate_at,
            known_at=rebate_at,
            cash=self._money("1"),
        )
        journal.post(rebate)
        assert journal.post(rebate).cash == (self._money("11900"),)
        correction_at = rebate_at + timedelta(seconds=1)
        journal.post(
            AccountPosting(
                identity="rebate-correction",
                account_id="shared",
                instance_id="beta",
                order_id=order_id,
                kind="correction",
                corrects="rebate-one",
                replacement_kind="rebate",
                event_at=rebate_at,
                known_at=correction_at,
                cash=self._money("1.50"),
            )
        )
        expected = AccountSnapshot(
            account_id="shared",
            instance_id=None,
            cash=(self._money("11900.50"),),
            positions=(self._quantity("80"),),
            fees=(self._money("1"),),
            rebates=(self._money("1.50"),),
            transfers=(self._money("19900"),),
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
        recovered = AccountJournal(path, self._config())
        assert AccountLedger(recovered.accounts()[0].ledger).snapshot() == expected
        assert recovered.reconcile(
            self._observation("settled-account", correction_at + timedelta(seconds=1), expected)
        )
        attributed = AccountLedger(recovered.accounts()[0].ledger).snapshot(instance_id="beta")
        assert attributed.cash == (self._money("-7999.50"),)
        assert attributed.positions == (self._quantity("80"),)
        assert attributed.transfers == (self._money("0"),)
        assert attributed.fill_ids == ("fill-two", "fill-seventy-eight")
        assert recovered.accounts()[0].fault is None

    def test_unauthorized_stale_and_bad_price_requests_leave_no_orders(
        self, tmp_path: Path
    ) -> None:
        """Reject unsafe requests without changing physical cash or pending risk."""
        journal = AccountJournal(tmp_path / "rejections.sqlite3", self._config())
        assert journal.reconcile(
            self._observation("opening", self.opening_at, self._opening_snapshot())
        )
        at = self.opening_at + timedelta(seconds=1)
        old_quote_at = at - timedelta(seconds=2)
        journal.observe(AccountQuote(price=self._price("100"), at=old_quote_at))
        assert (
            journal.admit(self._decision("stale-quote", "alpha", at, quote_at=old_quote_at)).reason
            == "stale_quote"
        )
        journal.observe(AccountQuote(price=self._price("100"), at=at))
        assert (
            journal.admit(self._decision("unauthorized", "rogue", at)).reason
            == "unauthorized_instance_or_instrument"
        )
        assert (
            journal.admit(self._decision("price-deviation", "alpha", at, limit="105")).reason
            == "price_deviation"
        )
        assert (
            journal.admit(
                self._decision("unobserved-quote", "alpha", at + timedelta(seconds=1))
            ).reason
            == "unobserved_quote"
        )
        late = at + timedelta(days=1, seconds=1)
        journal.observe(AccountQuote(price=self._price("100"), at=late))
        assert journal.admit(self._decision("stale-state", "alpha", late)).reason == "stale_state"
        assert journal.orders() == ()
        assert AccountLedger(journal.accounts()[0].ledger).snapshot() == self._opening_snapshot()

    def test_bad_or_stale_observation_blocks_but_cannot_clear_operator_stop(
        self, tmp_path: Path
    ) -> None:
        """A clean later observation repairs an account break while preserving a manual block."""
        journal = AccountJournal(tmp_path / "reconcile.sqlite3", self._config())
        snapshot = self._opening_snapshot()
        assert journal.reconcile(self._observation("opening", self.opening_at, snapshot))
        journal.block("shared", "operator-stop")
        later = self.opening_at + timedelta(seconds=1)
        changed = replace(snapshot, cash=(self._money("19999.99"),))
        assert not journal.reconcile(self._observation("mismatch", later, changed))
        assert journal.accounts()[0].fault == "account_break"
        assert journal.accounts()[0].operator_block == "operator-stop"
        assert not journal.reconcile(
            self._observation("stale", self.opening_at - timedelta(microseconds=1), snapshot)
        )
        assert journal.reconcile(self._observation("clean", later + timedelta(seconds=1), snapshot))
        assert journal.accounts()[0].fault is None
        assert journal.accounts()[0].operator_block == "operator-stop"
        rejected = journal.admit(self._decision("blocked", "alpha", later + timedelta(seconds=2)))
        assert (rejected.status, rejected.reason) == ("rejected", "operator-stop")
        assert journal.orders() == ()

    def test_matching_observation_cannot_clear_unfunded_pending_buy(self, tmp_path: Path) -> None:
        """A withdrawal below pending buy cash leaves a durable account break."""
        config = replace(
            self._config(),
            accounts=(OpeningAccount(account_id="shared", cash=(self._money("10000"),)),),
        )
        journal = AccountJournal(tmp_path / "unfunded.sqlite3", config)
        opening = replace(
            self._opening_snapshot(),
            cash=(self._money("10000"),),
            transfers=(self._money("10000"),),
        )
        assert journal.reconcile(self._observation("opening", self.opening_at, opening))
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("100"), at=decision_at))
        committed = journal.admit(self._decision("pending-buy", "alpha", decision_at))
        assert committed.status == "committed"
        withdrawal_at = decision_at + timedelta(seconds=1)
        journal.post(
            AccountPosting(
                identity="cash-withdrawal",
                account_id="shared",
                kind="transfer",
                event_at=withdrawal_at,
                known_at=withdrawal_at,
                cash=self._money("-3000"),
            )
        )
        observed = replace(
            opening,
            cash=(self._money("7000"),),
            transfers=(self._money("7000"),),
            posting_ids=("opening:USDT", "cash-withdrawal"),
        )
        assert AccountLedger(journal.accounts()[0].ledger).snapshot() == observed
        assert not journal.reconcile(
            self._observation(
                "unfunded-observation",
                withdrawal_at + timedelta(seconds=1),
                observed,
                committed.orders,
            )
        )
        assert journal.accounts()[0].fault == "account_break"
        assert journal.orders()[0].order.remaining == self._quantity("80")
        blocked = journal.admit(
            self._decision("second-after-withdrawal", "beta", withdrawal_at + timedelta(seconds=2))
        )
        assert (blocked.status, blocked.reason) == ("rejected", "account_break")

    def test_regressed_terminal_event_blocks_without_releasing_reservation(
        self, tmp_path: Path
    ) -> None:
        """A stale cancellation cannot erase a newer accepted order and pending cash."""
        journal = AccountJournal(tmp_path / "event-clock.sqlite3", self._config())
        assert journal.reconcile(
            self._observation("opening", self.opening_at, self._opening_snapshot())
        )
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("100"), at=decision_at))
        committed = journal.admit(self._decision("pending-buy", "alpha", decision_at))
        assert committed.status == "committed"
        order = committed.orders[0]
        accepted = journal.apply_event(
            self._event("accepted", order.identity, decision_at + timedelta(seconds=2), "accepted")
        )
        with pytest.raises(ValueError, match="account blocked: event knowledge precedes"):
            journal.apply_event(
                self._event(
                    "old-cancel", order.identity, decision_at + timedelta(seconds=1), "cancelled"
                )
            )
        assert journal.orders()[0].order == accepted
        assert journal.orders()[0].order.remaining == self._quantity("80")
        assert journal.accounts()[0].fault == "order_event_break"
        assert AccountLedger(journal.accounts()[0].ledger).snapshot() == self._opening_snapshot()

    def test_account_application_result_round_trips_through_public_codec(
        self, tmp_path: Path
    ) -> None:
        """An installed command result remains a decodable public wire record."""
        journal = AccountJournal(tmp_path / "result-wire.sqlite3", self._config())
        result = AccountExecutionResult(accounts=journal.accounts(), orders=journal.orders())
        codec = DomainCodec()
        assert codec.decode_json(codec.encode_json(result), AccountExecutionResult) == result
