"""Exercise durable paper order identity, fences, reservations and fill recovery."""

from __future__ import annotations

# standard library imports
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from io import BufferedReader
from pathlib import Path
from typing import cast

# third party library imports
import pytest

# project library imports
from accounting import Fill, Ledger, LedgerState
from execution import (
    MarketTouch,
    OrderDecision,
    OrderEvent,
    PaperOrderJournal,
    StepCommit,
    StepRecord,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import SpotLimits
from serialization import DomainCodec
from strategies import ExposureIntent, OrderIntent, QuoteIntent, TargetIntent


class TestPaperOrderJournal:
    """Use one exact cash-funded account and independently identified events."""

    currency = Currency(code="TEST", minor_unit=Decimal("0.01"))
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    start = datetime(2024, 6, 1, tzinfo=UTC)

    @classmethod
    def _money(cls, value: str) -> Money:
        """Construct a quote-currency account amount."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Construct an exact base-unit quantity."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Construct an exact spot limit."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _limits(cls) -> SpotLimits:
        """Use explicit fixed paper grids with no venue-rule qualification."""
        return SpotLimits(
            maximum=cls._quantity("10"),
            lot=cls._quantity("1"),
            tick=cls._price("0.01"),
            product="spot",
        )

    @classmethod
    def _state(cls, *, with_holding: bool = False) -> LedgerState:
        """Seed an owned position through an identified economic fill when requested."""
        initial = cls._money("1000")
        if not with_holding:
            return LedgerState(initial_cash=initial, dimension=cls.dimension)
        seed = Fill(
            identity="seed-holding",
            decision_at=cls.start - timedelta(seconds=2),
            filled_at=cls.start - timedelta(seconds=1),
            quantity=cls._quantity("2"),
            reference=cls._price("100"),
            effective=cls._price("100"),
            fee=cls._money("0"),
        )
        return LedgerState(initial_cash=initial, dimension=cls.dimension, fills=(seed,))

    @classmethod
    def _journal(cls, path: Path, *, with_holding: bool = False) -> PaperOrderJournal:
        """Bind the same exact account across simulated process restarts."""
        return PaperOrderJournal(
            path,
            account="paper-account",
            instance="signal-a",
            binding_identity="candidate-and-config",
            mode="paper",
            limits=cls._limits(),
            ledger_state=cls._state(with_holding=with_holding),
            fee_rate=Decimal(0),
        )

    @classmethod
    def _order(cls, *, side: str, quantity: str, limit: str) -> OrderIntent:
        """Build a supported explicit limit order for a test decision."""
        if side not in ("buy", "sell"):
            raise ValueError("unsupported test side")
        return OrderIntent(
            side="buy" if side == "buy" else "sell",
            quantity=cls._quantity(quantity),
            limit=cls._price(limit),
            time_in_force="gtc",
        )

    def test_journal_with_another_layout_is_refused(self, tmp_path: Path) -> None:
        """An earlier layout, such as fills kept inside the state row, is never reopened."""
        path = tmp_path / "paper.sqlite3"
        self._journal(path).close()
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("ALTER TABLE state ADD COLUMN ledger BLOB")
            connection.commit()
        with pytest.raises(ValueError, match="unsupported paper journal schema"):
            self._journal(path)

    def test_open_order_reads_refuse_a_disagreeing_terminal_flag(self, tmp_path: Path) -> None:
        """Reservations read only open orders and refuse a terminal one flagged open."""
        path = tmp_path / "paper.sqlite3"
        with self._journal(path) as journal:
            epoch = journal.claim("flag-owner")
            order = journal.commit_step(
                epoch=epoch,
                step_id="flag",
                checkpoint=b"flag",
                decision=OrderDecision(
                    identity="flag-buy",
                    at=self.start,
                    intent=self._order(side="buy", quantity="1", limit="100"),
                ),
                touch=None,
                maximum_fee=self._money("1"),
            ).orders[0]
            assert journal.reservations().cash.value == Decimal("101")
            journal.apply_event(
                epoch=epoch,
                event=OrderEvent(
                    identity="flag-rejected",
                    order_id=order.identity,
                    at=self.start + timedelta(seconds=1),
                    kind="rejected",
                ),
            )
            assert journal.reservations().cash.value == 0
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("UPDATE orders SET terminal = 0")
                connection.commit()
            with pytest.raises(ValueError, match="differs from its terminal flag"):
                journal.reservations()

    def test_ledger_rows_rebuild_the_same_ledger_after_reopening(self, tmp_path: Path) -> None:
        """Fills kept as rows replay to the ledger the writer holds, in any process."""
        path = tmp_path / "paper.sqlite3"
        with self._journal(path, with_holding=True) as journal:
            epoch = journal.claim("rows-owner")
            decision = OrderDecision(
                identity="rows-buy",
                at=self.start,
                intent=self._order(side="buy", quantity="2", limit="101"),
            )
            order = journal.commit_step(
                epoch=epoch,
                step_id="rows",
                checkpoint=b"rows",
                decision=decision,
                touch=None,
                maximum_fee=self._money("1"),
            ).orders[0]
            for kind in ("request_ack", "accepted"):
                journal.apply_event(
                    epoch=epoch,
                    event=OrderEvent(
                        identity=f"rows-{kind}",
                        order_id=order.identity,
                        at=self.start + timedelta(microseconds=1),
                        kind=kind,
                    ),
                )
            for index in range(2):
                journal.apply_event(
                    epoch=epoch,
                    event=OrderEvent(
                        identity=f"rows-fill-{index}",
                        order_id=order.identity,
                        at=self.start + timedelta(seconds=index + 1),
                        kind="fill",
                        fill=Fill(
                            identity=f"rows-fill-{index}",
                            decision_at=self.start,
                            filled_at=self.start + timedelta(seconds=index + 1),
                            quantity=self._quantity("1"),
                            reference=self._price("100"),
                            effective=self._price("101"),
                            fee=self._money("0"),
                        ),
                    ),
                )
            written = journal.ledger_state()
        reopened = self._journal(path, with_holding=True)
        assert reopened.ledger_state() == written
        assert len(written.fills) == 3
        assert reopened.ledger_balance() == Ledger(written).balance

    def test_quote_is_atomic_and_restarts_with_both_reservations(self, tmp_path: Path) -> None:
        """Two quote legs reserve cash and existing inventory in one checkpoint commit."""
        path = tmp_path / "orders.sqlite3"
        first = self._journal(path, with_holding=True)
        epoch = first.claim("writer-one")
        decision = OrderDecision(
            identity="quote-one",
            at=self.start,
            intent=QuoteIntent(
                bid=self._order(side="buy", quantity="1", limit="99"),
                ask=self._order(side="sell", quantity="1", limit="101"),
            ),
        )
        result = first.commit_step(
            epoch=epoch,
            step_id="tick-one",
            checkpoint=b"checkpoint-one",
            decision=decision,
            touch=None,
            maximum_fee=self._money("1"),
            input_bytes=b"market-one",
            result_bytes=b"candidate-one",
        )
        assert result.status == "committed"
        assert len(result.orders) == 2
        assert first.qualification == "fixture"
        assert first.reservations().cash.value == Decimal("101")
        assert first.reservations().sell_quantity.value == Decimal("1")
        assert first.checkpoint() == b"checkpoint-one"
        assert first.has_step("tick-one", b"market-one")
        with pytest.raises(ValueError, match="different input"):
            first.has_step("tick-one", b"mutated-market")
        with pytest.raises(ValueError, match="different state or input"):
            first.commit_step(
                epoch=epoch,
                step_id="tick-one",
                checkpoint=b"changed-checkpoint",
                decision=decision,
                touch=None,
                maximum_fee=self._money("1"),
                input_bytes=b"market-one",
                result_bytes=b"candidate-one",
            )
        competing = self._journal(path, with_holding=True)
        with pytest.raises(BlockingIOError):
            competing.claim("writer-two")
        first.release(epoch)
        holder: subprocess.Popen[bytes] = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import fcntl,sys,time\n"
                "with open(sys.argv[1], 'a+b') as lock:\n"
                " fcntl.flock(lock.fileno(), fcntl.LOCK_EX)\n"
                " print('held', flush=True)\n"
                " time.sleep(30)\n",
                str(path.with_name(path.name + ".lock")),
            ],
            stdout=subprocess.PIPE,
            text=False,
        )
        stream = cast(object, holder.stdout)
        if not isinstance(stream, BufferedReader):
            raise ValueError("lock holder pipe is unavailable")
        try:
            assert stream.readline() == b"held\n"
            with pytest.raises(BlockingIOError):
                competing.claim("writer-two")
        finally:
            holder.kill()
            holder.wait(timeout=5)
            stream.close()
        second_epoch = competing.claim("writer-two")
        assert second_epoch > epoch
        assert competing.orders() == result.orders
        with pytest.raises(ValueError, match="fenced owner"):
            first.commit_step(
                epoch=epoch,
                step_id="stale",
                checkpoint=b"stale",
                decision=None,
                touch=None,
                maximum_fee=self._money("0"),
            )
        competing.release(second_epoch)
        rejected_journal = self._journal(tmp_path / "unfunded-quote.sqlite3")
        rejected_epoch = rejected_journal.claim("writer")
        rejected = rejected_journal.commit_step(
            epoch=rejected_epoch,
            step_id="unfunded-quote",
            checkpoint=b"committed-rejection",
            decision=decision,
            touch=None,
            maximum_fee=self._money("1"),
        )
        assert rejected.status == "rejected"
        assert rejected.reason == "insufficient_holding"
        assert rejected_journal.orders() == ()
        assert rejected_journal.checkpoint() == b"committed-rejection"
        rejected_journal.release(rejected_epoch)

    def test_acknowledgements_fills_and_unknown_reconcile_release_only_confirmed_amounts(
        self, tmp_path: Path
    ) -> None:
        """A cancel acknowledgement keeps exposure and a duplicate fill posts once."""
        journal = self._journal(tmp_path / "events.sqlite3")
        epoch = journal.claim("writer")
        result = journal.commit_step(
            epoch=epoch,
            step_id="tick-one",
            checkpoint=b"cp-one",
            decision=OrderDecision(
                identity="buy-two",
                at=self.start,
                intent=self._order(side="buy", quantity="2", limit="100"),
            ),
            touch=None,
            maximum_fee=self._money("1"),
        )
        order = result.orders[0]
        pending_target = journal.commit_step(
            epoch=epoch,
            step_id="target-while-open",
            checkpoint=b"target-checkpoint",
            decision=OrderDecision(
                identity="target-while-open",
                at=self.start + timedelta(microseconds=1),
                intent=TargetIntent(quantity=self._quantity("3")),
            ),
            touch=MarketTouch(bid=self._price("99"), ask=self._price("100")),
            maximum_fee=self._money("1"),
        )
        assert (pending_target.status, pending_target.reason) == ("rejected", "pending_target")
        later = self.start + timedelta(seconds=1)
        request = OrderEvent(
            identity="request-ack", order_id=order.identity, at=later, kind="request_ack"
        )
        assert journal.apply_event(epoch=epoch, event=request).request_acknowledged
        observed = journal.order(order.identity)
        assert observed is not None and not observed.accepted
        journal.apply_event(
            epoch=epoch,
            event=OrderEvent(
                identity="accepted", order_id=order.identity, at=later, kind="accepted"
            ),
        )
        fill = Fill(
            identity="partial-fill",
            decision_at=self.start,
            filled_at=later,
            quantity=self._quantity("1"),
            reference=self._price("100"),
            effective=self._price("100"),
            fee=self._money("0.10"),
        )
        partial = OrderEvent(
            identity="partial-event", order_id=order.identity, at=later, kind="fill", fill=fill
        )
        assert journal.apply_event(epoch=epoch, event=partial).remaining.value == 1
        assert journal.apply_event(epoch=epoch, event=partial).remaining.value == 1
        assert journal.ledger_state().fills == (fill,)
        assert journal.reservations().cash.value == Decimal("100.90")
        journal.request_cancel(
            epoch=epoch,
            order_id=order.identity,
            event_id="cancel-request",
            at=later + timedelta(seconds=1),
        )
        journal.apply_event(
            epoch=epoch,
            event=OrderEvent(
                identity="cancel-ack",
                order_id=order.identity,
                at=later + timedelta(seconds=2),
                kind="cancel_ack",
            ),
        )
        assert journal.reservations().cash.value == Decimal("100.90")
        journal.apply_event(
            epoch=epoch,
            event=OrderEvent(
                identity="unknown",
                order_id=order.identity,
                at=later + timedelta(seconds=3),
                kind="unknown",
            ),
        )
        unresolved = journal.order(order.identity)
        assert unresolved is not None and unresolved.status == "unknown"
        journal.release(epoch)
        restored = self._journal(tmp_path / "events.sqlite3")
        new_epoch = restored.claim("restarted")
        assert restored.reservations().cash.value == Decimal("100.90")
        unknown_admission = restored.commit_step(
            epoch=new_epoch,
            step_id="unknown-new-risk",
            checkpoint=b"unknown-candidate-state",
            decision=OrderDecision(
                identity="unknown-new-risk",
                at=later + timedelta(seconds=4),
                intent=self._order(side="buy", quantity="1", limit="99"),
            ),
            touch=None,
            maximum_fee=self._money("1"),
        )
        assert (unknown_admission.status, unknown_admission.reason) == (
            "rejected",
            "order_outcome_unknown",
        )
        with pytest.raises(ValueError, match="confirmed terminal"):
            restored.replace(
                epoch=new_epoch,
                old_order_id=order.identity,
                step_id="replacement",
                checkpoint=b"cp-replacement",
                decision=OrderDecision(
                    identity="replace-buy",
                    at=later,
                    intent=self._order(side="buy", quantity="1", limit="99"),
                ),
                touch=None,
                maximum_fee=self._money("1"),
            )
        restored.apply_event(
            epoch=new_epoch,
            event=OrderEvent(
                identity="resolved-cancel",
                order_id=order.identity,
                at=later + timedelta(seconds=4),
                kind="reconcile_cancelled",
            ),
        )
        assert restored.reservations().cash.value == 0
        assert restored.ledger_state().fills == (fill,)
        replacement_decision = OrderDecision(
            identity="replace-buy",
            at=later + timedelta(seconds=5),
            intent=self._order(side="buy", quantity="1", limit="99"),
        )
        replacement = restored.replace(
            epoch=new_epoch,
            old_order_id=order.identity,
            step_id="replacement",
            checkpoint=b"cp-replacement",
            decision=replacement_decision,
            touch=None,
            maximum_fee=self._money("1"),
        )
        assert replacement.status == "committed"
        assert replacement.orders[0].replace_of == order.identity
        with pytest.raises(ValueError, match="another step"):
            restored.commit_step(
                epoch=new_epoch,
                step_id="duplicate-decision",
                checkpoint=b"duplicate",
                decision=replacement_decision,
                touch=None,
                maximum_fee=self._money("1"),
            )
        history = restored.events()
        assert tuple(item.sequence for item in history) == tuple(range(1, len(history) + 1))
        assert history[0].balance.cash.value == Decimal("1000")
        assert history[2].balance.cash.value == Decimal("899.90")
        assert history[-1].balance.cash.value == Decimal("899.90")
        late_fill = Fill(
            identity="late-after-confirmed-cancel",
            decision_at=self.start,
            filled_at=later + timedelta(seconds=1),
            quantity=self._quantity("1"),
            reference=self._price("100"),
            effective=self._price("100"),
            fee=self._money("0.10"),
        )
        with pytest.raises(ValueError, match="terminal order"):
            restored.apply_event(
                epoch=new_epoch,
                event=OrderEvent(
                    identity="late-after-cancel",
                    order_id=order.identity,
                    at=later + timedelta(seconds=6),
                    kind="fill",
                    fill=late_fill,
                ),
            )
        assert restored.ledger_state().fills == (fill,)
        assert restored.blocked_reason() == "late_terminal_fill"
        assert not restored.reconcile_account(
            epoch=new_epoch,
            expected_cash=Ledger(restored.ledger_state()).balance.cash,
            expected_holding=Ledger(restored.ledger_state()).balance.holding,
            open_order_ids=(replacement.orders[0].identity,),
        )
        assert restored.blocked_reason() == "late_terminal_fill"
        restored.release(new_epoch)

    def test_fill_after_cancel_ack_and_duplicate_transport_do_not_double_post(
        self, tmp_path: Path
    ) -> None:
        """A cancel/fill race consumes the order once and a second receipt is harmless."""
        journal = self._journal(tmp_path / "cancel-fill.sqlite3")
        epoch = journal.claim("writer")
        admitted = journal.commit_step(
            epoch=epoch,
            step_id="buy",
            checkpoint=b"buy-checkpoint",
            decision=OrderDecision(
                identity="buy",
                at=self.start,
                intent=self._order(side="buy", quantity="1", limit="100"),
            ),
            touch=None,
            maximum_fee=self._money("1"),
        )
        order = admitted.orders[0]
        later = self.start + timedelta(seconds=1)
        journal.apply_event(
            epoch=epoch,
            event=OrderEvent(identity="ack", order_id=order.identity, at=later, kind="request_ack"),
        )
        journal.apply_event(
            epoch=epoch,
            event=OrderEvent(identity="accept", order_id=order.identity, at=later, kind="accepted"),
        )
        journal.request_cancel(epoch=epoch, order_id=order.identity, event_id="cancel", at=later)
        journal.apply_event(
            epoch=epoch,
            event=OrderEvent(
                identity="cancel-ack", order_id=order.identity, at=later, kind="cancel_ack"
            ),
        )
        assert journal.reservations().cash.value == Decimal("101")
        fill = Fill(
            identity="venue-fill",
            decision_at=self.start,
            filled_at=later,
            quantity=self._quantity("1"),
            reference=self._price("100"),
            effective=self._price("100"),
            fee=self._money("0.10"),
        )
        event = OrderEvent(
            identity="first-receipt", order_id=order.identity, at=later, kind="fill", fill=fill
        )
        assert journal.apply_event(epoch=epoch, event=event).status == "filled"
        before = len(journal.events())
        duplicate = OrderEvent(
            identity="second-receipt", order_id=order.identity, at=later, kind="fill", fill=fill
        )
        assert journal.apply_event(epoch=epoch, event=duplicate).status == "filled"
        assert len(journal.events()) == before
        assert journal.ledger_state().fills == (fill,)
        assert journal.reservations().cash.value == 0
        with pytest.raises(ValueError, match="terminal order"):
            journal.apply_event(
                epoch=epoch,
                event=OrderEvent(
                    identity="late-cancel", order_id=order.identity, at=later, kind="cancelled"
                ),
            )
        journal.release(epoch)

    def test_account_break_rejects_new_risk_and_exact_units_ignore_decimal_context(
        self, tmp_path: Path
    ) -> None:
        """A durable break blocks orders until matched account facts are supplied."""
        journal = self._journal(tmp_path / "risk.sqlite3")
        epoch = journal.claim("writer")
        assert not journal.reconcile_account(
            epoch=epoch,
            expected_cash=self._money("999"),
            expected_holding=self._quantity("0"),
            open_order_ids=(),
        )
        assert journal.blocked_reason() == "account_break"
        rejected = journal.commit_step(
            epoch=epoch,
            step_id="blocked",
            checkpoint=b"advanced-candidate-state",
            decision=OrderDecision(
                identity="blocked-buy",
                at=self.start,
                intent=self._order(side="buy", quantity="1", limit="100"),
            ),
            touch=None,
            maximum_fee=self._money("1"),
        )
        assert (rejected.status, rejected.reason, rejected.orders) == (
            "rejected",
            "account_break",
            (),
        )
        assert journal.checkpoint() == b"advanced-candidate-state"
        assert journal.reconcile_account(
            epoch=epoch,
            expected_cash=self._money("1000"),
            expected_holding=self._quantity("0"),
            open_order_ids=(),
        )
        with localcontext() as context:
            context.prec = 2
            admitted = journal.commit_step(
                epoch=epoch,
                step_id="unblocked",
                checkpoint=b"next-state",
                decision=OrderDecision(
                    identity="target-buy",
                    at=self.start + timedelta(seconds=1),
                    intent=TargetIntent(quantity=self._quantity("2")),
                ),
                touch=MarketTouch(bid=self._price("99"), ask=self._price("100")),
                maximum_fee=self._money("1"),
            )
            assert admitted.status == "committed"
            assert journal.reservations().cash.value == Decimal("201")
        journal.release(epoch)

    def test_cancel_request_keeps_an_unknown_outcome_unknown(self, tmp_path: Path) -> None:
        """A cancel request records intent but only reconciliation resolves an unknown order."""
        journal = self._journal(tmp_path / "unknown-cancel.sqlite3")
        epoch = journal.claim("writer")
        order_id = (
            journal.commit_step(
                epoch=epoch,
                step_id="tick-one",
                checkpoint=b"cp-one",
                decision=OrderDecision(
                    identity="buy-two",
                    at=self.start,
                    intent=self._order(side="buy", quantity="2", limit="100"),
                ),
                touch=None,
                maximum_fee=self._money("1"),
            )
            .orders[0]
            .identity
        )
        journal.apply_event(
            epoch=epoch,
            event=OrderEvent(
                identity="lost-ack",
                order_id=order_id,
                at=self.start + timedelta(seconds=1),
                kind="unknown",
            ),
        )
        requested = journal.request_cancel(
            epoch=epoch,
            order_id=order_id,
            event_id="cancel",
            at=self.start + timedelta(seconds=2),
        )
        assert (requested.status, requested.cancel_requested) == ("unknown", True)
        with pytest.raises(ValueError, match="cancel request is already pending"):
            journal.request_cancel(
                epoch=epoch,
                order_id=order_id,
                event_id="cancel-again",
                at=self.start + timedelta(seconds=3),
            )
        journal.release(epoch)

    def test_targets_cross_their_own_touch_and_exposures_convert_at_the_midpoint(
        self, tmp_path: Path
    ) -> None:
        """Holding 2 against a 99 bid and 101 ask (midpoint 100), each target crosses its side."""
        touch = MarketTouch(bid=self._price("99"), ask=self._price("101"))
        lowered: dict[str, tuple[tuple[str, Decimal, Decimal], ...] | str] = {}
        for name, intent in (
            ("lower-target", TargetIntent(quantity=self._quantity("1"))),
            ("higher-target", TargetIntent(quantity=self._quantity("3"))),
            ("exposure-150", ExposureIntent(exposure=self._money("150"))),
            ("exposure-350", ExposureIntent(exposure=self._money("350"))),
            ("exposure-200", ExposureIntent(exposure=self._money("200"))),
            ("exposure-297", ExposureIntent(exposure=self._money("297"))),
        ):
            journal = self._journal(tmp_path / f"{name}.sqlite3", with_holding=True)
            epoch = journal.claim("writer")
            committed = journal.commit_step(
                epoch=epoch,
                step_id=name,
                checkpoint=name.encode(),
                decision=OrderDecision(identity=name, at=self.start, intent=intent),
                touch=touch,
                maximum_fee=self._money("1"),
            )
            lowered[name] = (
                tuple(
                    (order.intent.side, order.intent.quantity.value, order.intent.limit.value)
                    for order in committed.orders
                )
                or committed.reason
            )
            journal.release(epoch)
        assert lowered == {
            "lower-target": (("sell", Decimal(1), Decimal(99)),),
            "higher-target": (("buy", Decimal(1), Decimal(101)),),
            "exposure-150": (("sell", Decimal(1), Decimal(99)),),
            "exposure-350": (("buy", Decimal(1), Decimal(101)),),
            # 200 at the midpoint is exactly the 2 held; at the ask alone it would sell one.
            "exposure-200": "target_matched",
            # 297 at the midpoint floors to the 2 held; at the bid alone it is 3, a buy.
            "exposure-297": "target_matched",
        }

    def test_a_step_retained_with_a_single_reference_price_is_refused(self) -> None:
        """Steps from the earlier format, which named one reference price, no longer decode."""
        codec = DomainCodec()
        encoded = codec.encode_json(
            StepRecord(
                step_id="step",
                checkpoint=b"",
                input_bytes=b"",
                result_bytes=b"",
                decision=None,
                touch=None,
                maximum_fee=self._money("1"),
                commit=StepCommit(status="committed", reason="no_intent", orders=()),
            )
        )
        earlier = encoded.replace(b'"touch":null', b'"reference":null')
        assert earlier != encoded
        with pytest.raises(ValueError, match="reference"):
            codec.decode_json(earlier, StepRecord)
