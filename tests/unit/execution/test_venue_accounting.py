"""Check native spot charges and independent physical wallet reconciliation."""

from __future__ import annotations

# standard library imports
import multiprocessing
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger
from configuration.accounts import AccountConfiguration, InstrumentFeeRate, OpeningAccount
from execution.account_records import AccountControl, NativeFill, PhysicalAccountObservation
from execution.account_state import DispatchLease
from execution.accounts import (
    AccountDecision,
    AccountJournal,
    AccountQuote,
    NetOrder,
    PortfolioBatch,
    PortfolioDecision,
)
from execution.records import OrderDecision, OrderEvent, OrderState
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from portfolio import PortfolioContext
from reference_data.instruments import InstrumentId
from risk.budgets import AccountLimit, BudgetPolicy, InstanceLimit
from risk.spot import SpotLimits
from strategies import OrderIntent


class _ClientStop:
    """Run one stop from another client thread and record how it ended."""

    def __init__(self, action: Callable[[], object]) -> None:
        """Bind the stop with no outcome yet."""
        self._action = action
        self.finished = threading.Event()
        self.errors: list[BaseException] = []

    def __call__(self) -> None:
        """Issue the stop, keep any failure and signal completion."""
        try:
            self._action()
        except BaseException as error:
            self.errors.append(error)
        finally:
            self.finished.set()


class _SteppedClock:
    """Report wall-clock time shifted by an adjustable step."""

    def __init__(self) -> None:
        """Start without a step."""
        self.offset = timedelta(0)

    def __call__(self) -> datetime:
        """Return the current UTC time plus the step."""
        return datetime.now(UTC) + self.offset


class _SteppedMonotonic:
    """Report monotonic time shifted by an adjustable step in seconds."""

    def __init__(self) -> None:
        """Start without a step."""
        self.offset = 0.0

    def __call__(self) -> float:
        """Return the monotonic clock plus the step."""
        return time.monotonic() + self.offset


