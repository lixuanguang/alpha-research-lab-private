"""Exercise durable sends, physical reconciliation and private-stream recovery."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger
from configuration import (
    AccountConfiguration,
    CapabilityProfile,
    OpeningAccount,
    VenueAuthorization,
    VenueCredentialReferences,
    VenueExecutionConfiguration,
    VenueInstrument,
)
from execution import AccountDecision, AccountJournal, AccountQuote, OrderDecision, VenueGateway
from execution.venue_state import VenueStateStore
from execution.venues.contracts import (
    VenueBalance,
    VenueCapabilityProfile,
    VenueCommandAck,
    VenueFillFact,
    VenueFillPage,
    VenueOrderFact,
    VenueOrderRequest,
    VenueOutcomeUnknownError,
    VenueRejectedError,
    VenueStreamEvent,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.catalogs import InstrumentDefinition, ReferenceHistory, VenueSpecification
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from strategies import OrderIntent


class AdvancingClock:
    """Advance deterministic UTC at each bounded rate-limit wait."""

    def __init__(self, at: datetime) -> None:
        """Select the first actual receipt time."""
        self.at = at

    def now(self) -> datetime:
        """Expose controlled UTC time."""
        return self.at

    def sleep(self, seconds: float) -> None:
        """Advance without spending wall-clock time."""
        self.at += timedelta(seconds=seconds)


class ObservedVenue:
    """Supply independently authored venue balances and source outcomes."""

    def __init__(self, config: VenueExecutionConfiguration) -> None:
        """Start from a flat wallet with no accepted client identity."""
        self.config = config
        self.request: VenueOrderRequest | None = None
        self.submit_count = 0
        self.cancel_count = 0
        self.lose_cancel_ack = False
        self.lose_ack = False
        self.reject = False
        self.missing = False
        self.cancelled = False
        self.quote_balance = Decimal("10000")
        self.base_balance = Decimal(0)
        self.filled = Decimal(0)
        self.executions: tuple[VenueFillFact, ...] = ()
        self.nonces: list[int] = []

    def _nonce(self, nonce: int) -> None:
        """Require key-wide monotonic request identity even after gateway restart."""
        assert not self.nonces or nonce > self.nonces[-1]
        self.nonces.append(nonce)

    @property
    def capability_profiles(self) -> tuple[CapabilityProfile, ...]:
        """Declare exactly the operations supplied by this independent fixture."""
        return (
            CapabilityProfile(
                name="test_spot",
                kind="execution",
                implementation_identity="fixture",
                version="1",
                products=("spot",),
                venues=(self.config.venue,),
                calendars=("24x7",),
                modes=("venue_test",),
                operations=("submit", "cancel", "order", "open_orders", "fills", "balances"),
                order_types=("gtc", "ioc", "post-only"),
            ),
        )

    def qualify_account(self, *, at: datetime, nonce: int) -> VenueCapabilityProfile:
        """Report the authored test account without claiming external observation."""
        self._nonce(nonce)
        return VenueCapabilityProfile(
            venue=self.config.venue,
            environment=self.config.environment,
            account_verified=True,
            account_identity="42",
        )

    def submit(self, order: VenueOrderRequest, *, at: datetime, nonce: int) -> VenueCommandAck:
        """Accept once, optionally losing the response after the venue effect."""
        self._nonce(nonce)
        self.submit_count += 1
        if self.reject:
            raise VenueRejectedError("authored rejection")
        self.request = order
        if self.lose_ack:
            raise VenueOutcomeUnknownError("authored acknowledgement loss")
        return VenueCommandAck(
            operation="submit",
            client_id=order.client_id,
            venue_order_id="42",
            received_at=at,
            raw=b"accepted-request",
        )

    def cancel(
        self,
        symbol: str,
        client_id: str,
        *,
        submitted_at: datetime,
        venue_order_id: str | None,
        at: datetime,
        nonce: int,
    ) -> VenueCommandAck:
        """Acknowledge a request while leaving economic cancellation unresolved."""
        self._nonce(nonce)
        self.cancel_count += 1
        if self.lose_cancel_ack:
            raise VenueOutcomeUnknownError("lost cancel acknowledgement")
        return VenueCommandAck(
            operation="cancel",
            client_id=client_id,
            venue_order_id="42",
            received_at=at,
            raw=b"cancel-request",
        )

    def order(
        self,
        symbol: str,
        client_id: str,
        *,
        submitted_at: datetime,
        venue_order_id: str | None,
        at: datetime,
        nonce: int,
    ) -> VenueOrderFact | None:
        """Return authored cumulative state or an explicitly missing history result."""
        self._nonce(nonce)
        return None if self.missing or self.request is None else self._order(at)

    def _order(self, at: datetime) -> VenueOrderFact:
        """Expose cumulative quantities independent of local account state."""
        request = self.request
        assert request is not None
        return VenueOrderFact(
            client_id=request.client_id,
            venue_order_id="42",
            symbol=request.symbol,
            side=request.side,
            original_quantity=request.quantity,
            filled_quantity=self.filled,
            remaining_quantity=request.quantity - self.filled,
            limit_price=request.limit_price,
            time_in_force=request.time_in_force,
            post_only=request.post_only,
            status="cancelled" if self.cancelled else "partial" if self.filled else "open",
            source_at=at,
            received_at=at,
            raw=b"independent-order",
        )

    def open_orders(self, *, at: datetime, nonce: int) -> tuple[VenueOrderFact, ...]:
        """Return only active physical orders from the authored venue state."""
        self._nonce(nonce)
        return () if self.request is None or self.cancelled else (self._order(at),)

    def fills(
        self,
        *,
        symbol: str,
        start_ms: int,
        end_ms: int,
        limit: int,
        cursor: str | None,
        at: datetime,
        nonce: int,
    ) -> VenueFillPage:
        """Repeat original trade identities using a new delivery clock."""
        self._nonce(nonce)
        fills: tuple[VenueFillFact, ...] = tuple(
            replace(fill, received_at=at) for fill in self.executions
        )
        return VenueFillPage(fills=fills, next_cursor=None, complete=True)

    def balances(self, *, at: datetime, nonce: int) -> tuple[VenueBalance, ...]:
        """Return independently specified total balances, including locked funds."""
        self._nonce(nonce)
        instrument = self.config.instruments[0]
        return (
            VenueBalance(
                currency=instrument.quote_currency.code,
                total=self.quote_balance,
                available=self.quote_balance,
                received_at=at,
                raw=b"wallet-quote",
            ),
            VenueBalance(
                currency=instrument.base_currency.code,
                total=self.base_balance,
                available=self.base_balance,
                received_at=at,
                raw=b"wallet-base",
            ),
        )

    def private_login(self, *, at: datetime, nonce: int) -> bytes:
        """Supply a non-secret fixture login."""
        self._nonce(nonce)
        return b"login"

    def private_configuration(self) -> tuple[bytes, ...]:
        """No additional fixture configuration is needed."""
        return ()

    def private_subscriptions(self) -> tuple[bytes, ...]:
        """Supply one observable subscription."""
        return (b"subscribe",)

    def decode_private(self, raw: bytes, *, received_at: datetime) -> VenueStreamEvent:
        """Interpret only explicit fixture authentication and loss signals."""
        return VenueStreamEvent(
            kind="authenticated" if raw == b"authenticated" else "recovery_required",
            raw=raw,
            received_at=received_at,
        )


class BrokenSession:
    """Disconnect immediately after authentication while recording cleanup."""

    def __init__(self, clock: AdvancingClock) -> None:
        """Bind the deterministic receipt clock."""
        self.clock = clock
        self.receives = 0
        self.closed = False

    def open(self, login: bytes, *, configuration: tuple[bytes, ...] = ()) -> None:
        """Accept only the expected fixture login."""
        assert login == b"login"

    def send(self, frame: bytes) -> None:
        """Require authentication to precede subscription."""
        assert self.receives == 1 and frame == b"subscribe"

    def receive(self) -> tuple[bytes, datetime]:
        """Authenticate once and then raise a transport-loss error."""
        self.receives += 1
        if self.receives > 1:
            raise VenueOutcomeUnknownError("private connection lost")
        return b"authenticated", self.clock.now()

    def close(self) -> None:
        """Record deterministic socket cleanup."""
        self.closed = True


class TestVenueGateway:
    """Verify economic safety at uncertain external boundaries."""

    at = datetime(2026, 9, 26, 12, tzinfo=UTC)
    instrument_id = InstrumentId.from_canonical_text("33333333-3333-4333-8333-333333333333")
    dimension = Dimension(instrument_id=instrument_id, kind=QuantityKind.BASE_UNIT)
    base_currency = Currency(code="ETH", minor_unit=Decimal("0.00000001"))

    @classmethod
    def _money(cls, value: str, currency: Currency) -> Money:
        """Construct an exact scoped currency amount."""
        return Money(value=Decimal(value), currency=currency)

    @classmethod
    def _config(cls, venue: Literal["okx", "bitfinex"] = "okx") -> VenueExecutionConfiguration:
        """Build one venue-bound test account with independently authored limits."""
        if venue == "okx":
            quote = Currency.from_code("USDT")
            symbol = "ETH-USDT"
            environment: Literal["okx_demo", "bitfinex_paper"] = "okx_demo"
            credentials = VenueCredentialReferences(
                api_key_env="TEST_OKX_KEY",
                api_secret_env="TEST_OKX_SECRET",
                passphrase_env="TEST_OKX_PASSPHRASE",
            )
        elif venue == "bitfinex":
            quote = Currency.from_code("USD")
            symbol = "tETHUSD"
            environment = "bitfinex_paper"
            credentials = VenueCredentialReferences(
                api_key_env="TEST_BITFINEX_KEY", api_secret_env="TEST_BITFINEX_SECRET"
            )
        else:
            raise ValueError("unsupported test venue")
        maximum = Quantity(value=Decimal("10"), dimension=cls.dimension)
        account = AccountConfiguration(
            mode="venue_test",
            opening_at=cls.at,
            accounts=(
                OpeningAccount(account_id="test-account", cash=(cls._money("10000", quote),)),
            ),
            instruments=(
                SpotLimits(
                    maximum=maximum,
                    lot=Quantity(value=Decimal("0.01"), dimension=cls.dimension),
                    tick=Price(value=Decimal("0.01"), currency=quote, per=cls.dimension),
                    product="spot",
                ),
            ),
            budgets=BudgetPolicy(
                valuation_currency=quote,
                firm_maximum=cls._money("10000", quote),
                accounts=(
                    AccountLimit(account_id="test-account", maximum=cls._money("10000", quote)),
                ),
                instances=(
                    InstanceLimit(
                        instance_id="reference-instance",
                        account_id="test-account",
                        maximum=cls._money("5000", quote),
                        instruments=(cls.instrument_id,),
                    ),
                ),
                max_quote_age_us=3_600_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=100,
                max_order_notional=cls._money("5000", quote),
            ),
        )
        reference = ReferenceHistory(
            specifications=(
                VenueSpecification(
                    instrument=InstrumentDefinition(
                        instrument_id=cls.instrument_id,
                        venue=venue,
                        symbol=symbol,
                        product="spot",
                        base_currency="ETH",
                        quote_currency=quote.code,
                        calendar="24x7",
                    ),
                    valid_from=cls.at,
                    valid_to=None,
                    ts_knowledge=cls.at,
                    source_digest="a" * 64,
                    basis="current_observation",
                    price_tick=Decimal("0.01"),
                    quantity_step=Decimal("0.01"),
                    minimum_quantity=Decimal("0.01"),
                    status="live",
                ),
            ),
        )
        account = replace(
            account,
            instruments=(
                SpotLimits.from_reference(
                    reference,
                    maximum=maximum,
                    quote_currency=quote,
                    valid_at=cls.at,
                    known_at=cls.at,
                    max_age=timedelta(hours=1),
                ),
            ),
        )
        return VenueExecutionConfiguration(
            account=account,
            account_id="test-account",
            venue_account_id="42",
            venue=venue,
            environment=environment,
            instruments=(
                VenueInstrument(
                    dimension=cls.dimension,
                    base_currency=cls.base_currency,
                    quote_currency=quote,
                    native_symbol=symbol,
                ),
            ),
            reference=reference,
            max_reference_age_us=3_600_000_000,
            credentials=credentials,
        )

    @classmethod
    def _authorization(
        cls, config: VenueExecutionConfiguration, *, enabled: bool
    ) -> VenueAuthorization:
        """Create a separate envelope pinned to one exact configuration."""
        return VenueAuthorization(
            config_sha256=config.identity,
            account_id=config.account_id,
            environment=config.environment,
            instrument_ids=(cls.instrument_id,),
            valid_from=cls.at,
            valid_until=cls.at + timedelta(hours=1),
            maximum_order_notional=cls._money("1000", config.account.budgets.valuation_currency),
            submit_enabled=enabled,
        )

    def _ready(
        self, tmp_path: Path, venue: Literal["okx", "bitfinex"] = "okx"
    ) -> tuple[
        AccountJournal, VenueGateway, ObservedVenue, AdvancingClock, VenueAuthorization, str
    ]:
        """Admit an independently reserved two-unit order after physical observation."""
        config = self._config(venue)
        clock = AdvancingClock(self.at + timedelta(seconds=10))
        adapter = ObservedVenue(config)
        journal = AccountJournal(tmp_path / "account.sqlite3", config.account)
        gateway = VenueGateway(journal, config, adapter, clock=clock)
        assert not gateway.reconcile().recovery_required
        quote = AccountQuote(
            price=Price(
                value=Decimal("100"),
                currency=config.instruments[0].quote_currency,
                per=self.dimension,
            ),
            at=clock.now(),
        )
        journal.observe(quote)
        decision = OrderDecision(
            identity="reference-order",
            at=clock.now(),
            intent=OrderIntent(
                side="buy",
                quantity=Quantity(value=Decimal("2"), dimension=self.dimension),
                limit=quote.price,
                time_in_force="gtc",
            ),
        )
        admitted = journal.admit(
            AccountDecision(
                account_id=config.account_id,
                instance_id="reference-instance",
                decision=decision,
                quote=quote,
                maximum_fee=self._money("5", config.instruments[0].quote_currency),
            )
        )
        assert admitted.status == "committed", admitted.reason
        return (
            journal,
            gateway,
            adapter,
            clock,
            self._authorization(config, enabled=True),
            admitted.orders[0].identity,
        )

    @pytest.mark.parametrize("venue", ["okx", "bitfinex"])
    def test_lost_ack_recovery_never_resubmits_and_posts_base_fee_once(
        self, tmp_path: Path, venue: Literal["okx", "bitfinex"]
    ) -> None:
        """Accepted-but-unacknowledged orders retain identity and exact native fees."""
        journal, gateway, adapter, clock, authorization, order_id = self._ready(tmp_path, venue)
        adapter.lose_ack = True
        with pytest.raises(VenueOutcomeUnknownError):
            gateway.submit(order_id, authorization)
        assert adapter.submit_count == 1
        assert journal.orders()[0].order.status == "unknown"
        assert gateway.inspect().recovery_required
        request = adapter.request
        assert request is not None
        adapter.filled = Decimal("1")
        adapter.quote_balance = Decimal("9900")
        adapter.base_balance = Decimal("0.99")
        adapter.executions = (
            VenueFillFact(
                fill_id="trade-1",
                client_id=request.client_id,
                venue_order_id="42",
                symbol=request.symbol,
                side="buy",
                quantity=Decimal("1"),
                price=Decimal("100"),
                fee=Decimal("0.01"),
                fee_currency="ETH",
                source_at=clock.now(),
                received_at=clock.now(),
                raw=b"trade-with-base-fee",
            ),
        )
        recovered = VenueGateway(journal, adapter.config, adapter, clock=clock)
        assert not recovered.reconcile().recovery_required
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert snapshot.positions[0].value == Decimal("0.99")
        assert next(cash.value for cash in snapshot.cash if cash.currency.code != "ETH") == Decimal(
            "9900"
        )
        assert not recovered.submit(order_id, authorization).submission_attempted
        assert adapter.submit_count == 1
        assert AccountLedger(journal.accounts()[0].ledger).snapshot() == snapshot

    def test_missing_lookup_keeps_exposure_and_never_retries_send(self, tmp_path: Path) -> None:
        """An absent order lookup does not establish that a timed-out send failed."""
        journal, gateway, adapter, _, authorization, order_id = self._ready(tmp_path)
        adapter.lose_ack = True
        with pytest.raises(VenueOutcomeUnknownError):
            gateway.submit(order_id, authorization)
        adapter.missing = True
        with pytest.raises(ValueError, match="absent"):
            gateway.submit(order_id, authorization)
        assert adapter.submit_count == 1
        assert not journal.orders()[0].order.is_terminal
        assert journal.accounts()[0].fault is not None

    def test_cancel_ack_keeps_reservation_until_observed_terminal(self, tmp_path: Path) -> None:
        """Cancellation and economic completion remain distinct through restart."""
        journal, gateway, adapter, _, authorization, order_id = self._ready(tmp_path)
        assert gateway.submit(order_id, authorization).submission_attempted
        assert not journal.orders()[0].order.accepted
        assert not gateway.reconcile().recovery_required
        gateway.cancel(order_id, authorization)
        assert journal.orders()[0].order.status == "cancel_ack"
        assert not journal.orders()[0].order.is_terminal
        adapter.cancelled = True
        assert not gateway.reconcile().recovery_required
        assert journal.orders()[0].order.status == "cancelled"
        gateway.cancel(order_id, authorization)
        assert adapter.cancel_count == 1

    def test_definite_reject_releases_order_without_requiring_nonexistent_history(
        self, tmp_path: Path
    ) -> None:
        """A definite reject can reconcile, while the client identity stays consumed."""
        journal, gateway, adapter, _, authorization, order_id = self._ready(tmp_path)
        adapter.reject = True
        with pytest.raises(VenueRejectedError):
            gateway.submit(order_id, authorization)
        assert journal.orders()[0].order.status == "rejected"
        assert not gateway.reconcile().recovery_required
        gateway.submit(order_id, authorization)
        assert adapter.submit_count == 1

    def test_private_loss_invalidates_account_and_closes_session(self, tmp_path: Path) -> None:
        """Losing authenticated input cannot leave independently admissible stale state."""
        journal, gateway, _, clock, _, _ = self._ready(tmp_path)
        session = BrokenSession(clock)
        with pytest.raises(VenueOutcomeUnknownError, match="connection lost"):
            gateway.stream(session, max_messages=3, duration_seconds=60)
        assert session.closed
        assert gateway.inspect().recovery_required
        assert journal.accounts()[0].reconciled_at is None
        assert not gateway.reconcile().recovery_required

    def test_cancel_retry_requires_fresh_known_open_outcome(self, tmp_path: Path) -> None:
        """Reconciled active state permits a new explicitly requested cancellation."""
        _, gateway, adapter, _, authorization, order_id = self._ready(tmp_path)
        gateway.submit(order_id, authorization)
        adapter.lose_cancel_ack = True
        with pytest.raises(VenueOutcomeUnknownError):
            gateway.cancel(order_id, authorization)
        adapter.missing = True
        with pytest.raises(ValueError, match="absent"):
            gateway.cancel(order_id, authorization)
        assert adapter.cancel_count == 1
        adapter.missing = False
        adapter.lose_cancel_ack = False
        gateway.cancel(order_id, authorization)
        assert adapter.cancel_count == 2

    def test_stopped_account_cannot_cross_final_dispatch_guard(self, tmp_path: Path) -> None:
        """A stale admitted intent cannot bypass an independent operator block."""
        journal, gateway, adapter, _, authorization, order_id = self._ready(tmp_path)
        journal.block(adapter.config.account_id, "independent operator stop")
        with pytest.raises(ValueError):
            gateway.submit(order_id, authorization)
        assert adapter.submit_count == 0

    def test_venue_owner_lock_rejects_second_sender(self, tmp_path: Path) -> None:
        """A second process owner cannot replace an active network-capable owner."""
        path = tmp_path / "account.sqlite3"
        first = VenueStateStore(path, "account", b"scope")
        second = VenueStateStore(path, "account", b"scope")
        with first.claim(), pytest.raises(ValueError, match="already active"), second.claim():
            pytest.fail("second sender acquired the live owner fence")

    def test_same_physical_wallet_cannot_fund_two_local_accounts(self, tmp_path: Path) -> None:
        """Independent aliases cannot duplicate one authenticated account's funding."""
        path = tmp_path / "firm.sqlite3"
        first = VenueStateStore(path, "local-one", b"one")
        second = VenueStateStore(path, "local-two", b"two")
        with first.claim():
            first.bind_account("okx", "okx_demo", "native-42")
        with second.claim(), pytest.raises(ValueError, match="already belongs"):
            second.bind_account("okx", "okx_demo", "native-42")
