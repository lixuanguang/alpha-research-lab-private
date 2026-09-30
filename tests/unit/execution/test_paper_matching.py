"""Verify finite paper quote matching, exact fees, and replayed event identities."""

from __future__ import annotations

# standard library imports
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import Ledger, LedgerState
from configuration import PaperConfiguration, PaperExecutionScenario
from execution import (
    OrderDecision,
    OrderEvent,
    OrderState,
    PaperMarket,
    PaperMatcher,
    PaperOrderJournal,
)
from execution.paper import PaperFeeSchedule
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import SpotLimits
from serialization import DomainCodec
from simulation import SpotCosts
from strategies import OrderIntent


class _ReserveBlindFeeSchedule(PaperFeeSchedule):
    """Model a defective fee schedule that ignores each order's remaining fee reserve."""

    def affordable(
        self, order: OrderState, size: Fraction, price: Price, lot: Fraction
    ) -> Fraction:
        """Return every whole lot, as a model without the reserve bound would."""
        return (size // lot) * lot


class _OverchargingFeeSchedule(_ReserveBlindFeeSchedule):
    """Model a defective fee schedule that also charges ten times its own rate."""

    def fee(self, size: Fraction, price: Price) -> Money:
        """Charge ten times the modeled fee, beyond any reserve sized for the rate."""
        modeled = super().fee(size, price)
        return Money(value=modeled.value * 10, currency=modeled.currency)


class TestPaperMatcher:
    """Compare matched orders with hand-calculated liquidity and account economics."""

    currency = Currency(code="TEST", minor_unit=Decimal("0.01"))
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    decision_at = datetime(2025, 1, 1, tzinfo=UTC)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Construct exact base units for an independent account scenario."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Construct exact quote currency per base unit."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _money(cls, value: str) -> Money:
        """Construct exact quote currency amounts."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _journal(cls, root: Path) -> PaperOrderJournal:
        """Open one fenced account with ample cash and a one-unit quantity grid."""
        return PaperOrderJournal(
            root / "paper.sqlite3",
            account="paper-account",
            instance="strategy-one",
            binding_identity="a" * 64,
            mode="paper",
            limits=SpotLimits(
                maximum=cls._quantity("10"),
                lot=cls._quantity("1"),
                tick=cls._price("0.01"),
                product="spot",
            ),
            ledger_state=LedgerState(initial_cash=cls._money("1000"), dimension=cls.dimension),
            fee_rate=Decimal("0.005"),
        )

    @classmethod
    def _admit(
        cls,
        journal: PaperOrderJournal,
        epoch: int,
        *,
        step_id: str,
        quantity: str,
        limit: str,
        time_in_force: Literal["gtc", "ioc", "post-only"] = "gtc",
        maximum_fee: str = "0.50",
        at: datetime | None = None,
    ) -> OrderState:
        """Admit one cash-backed buy order with an explicit fee reserve."""
        result = journal.commit_step(
            epoch=epoch,
            step_id=step_id,
            checkpoint=step_id.encode(),
            decision=OrderDecision(
                identity=f"decision-{step_id}",
                at=cls.decision_at if at is None else at,
                intent=OrderIntent(
                    side="buy",
                    quantity=cls._quantity(quantity),
                    limit=cls._price(limit),
                    time_in_force=time_in_force,
                ),
            ),
            reference=cls._price("1.00"),
            maximum_fee=cls._money(maximum_fee),
        )
        assert result.status == "committed" and len(result.orders) == 1
        return result.orders[0]

    @classmethod
    def _market(
        cls,
        identity: str,
        *,
        at: datetime,
        bid: str = "0.90",
        ask: str = "1.00",
        ask_quantity: str = "3",
    ) -> PaperMarket:
        """Declare one no-impact top-of-book snapshot and finite ask liquidity."""
        return PaperMarket(
            identity=identity,
            at=at,
            bid=cls._price(bid),
            ask=cls._price(ask),
            bid_quantity=cls._quantity("10"),
            ask_quantity=cls._quantity(ask_quantity),
        )

    @classmethod
    def _scenario(
        cls,
        *,
        entry_delay_us: int = 0,
        cancel_delay_us: int = 0,
        adverse: str = "0.02",
    ) -> PaperExecutionScenario:
        """Declare an authored venue assumption independent of native source evidence."""
        return PaperExecutionScenario(
            venue="okx",
            instrument_id=cls.dimension.instrument_id,
            entry_delay_us=entry_delay_us,
            cancel_delay_us=cancel_delay_us,
            adverse=cls._price(adverse),
            fee_rate=Decimal("0.005"),
            take_fraction=Decimal("1"),
            gas_inapplicable_reason="off-chain spot orders have no on-chain settlement",
        )

    @classmethod
    def _matcher(cls, journal: PaperOrderJournal) -> PaperMatcher:
        """Match at the displayed touch with no modeled delay or adverse cost."""
        return PaperMatcher(
            journal,
            fee_rate=Decimal("0.005"),
            lot=cls._quantity("1"),
            scenario=cls._scenario(adverse="0.00"),
        )

    def test_two_orders_share_finite_ask_and_replay_has_no_extra_fill(self, tmp_path: Path) -> None:
        """Three displayed units fill two then one, with half-even fees and one reserve."""
        market = self._market("shared-ask", at=self.decision_at + timedelta(seconds=1))
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("first-owner")
            first = self._admit(journal, epoch, step_id="first", quantity="2", limit="1.10")
            second = self._admit(journal, epoch, step_id="second", quantity="2", limit="1.10")
            matcher = self._matcher(journal)
            matcher.match(market, epoch=epoch)
            filled = journal.order(first.identity)
            assert filled is not None and filled.status == "filled"
            partial = journal.order(second.identity)
            assert partial is not None
            assert partial.status == "partial"
            assert partial.filled.value == Decimal("1")
            assert partial.remaining.value == Decimal("1")
            fills = journal.ledger_state().fills
            assert tuple(fill.quantity.value for fill in fills) == (Decimal("2"), Decimal("1"))
            assert tuple(fill.effective.value for fill in fills) == (
                Decimal("1.00"),
                Decimal("1.00"),
            )
            assert all(fill.reference == fill.effective for fill in fills)
            # 2 * 1.00 * .005 = .01; 1 * 1.00 * .005 = .005 rounds to .00.
            assert tuple(fill.fee.value for fill in fills) == (
                Decimal("0.01"),
                Decimal("0.00"),
            )
            balance = Ledger(journal.ledger_state()).balance
            assert balance.holding.value == Decimal("3")
            assert balance.cash.value == Decimal("996.99")
            assert balance.fees.value == Decimal("0.01")
            assert balance.slippage.value == Decimal("0")
            assert journal.reservations().cash.value == Decimal("1.60")
            before = (journal.events(), journal.orders(), journal.ledger_state())
            matcher.match(market, epoch=epoch)
            assert (journal.events(), journal.orders(), journal.ledger_state()) == before
        with self._journal(tmp_path) as restarted:
            epoch = restarted.claim("restarted-owner")
            self._matcher(restarted).match(market, epoch=epoch)
            assert (restarted.events(), restarted.orders(), restarted.ledger_state()) == before

    def test_ioc_cancels_unfilled_remainder_after_touch(self, tmp_path: Path) -> None:
        """One displayed unit fills and the remaining three release their reservation."""
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("ioc-owner")
            order = self._admit(
                journal,
                epoch,
                step_id="ioc",
                quantity="4",
                limit="1.10",
                time_in_force="ioc",
            )
            market = self._market(
                "thin-ask", at=self.decision_at + timedelta(seconds=1), ask_quantity="1"
            )
            self._matcher(journal).match(market, epoch=epoch)
            current = journal.order(order.identity)
            assert current is not None
            assert current.status == "cancelled"
            assert current.filled.value == Decimal("1")
            assert current.remaining.value == Decimal("3")
            assert tuple(item.event.kind for item in journal.events()) == (
                "request_ack",
                "accepted",
                "fill",
                "cancelled",
            )
            assert len(journal.ledger_state().fills) == 1
            assert journal.reservations().cash.value == Decimal("0")

    def test_interrupted_market_rejects_changed_bytes_before_another_fill(
        self, tmp_path: Path
    ) -> None:
        """A quote claim survives restart even when its final market step is absent."""
        market = self._market(
            "unfinished-quote", at=self.decision_at + timedelta(seconds=1), ask_quantity="1"
        )
        changed = self._market(
            "unfinished-quote",
            at=market.at,
            ask="1.01",
            ask_quantity="1",
        )
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("interrupted-owner")
            order = self._admit(journal, epoch, step_id="interrupted", quantity="2", limit="1.10")
            self._matcher(journal).match(market, epoch=epoch)
            current = journal.order(order.identity)
            assert current is not None and current.filled.value == Decimal("1")
            assert journal.step("market:unfinished-quote") is None
            assert journal.markets() == ((market.identity, DomainCodec().encode_json(market)),)
            before = (journal.events(), journal.orders(), journal.ledger_state())
        with self._journal(tmp_path) as restarted:
            epoch = restarted.claim("restarted-owner")
            matcher = self._matcher(restarted)
            with pytest.raises(ValueError, match="market identity was reused"):
                matcher.match(changed, epoch=epoch)
            assert (restarted.events(), restarted.orders(), restarted.ledger_state()) == before
            matcher.match(market, epoch=epoch)
            assert (restarted.events(), restarted.orders(), restarted.ledger_state()) == before

    def test_scenario_charging_above_the_journal_worst_case_is_refused(
        self, tmp_path: Path
    ) -> None:
        """A dedicated journal refuses a matching scenario above its configured fee rate."""
        scenario = replace(self._scenario(), fee_rate=Decimal("0.006"))
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("over-rate-owner")
            with pytest.raises(ValueError, match="exceeds the configured worst case"):
                journal.match_scenario_market(
                    epoch=epoch,
                    market=self._market("over-rate", at=self.decision_at + timedelta(seconds=1)),
                    scenario=scenario,
                )

    def test_admission_reserves_for_per_fill_rounding(self, tmp_path: Path) -> None:
        """A reserve must cover each fill rounding up, so separate fills never outrun it."""
        scenario = self._scenario(adverse="0.01")
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("rounding-owner")
            # Three units at 1.20 cost 0.018, plus one cent per lot for rounding: 0.048.
            refused = journal.commit_step(
                epoch=epoch,
                step_id="under-reserved",
                checkpoint=b"under-reserved",
                decision=OrderDecision(
                    identity="decision-under-reserved",
                    at=self.decision_at,
                    intent=OrderIntent(
                        side="buy",
                        quantity=self._quantity("3"),
                        limit=self._price("1.20"),
                        time_in_force="gtc",
                    ),
                ),
                reference=self._price("1.00"),
                maximum_fee=self._money("0.04"),
            )
            assert (refused.status, refused.reason) == (
                "rejected",
                "fee_reserve_below_worst_case",
            )
            order = self._admit(
                journal,
                epoch,
                step_id="rounding",
                quantity="3",
                limit="1.20",
                maximum_fee="0.05",
            )
            matcher = PaperMatcher(
                journal, fee_rate=scenario.fee_rate, lot=self._quantity("1"), scenario=scenario
            )
            # Each one-unit touch fills near 0.006 in fees, which rounds up to 0.01.
            for index, ask in enumerate(("1.19", "1.18", "1.19"), start=1):
                matcher.match(
                    self._market(
                        f"rounding-{index}",
                        at=self.decision_at + timedelta(seconds=index),
                        ask=ask,
                        ask_quantity="1",
                    ),
                    epoch=epoch,
                )
            current = journal.order(order.identity)
            assert current is not None
            assert (current.status, current.filled.value, current.paid_fee.value) == (
                "filled",
                Decimal("3"),
                Decimal("0.03"),
            )
            fees = tuple(fill.fee.value for fill in journal.ledger_state().fills)
            assert fees == (Decimal("0.01"), Decimal("0.01"), Decimal("0.01"))

    def test_fee_cap_prevents_fill_and_keeps_order_reserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A defective model's fee above an admitted reserve still cannot post."""
        monkeypatch.setattr("execution.paper.PaperFeeSchedule", _OverchargingFeeSchedule)
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("fee-cap-owner")
            # The floor is 0.011 at the limit plus two cents; the model charges 0.10.
            order = self._admit(
                journal,
                epoch,
                step_id="fee-cap",
                quantity="2",
                limit="1.10",
                maximum_fee="0.04",
            )
            matcher = self._matcher(journal)
            with pytest.raises(ValueError, match="fill exceeds order economics or limit"):
                matcher.match(
                    self._market("fee-cap", at=self.decision_at + timedelta(seconds=1)),
                    epoch=epoch,
                )
            assert journal.order(order.identity) == order
            assert journal.ledger_state().fills == ()
            assert journal.reservations().cash.value == Decimal("2.24")

    def test_crossing_post_only_rejects_without_economics(self, tmp_path: Path) -> None:
        """A post-only buy crossing the first available ask never posts a fill."""
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("crossing-owner")
            order = self._admit(
                journal,
                epoch,
                step_id="crossing",
                quantity="2",
                limit="1.10",
                time_in_force="post-only",
            )
            self._matcher(journal).match(
                self._market("crossing", at=self.decision_at + timedelta(seconds=1)),
                epoch=epoch,
            )
            current = journal.order(order.identity)
            assert current is not None and current.status == "rejected"
            assert tuple(item.event.kind for item in journal.events()) == (
                "request_ack",
                "rejected",
            )
            assert journal.ledger_state().fills == ()
            assert journal.reservations().cash.value == Decimal("0")

    def test_resting_post_only_fills_on_later_crossed_quote(self, tmp_path: Path) -> None:
        """An initially nonmarketable bid rests until a later ask crosses its limit."""
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("resting-owner")
            order = self._admit(
                journal,
                epoch,
                step_id="resting",
                quantity="2",
                limit="0.95",
                time_in_force="post-only",
            )
            matcher = self._matcher(journal)
            matcher.match(
                self._market("noncrossing", at=self.decision_at + timedelta(seconds=1)),
                epoch=epoch,
            )
            current = journal.order(order.identity)
            assert current is not None and current.status == "accepted"
            assert journal.ledger_state().fills == ()
            matcher.match(
                self._market(
                    "crossed",
                    at=self.decision_at + timedelta(seconds=2),
                    ask="0.94",
                    ask_quantity="2",
                ),
                epoch=epoch,
            )
            current = journal.order(order.identity)
            assert current is not None and current.status == "filled"
            (fill,) = journal.ledger_state().fills
            assert fill.quantity.value == Decimal("2")
            assert fill.effective.value == Decimal("0.94")
            assert fill.fee.value == Decimal("0.01")
            assert Ledger(journal.ledger_state()).balance.cash.value == Decimal("998.11")

    def test_scenario_reuses_touch_debt_after_restart_and_attributes_adverse_cost(
        self, tmp_path: Path
    ) -> None:
        """An unchanged public touch cannot refill twice; new visible size adds only its delta."""
        scenario = self._scenario()
        first = self._market(
            "first-depth", at=self.decision_at + timedelta(seconds=1), ask_quantity="2"
        )
        unchanged = self._market(
            "same-depth", at=self.decision_at + timedelta(seconds=2), ask_quantity="2"
        )
        increased = self._market(
            "more-depth", at=self.decision_at + timedelta(seconds=3), ask_quantity="3"
        )
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("initial-owner")
            order = self._admit(journal, epoch, step_id="debt", quantity="3", limit="1.10")
            matcher = PaperMatcher(
                journal, fee_rate=scenario.fee_rate, lot=self._quantity("1"), scenario=scenario
            )
            matcher.match(first, epoch=epoch)
            state = journal.order(order.identity)
            assert state is not None and state.filled.value == Decimal("2")
            first_economics = journal.ledger_state()
        with self._journal(tmp_path) as restarted:
            epoch = restarted.claim("second-owner")
            matcher = PaperMatcher(
                restarted,
                fee_rate=scenario.fee_rate,
                lot=self._quantity("1"),
                scenario=scenario,
            )
            matcher.match(first, epoch=epoch)
            with pytest.raises(ValueError, match="market availability regressed"):
                matcher.match(
                    self._market("older-quote", at=self.decision_at + timedelta(milliseconds=500)),
                    epoch=epoch,
                )
            matcher.match(unchanged, epoch=epoch)
            assert restarted.ledger_state() == first_economics
            matcher.match(increased, epoch=epoch)
            matcher.match(increased, epoch=epoch)
            completed_economics = restarted.ledger_state()
            original = restarted.match_scenario_market(epoch=epoch, market=first, scenario=scenario)
            assert tuple(event.kind for event in original) == ("request_ack", "accepted", "fill")
            assert restarted.ledger_state() == completed_economics
            state = restarted.order(order.identity)
            assert state is not None and state.status == "filled"
            fills = restarted.ledger_state().fills
            assert tuple(fill.quantity.value for fill in fills) == (Decimal("2"), Decimal("1"))
            assert tuple(fill.reference.value for fill in fills) == (
                Decimal("1.00"),
                Decimal("1.00"),
            )
            assert tuple(fill.effective.value for fill in fills) == (
                Decimal("1.02"),
                Decimal("1.02"),
            )
            assert tuple(fill.fee.value for fill in fills) == (
                Decimal("0.01"),
                Decimal("0.01"),
            )
            expected = SpotCosts(
                adverse=scenario.adverse, fee_rate=scenario.fee_rate, rounding="half_even"
            ).fill(
                fills[0].identity,
                decision_at=order.decision_at,
                filled_at=first.at,
                quantity=self._quantity("2"),
                reference=first.ask,
            )
            assert fills[0] == expected
            balance = Ledger(restarted.ledger_state()).balance
            assert balance.cash.value == Decimal("996.92")
            assert balance.slippage.value == Decimal("0.06")
            with pytest.raises(ValueError, match="scenario differs from retained journal"):
                PaperMatcher(
                    restarted,
                    fee_rate=scenario.fee_rate,
                    lot=self._quantity("1"),
                    scenario=self._scenario(adverse="0.03"),
                ).match(first, epoch=epoch)
            assert restarted.ledger_state().fills == fills

    def test_entry_and_cancel_delay_allow_a_partial_fill_before_confirmed_cancel(
        self, tmp_path: Path
    ) -> None:
        """A pending cancellation retains risk until its modeled later quote."""
        scenario = self._scenario(entry_delay_us=2_000_000, cancel_delay_us=3_000_000)
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("delayed-owner")
            order = self._admit(journal, epoch, step_id="delay", quantity="2", limit="1.10")
            matcher = PaperMatcher(
                journal, fee_rate=scenario.fee_rate, lot=self._quantity("1"), scenario=scenario
            )
            matcher.match(
                self._market("early", at=self.decision_at + timedelta(seconds=1)), epoch=epoch
            )
            assert journal.order(order.identity) == order
            matcher.match(
                self._market("arrival", at=self.decision_at + timedelta(seconds=2), ask="1.20"),
                epoch=epoch,
            )
            journal.request_cancel(
                epoch=epoch,
                order_id=order.identity,
                event_id="cancel-request",
                at=self.decision_at + timedelta(seconds=2, milliseconds=500),
            )
            matcher.match(
                self._market(
                    "cancel-in-flight",
                    at=self.decision_at + timedelta(seconds=3),
                    ask_quantity="1",
                ),
                epoch=epoch,
            )
            pending = journal.order(order.identity)
            assert pending is not None and pending.status == "cancel_requested"
            assert pending.filled.value == Decimal("1")
            assert journal.reservations().cash.value > 0
            matcher.match(
                self._market(
                    "cancel-due", at=self.decision_at + timedelta(seconds=6), ask_quantity="1"
                ),
                epoch=epoch,
            )
            final = journal.order(order.identity)
            assert final is not None and final.status == "cancelled"
            assert len(journal.ledger_state().fills) == 1
            assert journal.reservations().cash.value == 0

    def test_scenario_never_fills_on_its_own_decision_quote(self, tmp_path: Path) -> None:
        """Zero modeled entry delay still requires a subsequent public observation."""
        scenario = self._scenario()
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("same-time-owner")
            order = self._admit(journal, epoch, step_id="same-time", quantity="1", limit="1.10")
            matcher = PaperMatcher(
                journal, fee_rate=scenario.fee_rate, lot=self._quantity("1"), scenario=scenario
            )
            matcher.match(self._market("decision-quote", at=self.decision_at), epoch=epoch)
            assert journal.order(order.identity) == order
            assert journal.ledger_state().fills == ()
            matcher.match(
                self._market("later-quote", at=self.decision_at + timedelta(microseconds=1)),
                epoch=epoch,
            )
            current = journal.order(order.identity)
            assert current is not None and current.status == "filled"

    def test_smaller_public_touch_caps_fill_even_without_prior_consumption(
        self, tmp_path: Path
    ) -> None:
        """A later smaller visible quote cannot reuse a larger earlier display."""
        scenario = self._scenario()
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("shrink-owner")
            matcher = PaperMatcher(
                journal, fee_rate=scenario.fee_rate, lot=self._quantity("1"), scenario=scenario
            )
            matcher.match(
                self._market(
                    "initial-large", at=self.decision_at + timedelta(seconds=1), ask_quantity="3"
                ),
                epoch=epoch,
            )
            order = self._admit(
                journal,
                epoch,
                step_id="after-large",
                quantity="3",
                limit="1.10",
                at=self.decision_at + timedelta(seconds=1, milliseconds=500),
            )
            matcher.match(
                self._market(
                    "later-small", at=self.decision_at + timedelta(seconds=2), ask_quantity="1"
                ),
                epoch=epoch,
            )
            current = journal.order(order.identity)
            assert current is not None and current.status == "partial"
            assert current.filled.value == Decimal("1")

    def test_cancel_confirmed_before_entry_delay_releases_unfilled_reservation(
        self, tmp_path: Path
    ) -> None:
        """A cancelled in-flight intent cannot become a later modeled fill."""
        scenario = self._scenario(entry_delay_us=5_000_000, cancel_delay_us=1_000_000)
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("pre-arrival-cancel-owner")
            order = self._admit(journal, epoch, step_id="pre-arrival", quantity="1", limit="1.10")
            journal.request_cancel(
                epoch=epoch,
                order_id=order.identity,
                event_id="pre-arrival-cancel",
                at=self.decision_at + timedelta(seconds=1),
            )
            PaperMatcher(
                journal, fee_rate=scenario.fee_rate, lot=self._quantity("1"), scenario=scenario
            ).match(
                self._market("cancel-confirmation", at=self.decision_at + timedelta(seconds=2)),
                epoch=epoch,
            )
            current = journal.order(order.identity)
            assert current is not None and current.status == "cancelled"
            assert journal.reservations().cash.value == 0
            assert journal.ledger_state().fills == ()

    def test_scenario_fee_shortfall_rolls_back_entire_market(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A defective model's late fee-cap failure leaves no order partially committed."""
        monkeypatch.setattr("execution.paper.PaperFeeSchedule", _OverchargingFeeSchedule)
        scenario = self._scenario()
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("atomic-market-owner")
            first = self._admit(journal, epoch, step_id="funded", quantity="2", limit="1.10")
            second = self._admit(
                journal,
                epoch,
                step_id="underfunded-fee",
                quantity="1",
                limit="1.10",
                maximum_fee="0.03",
            )
            with pytest.raises(ValueError, match="fill exceeds order economics or limit"):
                PaperMatcher(
                    journal,
                    fee_rate=scenario.fee_rate,
                    lot=self._quantity("1"),
                    scenario=scenario,
                ).match(
                    self._market("fee-shortfall", at=self.decision_at + timedelta(seconds=1)),
                    epoch=epoch,
                )
            assert journal.order(first.identity) == first
            assert journal.order(second.identity) == second
            assert journal.markets() == ()
            assert journal.events() == ()
            assert journal.ledger_state().fills == ()

    def test_unknown_order_stays_reserved_and_unmatched(self, tmp_path: Path) -> None:
        """A public touch cannot resolve or release an unknown order outcome."""
        scenario = self._scenario()
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("unknown-owner")
            order = self._admit(journal, epoch, step_id="uncertain", quantity="1", limit="1.10")
            journal.apply_event(
                epoch=epoch,
                event=OrderEvent(
                    identity="uncertain-send",
                    order_id=order.identity,
                    at=self.decision_at + timedelta(microseconds=1),
                    kind="unknown",
                ),
            )
            reserved = journal.reservations()
            PaperMatcher(
                journal, fee_rate=scenario.fee_rate, lot=self._quantity("1"), scenario=scenario
            ).match(
                self._market("unknown-touch", at=self.decision_at + timedelta(seconds=1)),
                epoch=epoch,
            )
            current = journal.order(order.identity)
            assert current is not None and current.status == "unknown"
            assert journal.reservations() == reserved
            assert journal.ledger_state().fills == ()

    def test_unfinished_markets_are_claims_without_their_market_step(self, tmp_path: Path) -> None:
        """Restart recovers only claims whose market step never committed, in claim order."""
        codec = DomainCodec()
        markets = tuple(
            self._market(f"claim-{index}", at=self.decision_at + timedelta(seconds=index))
            for index in range(1, 6)
        )
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("restart-owner")
            for market in markets:
                payload = codec.encode_json(market)
                journal.claim_market(epoch=epoch, identity=market.identity, payload=payload)
                if market.identity in ("claim-2", "claim-5"):
                    journal.commit_step(
                        epoch=epoch,
                        step_id=f"market:{market.identity}",
                        checkpoint=b"checkpoint",
                        decision=None,
                        reference=None,
                        maximum_fee=self._money("0"),
                        input_bytes=payload,
                    )
            # An unrelated step whose name only contains a claim identity finishes nothing.
            journal.commit_step(
                epoch=epoch,
                step_id="timer:claim-3",
                checkpoint=b"checkpoint",
                decision=None,
                reference=None,
                maximum_fee=self._money("0"),
            )
            unfinished = journal.unfinished_markets()
            assert unfinished == tuple(
                claim for claim in journal.markets() if journal.step(f"market:{claim[0]}") is None
            )
            assert tuple(identity for identity, _ in unfinished) == (
                "claim-1",
                "claim-3",
                "claim-4",
            )
            journal.release(epoch)
        with closing(sqlite3.connect(tmp_path / "paper.sqlite3")) as connection:
            connection.execute(
                "UPDATE steps SET payload = ? WHERE step_id = 'market:claim-5'", (b"{}",)
            )
            connection.commit()
        with self._journal(tmp_path) as journal, pytest.raises(ValueError):
            journal.unfinished_markets()

    def test_shadow_claim_is_not_mistaken_for_completed_scenario_match(
        self, tmp_path: Path
    ) -> None:
        """A preclaimed shadow quote has no atomic scenario result to replay."""
        scenario = self._scenario()
        market = self._market("shadow-claim", at=self.decision_at + timedelta(seconds=1))
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("shadow-claim-owner")
            journal.claim_market(
                epoch=epoch, identity=market.identity, payload=DomainCodec().encode_json(market)
            )
            with pytest.raises(ValueError, match="shadow market history cannot adopt"):
                journal.match_scenario_market(epoch=epoch, market=market, scenario=scenario)
            assert journal.markets() == ((market.identity, DomainCodec().encode_json(market)),)

    def test_scenario_rejects_off_grid_public_touch_before_any_effect(self, tmp_path: Path) -> None:
        """An invalid native quote cannot acquire liquidity or advance the ledger."""
        scenario = self._scenario()
        market = self._market("off-grid", at=self.decision_at + timedelta(seconds=1), ask="1.005")
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("grid-owner")
            order = self._admit(journal, epoch, step_id="grid", quantity="1", limit="1.10")
            with pytest.raises(ValueError, match="paper market, account or scenario differs"):
                PaperMatcher(
                    journal,
                    fee_rate=scenario.fee_rate,
                    lot=self._quantity("1"),
                    scenario=scenario,
                ).match(market, epoch=epoch)
            assert journal.order(order.identity) == order
            assert journal.markets() == ()
            assert journal.ledger_state().fills == ()

    def test_paper_configuration_requires_an_execution_scenario(self) -> None:
        """A configuration saved without its authored scenario is refused."""
        with pytest.raises(ValueError, match="execution"):
            DomainCodec().decode_json(
                DomainCodec().encode_json(
                    {
                        "account": "paper-account",
                        "mode": "paper",
                        "initial_cash": self._money("1000"),
                        "maximum": self._quantity("10"),
                        "lot": self._quantity("1"),
                        "tick": self._price("0.01"),
                        "maximum_fee": self._money("0.50"),
                        "fee_rate": Decimal("0.005"),
                        "market_max_age_us": 5_000_000,
                    }
                ),
                PaperConfiguration,
            )