class TestVenueAccounting:
    """Keep native source costs and wallet evidence distinct from local IDs."""

    quote = Currency.from_code("USDT")
    base = Currency(code="QBTC", minor_unit=Decimal("0.00000001"))
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)

    @classmethod
    def _money(cls, value: str, currency: Currency | None = None) -> Money:
        """Create exact quote or base wallet amounts."""
        return Money(value=Decimal(value), currency=currency or cls.quote)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Create exact signed base units."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls, value: str = "100") -> Price:
        """Create one exact quote per base unit."""
        return Price(value=Decimal(value), currency=cls.quote, per=cls.dimension)

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Pin one account, instrument and independent 500 quote cap."""
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(
                maximum=cls._quantity("10"),
                lot=cls._quantity("1"),
                tick=cls._price("0.01"),
                product="spot",
            ),
        )
        return AccountConfiguration(
            mode="venue_test",
            opening_at=cls.opening_at,
            accounts=(OpeningAccount(account_id="venue", cash=(cls._money("1000"),)),),
            instruments=spot_limits,
            fee_rates=tuple(
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal(0)
                )
                for limits in spot_limits
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.quote,
                firm_maximum=cls._money("500"),
                accounts=(AccountLimit(account_id="venue", maximum=cls._money("500")),),
                instances=(
                    InstanceLimit(
                        instance_id="alpha",
                        account_id="venue",
                        maximum=cls._money("500"),
                        instruments=(cls.dimension.instrument_id,),
                    ),
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=100,
                max_order_notional=cls._money("500"),
            ),
        )

    @classmethod
    def _observation(
        cls,
        identity: str,
        at: datetime,
        quote: str,
        base: str,
        orders: tuple[OrderState, ...] = (),
    ) -> PhysicalAccountObservation:
        """State independent wallet totals without any local posting identifiers."""
        balances: tuple[Money, ...] = (cls._money(quote),)
        if Decimal(base):
            balances = (*balances, cls._money(base, cls.base))
        return PhysicalAccountObservation(
            identity=identity,
            account_id="venue",
            at=at,
            balances=balances,
            instrument_currencies=((cls.dimension, cls.base),),
            open_orders=orders,
        )

    @classmethod
    def _ready(cls, path: Path, *, clock: Callable[[], datetime] | None = None) -> AccountJournal:
        """Reconcile the authorized opening wallet before sending orders."""
        journal = AccountJournal(path, cls._config(), clock=clock)
        assert journal.reconcile_venue(cls._observation("opening", cls.opening_at, "1000", "0"))
        return journal

    @classmethod
    def _buy(cls, journal: AccountJournal, at: datetime, identity: str = "buy") -> OrderState:
        """Admit a two-unit purchase with a one-quote-unit maximum fee."""
        quote = AccountQuote(price=cls._price(), at=at)
        journal.observe(quote)
        result = journal.admit(
            AccountDecision(
                account_id="venue",
                instance_id="alpha",
                decision=OrderDecision(
                    identity=identity,
                    at=at,
                    intent=OrderIntent(
                        side="buy",
                        quantity=cls._quantity("2"),
                        limit=cls._price(),
                        time_in_force="gtc",
                    ),
                ),
                quote=quote,
                maximum_fee=cls._money("1"),
            )
        )
        assert result.status == "committed"
        return result.orders[0]

    @classmethod
    def _native(
        cls,
        order: OrderState,
        at: datetime,
        *,
        identity: str = "venue-trade-1",
        fee: str = "0.01",
        fee_currency: Currency | None = None,
    ) -> NativeFill:
        """Describe a signed actual trade with a native asset fee or rebate."""
        return NativeFill(
            identity=identity,
            order_id=order.identity,
            at=at,
            filled_at=at - timedelta(microseconds=1),
            quantity=cls._quantity("2"),
            price=cls._price(),
            fee=cls._money(fee, fee_currency or cls.base),
            base_currency=cls.base,
        )

    def test_base_fee_restart_retry_wallet_break_and_conflicting_trade(
        self, tmp_path: Path
    ) -> None:
        """A base charge removes inventory and an actual wallet break blocks recovery."""
        path = tmp_path / "venue.sqlite3"
        journal = self._ready(path)
        decision_at = self.opening_at + timedelta(seconds=1)
        order = self._buy(journal, decision_at)
        # An admitted but unsent local intent is absent from the venue open set.
        assert journal.reconcile_venue(self._observation("before-send", decision_at, "1000", "0"))
        source = self._native(order, decision_at + timedelta(seconds=1))
        filled = journal.apply_native_fill(source)
        assert isinstance(filled, OrderState) and filled.status == "filled"
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert tuple(item.value for item in snapshot.cash) == (Decimal("800"), Decimal(0))
        assert snapshot.positions[0].value == Decimal("1.99")
        assert tuple(item.value for item in snapshot.fees) == (Decimal(0), Decimal("0.01"))
        assert snapshot.fill_ids == (source.identity,)
        reopened = AccountJournal(path, self._config())
        assert reopened.apply_native_fill(source) == filled
        assert AccountLedger(reopened.accounts()[0].ledger).snapshot() == snapshot
        observed_at = source.at + timedelta(seconds=1)
        assert not reopened.reconcile_venue(
            self._observation("wrong-base", observed_at, "800", "2")
        )
        assert reopened.accounts()[0].fault == "account_break"
        assert reopened.reconcile_venue(
            self._observation("exact-wallet", observed_at, "800", "1.99")
        )
        reopened.block("venue", "operator-stop")
        assert reopened.reconcile_venue(
            self._observation("still-stopped", observed_at, "800", "1.99")
        )
        assert reopened.accounts()[0].operator_block == "operator-stop"
        with pytest.raises(ValueError, match="native fill identity reused"):
            reopened.apply_native_fill(replace(source, fee=self._money("0.02", self.base)))
        assert AccountLedger(reopened.accounts()[0].ledger).snapshot() == snapshot
        assert not reopened.reconcile_venue(
            self._observation(
                "conflicting-source", observed_at + timedelta(seconds=1), "800", "1.99"
            )
        )

    def test_quote_rebate_and_dispatch_guard(self, tmp_path: Path) -> None:
        """Quote rebate credits cash; stopped dispatch is fenced while cancel stays open."""
        journal = self._ready(tmp_path / "rebate.sqlite3")
        decision_at = self.opening_at + timedelta(seconds=1)
        order = self._buy(journal, decision_at)
        unknown_at = decision_at + timedelta(microseconds=1)
        journal.apply_event(
            OrderEvent(
                identity="pending-send", order_id=order.identity, at=unknown_at, kind="unknown"
            )
        )
        with journal.execution_guard("venue", order.identity, unknown_at) as permit:
            assert permit.order.identity == order.identity
        source = self._native(
            order,
            decision_at + timedelta(seconds=1),
            fee="-0.25",
            fee_currency=self.quote,
        )
        journal.apply_native_fill(source)
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert snapshot.cash[0].value == Decimal("800.25")
        assert snapshot.positions[0].value == Decimal("2")
        assert snapshot.rebates[0].value == Decimal("0.25")
        assert journal.reconcile_venue(
            self._observation("rebated", source.at + timedelta(seconds=1), "800.25", "2")
        )
        second_at = source.at + timedelta(seconds=2)
        second = self._buy(journal, second_at, identity="second")
        journal.block("venue", "operator-stop")
        with pytest.raises(ValueError, match="dispatch is blocked"):
            with journal.execution_guard("venue", second.identity, second_at):
                pass
        with journal.execution_guard("venue", second.identity, second_at, cancel=True):
            pass
        journal.invalidate_venue("venue", "private-disconnect")
        assert journal.accounts()[0].reconciled_at is None
        assert journal.accounts()[0].operator_block == "operator-stop"

    def _pending_send(
        self, journal: AccountJournal, *, identity: str = "buy"
    ) -> tuple[OrderState, datetime]:
        """Admit an order and record its send as unknown, as a submitter does."""
        decision_at = self.opening_at + timedelta(seconds=1)
        order = self._buy(journal, decision_at, identity=identity)
        unknown_at = decision_at + timedelta(microseconds=1)
        journal.apply_event(
            OrderEvent(
                identity=f"send-{identity}", order_id=order.identity, at=unknown_at, kind="unknown"
            )
        )
        return order, unknown_at

    @staticmethod
    def _leases(journal: AccountJournal) -> tuple[DispatchLease, ...]:
        """Read the journal's dispatch leases."""
        with journal._store.write() as transaction:
            return transaction.leases()

    def test_dispatch_send_holds_a_lease_not_the_write_lock(self, tmp_path: Path) -> None:
        """Other writers commit while a send is pending; release removes the lease."""
        journal = self._ready(tmp_path / "lease.sqlite3")
        order, unknown_at = self._pending_send(journal)
        with journal.execution_guard("venue", order.identity, unknown_at) as permit:
            assert permit.lease is not None and permit.lease.order_id == order.identity
            assert permit.lease.instance_ids == ("alpha",)
            # Before leases this write waited for the send and failed "database is locked".
            journal.observe(AccountQuote(price=self._price(), at=unknown_at))
            assert self._leases(journal) == (permit.lease,)
            permit.require_sendable()
        assert self._leases(journal) == ()

    @staticmethod
    def _stop(journal: AccountJournal, writer: str) -> None:
        """Issue one stop-type write to the journal."""
        if writer == "block":
            journal.block("venue", "operator-stop")
        elif writer == "invalidate_venue":
            journal.invalidate_venue("venue", "stream-lost")
        elif writer == "control_stop":
            journal.control(
                AccountControl(
                    identity="stop-during-send",
                    account_id="venue",
                    kind="stop",
                    at=datetime.now(UTC),
                    reason="operator",
                )
            )
        else:
            journal.stop_instance("alpha", datetime.now(UTC))

    @staticmethod
    def _committed(journal: AccountJournal, writer: str) -> bool:
        """Report whether the stop-type write has committed."""
        if writer == "block":
            return journal.accounts()[0].operator_block is not None
        if writer == "invalidate_venue":
            return journal.accounts()[0].fault is not None
        if writer == "control_stop":
            return journal.accounts()[0].phase != "running"
        return "alpha" in journal.stopped_instances()

    @pytest.mark.parametrize(
        "writer", ["block", "invalidate_venue", "control_stop", "stop_instance"]
    )
    def test_stop_type_writers_wait_for_a_held_lease(self, tmp_path: Path, writer: str) -> None:
        """A stop issued during a pending send commits only after the send ends."""
        journal = self._ready(tmp_path / f"{writer}.sqlite3")
        order, unknown_at = self._pending_send(journal)
        stop = _ClientStop(partial(self._stop, journal, writer))
        with journal.execution_guard("venue", order.identity, unknown_at):
            worker = threading.Thread(target=stop)
            worker.start()
            assert not stop.finished.wait(0.3)
            assert not self._committed(journal, writer)
        assert stop.finished.wait(5) and not stop.errors
        worker.join(5)
        assert self._committed(journal, writer)

    def test_a_dead_sender_frees_its_lease_at_once(self, tmp_path: Path) -> None:
        """A sender killed mid-send stops holding its lease; the order stays unknown."""
        path = tmp_path / "abandoned.sqlite3"
        journal = self._ready(path)
        order, unknown_at = self._pending_send(journal)
        context = multiprocessing.get_context("spawn")
        sender = context.Process(
            target=TestVenueAccounting.arm_and_die, args=(str(path), order.identity, unknown_at)
        )
        sender.start()
        sender.join(30)
        assert sender.exitcode == 0
        assert len(self._leases(journal)) == 1
        stop = _ClientStop(partial(journal.block, "venue", "operator-stop"))
        threading.Thread(target=stop, daemon=True).start()
        # Before liveness this waited out a 30-second wall-clock deadline.
        assert stop.finished.wait(5) and not stop.errors
        assert journal.accounts()[0].operator_block == "operator-stop"
        assert self._leases(journal) == ()
        assert not list(tmp_path.glob("abandoned.sqlite3.lease-*"))
        assert next(item.order for item in journal.orders()).status == "unknown"
        with pytest.raises(ValueError, match="dispatch is blocked"):
            with journal.execution_guard("venue", order.identity, unknown_at):
                pass

    def test_a_wall_clock_step_cannot_expire_a_live_send(self, tmp_path: Path) -> None:
        """A forward wall-clock jump during a send does not let a stop commit under it."""
        clock = _SteppedClock()
        journal = self._ready(tmp_path / "step.sqlite3", clock=clock)
        order, unknown_at = self._pending_send(journal)
        stop = _ClientStop(partial(journal.block, "venue", "operator-stop"))
        with journal.execution_guard("venue", order.identity, unknown_at):
            clock.offset = timedelta(minutes=5)
            threading.Thread(target=stop, daemon=True).start()
            assert not stop.finished.wait(0.3)
            assert journal.accounts()[0].operator_block is None
        assert stop.finished.wait(5) and not stop.errors
        assert journal.accounts()[0].operator_block == "operator-stop"

    def test_a_hung_sender_bounds_the_stop_wait(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stop never commits under a live lease; past its bound it refuses instead."""
        journal = self._ready(tmp_path / "hung.sqlite3")
        order, unknown_at = self._pending_send(journal)
        stop = _ClientStop(partial(journal.block, "venue", "operator-stop"))
        with journal.execution_guard("venue", order.identity, unknown_at):
            # Shorten only the stop's wait; the armed lease keeps its own bounds.
            monkeypatch.setattr(journal, "_STOP_WAIT_SECONDS", 0.3)
            threading.Thread(target=stop, daemon=True).start()
            assert stop.finished.wait(5)
            assert len(stop.errors) == 1 and isinstance(stop.errors[0], ValueError)
            assert "stop not committed" in str(stop.errors[0])
            assert journal.accounts()[0].operator_block is None

    def test_sender_past_its_send_window_does_not_send(self, tmp_path: Path) -> None:
        """A send that would start too late to finish within its lease is refused."""
        journal = self._ready(tmp_path / "late.sqlite3")
        order, unknown_at = self._pending_send(journal)
        monotonic = _SteppedMonotonic()
        journal._monotonic = monotonic
        with journal.execution_guard("venue", order.identity, unknown_at) as permit:
            monotonic.offset = 11.0
            with pytest.raises(ValueError, match="send window passed"):
                permit.require_sendable()
        assert self._leases(journal) == ()

    @pytest.mark.parametrize(
        "row",
        [
            ("order", "venue", b'["alpha"]', "not a holder", "2026-10-01T12:00:00+00:00"),
            ("order", "venue", b"not json", "holder1", "2026-10-01T12:00:00+00:00"),
            ("order", "venue", b'["alpha"]', "holder1", "yesterday"),
            ("order", "venue", b'["alpha"]', "holder1", "2026-10-01T12:00:00"),
        ],
        ids=["holder", "instances", "clock", "naive-clock"],
    )
    def test_malformed_lease_row_is_refused(self, tmp_path: Path, row: tuple[object, ...]) -> None:
        """A lease row that is not a valid DispatchLease stops writers with one error."""
        path = tmp_path / "leases.sqlite3"
        journal = self._ready(path)
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("INSERT INTO dispatch_leases VALUES (?, ?, ?, ?, ?)", row)
            connection.commit()
        with pytest.raises(ValueError, match="invalid dispatch lease row"):
            journal.block("venue", "operator-stop")

    def test_journal_whose_table_changed_under_its_name_is_refused(self, tmp_path: Path) -> None:
        """Matching table names are not enough; every column and constraint must match."""
        path = tmp_path / "changed.sqlite3"
        self._ready(path)
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("ALTER TABLE dispatch_leases ADD COLUMN deadline TEXT")
            connection.commit()
        with pytest.raises(ValueError, match="unsupported account journal schema"):
            AccountJournal(path, self._config())
        with pytest.raises(ValueError, match="unsupported account journal schema"):
            AccountJournal.verify(path, self._config())

    def test_journal_without_dispatch_leases_is_refused(self, tmp_path: Path) -> None:
        """A journal in the layout before dispatch leases is refused, not extended."""
        path = tmp_path / "earlier.sqlite3"
        self._ready(path)
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("DROP TABLE dispatch_leases")
            connection.commit()
        with pytest.raises(ValueError, match="unsupported account journal schema"):
            AccountJournal(path, self._config())
        with pytest.raises(ValueError, match="unsupported account journal schema"):
            AccountJournal.verify(path, self._config())

    def test_native_fees_above_the_reservation_grow_it_and_post(self, tmp_path: Path) -> None:
        """The venue already charged 0.8 and 0.3 quote-equivalent against a one-unit cap."""
        journal = self._ready(tmp_path / "partial.sqlite3")
        decision_at = self.opening_at + timedelta(seconds=1)
        order = self._buy(journal, decision_at)
        first_at = decision_at + timedelta(seconds=1)
        first = NativeFill(
            identity="partial-1",
            order_id=order.identity,
            at=first_at,
            filled_at=first_at - timedelta(microseconds=1),
            quantity=self._quantity("1"),
            price=self._price(),
            fee=self._money("0.008", self.base),
            base_currency=self.base,
        )
        first_result = journal.apply_native_fill(first)
        assert isinstance(first_result, OrderState) and first_result.status == "partial"
        before = journal.accounts()[0].ledger
        second_at = first_at + timedelta(seconds=1)
        second = replace(
            first,
            identity="partial-2",
            at=second_at,
            filled_at=second_at - timedelta(microseconds=1),
            fee=self._money("0.003", self.base),
        )
        # The fill happened, so it posts: the reserve grows by the 0.1 shortfall and
        # the excess is paid from free cash, which covers it.
        second_result = journal.apply_native_fill(second)
        assert isinstance(second_result, OrderState) and second_result.status == "filled"
        assert second_result.maximum_fee == self._money("1.1")
        assert journal.accounts()[0].ledger != before
        assert journal.accounts()[0].fault is None
        assert journal.reconcile_venue(
            self._observation("partial-wallet", second_at, "800", "1.989")
        )

    def test_native_fee_overage_beyond_free_cash_posts_and_faults(self, tmp_path: Path) -> None:
        """A venue fee free cash cannot cover still posts, and blocks new exposure."""
        journal = self._ready(tmp_path / "uncovered.sqlite3")
        decision_at = self.opening_at + timedelta(seconds=1)
        order = self._buy(journal, decision_at)
        at = decision_at + timedelta(seconds=1)
        # 100 for the unit plus a 900 fee leaves no cash for the other reserved unit.
        result = journal.apply_native_fill(
            NativeFill(
                identity="overcharged",
                order_id=order.identity,
                at=at,
                filled_at=at - timedelta(microseconds=1),
                quantity=self._quantity("1"),
                price=self._price(),
                fee=self._money("900"),
                base_currency=self.base,
            )
        )
        assert isinstance(result, OrderState) and result.status == "partial"
        assert result.paid_fee == self._money("900")
        assert result.maximum_fee.value >= Decimal("900")
        assert journal.accounts()[0].fault == "native_fee_overage_uncovered"

    def test_net_parent_base_fee_is_exactly_attributed_to_both_children(
        self, tmp_path: Path
    ) -> None:
        """A physical four-unit fill charges each two-unit child 0.01 base."""
        initial = self._config()
        second_owner = InstanceLimit(
            instance_id="beta",
            account_id="venue",
            maximum=self._money("500"),
            instruments=(self.dimension.instrument_id,),
        )
        instance_limits: tuple[InstanceLimit, ...] = (
            *initial.budgets.instances,
            second_owner,
        )
        config = replace(
            initial,
            budgets=replace(
                initial.budgets,
                instances=instance_limits,
            ),
        )
        journal = AccountJournal(tmp_path / "net.sqlite3", config)
        assert journal.reconcile_venue(self._observation("opening", self.opening_at, "1000", "0"))
        decision_at = self.opening_at + timedelta(seconds=1)
        quote = AccountQuote(price=self._price(), at=decision_at)
        journal.observe(quote)
        decisions: list[PortfolioDecision] = []
        for instance in ("alpha", "beta"):
            decisions.append(
                PortfolioDecision(
                    request=AccountDecision(
                        account_id="venue",
                        instance_id=instance,
                        decision=OrderDecision(
                            identity=f"{instance}-buy",
                            at=decision_at,
                            intent=OrderIntent(
                                side="buy",
                                quantity=self._quantity("2"),
                                limit=self._price(),
                                time_in_force="gtc",
                            ),
                        ),
                        quote=quote,
                        maximum_fee=self._money("1"),
                    ),
                    context=PortfolioContext(
                        portfolio_id="portfolio",
                        strategy_id=instance,
                        model_revision="reference",
                        config_revision="reference",
                        horizon="one-minute",
                        reason="native-account-test",
                        venue="OKX",
                        settlement="spot-immediate",
                        risk_bucket="spot",
                        authority_scope="venue-test",
                    ),
                )
            )
        batch = PortfolioBatch(
            identity="two-buyers",
            at=decision_at + timedelta(microseconds=1),
            decisions=tuple(decisions),
        )
        committed = journal.coordinate(batch)
        assert committed.status == "committed"
        parent = committed.net_orders[0]
        assert parent.order.intent.quantity.value == Decimal("4")
        source_at = batch.at + timedelta(seconds=1)
        source = NativeFill(
            identity="physical-trade",
            order_id=parent.order.identity,
            at=source_at,
            filled_at=source_at - timedelta(microseconds=1),
            quantity=self._quantity("4"),
            price=self._price(),
            fee=self._money("0.02", self.base),
            base_currency=self.base,
        )
        result = journal.apply_native_fill(source)
        assert isinstance(result, NetOrder) and result.order.status == "filled"
        ledger = AccountLedger(journal.accounts()[0].ledger)
        snapshot = ledger.snapshot()
        assert snapshot.cash[0].value == Decimal("600")
        assert snapshot.positions[0].value == Decimal("3.98")
        assert snapshot.fees[1].value == Decimal("0.02")
        assert ledger.snapshot("alpha").positions[0].value == Decimal("1.99")
        assert ledger.snapshot("beta").positions[0].value == Decimal("1.99")
        assert journal.reconcile_venue(
            self._observation("net-wallet", source_at + timedelta(seconds=1), "600", "3.98")
        )

    @staticmethod
    def arm_and_die(path: str, order_id: str, at: datetime) -> None:
        """Arm a dispatch lease in a separate process, then exit without releasing it."""
        journal = AccountJournal(Path(path), TestVenueAccounting._config())
        # Keep the guard referenced: collecting it would run its release.
        guard = journal.execution_guard("venue", order_id, at)
        guard.__enter__()
        os._exit(0)
