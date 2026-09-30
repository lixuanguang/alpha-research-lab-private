"""Exercise durable sends, physical reconciliation and private-stream recovery."""

from __future__ import annotations

# standard library imports
import sqlite3
import threading
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl

# third party library imports
import msgspec
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
from execution import (
    AccountDecision,
    AccountJournal,
    AccountQuote,
    OrderDecision,
    OrderEvent,
    OrderState,
    VenueGateway,
)
from execution.account_state import DispatchLease, _AccountTransaction
from execution.venue_state import VenueState, VenueStateStore
from execution.venues import (
    BitfinexSpotAdapter,
    OKXSpotAdapter,
    TlsVenueHttpTransport,
    VenueCredentials,
)
from execution.venues.contracts import (
    VenueAdapter,
    VenueBalance,
    VenueCapabilityProfile,
    VenueCommandAck,
    VenueFillFact,
    VenueFillPage,
    VenueHttpRequest,
    VenueHttpResponse,
    VenueOrderFact,
    VenueOrderRequest,
    VenueOutcomeUnknownError,
    VenueProtocolError,
    VenueRejectedError,
    VenueStreamEvent,
)
from execution.venues.throttle import VenueRateLimiter
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.catalogs import InstrumentDefinition, ReferenceHistory, VenueSpecification
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec
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

    def wait_for_request_slot(self) -> None:
        """This fixture has no local request budget."""

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

    def receive(self, wait_seconds: float | None = None) -> tuple[bytes, datetime] | None:
        """Authenticate once and then raise a transport-loss error."""
        self.receives += 1
        if self.receives > 1:
            raise VenueOutcomeUnknownError("private connection lost")
        return b"authenticated", self.clock.now()

    def close(self) -> None:
        """Record deterministic socket cleanup."""
        self.closed = True


class ScriptedPrivateSession:
    """Deliver exact private frames once, recording subscriptions and cleanup.

    A None entry is a quiet period: it lasts the gateway's whole requested wait.
    Each frame arrives ``spacing`` seconds after the previous receive returned.
    """

    def __init__(
        self, clock: AdvancingClock, frames: tuple[bytes | None, ...], *, spacing: float = 0.0
    ) -> None:
        """Bind a finite native frame script and its receipt clock."""
        self.clock = clock
        self.frames = frames
        self.spacing = spacing
        self.receipts: list[tuple[bytes, datetime]] = []
        self.received = 0
        self.sent: list[bytes] = []
        self.closed = False

    def open(self, login: bytes, *, configuration: tuple[bytes, ...] = ()) -> None:
        """Accept the signed login and configuration without network access."""
        assert login and configuration

    def send(self, frame: bytes) -> None:
        """Record one subscription frame."""
        self.sent.append(frame)

    def receive(self, wait_seconds: float | None = None) -> tuple[bytes, datetime] | None:
        """Return the next scripted frame at the current receipt clock."""
        if self.received >= len(self.frames):
            raise VenueOutcomeUnknownError("scripted private session is exhausted")
        frame = self.frames[self.received]
        self.received += 1
        if frame is None:
            assert wait_seconds is not None, "quiet period without pending facts"
            self.clock.sleep(wait_seconds)
            return None
        if wait_seconds is not None and self.spacing > wait_seconds:
            # The next frame arrives after the requested wait ends.
            self.received -= 1
            self.clock.sleep(wait_seconds)
            return None
        self.clock.sleep(self.spacing)
        self.receipts.append((frame, self.clock.now()))
        return frame, self.clock.now()

    def close(self) -> None:
        """Record deterministic socket cleanup."""
        self.closed = True


class ReconcileRecordingGateway(VenueGateway):
    """Record when each REST reconciliation starts on the deterministic clock."""

    started: list[datetime]

    def _reconcile(self) -> None:
        """Note the start, then reconcile as usual."""
        if not hasattr(self, "started"):
            self.started = []
        self.started.append(self.clock.now())
        super()._reconcile()


class GuardProbingPause:
    """Advance a fake throttle clock, recording whether the account journal is writable."""

    def __init__(self, journal_path: Path) -> None:
        """Bind the account journal whose write lock each pause probes."""
        self.journal_path = journal_path
        self.now = 0.0
        self.locked = 0
        self.free = 0

    def clock(self) -> float:
        """Expose monotonic seconds that advance only through pauses."""
        return self.now

    def pause(self, seconds: float) -> None:
        """Probe the journal write lock without waiting, then advance the clock."""
        with closing(sqlite3.connect(self.journal_path, timeout=0)) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError:
                self.locked += 1
            else:
                connection.rollback()
                self.free += 1
        self.now += seconds


class NativeExecution(msgspec.Struct, frozen=True):
    """Describe one venue-identified execution of the simulated physical order."""

    identity: int
    at: datetime
    quantity: Decimal
    price: Decimal
    fee: Decimal


class BitfinexSubmitBody(msgspec.Struct, frozen=True):
    """Read the native Bitfinex submit fields the simulated account needs."""

    symbol: str
    amount: str
    price: str
    cid: int


