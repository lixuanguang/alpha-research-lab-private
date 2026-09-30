"""Reconcile test-venue facts and dispatch already reserved physical orders once."""

from __future__ import annotations

# standard library imports
import hashlib
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

# third party library imports
from msgspec.structs import replace

# project library imports
from configuration import (
    CapabilityBinding,
    CapabilityRequirement,
    VenueAuthorization,
    VenueExecutionConfiguration,
    VenueInstrument,
)
from execution.account_records import NativeFill, PhysicalAccountObservation
from execution.accounts import AccountJournal
from execution.records import EventKind, OrderEvent, OrderState
from execution.venue_state import VenueDispatch, VenueStateStore
from execution.venues.contracts import (
    VenueAdapter,
    VenueCommandAck,
    VenueFillFact,
    VenueOrderFact,
    VenueOrderRequest,
    VenueProtocolError,
    VenueRejectedError,
)
from financial_units import Money, Price, Quantity
from risk import SpotLimits
from serialization import DomainCodec, WireRecord


class VenueClock(Protocol):
    """Supply UTC and bounded waits independently of strategy decision clocks."""

    def now(self) -> datetime:
        """Read current UTC knowledge time."""

    def sleep(self, seconds: float) -> None:
        """Wait for the durable conservative request-rate interval."""


class VenuePrivateConnection(Protocol):
    """Expose a bounded private socket without coupling the gateway to a vendor."""

    def open(self, login: bytes, *, configuration: tuple[bytes, ...] = ()) -> None:
        """Connect and send the explicit login/configuration frames."""

    def send(self, frame: bytes) -> None:
        """Send a selected subscription frame."""

    def receive(self, wait_seconds: float | None = None) -> tuple[bytes, datetime] | None:
        """Receive one bounded native frame with actual UTC receipt.

        With ``wait_seconds``, return None if no frame arrives within it; stream
        loss keeps its own bound and still raises.
        """

    def close(self) -> None:
        """Close the socket without changing any account economics."""


class SystemVenueClock:
    """Read the operating clock and wait without retrying protocol requests."""

    def now(self) -> datetime:
        """Return actual UTC wall-clock time."""
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        """Wait at most one configured venue request interval."""
        time.sleep(seconds)


class GatewayView(WireRecord, frozen=True):
    """Expose transport and account state without credentials or raw private data."""

    account_id: str
    venue: str
    environment: str
    config_sha256: str
    recovery_required: bool
    reason: str
    reconciled_at: datetime | None
    dispatches: tuple[VenueDispatch, ...]
    receipt_count: int
    submission_attempted: bool = False
    qualification: str = "software-only"


