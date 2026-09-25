"""Verify finite paper quote matching, exact fees, and replayed event identities."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

# third party library imports
import pytest

# project library imports
from accounting import Ledger, LedgerState
from execution import OrderDecision, OrderState, PaperMarket, PaperMatcher, PaperOrderJournal
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent


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
    ) -> OrderState:
        """Admit one cash-backed buy order with an explicit fee reserve."""
        result = journal.commit_step(
            epoch=epoch,
            step_id=step_id,
            checkpoint=step_id.encode(),
            decision=OrderDecision(
                identity=f"decision-{step_id}",
                at=cls.decision_at,
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

    def test_two_orders_share_finite_ask_and_replay_has_no_extra_fill(self, tmp_path: Path) -> None:
        """Three displayed units fill two then one, with half-even fees and one reserve."""
        market = self._market("shared-ask", at=self.decision_at + timedelta(seconds=1))
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("first-owner")
            first = self._admit(journal, epoch, step_id="first", quantity="2", limit="1.10")
            second = self._admit(journal, epoch, step_id="second", quantity="2", limit="1.10")
            matcher = PaperMatcher(journal, fee_rate=Decimal("0.005"), lot=self._quantity("1"))
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
            PaperMatcher(restarted, fee_rate=Decimal("0.005"), lot=self._quantity("1")).match(
                market, epoch=epoch
            )
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
            PaperMatcher(journal, fee_rate=Decimal("0.005"), lot=self._quantity("1")).match(
                market, epoch=epoch
            )
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
            PaperMatcher(journal, fee_rate=Decimal("0.005"), lot=self._quantity("1")).match(
                market, epoch=epoch
            )
            current = journal.order(order.identity)
            assert current is not None and current.filled.value == Decimal("1")
            assert journal.step("market:unfinished-quote") is None
            assert journal.markets() == ((market.identity, DomainCodec().encode_json(market)),)
            before = (journal.events(), journal.orders(), journal.ledger_state())
        with self._journal(tmp_path) as restarted:
            epoch = restarted.claim("restarted-owner")
            matcher = PaperMatcher(restarted, fee_rate=Decimal("0.005"), lot=self._quantity("1"))
            with pytest.raises(ValueError, match="market identity was reused"):
                matcher.match(changed, epoch=epoch)
            assert (restarted.events(), restarted.orders(), restarted.ledger_state()) == before
            matcher.match(market, epoch=epoch)
            assert (restarted.events(), restarted.orders(), restarted.ledger_state()) == before

    def test_fee_cap_prevents_fill_and_keeps_order_reserved(self, tmp_path: Path) -> None:
        """A one-cent calculated fee cannot post against a zero maximum fee."""
        with self._journal(tmp_path) as journal:
            epoch = journal.claim("fee-cap-owner")
            order = self._admit(
                journal,
                epoch,
                step_id="fee-cap",
                quantity="2",
                limit="1.10",
                maximum_fee="0.00",
            )
            matcher = PaperMatcher(journal, fee_rate=Decimal("0.005"), lot=self._quantity("1"))
            with pytest.raises(ValueError, match="fill exceeds order economics or limit"):
                matcher.match(
                    self._market("fee-cap", at=self.decision_at + timedelta(seconds=1)),
                    epoch=epoch,
                )
            current = journal.order(order.identity)
            assert current is not None and current.status == "accepted"
            assert journal.ledger_state().fills == ()
            assert journal.reservations().cash.value == Decimal("2.20")

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
            PaperMatcher(journal, fee_rate=Decimal("0.005"), lot=self._quantity("1")).match(
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
            matcher = PaperMatcher(journal, fee_rate=Decimal("0.005"), lot=self._quantity("1"))
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