class BitfinexOrderQuery(msgspec.Struct, frozen=True):
    """Read an active-order selector by native ID, client ID/date or everything."""

    id: int | None = None
    cid: int | None = None
    cid_date: str | None = None


class BitfinexTradeQuery(msgspec.Struct, frozen=True):
    """Read the documented trade history time window and ordering."""

    start: int
    end: int
    limit: int
    sort: int


class NativeVenueAccount:
    """Answer documented native REST requests for one simulated test account.

    The account holds one physical buy order and its individually identified
    executions. Fill history applies the venue's own ordering, time window and
    page limit, so paging and retention behavior come from the real adapters.
    """

    order_number = 9001

    def __init__(
        self, venue: Literal["okx", "bitfinex"], clock: AdvancingClock, symbol: str, quote: str
    ) -> None:
        """Start a funded account with no physical order."""
        self.venue, self.clock, self.symbol, self.quote = venue, clock, symbol, quote
        self.cash = Decimal("10000")
        self.base = Decimal(0)
        self.client_id: str | None = None
        self.created_at: datetime | None = None
        self.quantity = Decimal(0)
        self.price = Decimal(0)
        self.cancelled = False
        self.executions: list[NativeExecution] = []
        self.requests: list[VenueHttpRequest] = []
        self.request_times: list[datetime] = []
        # When set, a request to this path signals the first event and waits for the second.
        self.hold: tuple[str, threading.Event, threading.Event] | None = None

    def request(self, request: VenueHttpRequest) -> VenueHttpResponse:
        """Record one signed request and answer it from native account state."""
        if self.hold is not None and request.path == self.hold[0]:
            self.hold[1].set()
            assert self.hold[2].wait(10)
        self.requests.append(request)
        self.request_times.append(self.clock.now())
        body = self._okx(request) if self.venue == "okx" else self._bitfinex(request)
        return VenueHttpResponse(status=200, body=body, received_at=self.clock.now())

    def execute(self, count: int, *, quantity: str, fee: str, per_millisecond: int) -> None:
        """Fill the order with executions that share each millisecond in fixed groups."""
        if self.created_at is None:
            raise AssertionError("simulated execution requires a submitted order")
        first = (
            self.executions[-1].at + timedelta(milliseconds=1)
            if self.executions
            else self.created_at + timedelta(seconds=1)
        )
        for index in range(count):
            execution = NativeExecution(
                identity=7000 + len(self.executions),
                at=first + timedelta(milliseconds=index // per_millisecond),
                quantity=Decimal(quantity),
                price=self.price,
                fee=Decimal(fee),
            )
            self.executions.append(execution)
            self.cash -= execution.quantity * execution.price + execution.fee
            self.base += execution.quantity

    def fill_windows(self) -> tuple[tuple[int, int], ...]:
        """Return each requested fill-history window as inclusive epoch milliseconds."""
        windows: list[tuple[int, int]] = []
        for request in self.requests:
            if self.venue == "bitfinex" and request.path.startswith("/v2/auth/r/trades/"):
                query = msgspec.json.decode(request.body, type=BitfinexTradeQuery)
                windows.append((query.start, query.end))
            elif request.path.startswith("/api/v5/trade/fills-history?"):
                fields = dict(parse_qsl(request.path.partition("?")[2]))
                windows.append((int(fields["begin"]), int(fields["end"])))
        return tuple(windows)

    @property
    def filled(self) -> Decimal:
        """Return the cumulative executed quantity."""
        return sum((item.quantity for item in self.executions), Decimal(0))

    @property
    def is_active(self) -> bool:
        """Report whether the submitted order still rests on the venue."""
        return self.client_id is not None and not self.cancelled and self.filled < self.quantity

    @staticmethod
    def _execution_identity(execution: NativeExecution) -> int:
        """Order OKX bills by their native identity."""
        return execution.identity

    @staticmethod
    def milliseconds(at: datetime) -> int:
        """Encode a UTC instant as integer epoch milliseconds."""
        delta = at - datetime(1970, 1, 1, tzinfo=UTC)
        return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000

    def _submit(self, client_id: str, *, quantity: str, price: str) -> None:
        """Accept exactly one order at a venue clock no earlier than the local send."""
        if self.client_id is not None:
            raise AssertionError("duplicate physical submit reached the simulated venue")
        now = self.clock.now()
        created = self.milliseconds(now) + (1 if now.microsecond % 1000 else 0)
        self.client_id = client_id
        self.created_at = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=created)
        self.quantity, self.price = Decimal(quantity), Decimal(price)

    def _bitfinex(self, request: VenueHttpRequest) -> bytes:
        """Serve paper account info, exchange orders, ascending trades and wallets."""
        path = request.path
        if path == "/v2/auth/r/info/user":
            info: list[object] = [None] * 22
            info[0], info[21] = 42, 1
            return msgspec.json.encode(info)
        if path == "/v2/auth/w/order/submit":
            submit = msgspec.json.decode(request.body, type=BitfinexSubmitBody)
            self._submit(str(submit.cid), quantity=submit.amount, price=submit.price)
            notice = [0, "on-req", None, None, [self._bitfinex_order()], None, "SUCCESS", ""]
            return msgspec.json.encode(notice)
        if path == "/v2/auth/w/order/cancel":
            if not self.is_active:
                raise AssertionError("simulated Bitfinex cancel requires an active order")
            self.cancelled = True
            notice = [0, "oc-req", None, None, self._bitfinex_order(), None, "SUCCESS", ""]
            return msgspec.json.encode(notice)
        if path == "/v2/auth/r/orders":
            query = msgspec.json.decode(request.body, type=BitfinexOrderQuery)
            is_selected = query.id in (None, self.order_number) and query.cid in (
                None,
                None if self.client_id is None else int(self.client_id),
            )
            active = [self._bitfinex_order()] if self.is_active and is_selected else []
            return msgspec.json.encode(active)
        if path == "/v2/auth/r/orders/hist":
            closed = [self._bitfinex_order()] if self.client_id and not self.is_active else []
            return msgspec.json.encode(closed)
        if path == f"/v2/auth/r/trades/{self.symbol}/hist":
            window = msgspec.json.decode(request.body, type=BitfinexTradeQuery)
            if window.sort != 1:
                raise AssertionError("simulated venue serves ascending trade history only")
            rows = [
                self._bitfinex_trade(item)
                for item in self.executions
                if window.start <= self.milliseconds(item.at) <= window.end
            ]
            return msgspec.json.encode(rows[: window.limit])
        if path == "/v2/auth/r/wallets":
            wallets = [
                ["exchange", self.quote, str(self.cash), 0, str(self.cash)],
                ["exchange", "ETH", str(self.base), 0, str(self.base)],
            ]
            return msgspec.json.encode(wallets)
        raise AssertionError(f"unexpected Bitfinex request: {path}")

    def _bitfinex_order(self) -> list[object]:
        """Describe the order in the documented 32-field native array."""
        if self.client_id is None or self.created_at is None:
            raise AssertionError("simulated Bitfinex order is absent")
        remaining = self.quantity - self.filled
        status = (
            "CANCELED"
            if self.cancelled
            else "ACTIVE"
            if not self.filled
            else f"PARTIALLY FILLED @ {self.price}({self.filled})"
            if remaining
            else f"EXECUTED @ {self.price}({self.filled})"
        )
        values: list[object] = [None] * 32
        values[0] = self.order_number
        values[2] = int(self.client_id)
        values[3] = self.symbol
        values[4] = values[5] = self.milliseconds(self.created_at)
        values[6] = str(remaining)
        values[7] = str(self.quantity)
        values[8] = "EXCHANGE LIMIT"
        values[12] = 0
        values[13] = status
        values[16] = str(self.price)
        return values

    def _bitfinex_trade(self, execution: NativeExecution) -> list[object]:
        """Describe one execution with its native negative quote fee."""
        if self.client_id is None:
            raise AssertionError("simulated Bitfinex trade lacks a client identity")
        return [
            execution.identity,
            self.symbol,
            self.milliseconds(execution.at),
            self.order_number,
            str(execution.quantity),
            str(execution.price),
            "EXCHANGE LIMIT",
            str(self.price),
            1,
            str(execution.fee.copy_negate()),
            self.quote,
            int(self.client_id),
        ]

    def _okx(self, request: VenueHttpRequest) -> bytes:
        """Serve demo account mode, orders, newest-first fills and balances."""
        path, _, query_text = request.path.partition("?")
        fields = dict(parse_qsl(query_text))
        data: list[object]
        if path == "/api/v5/account/config":
            data = [{"acctLv": "1", "uid": "42"}]
        elif path == "/api/v5/trade/order" and request.method == "POST":
            submit = msgspec.json.decode(request.body, type=dict[str, str])
            self._submit(submit["clOrdId"], quantity=submit["sz"], price=submit["px"])
            data = [{"sCode": "0", "clOrdId": submit["clOrdId"], "ordId": str(self.order_number)}]
        elif path == "/api/v5/trade/order":
            if self.client_id is None:
                missing = {"code": "51603", "data": [], "msg": "Order does not exist"}
                return msgspec.json.encode(missing)
            data = [self._okx_order()]
        elif path == "/api/v5/trade/orders-pending":
            data = [self._okx_order()] if self.is_active else []
        elif path == "/api/v5/trade/fills-history":
            begin, end, limit = int(fields["begin"]), int(fields["end"]), int(fields["limit"])
            rows = sorted(
                (item for item in self.executions if begin <= self.milliseconds(item.at) <= end),
                key=self._execution_identity,
                reverse=True,
            )
            if "after" in fields:
                rows = [item for item in rows if item.identity < int(fields["after"])]
            data = [self._okx_fill(item) for item in rows[:limit]]
        elif path == "/api/v5/account/balance":
            details: list[object] = []
            for currency, total in ((self.quote, self.cash), ("ETH", self.base)):
                amount = str(total)
                details.append(
                    {"ccy": currency, "cashBal": amount, "availBal": amount, "liab": "0"}
                )
            data = [{"details": details}]
        else:
            raise AssertionError(f"unexpected OKX request: {path}")
        envelope: dict[str, object] = {"code": "0", "data": data, "msg": ""}
        return msgspec.json.encode(envelope)

    def _okx_order(self) -> dict[str, object]:
        """Describe cumulative order state in OKX cash-spot fields."""
        if self.client_id is None or self.created_at is None:
            raise AssertionError("simulated OKX order is absent")
        state = (
            "live"
            if not self.filled
            else "partially_filled"
            if self.filled < self.quantity
            else "filled"
        )
        return {
            "instType": "SPOT",
            "tdMode": "cash",
            "instId": self.symbol,
            "ordId": str(self.order_number),
            "clOrdId": self.client_id,
            "side": "buy",
            "ordType": "limit",
            "sz": str(self.quantity),
            "accFillSz": str(self.filled),
            "px": str(self.price),
            "state": state,
            "cTime": str(self.milliseconds(self.created_at)),
        }

    def _okx_fill(self, execution: NativeExecution) -> dict[str, object]:
        """Describe one bill-identified execution with its native negative fee."""
        return {
            "instType": "SPOT",
            "instId": self.symbol,
            "ordId": str(self.order_number),
            "clOrdId": self.client_id,
            "billId": str(execution.identity),
            "side": "buy",
            "fillSz": str(execution.quantity),
            "fillPx": str(execution.price),
            "fee": str(execution.fee.copy_negate()),
            "feeCcy": self.quote,
            "fillTime": str(self.milliseconds(execution.at)),
        }


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
        return (
            journal,
            gateway,
            adapter,
            clock,
            self._authorization(config, enabled=True),
            self._admit(journal, config, clock),
        )

    def _admit(
        self, journal: AccountJournal, config: VenueExecutionConfiguration, clock: AdvancingClock
    ) -> str:
        """Reserve one independently quoted two-unit buy and return its order identity."""
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
        return admitted.orders[0].identity

    def _native_gateway(
        self, tmp_path: Path, venue: Literal["okx", "bitfinex"]
    ) -> tuple[AccountJournal, VenueGateway, NativeVenueAccount, AdvancingClock]:
        """Reconcile an empty account through a real adapter and simulated native venue."""
        config = self._config(venue)
        clock = AdvancingClock(self.at + timedelta(seconds=10))
        instrument = config.instruments[0]
        account = NativeVenueAccount(
            venue, clock, instrument.native_symbol, instrument.quote_currency.code
        )
        adapter: VenueAdapter = (
            BitfinexSpotAdapter(VenueCredentials("key", "secret"), account)
            if venue == "bitfinex"
            else OKXSpotAdapter(VenueCredentials("key", "secret", "pass"), account)
        )
        journal = AccountJournal(tmp_path / "account.sqlite3", config.account)
        gateway = VenueGateway(journal, config, adapter, clock=clock)
        assert not gateway.reconcile().recovery_required
        return journal, gateway, account, clock

    def _native(
        self, tmp_path: Path, venue: Literal["okx", "bitfinex"]
    ) -> tuple[AccountJournal, VenueGateway, NativeVenueAccount, AdvancingClock, str]:
        """Reconcile and send one reference order through a real adapter and native account."""
        journal, gateway, account, clock = self._native_gateway(tmp_path, venue)
        order_id = self._admit(journal, gateway.config, clock)
        authorization = self._authorization(gateway.config, enabled=True)
        assert gateway.submit(order_id, authorization).submission_attempted
        return journal, gateway, account, clock, order_id

    def test_stop_before_arming_sends_nothing(self, tmp_path: Path) -> None:
        """An operator stop committed before the final check leaves zero submit requests."""
        journal, gateway, account, clock = self._native_gateway(tmp_path, "bitfinex")
        order_id = self._admit(journal, gateway.config, clock)
        journal.block(gateway.config.account_id, "operator-stop")
        with pytest.raises(ValueError, match="dispatch is blocked"):
            gateway.submit(order_id, self._authorization(gateway.config, enabled=True))
        assert not any(item.path == "/v2/auth/w/order/submit" for item in account.requests)

    @pytest.mark.parametrize("venue", ["okx", "bitfinex"])
    @pytest.mark.parametrize("trigger", ["operator_stop", "other_lease"])
    def test_dispatch_refused_before_sending_is_recorded_not_sent(
        self, tmp_path: Path, venue: Literal["okx", "bitfinex"], trigger: str
    ) -> None:
        """A refusal before the send rejects the order locally instead of wedging reconcile."""
        journal, gateway, account, clock = self._native_gateway(tmp_path, venue)
        order_id = self._admit(journal, gateway.config, clock)
        account_id = gateway.config.account_id
        if trigger == "operator_stop":
            journal.block(account_id, "operator-stop")
            refusal = "dispatch is blocked"
        else:
            now = datetime.now(UTC)
            with journal._store.write() as transaction:
                transaction.arm_lease(
                    DispatchLease(
                        order_id="other-order",
                        account_id=account_id,
                        instance_ids=("reference-instance",),
                        holder="other-holder",
                        armed_at=now,
                        deadline=now + VenueGateway.DISPATCH_LEASE,
                    )
                )
            refusal = "another dispatch is in progress"
        sent = len(account.requests)
        with pytest.raises(ValueError, match=refusal):
            gateway.submit(order_id, self._authorization(gateway.config, enabled=True))
        submit_path = "/api/v5/trade/order" if venue == "okx" else "/v2/auth/w/order/submit"
        assert not any(
            item.path == submit_path and item.method == "POST" for item in account.requests[sent:]
        )
        assert self._order_state(journal, order_id).status == "rejected"
        assert journal.accounts()[0].fault == "venue_unavailable:dispatch_not_sent"
        if trigger == "other_lease":
            with journal._store.write() as transaction:
                transaction.release_lease("other-order", "other-holder")
        # The unsent order no longer needs venue history, so reconcile matches.
        assert not gateway.reconcile().recovery_required
        assert self._order_state(journal, order_id).status == "rejected"

    def test_send_blocked_in_transport_holds_no_journal_lock(self, tmp_path: Path) -> None:
        """Other writers commit during a pending send; a stop waits for it to finish."""
        journal, gateway, account, clock = self._native_gateway(tmp_path, "bitfinex")
        order_id = self._admit(journal, gateway.config, clock)
        sending, release = threading.Event(), threading.Event()
        account.hold = ("/v2/auth/w/order/submit", sending, release)
        failures: list[BaseException] = []
        stopped = threading.Event()

        def submit() -> None:
            """Send from the gateway's own thread."""
            try:
                gateway.submit(order_id, self._authorization(gateway.config, enabled=True))
            except BaseException as error:
                failures.append(error)

        def stop() -> None:
            """Issue an operator stop while the send is pending."""
            journal.block(gateway.config.account_id, "operator-stop")
            stopped.set()

        sender = threading.Thread(target=submit)
        sender.start()
        assert sending.wait(10)
        # Before dispatch leases this write failed with "database is locked".
        price = Price(
            value=Decimal("100"),
            currency=gateway.config.instruments[0].quote_currency,
            per=self.dimension,
        )
        journal.observe(AccountQuote(price=price, at=clock.now()))
        stopper = threading.Thread(target=stop)
        stopper.start()
        assert not stopped.wait(0.3)
        release.set()
        sender.join(10)
        assert stopped.wait(10) and not failures
        stopper.join(10)
        assert self._order_state(journal, order_id).request_acknowledged
        assert journal.accounts()[0].operator_block == "operator-stop"

    def test_transport_total_bound_fits_the_dispatch_lease(self) -> None:
        """A send started within its window ends before the lease any stop waits for."""
        transport = TlsVenueHttpTransport("bitfinex")
        window = VenueGateway.DISPATCH_SEND_WINDOW.total_seconds()
        assert window + transport.total_seconds <= VenueGateway.DISPATCH_LEASE.total_seconds()

    def test_throttle_waits_outside_the_account_write_fence(self, tmp_path: Path) -> None:
        """A full local request budget never sleeps while dispatch holds the account journal."""
        journal, gateway, _, clock = self._native_gateway(tmp_path, "bitfinex")
        adapter = gateway.adapter
        assert isinstance(adapter, BitfinexSpotAdapter)
        probe = GuardProbingPause(journal.path)
        # One request per window: every request, including the send, needs a wait.
        adapter.throttle = VenueRateLimiter(
            requests=1, seconds=60.0, clock=probe.clock, pause=probe.pause
        )
        order_id = self._admit(journal, gateway.config, clock)
        authorization = self._authorization(gateway.config, enabled=True)
        assert gateway.submit(order_id, authorization).submission_attempted
        assert probe.free > 0 and probe.locked == 0
        submitted = probe.free
        gateway.cancel(order_id, authorization)
        assert self._order_state(journal, order_id).status == "cancel_ack"
        assert probe.free > submitted and probe.locked == 0

    def test_bitfinex_private_session_survives_flat_account_snapshots(self, tmp_path: Path) -> None:
        """Documented snapshots after authentication neither end nor break the session."""
        _, gateway, account, clock = self._native_gateway(tmp_path, "bitfinex")
        frames = (
            b'{"event":"info","version":2,"platform":{"status":1}}',
            b'{"event":"conf","status":"OK","flags":65536}',
            b'{"event":"auth","status":"OK","userId":42}',
            b'[0,"ps",[],1]',
            b'[0,"ws",[["exchange","USD",10000,0,null],["exchange","ETH",0,0,null]],2]',
            b'[0,"os",[],3]',
            b'[0,"fos",[],4]',
            b'[0,"fcs",[],5]',
            b'[0,"fls",[],6]',
            b'[0,"bu",[10000,10000],7]',
            b'[0,"hb",8]',
        )
        session = ScriptedPrivateSession(clock, frames)
        requests = len(account.requests)
        view = gateway.stream(session, max_messages=len(frames), duration_seconds=3600)
        assert session.received == len(frames) and session.closed
        assert view.reason == "private_stream_closed"
        # Authentication reconciles at once; the snapshots coalesce into one at exit.
        assert sum(item.path == "/v2/auth/r/wallets" for item in account.requests[requests:]) == 2

    @staticmethod
    def _bitfinex_prefix() -> list[bytes | None]:
        """Authenticate and deliver flat snapshots, numbered from sequence 1."""
        return [
            b'{"event":"info","version":2,"platform":{"status":1}}',
            b'{"event":"conf","status":"OK","flags":65536}',
            b'{"event":"auth","status":"OK","userId":42}',
            b'[0,"ps",[],1]',
            b'[0,"os",[],2]',
        ]

    @staticmethod
    def _bitfinex_fill(account: NativeVenueAccount, sequence: int) -> list[bytes | None]:
        """Encode one execution's native on/te/tu/wu frames from the next sequence."""
        trade = account._bitfinex_trade(account.executions[-1])
        wallet = ["exchange", account.quote, str(account.cash), 0, str(account.cash)]
        payloads: list[tuple[str, object]] = [
            ("ou", account._bitfinex_order()),
            ("te", trade),
            ("tu", trade),
            ("wu", wallet),
        ]
        frames: list[bytes | None] = []
        for index, (kind, body) in enumerate(payloads):
            frame: list[object] = [0, kind, body, sequence + index]
            frames.append(msgspec.json.encode(frame))
        return frames

    def _wallet_reads(self, account: NativeVenueAccount, start: int) -> int:
        """Count REST wallet reads, one per reconciliation, since a request index."""
        return sum(item.path == "/v2/auth/r/wallets" for item in account.requests[start:])

    def test_one_fill_burst_reconciles_once(self, tmp_path: Path) -> None:
        """The four private frames of one fill cause exactly one REST reconciliation."""
        journal, gateway, account, clock, order_id = self._native(tmp_path, "bitfinex")
        account.execute(1, quantity="2", fee="0.01", per_millisecond=1)
        frames = [*self._bitfinex_prefix(), None, *self._bitfinex_fill(account, 3), None]
        frames.append(b'[0,"hb",7]')
        session = ScriptedPrivateSession(clock, tuple(frames), spacing=0.01)
        start = len(account.requests)
        gateway.stream(session, max_messages=8, duration_seconds=3600)
        # Authentication, the snapshots after a quiet second, and the fill burst.
        assert self._wallet_reads(account, start) == 3
        assert self._order_state(journal, order_id).status == "filled"
        stream = [item for item in account.requests[start:] if item.path.startswith("/v2/auth/")]
        per_fill = len(stream) // 3
        print(f"REST requests per coalesced reconciliation: {per_fill}")

    def test_coalesced_stream_matches_per_frame_reconciliation(self, tmp_path: Path) -> None:
        """Reconciling after every fact frame or once per burst ends in the same state."""
        outcomes = []
        for label, quiet_after_each in (("coalesced", False), ("per-frame", True)):
            journal, gateway, account, clock, order_id = self._native(tmp_path / label, "bitfinex")
            account.execute(1, quantity="0.5", fee="0.01", per_millisecond=1)
            fill = self._bitfinex_fill(account, 3)
            frames = [*self._bitfinex_prefix(), None]
            for frame in fill:
                frames.append(frame)
                if quiet_after_each and frame is not None and b'"te"' not in frame:
                    frames.append(None)
            if not quiet_after_each:
                frames.append(None)
            frames.append(b'[0,"hb",7]')
            session = ScriptedPrivateSession(clock, tuple(frames), spacing=0.01)
            gateway.stream(session, max_messages=8, duration_seconds=3600)
            state = self._order_state(journal, order_id)
            snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
            venue = gateway.inspect()
            outcomes.append(
                (state.status, state.filled, snapshot, venue.recovery_required, venue.reason)
            )
        assert outcomes[0] == outcomes[1]
        assert outcomes[0][0] == "partial"

    def test_continuous_facts_reconcile_within_the_maximum_delay(self, tmp_path: Path) -> None:
        """Facts closer together than the quiet period still reconcile every ten seconds."""
        journal, gateway, account, clock = self._native_gateway(tmp_path, "bitfinex")
        recording = ReconcileRecordingGateway(journal, gateway.config, gateway.adapter, clock=clock)
        frames = self._bitfinex_prefix()
        wallet: list[object] = ["exchange", account.quote, str(account.cash), 0, str(account.cash)]
        for index in range(60):
            update: list[object] = [0, "wu", wallet, 3 + index]
            frames.append(msgspec.json.encode(update))
        session = ScriptedPrivateSession(clock, tuple(frames), spacing=0.5)
        recording.stream(session, max_messages=len(frames), duration_seconds=3600)
        # A flat position snapshot decodes as a heartbeat; the rest are facts.
        facts = [
            at for raw, at in session.receipts if raw.startswith(b"[0,") and b'"ps"' not in raw
        ]
        authenticated, *starts = recording.started
        # Mid-stream reconciliations, then the one at exit.
        assert len(starts) >= 3
        for previous, started in zip((authenticated, *starts), starts[:-1], strict=False):
            pending = [at for at in facts if previous < at <= started]
            assert pending and started - pending[0] <= VenueGateway.PRIVATE_MAX_PENDING
            assert started - pending[-1] < VenueGateway.PRIVATE_QUIET
        # Bitfinex allows 80 authenticated REST requests per minute.
        times = account.request_times
        busiest = max(
            sum(1 for later in times if at <= later < at + timedelta(minutes=1)) for at in times
        )
        assert busiest <= 80

    def test_sequence_gap_with_pending_facts_aborts_without_reconciling(
        self, tmp_path: Path
    ) -> None:
        """A gap still ends the session at once; pending facts are left to recovery."""
        _, gateway, account, clock, _ = self._native(tmp_path, "bitfinex")
        account.execute(1, quantity="2", fee="0.01", per_millisecond=1)
        fill = self._bitfinex_fill(account, 3)
        frames = [*self._bitfinex_prefix(), None, fill[0], b'[0,"hb",9]']
        session = ScriptedPrivateSession(clock, tuple(frames), spacing=0.01)
        start = len(account.requests)
        with pytest.raises(VenueProtocolError, match="new authenticated session"):
            gateway.stream(session, max_messages=10, duration_seconds=3600)
        assert self._wallet_reads(account, start) == 2
        assert gateway.inspect().recovery_required and session.closed

    def test_session_end_reconciles_pending_facts(self, tmp_path: Path) -> None:
        """Facts still pending when the message bound ends are reconciled before exit."""
        journal, gateway, account, clock, order_id = self._native(tmp_path, "bitfinex")
        account.execute(1, quantity="2", fee="0.01", per_millisecond=1)
        frames = [*self._bitfinex_prefix(), None, *self._bitfinex_fill(account, 3)]
        session = ScriptedPrivateSession(clock, tuple(frames), spacing=0.01)
        start = len(account.requests)
        gateway.stream(session, max_messages=9, duration_seconds=3600)
        assert self._wallet_reads(account, start) == 3
        assert self._order_state(journal, order_id).status == "filled"

    @staticmethod
    def _order_state(journal: AccountJournal, order_id: str) -> OrderState:
        """Read one direct order's current lifecycle state."""
        return next(item.order for item in journal.orders() if item.order.identity == order_id)

    def test_bitfinex_fill_history_pages_past_one_hundred_executions(self, tmp_path: Path) -> None:
        """Executions beyond one page, split inside a millisecond, post exactly once."""
        journal, gateway, account, clock, order_id = self._native(tmp_path, "bitfinex")
        # Seven executions share each millisecond, so the first full page of one
        # hundred ends inside a millisecond whose last executions it omits.
        account.execute(150, quantity="0.01", fee="0.01", per_millisecond=7)
        clock.sleep(60)
        assert not gateway.reconcile().recovery_required
        assert self._order_state(journal, order_id).filled.value == Decimal("1.50")
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert snapshot.positions[0].value == Decimal("1.50")
        assert next(fee.value for fee in snapshot.fees if fee.currency.code == "USD") == Decimal(
            "1.50"
        )
        windows = account.fill_windows()
        boundary = account.milliseconds(account.executions[99].at)
        assert windows[-2][0] < boundary and windows[-1][0] == boundary

    @pytest.mark.parametrize("venue", ["okx", "bitfinex"])
    def test_terminal_history_outlives_lookup_and_fill_retention(
        self, tmp_path: Path, venue: Literal["okx", "bitfinex"]
    ) -> None:
        """A dispatch past 13 days and an account past 89 days still reconcile."""
        journal, gateway, account, clock, order_id = self._native(tmp_path, venue)
        account.execute(1, quantity="2", fee="0.01", per_millisecond=1)
        clock.sleep(60)
        assert not gateway.reconcile().recovery_required
        assert self._order_state(journal, order_id).status == "filled"
        # Bitfinex closed-order lookups cannot prove outcomes older than 13 days.
        clock.sleep(14 * 86_400)
        assert not gateway.reconcile().recovery_required
        # OKX fill history refuses windows reaching back more than 89 days.
        clock.sleep(76 * 86_400)
        assert not gateway.reconcile().recovery_required
        start, end = account.fill_windows()[-1]
        opening = account.milliseconds(gateway.config.account.opening_at)
        assert end - opening > 89 * 86_400_000 > end - start
        assert self._order_state(journal, order_id).status == "filled"

    def test_bitfinex_order_resting_past_closed_retention_still_reconciles(
        self, tmp_path: Path
    ) -> None:
        """Active orders prove a resting order at any age; only closed lookups stay bounded."""
        journal, gateway, account, clock, order_id = self._native(tmp_path, "bitfinex")
        account.execute(1, quantity="0.5", fee="0.01", per_millisecond=1)
        clock.sleep(14 * 86_400)
        assert not gateway.reconcile().recovery_required
        assert self._order_state(journal, order_id).filled.value == Decimal("0.5")
        # Once it closes, absence from active orders past closed-order retention proves nothing.
        account.cancelled = True
        requests = len(account.requests)
        with pytest.raises(VenueProtocolError, match="closed-order retention"):
            gateway.reconcile()
        paths = [item.path for item in account.requests[requests:]]
        assert "/v2/auth/r/orders/hist" not in paths

    def test_fill_history_resumes_from_the_last_matched_window(self, tmp_path: Path) -> None:
        """A durable mark bounds later fill reads and advances only on a matched account."""
        journal, gateway, account, clock, _ = self._native(tmp_path, "okx")
        account.execute(1, quantity="0.5", fee="0.01", per_millisecond=1)
        clock.sleep(5 * 3600)
        assert not gateway.reconcile().recovery_required
        matched_end = account.fill_windows()[-1][1]
        clock.sleep(5 * 3600)
        # An unexplained physical deposit is a break, so its window proves nothing new.
        account.cash += Decimal("1")
        assert gateway.reconcile().recovery_required
        account.cash -= Decimal("1")
        clock.sleep(5 * 3600)
        restarted = VenueGateway(journal, gateway.config, gateway.adapter, clock=clock)
        assert not restarted.reconcile().recovery_required
        assert account.fill_windows()[-1][0] == matched_end - 3_600_000
        opening = account.milliseconds(gateway.config.account.opening_at)
        assert all(start > opening for start, _ in account.fill_windows()[-2:])

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

    @staticmethod
    def _locked_release(journal: AccountJournal, monkeypatch: pytest.MonkeyPatch) -> None:
        """Make the guard's lease release time out as if another writer held the lock."""

        def release_lease(self: _AccountTransaction, order_id: str, holder: str) -> None:
            """Time out the guard's release as if another writer held the lock."""
            # The orphaned lease is dropped once its deadline passes; jump past it.
            journal._clock = lambda: datetime.now(UTC) + VenueGateway.DISPATCH_LEASE
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(_AccountTransaction, "release_lease", release_lease)

    def test_failed_lease_release_keeps_the_venue_rejection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A release timing out after a definite reject cannot hide the reject."""
        journal, gateway, adapter, _, authorization, order_id = self._ready(tmp_path)
        adapter.reject = True
        self._locked_release(journal, monkeypatch)
        with pytest.raises(VenueRejectedError) as raised:
            gateway.submit(order_id, authorization)
        assert any("lease release failed" in note for note in raised.value.__notes__)
        assert journal.orders()[0].order.status == "rejected"
        assert journal.accounts()[0].fault == "venue_unavailable:venue_rejected_submission"

    def test_failed_lease_release_keeps_the_acknowledgement(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A release timing out after a sent order still records its acknowledgement."""
        journal, gateway, adapter, _, authorization, order_id = self._ready(tmp_path)
        self._locked_release(journal, monkeypatch)
        assert gateway.submit(order_id, authorization).submission_attempted
        assert journal.orders()[0].order.request_acknowledged
        assert adapter.submit_count == 1

    def test_journal_lock_timeout_before_the_send_faults_the_account(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A SQLite error inside submit faults the account instead of escaping the fence."""
        journal, gateway, adapter, _, authorization, order_id = self._ready(tmp_path)
        apply_event = journal.apply_event

        def locked_unknown(event: OrderEvent) -> None:
            """Time out the "unknown" event write; apply every other event."""
            if event.kind == "unknown":
                raise sqlite3.OperationalError("database is locked")
            apply_event(event)

        monkeypatch.setattr(journal, "apply_event", locked_unknown)
        with pytest.raises(sqlite3.OperationalError):
            gateway.submit(order_id, authorization)
        assert adapter.submit_count == 0
        assert journal.orders()[0].order.status == "rejected"
        assert journal.accounts()[0].fault == "venue_unavailable:dispatch_not_sent"

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

    def test_old_venue_state_schema_is_refused(self, tmp_path: Path) -> None:
        """A saved state in the removed version 1 schema is refused, never upgraded."""
        store = VenueStateStore(tmp_path / "account.sqlite3", "account", b"scope")
        codec = DomainCodec()
        with store.claim():
            old = codec.encode_json(VenueState(nonce=7)).replace(
                b'"schema_version":"venue-journal"', b'"schema_version":"venue-journal-unsupported"'
            )
            with closing(sqlite3.connect(store.path)) as connection, connection:
                connection.execute("UPDATE state SET payload=? WHERE id=1", (old,))
            with pytest.raises(ValueError, match="unsupported venue journal schema"):
                store.read()

    def test_same_physical_wallet_cannot_fund_two_local_accounts(self, tmp_path: Path) -> None:
        """Independent aliases cannot duplicate one authenticated account's funding."""
        path = tmp_path / "firm.sqlite3"
        first = VenueStateStore(path, "local-one", b"one")
        second = VenueStateStore(path, "local-two", b"two")
        with first.claim():
            first.bind_account("okx", "okx_demo", "native-42")
        with second.claim(), pytest.raises(ValueError, match="already belongs"):
            second.bind_account("okx", "okx_demo", "native-42")