class VenueGateway:
    """Own one account's fenced test transport and replayable native receipts.

    Strategies cannot submit arbitrary payloads: only physical orders already
    reserved by AccountJournal can cross this boundary. Every attempted client
    identity is permanently consumed before network I/O. Missing history or an
    absent lookup preserves uncertainty; it never permits a retry to send again.
    """

    # Later fill reads restart this long before the last matched window's end, so
    # executions the venue published late, or stamped ahead of the local clock,
    # are still read. Repeated executions are applied once by identity.
    _FILL_HISTORY_OVERLAP = timedelta(hours=1)
    # One fill arrives as several private frames (Bitfinex on/te/tu/wu) well
    # within a second; reconcile once the stream is that quiet, and at least
    # this often while facts keep arriving.
    # A submission's lease covers the time to start its send plus the transport's
    # total bound (TlsVenueHttpTransport.total_seconds).
    DISPATCH_SEND_WINDOW = timedelta(seconds=10)
    DISPATCH_LEASE = timedelta(seconds=30)
    PRIVATE_QUIET = timedelta(seconds=1)
    PRIVATE_MAX_PENDING = timedelta(seconds=10)

    def __init__(
        self,
        journal: AccountJournal,
        config: VenueExecutionConfiguration,
        adapter: VenueAdapter | None = None,
        *,
        clock: VenueClock | None = None,
    ) -> None:
        """Bind exact account/configuration identity and an explicit protocol adapter."""
        config.__post_init__()
        if journal.config != config.account:
            raise ValueError("venue and account journal configurations differ")
        self.journal, self.config, self.adapter = journal, config, adapter
        self.clock: VenueClock = clock if clock is not None else SystemVenueClock()
        self._codec = DomainCodec()
        self._store = VenueStateStore(
            journal.path,
            config.account_id,
            self._codec.encode_json((str(journal.path.resolve()), config)),
        )

    def inspect(self) -> GatewayView:
        """Read retained state without resolving credentials or contacting a venue."""
        with self._store.claim():
            return self._view()

    def reconcile(self) -> GatewayView:
        """Recover individual fills and compare complete physical orders and balances."""
        with self._store.claim():
            try:
                self._reconcile()
            except (OSError, RuntimeError, ValueError) as error:
                self._fault(type(error).__name__)
                raise
            return self._view()

    def submit(self, order_id: str, authorization: VenueAuthorization) -> GatewayView:
        """Reconcile, revalidate risk/authority and attempt a reserved order once."""
        adapter = self._adapter()
        with self._store.claim():
            order = self._order(order_id)
            instrument = self._instrument(order)
            authorization.authorize(
                self.config,
                self.clock.now(),
                instrument.dimension.instrument_id,
                order.intent.limit.amount(order.intent.quantity),
            )
            if any(item.order_id == order_id for item in self._store.read().dispatches):
                # Even an absent exchange lookup is not proof of a failed send.
                try:
                    self._reconcile()
                except (OSError, RuntimeError, ValueError) as error:
                    self._fault(type(error).__name__)
                    raise
                return self._view()
            fault: str | None = None
            try:
                self._reconcile()
                if self._store.read().recovery_required:
                    raise ValueError("venue reconciliation is required before submission")
                at, nonce = self._request_clock()
                authorization.authorize(
                    self.config,
                    at,
                    instrument.dimension.instrument_id,
                    order.intent.limit.amount(order.intent.quantity),
                )
                self._reference(order, instrument, at)
                client_id = self._client_id(order_id)
                request = VenueOrderRequest(
                    client_id=client_id,
                    symbol=instrument.native_symbol,
                    side=order.intent.side,
                    quantity=order.intent.quantity.value,
                    limit_price=order.intent.limit.value,
                    time_in_force="ioc" if order.intent.time_in_force == "ioc" else "gtc",
                    post_only=order.intent.time_in_force == "post-only",
                )
                state = self._store.read()
                dispatch = VenueDispatch(
                    order_id=order_id,
                    client_id=client_id,
                    symbol=instrument.native_symbol,
                    submitted_at=at,
                    request=self._codec.encode_json(request),
                )
                dispatches: tuple[VenueDispatch, ...] = (*state.dispatches, dispatch)
                self._store.save(
                    replace(
                        state,
                        dispatches=dispatches,
                        recovery_required=True,
                        reason="submission_outcome_unknown",
                    )
                )
                # Set immediately before the single send: whatever fails while it is
                # unset left no bytes, and whatever fails after it may have.
                sent = False
                try:
                    self._event(order_id, "unknown", at, f"send:{client_id}")
                    # Throttle sleeps happen here, never under the journal write fence.
                    adapter.wait_for_request_slot()
                    with self.journal.execution_guard(
                        self.config.account_id,
                        order_id,
                        at,
                        clock=self.clock.now,
                        lease=self.DISPATCH_LEASE,
                        send_window=self.DISPATCH_SEND_WINDOW,
                    ) as permit:
                        send_at = self.clock.now()
                        authorization.authorize(
                            self.config,
                            send_at,
                            instrument.dimension.instrument_id,
                            order.intent.limit.amount(order.intent.quantity),
                        )
                        self._reference(order, instrument, send_at)
                        permit.require_sendable()
                        sent = True
                        ack = adapter.submit(request, at=send_at, nonce=nonce)
                except VenueRejectedError:
                    self._reject(order_id, client_id)
                    self._fault("venue_rejected_submission")
                    raise
                except BaseException:
                    if not sent:
                        # Definitely unsent: reconcile resolves it without venue history.
                        self._reject(order_id, client_id)
                        fault = "dispatch_not_sent"
                    raise
                self._ack(dispatch, ack)
            except (OSError, RuntimeError, ValueError) as error:
                self._fault(fault or type(error).__name__)
                raise
            return self._view(submission_attempted=True)

    def _reject(self, order_id: str, client_id: str) -> None:
        """Record a dispatch that never reached, or was refused by, the venue.

        The venue-store flag is written first: it is the durable record, and
        reconcile rebuilds the local ``rejected`` event from it.
        """
        state = self._store.read()
        dispatches: tuple[VenueDispatch, ...] = tuple(
            replace(item, submission_rejected=True) if item.order_id == order_id else item
            for item in state.dispatches
        )
        self._store.save(replace(state, dispatches=dispatches))
        self._event(order_id, "rejected", self.clock.now(), f"reject:{client_id}")

    def cancel(self, order_id: str, authorization: VenueAuthorization) -> GatewayView:
        """Request cancellation while retaining exposure until a venue terminal fact."""
        adapter = self._adapter()
        with self._store.claim():
            order = self._order(order_id)
            instrument = self._instrument(order)
            authorization.authorize(
                self.config,
                self.clock.now(),
                instrument.dimension.instrument_id,
                None,
                cancel=True,
            )
            dispatch = self._dispatch(order_id=order_id)
            if order.is_terminal:
                return self._view()
            # A new explicit cancel may proceed only after a prior uncertain
            # attempt has been observed as still open in a complete snapshot.
            if dispatch.cancel_attempted:
                try:
                    self._reconcile()
                except (OSError, RuntimeError, ValueError) as error:
                    self._fault(type(error).__name__)
                    raise
                order = self._order(order_id)
                dispatch = self._dispatch(order_id=order_id)
                if self._store.read().recovery_required or order.is_terminal:
                    return self._view()
            try:
                self._qualify()
                at, nonce = self._request_clock()
            except (OSError, RuntimeError, ValueError) as error:
                self._fault(type(error).__name__)
                raise
            state = self._store.read()
            updated = replace(
                dispatch, cancel_attempted=True, cancel_attempts=dispatch.cancel_attempts + 1
            )
            dispatches: tuple[VenueDispatch, ...] = tuple(
                updated if item == dispatch else item for item in state.dispatches
            )
            self._store.save(
                replace(
                    state,
                    dispatches=dispatches,
                    recovery_required=True,
                    reason="cancellation_outcome_unknown",
                )
            )
            if not order.cancel_requested:
                self._event(order_id, "cancel_requested", at, f"cancel:{dispatch.client_id}")
            try:
                adapter.wait_for_request_slot()
                with self.journal.execution_guard(
                    self.config.account_id, order_id, at, cancel=True
                ):
                    ack = adapter.cancel(
                        dispatch.symbol,
                        dispatch.client_id,
                        submitted_at=dispatch.submitted_at,
                        venue_order_id=dispatch.venue_order_id,
                        at=at,
                        nonce=nonce,
                    )
                self._ack(updated, ack, attempt=updated.cancel_attempts)
            except (OSError, RuntimeError, ValueError) as error:
                self._fault(type(error).__name__)
                raise
            return self._view()

    def stream(
        self,
        session: VenuePrivateConnection,
        *,
        max_messages: int,
        duration_seconds: float,
    ) -> GatewayView:
        """Consume bounded private input, reconciling recovery and fencing on exit.

        Private pushes are retained observations, not proof of complete history.
        Economic updates mark the account stale and trigger one REST fill/order/
        wallet reconciliation once the stream is quiet for ``PRIVATE_QUIET``, at
        least every ``PRIVATE_MAX_PENDING`` while facts continue, and before a
        normal exit. Authentication reconciles at once; recovery frames, sequence
        gaps and malformed frames end the session at once.
        Loss, malformed input or end of this supervised session invalidates account
        freshness; the next dispatch must recover through independent observations.
        """
        if type(max_messages) is not int or not 0 < max_messages <= 100_000:
            raise ValueError("private stream requires a bounded positive message count")
        if not 0 < duration_seconds <= 3600:
            raise ValueError("private stream duration must be within one hour")
        adapter = self._adapter()
        with self._store.claim():
            self._fault("private_stream_starting")
            authenticated = False
            try:
                self._qualify()
                at, nonce = self._request_clock()
                session.open(
                    adapter.private_login(at=at, nonce=nonce),
                    configuration=adapter.private_configuration(),
                )
                deadline = self.clock.now() + timedelta(seconds=duration_seconds)
                # Facts received since the last reconciliation: first and latest receipt.
                pending: tuple[datetime, datetime] | None = None
                messages = 0
                while messages < max_messages:
                    now = self.clock.now()
                    if now >= deadline:
                        break
                    wait: float | None = None
                    if pending is not None:
                        due = min(
                            pending[1] + self.PRIVATE_QUIET, pending[0] + self.PRIVATE_MAX_PENDING
                        )
                        if now >= due:
                            self._reconcile()
                            pending = None
                            continue
                        wait = (due - now).total_seconds()
                    received = session.receive(wait)
                    if received is None:
                        continue
                    messages += 1
                    raw, received_at = received
                    event = adapter.decode_private(raw, received_at=received_at)
                    self._store.receipt("private-frame", raw, received_at)
                    if event.kind == "authenticated":
                        if authenticated:
                            raise VenueProtocolError("duplicate private authentication boundary")
                        authenticated = True
                        for frame in adapter.private_subscriptions():
                            session.send(frame)
                        self._reconcile()
                        pending = None
                    elif event.kind == "recovery_required":
                        raise VenueProtocolError(
                            "private stream requires a new authenticated session"
                        )
                    elif event.kind != "heartbeat":
                        if not authenticated:
                            raise VenueProtocolError("private facts arrived before authentication")
                        now = self.clock.now()
                        if pending is None:
                            # Durably stale until the coalesced reconciliation proves it.
                            self._fault("private_facts_pending", stop_account=False)
                            pending = (now, now)
                        else:
                            pending = (pending[0], now)
                if not authenticated:
                    raise VenueProtocolError("private stream ended before authentication")
                if pending is not None:
                    self._reconcile()
            except (OSError, RuntimeError, ValueError) as error:
                self._fault(type(error).__name__)
                raise
            finally:
                session.close()
                self._fault("private_stream_closed")
            return self._view()

    def _qualify(self) -> None:
        """Check installed capabilities and authenticated physical test-account scope."""
        adapter = self._adapter()
        profiles = adapter.capability_profiles
        execution_profile = next(
            (profile for profile in profiles if profile.kind == "execution"), None
        )
        if execution_profile is None:
            raise VenueProtocolError("adapter lacks an execution capability profile")
        for instrument in self.config.instruments:
            calendars = {
                spec.instrument.calendar
                for spec in self.config.reference.specifications
                if spec.instrument.instrument_id == instrument.dimension.instrument_id
            }
            if len(calendars) != 1:
                raise VenueProtocolError("venue instrument calendar is ambiguous")
            CapabilityBinding(
                requirement=CapabilityRequirement(
                    name="venue_execution",
                    kind="execution",
                    product="spot",
                    venue=self.config.venue,
                    calendar=next(iter(calendars)),
                    operations=("submit", "cancel", "order", "open_orders", "fills", "balances"),
                    order_types=("gtc", "ioc", "post-only"),
                ),
                profile=execution_profile,
                mode="venue_test",
            )
        at, nonce = self._request_clock()
        profile = adapter.qualify_account(at=at, nonce=nonce)
        if (profile.venue, profile.environment, profile.account_verified) != (
            self.config.venue,
            self.config.environment,
            True,
        ):
            raise VenueProtocolError("adapter did not verify the configured test account")
        if profile.account_identity != self.config.venue_account_id:
            raise VenueProtocolError(
                "authenticated venue account identity differs from configuration"
            )
        self._store.bind_account(profile.venue, profile.environment, profile.account_identity)
        self._store.receipt("account-profile", self._codec.encode_json(profile), at)

    def _reconcile(self) -> None:
        """Prove a bounded complete history window before publishing account readiness."""
        adapter = self._adapter()
        self._fault("reconciliation_in_progress", stop_account=False)
        self._qualify()
        # Replay receipts first: a crash after the account commit but before the
        # receipt mark is handled by the account journal's identical-fill retry.
        for receipt in self._store.read().receipts:
            if receipt.kind.startswith("fill:") and not receipt.applied:
                self._ingest_fill(self._codec.decode_json(receipt.payload, VenueFillFact))
        at, nonce = self._request_clock()
        before = adapter.open_orders(at=at, nonce=nonce)
        for fact in before:
            self._dispatch(client_id=fact.client_id)
        start = self.config.account.opening_at
        proven = self._store.read().fills_complete_through
        if proven is not None:
            start = max(start, proven - self._FILL_HISTORY_OVERLAP)
        end = self.clock.now()
        fills: dict[tuple[str, str], VenueFillFact] = {}
        for instrument in self.config.instruments:
            cursor: str | None = None
            seen: set[str] = set()
            for _ in range(100):
                at, nonce = self._request_clock()
                page = adapter.fills(
                    symbol=instrument.native_symbol,
                    start_ms=self._milliseconds(start),
                    end_ms=self._milliseconds(end),
                    limit=100,
                    cursor=cursor,
                    at=at,
                    nonce=nonce,
                )
                for fill in page.fills:
                    if fill.symbol != instrument.native_symbol or fill.source_at is None:
                        raise VenueProtocolError("fill history lacks instrument or source clock")
                    if not start <= fill.source_at <= end:
                        raise VenueProtocolError("fill history falls outside the requested window")
                    # A continuation may repeat executions at its page boundary.
                    prior = fills.setdefault((fill.symbol, fill.fill_id), fill)
                    if self._fill_economics(prior) != self._fill_economics(fill):
                        raise VenueProtocolError("venue fill identity changed economics")
                if page.complete:
                    if page.next_cursor is not None:
                        raise VenueProtocolError("complete fill page contains a continuation")
                    break
                if page.next_cursor is None or page.next_cursor in seen:
                    raise VenueProtocolError("fill history is incomplete or cursor did not advance")
                cursor = page.next_cursor
                seen.add(cursor)
            else:
                raise VenueProtocolError("fill history exceeds bounded recovery capacity")
        # Economic order matters for base inventory; receipt clocks are assigned
        # at application in source order, while original receipts remain retained.
        for fill in sorted(fills.values(), key=self._fill_sort):
            self._ingest_fill(fill)
        observed: list[OrderState] = []
        for dispatch in self._store.read().dispatches:
            if dispatch.submission_rejected:
                self._event(
                    dispatch.order_id, "rejected", self.clock.now(), f"reject:{dispatch.client_id}"
                )
                continue
            if self._order(dispatch.order_id).is_terminal:
                # A journaled terminal outcome already matched every identified fill.
                # Later fills still arrive through fill history, and a venue order
                # that is open again appears in the open-order snapshots.
                continue
            at, nonce = self._request_clock()
            found = adapter.order(
                dispatch.symbol,
                dispatch.client_id,
                submitted_at=dispatch.submitted_at,
                venue_order_id=dispatch.venue_order_id,
                at=at,
                nonce=nonce,
            )
            if found is None:
                raise VenueProtocolError("submitted order absent from available venue history")
            self._ingest_order(found)
        at, nonce = self._request_clock()
        balances = adapter.balances(at=at, nonce=nonce)
        at, nonce = self._request_clock()
        after = adapter.open_orders(at=at, nonce=nonce)
        if self._order_set(before) != self._order_set(after):
            raise VenueProtocolError(
                "venue orders changed during reconciliation; repeat observation"
            )
        for fact in after:
            self._ingest_order(fact)
            observed.append(self._order(self._dispatch(client_id=fact.client_id).order_id))
        currencies = {
            money.currency.code: money.currency
            for account in self.config.account.accounts
            if account.account_id == self.config.account_id
            for money in account.cash
        }
        for instrument in self.config.instruments:
            currencies[instrument.base_currency.code] = instrument.base_currency
            currencies[instrument.quote_currency.code] = instrument.quote_currency
        amounts: dict[str, Money] = {}
        for balance in balances:
            if balance.currency in amounts:
                raise VenueProtocolError("venue balance repeats a currency")
            if balance.currency not in currencies:
                if balance.total != 0:
                    raise VenueProtocolError("unmapped physical wallet currency")
                continue
            amounts[balance.currency] = Money(
                value=balance.total, currency=currencies[balance.currency]
            )
        # Both adapters guarantee full wallet scope; absent zero assets are explicit.
        physical = tuple(
            amounts.get(code, Money(value=Decimal(0), currency=currency))
            for code, currency in sorted(currencies.items())
        )
        observation_at = self.clock.now()
        receipt = self._store.receipt(
            "reconciliation",
            self._codec.encode_json((before, balances, after, observation_at)),
            observation_at,
        )
        observation = PhysicalAccountObservation(
            identity=receipt.identity,
            account_id=self.config.account_id,
            at=observation_at,
            balances=physical,
            open_orders=tuple(observed),
            instrument_currencies=tuple(
                (item.dimension, item.base_currency) for item in self.config.instruments
            ),
        )
        matched = self.journal.reconcile_venue(observation)
        self._store.applied(receipt.identity)
        state = self._store.read()
        # A break may come from an execution the venue published late, so only a
        # matched account advances the proven fill window.
        self._store.save(
            replace(
                state,
                recovery_required=not matched,
                reason="reconciled" if matched else "physical_account_break",
                reconciled_at=observation.at if matched else state.reconciled_at,
                fills_complete_through=end if matched else state.fills_complete_through,
            )
        )

    def _ingest_fill(self, fact: VenueFillFact) -> None:
        """Retain native economics and atomically apply fees and attributed fills."""
        dispatch = self._dispatch(client_id=fact.client_id)
        order = self._order(dispatch.order_id)
        instrument = self._instrument(order)
        if fact.symbol != dispatch.symbol or fact.side != order.intent.side:
            raise VenueProtocolError("venue fill differs from admitted order")
        if dispatch.venue_order_id is not None and fact.venue_order_id != dispatch.venue_order_id:
            raise VenueProtocolError("venue fill order identity changed")
        key = f"fill:{fact.symbol}:{fact.fill_id}"
        for prior in self._store.read().receipts:
            if prior.kind == key:
                saved = self._codec.decode_json(prior.payload, VenueFillFact)
                if self._fill_economics(saved) != self._fill_economics(fact):
                    raise VenueProtocolError("venue fill identity changed economics")
                if prior.applied:
                    return
                fact = saved
                break
        receipt = self._store.receipt(key, self._codec.encode_json(fact), fact.received_at)
        if fact.source_at is None:
            raise VenueProtocolError("venue fill source time is unavailable")
        currency = next(
            (
                item
                for item in (instrument.base_currency, instrument.quote_currency)
                if item.code == fact.fee_currency
            ),
            None,
        )
        if currency is None:
            raise VenueProtocolError("unsupported third-currency venue fee")
        # Persist the local application clock too, so crash replay is byte-identical.
        native_key = f"native:{receipt.identity}"
        native_receipt = next(
            (item for item in self._store.read().receipts if item.kind == native_key), None
        )
        if native_receipt is None:
            native = NativeFill(
                identity=f"{self.config.venue}:{fact.symbol}:{fact.fill_id}",
                order_id=dispatch.order_id,
                at=self.clock.now(),
                filled_at=fact.source_at,
                quantity=Quantity(
                    value=fact.quantity if fact.side == "buy" else fact.quantity.copy_negate(),
                    dimension=instrument.dimension,
                ),
                price=Price(
                    value=fact.price, currency=instrument.quote_currency, per=instrument.dimension
                ),
                fee=Money(value=fact.fee, currency=currency),
                base_currency=instrument.base_currency,
            )
            self._store.receipt(native_key, self._codec.encode_json(native), native.at)
        else:
            native = self._codec.decode_json(native_receipt.payload, NativeFill)
        self.journal.apply_native_fill(native)
        self._store.applied(receipt.identity)

    def _ingest_order(self, fact: VenueOrderFact) -> None:
        """Require cumulative state to agree with individually identified fills."""
        dispatch = self._dispatch(client_id=fact.client_id)
        request = self._codec.decode_json(dispatch.request, VenueOrderRequest)
        order = self._order(dispatch.order_id)
        if (
            (
                fact.symbol,
                fact.side,
                fact.original_quantity,
                fact.limit_price,
                fact.time_in_force,
                fact.post_only,
            )
            != (
                request.symbol,
                request.side,
                request.quantity,
                request.limit_price,
                request.time_in_force,
                request.post_only,
            )
            or fact.filled_quantity != order.filled.value
            or (
                dispatch.venue_order_id is not None
                and dispatch.venue_order_id != fact.venue_order_id
            )
        ):
            raise VenueProtocolError(
                "venue order differs from admitted mechanics or identified fills"
            )
        receipt = self._store.receipt("order", self._codec.encode_json(fact), fact.received_at)
        state = self._store.read()
        dispatches: tuple[VenueDispatch, ...] = tuple(
            replace(item, venue_order_id=fact.venue_order_id)
            if item.order_id == dispatch.order_id
            else item
            for item in state.dispatches
        )
        self._store.save(
            replace(
                state,
                dispatches=dispatches,
            )
        )
        if fact.status == "filled":
            if not order.is_terminal or order.status != "filled":
                raise VenueProtocolError("terminal venue fill lacks individual executions")
        elif fact.status in ("cancelled", "rejected"):
            if not order.is_terminal:
                kind: EventKind = "cancelled" if fact.status == "cancelled" else "rejected"
                if order.status == "unknown":
                    kind = (
                        "reconcile_cancelled"
                        if fact.status == "cancelled"
                        else "reconcile_rejected"
                    )
                self._event(order.identity, kind, self.clock.now(), receipt.identity)
            elif order.status != fact.status:
                raise VenueProtocolError("contradictory terminal venue order")
        elif not order.is_terminal:
            if order.status == "unknown":
                self._event(order.identity, "reconcile_open", self.clock.now(), receipt.identity)
            elif not order.accepted:
                self._event(order.identity, "accepted", self.clock.now(), receipt.identity)
        else:
            raise VenueProtocolError("venue reports a terminal local order as open")
        self._store.applied(receipt.identity)

    def _ack(self, dispatch: VenueDispatch, ack: VenueCommandAck, *, attempt: int = 0) -> None:
        """Persist a request receipt without treating it as economic finality."""
        if ack.client_id != dispatch.client_id:
            raise VenueProtocolError("venue acknowledgement client identity differs")
        receipt = self._store.receipt(
            f"ack:{attempt}", self._codec.encode_json(ack), ack.received_at
        )
        state = self._store.read()
        dispatches: tuple[VenueDispatch, ...] = tuple(
            replace(item, venue_order_id=ack.venue_order_id or item.venue_order_id)
            if item.order_id == dispatch.order_id
            else item
            for item in state.dispatches
        )
        self._store.save(
            replace(
                state,
                dispatches=dispatches,
            )
        )
        self._event(
            dispatch.order_id,
            "request_ack" if ack.operation == "submit" else "cancel_ack",
            self.clock.now(),
            receipt.identity,
        )
        self._store.applied(receipt.identity)

    def _event(self, order_id: str, kind: EventKind, at: datetime, identity: str) -> None:
        """Route canonical facts through the existing direct or net-parent owner."""
        key = f"canonical:{identity}:{kind}"
        saved = next((item for item in self._store.read().receipts if item.kind == key), None)
        if saved is None:
            event = OrderEvent(
                identity=f"venue:{identity}:{kind}", order_id=order_id, at=at, kind=kind
            )
            saved = self._store.receipt(key, self._codec.encode_json(event), at)
        else:
            event = self._codec.decode_json(saved.payload, OrderEvent)
            if event.order_id != order_id or event.kind != kind:
                raise VenueProtocolError("conflicting canonical venue event identity")
        if any(parent.order.identity == order_id for parent in self.journal.net_orders()):
            self.journal.apply_net_event(event)
        else:
            self.journal.apply_event(event)
        self._store.applied(saved.identity)

    def _fault(self, reason: str, *, stop_account: bool = True) -> None:
        """Persist a visible transport recovery fence without releasing reservations."""
        if stop_account:
            # Account reconciliation invalidation is recoverable only by a later
            # independent physical observation, never by strategy callbacks.
            self.journal.invalidate_venue(self.config.account_id, reason)
        state = self._store.read()
        self._store.save(replace(state, recovery_required=True, reason=reason))

    def _request_clock(self) -> tuple[datetime, int]:
        """Reserve an increasing nonce and conservative account-wide request interval."""
        state = self._store.read()
        at = self.clock.now()
        interval = timedelta(seconds=6.1 if self.config.venue == "bitfinex" else 0.25)
        if state.last_request_at is not None:
            if at < state.last_request_at:
                raise ValueError("venue request clock regressed")
            wait = (state.last_request_at + interval - at).total_seconds()
            if wait > 0:
                self.clock.sleep(wait)
                at = self.clock.now()
                if at < state.last_request_at + interval:
                    raise ValueError("venue rate-limit clock did not advance")
        nonce = max(self._milliseconds(at) * 1000, state.nonce + 1)
        self._store.save(replace(state, nonce=nonce, last_request_at=at))
        return at, nonce

    def _reference(self, order: OrderState, instrument: VenueInstrument, at: datetime) -> None:
        """Resolve current evidenced rules instead of trusting authored paper grids."""
        limits = next(
            item
            for item in self.config.account.instruments
            if item.lot.dimension == instrument.dimension
        )
        current = SpotLimits.from_reference(
            self.config.reference,
            maximum=limits.maximum,
            quote_currency=instrument.quote_currency,
            valid_at=at,
            known_at=at,
            max_age=timedelta(microseconds=self.config.max_reference_age_us),
        )
        if current.order_reason(order.intent.quantity, order.intent.limit) is not None:
            raise ValueError("order fails current venue specification")
        if limits.specification_identity != current.specification_identity:
            raise ValueError("admitted and current venue specification identities differ")

    def _order(self, order_id: str) -> OrderState:
        """Resolve only this account's routable direct orders or physical parents."""
        for parent in self.journal.net_orders():
            if parent.account_id == self.config.account_id and parent.order.identity == order_id:
                return parent.order
        for child in self.journal.orders():
            if (
                child.account_id == self.config.account_id
                and child.context is None
                and child.order.identity == order_id
            ):
                return child.order
        raise ValueError("unknown or nonphysical venue order")

    def _instrument(self, order: OrderState) -> VenueInstrument:
        """Resolve native units only through the pinned configuration mapping."""
        for instrument in self.config.instruments:
            if instrument.dimension == order.intent.quantity.dimension:
                return instrument
        raise ValueError("order instrument is outside venue scope")

    def _dispatch(
        self, *, order_id: str | None = None, client_id: str | None = None
    ) -> VenueDispatch:
        """Resolve durable ownership; unknown external orders remain account breaks."""
        for dispatch in self._store.read().dispatches:
            if (order_id is not None and dispatch.order_id == order_id) or (
                client_id is not None and dispatch.client_id == client_id
            ):
                return dispatch
        raise VenueProtocolError("unowned or never-submitted venue order")

    def _client_id(self, order_id: str) -> str:
        """Derive bounded venue identities and reject even a truncated-hash collision."""
        digest = hashlib.sha256(
            self._codec.encode_json((self.config.identity, order_id))
        ).hexdigest()
        identity = (
            str(int(digest[:11], 16) + 1) if self.config.venue == "bitfinex" else "ar" + digest[:30]
        )
        if any(item.client_id == identity for item in self._store.read().dispatches):
            raise ValueError("venue client identity collision")
        return identity

    def _adapter(self) -> VenueAdapter:
        """Require explicit credential-resolved transport for any external operation."""
        if self.adapter is None:
            raise ValueError("venue operation requires an explicit authenticated adapter")
        return self.adapter

    def _view(self, *, submission_attempted: bool = False) -> GatewayView:
        """Project retained transport evidence without secret or account payload bytes."""
        state = self._store.read()
        return GatewayView(
            account_id=self.config.account_id,
            venue=self.config.venue,
            environment=self.config.environment,
            config_sha256=self.config.identity,
            recovery_required=state.recovery_required,
            reason=state.reason,
            reconciled_at=state.reconciled_at,
            dispatches=state.dispatches,
            receipt_count=len(state.receipts),
            submission_attempted=submission_attempted,
        )

    @staticmethod
    def _milliseconds(at: datetime) -> int:
        """Convert UTC timestamps with integer arithmetic instead of floating epoch time."""
        if at.tzinfo is None or at.utcoffset() != timedelta(0):
            raise ValueError("venue time must use UTC")
        delta = at - datetime(1970, 1, 1, tzinfo=UTC)
        return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000

    @staticmethod
    def _fill_sort(fact: VenueFillFact) -> tuple[datetime, str]:
        """Sort recovery executions by source time and stable native identity."""
        if fact.source_at is None:
            raise VenueProtocolError("fill source clock is required for recovery")
        return fact.source_at, fact.fill_id

    @staticmethod
    def _fill_economics(fact: VenueFillFact) -> tuple[object, ...]:
        """Compare economic identity while allowing repeated transport delivery clocks."""
        return (
            fact.fill_id,
            fact.client_id,
            fact.venue_order_id,
            fact.symbol,
            fact.side,
            fact.quantity,
            fact.price,
            fact.fee,
            fact.fee_currency,
            fact.source_at,
        )

    @staticmethod
    def _order_set(facts: tuple[VenueOrderFact, ...]) -> dict[str, tuple[object, ...]]:
        """Compare native open snapshots without receipt-time or wire-format noise."""
        result: dict[str, tuple[object, ...]] = {}
        for fact in facts:
            if fact.client_id in result:
                raise VenueProtocolError("duplicate open venue order")
            result[fact.client_id] = (
                fact.venue_order_id,
                fact.symbol,
                fact.side,
                fact.original_quantity,
                fact.filled_quantity,
                fact.remaining_quantity,
                fact.limit_price,
                fact.time_in_force,
                fact.post_only,
                fact.status,
            )
        return result
