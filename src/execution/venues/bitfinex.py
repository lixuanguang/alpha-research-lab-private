"""Authenticate and normalize Bitfinex paper-subaccount spot protocols."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from hashlib import sha384
from hmac import new
from itertools import pairwise
from typing import ClassVar

# project library imports
from configuration import CapabilityProfile
from execution.venues.codec import VenueJson
from execution.venues.contracts import (
    VenueBalance,
    VenueCapabilityProfile,
    VenueCommandAck,
    VenueCredentials,
    VenueFillFact,
    VenueFillPage,
    VenueHttpRequest,
    VenueHttpResponse,
    VenueHttpTransport,
    VenueOrderFact,
    VenueOrderRequest,
    VenueOrderStatus,
    VenueOutcomeUnknownError,
    VenueProtocolError,
    VenueRejectedError,
    VenueSide,
    VenueStreamEvent,
    VenueTimeInForce,
)
from execution.venues.exact import VenueExactDecimal
from execution.venues.throttle import VenueRateLimiter


class BitfinexSpotAdapter:
    """Translate admitted orders into exchange-wallet paper account operations."""

    # Documented amount slot of each position (ps) and funding offer (fos),
    # credit (fcs) and loan (fls) snapshot entry.
    _EXPOSURE_AMOUNT_INDEX: ClassVar[dict[str, int]] = {"ps": 2, "fos": 4, "fcs": 5, "fls": 5}

    def __init__(self, credentials: VenueCredentials, transport: VenueHttpTransport) -> None:
        """Bind caller-resolved subaccount credentials and one REST transport."""
        credentials.__post_init__()
        self.credentials = credentials
        self.transport = transport
        self.throttle = VenueRateLimiter(requests=80, seconds=60.0)
        self.account_verified = False
        self.account_identity: str | None = None
        self.private_authenticated = False
        self.private_configured = False
        self.private_sequence: int | None = None

    @property
    def capability_profiles(self) -> tuple[CapabilityProfile, ...]:
        """Advertise paper spot support without claiming venue conformance."""
        return (
            CapabilityProfile(
                name="bitfinex_paper_spot_execution",
                kind="execution",
                implementation_identity="execution.venues.bitfinex",
                version="1",
                products=("spot",),
                venues=("bitfinex",),
                calendars=("24x7", "continuous"),
                modes=("venue_test",),
                operations=("submit", "cancel", "order", "open_orders", "fills", "balances"),
                order_types=("gtc", "ioc", "post-only"),
                lifecycle=("partial_fill", "cancel_confirmed", "reconcile"),
                qualification="fixture",
            ),
            CapabilityProfile(
                name="bitfinex_paper_spot_account",
                kind="account",
                implementation_identity="execution.venues.bitfinex",
                version="1",
                products=("spot",),
                venues=("bitfinex",),
                calendars=("24x7", "continuous"),
                modes=("venue_test",),
                operations=("balances", "open_orders", "fills"),
                qualification="fixture",
            ),
        )

    def qualify_account(self, *, at: datetime, nonce: int) -> VenueCapabilityProfile:
        """Require the authenticated subaccount's documented PPT_ENABLED flag."""
        self.account_verified = False
        self.account_identity = None
        response = self._request("/v2/auth/r/info/user", b"{}", nonce=nonce)
        info = VenueJson.array(VenueJson.parse(response.body))
        if VenueJson.integer(VenueJson.indexed(info, 21)) != 1:
            raise VenueProtocolError("Bitfinex API key does not belong to a paper account")
        account_number = VenueJson.integer(VenueJson.indexed(info, 0))
        if account_number <= 0:
            raise VenueProtocolError("Bitfinex paper account identity is missing")
        profile = VenueCapabilityProfile(
            venue="bitfinex",
            environment="bitfinex_paper",
            account_identity=str(account_number),
            account_verified=True,
        )
        self.account_verified = True
        self.account_identity = profile.account_identity
        return profile

    def submit(self, order: VenueOrderRequest, *, at: datetime, nonce: int) -> VenueCommandAck:
        """Submit one exchange-wallet spot order with the durable int45 CID."""
        del at
        self._require_verified()
        order.__post_init__()
        self._validate_symbol(order.symbol)
        client_number = self._client_number(order.client_id)
        self._validate_precision(order)
        order_type = "EXCHANGE IOC" if order.time_in_force == "ioc" else "EXCHANGE LIMIT"
        signed_quantity = order.quantity if order.side == "buy" else order.quantity.copy_negate()
        response = self._request(
            "/v2/auth/w/order/submit",
            VenueJson.encode(
                {
                    "type": order_type,
                    "symbol": order.symbol,
                    "amount": str(signed_quantity),
                    "price": str(order.limit_price),
                    "cid": client_number,
                    "flags": 4096 if order.post_only else 0,
                }
            ),
            nonce=nonce,
        )
        order_data = self._notification_order(response.body, "on-req", nested=True)
        fact = self._order_fact(order_data, response)
        if fact.client_id != order.client_id or fact.symbol != order.symbol:
            raise VenueProtocolError("Bitfinex submit identity mismatch")
        return VenueCommandAck(
            operation="submit",
            client_id=order.client_id,
            venue_order_id=fact.venue_order_id,
            received_at=response.received_at,
            raw=response.body,
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
        """Request a cancel by ID or CID/date, retaining acknowledgement only."""
        del at
        self._require_verified()
        self._validate_symbol(symbol)
        client_number = self._client_number(client_id)
        body: dict[str, object] = (
            {"id": self._venue_order_number(venue_order_id)}
            if venue_order_id is not None
            else {"cid": client_number, "cid_date": submitted_at.astimezone(UTC).date().isoformat()}
        )
        response = self._request("/v2/auth/w/order/cancel", VenueJson.encode(body), nonce=nonce)
        order_data = self._notification_order(response.body, "oc-req", nested=False)
        fact = self._order_fact(order_data, response)
        if (
            fact.client_id != client_id
            or fact.symbol != symbol
            or (venue_order_id is not None and fact.venue_order_id != venue_order_id)
        ):
            raise VenueProtocolError("Bitfinex cancel identity mismatch")
        return VenueCommandAck(
            operation="cancel",
            client_id=client_id,
            venue_order_id=fact.venue_order_id,
            received_at=response.received_at,
            raw=response.body,
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
        """Resolve active and retained closed state without treating absence as finality."""
        self._require_verified()
        self._validate_symbol(symbol)
        client_number = self._client_number(client_id)
        if at - submitted_at > timedelta(days=13):
            raise VenueProtocolError("Bitfinex closed-order retention cannot prove older outcome")
        active_body: dict[str, object] = (
            {"id": self._venue_order_number(venue_order_id)}
            if venue_order_id is not None
            else {"cid": client_number, "cid_date": submitted_at.astimezone(UTC).date().isoformat()}
        )
        active = self._request("/v2/auth/r/orders", VenueJson.encode(active_body), nonce=nonce)
        active_items = self._order_array(active.body)
        if len(active_items) > 1:
            raise VenueProtocolError("Bitfinex active order identity is ambiguous")
        if active_items:
            return self._verified_lookup(
                active_items[0], active, symbol, client_id, venue_order_id, submitted_at
            )
        # A distinct externally persisted nonce is needed for this second signed call.
        # The caller supplies a base nonce; the adapter never invents one from wall time.
        history_body: dict[str, object] = (
            {"id": [self._venue_order_number(venue_order_id)], "limit": 2500}
            if venue_order_id is not None
            else {
                "start": VenueJson.epoch_milliseconds(submitted_at),
                "end": VenueJson.epoch_milliseconds(at),
                "limit": 2500,
            }
        )
        history = self._request(
            "/v2/auth/r/orders/hist", VenueJson.encode(history_body), nonce=nonce, offset=1
        )
        history_items = self._order_array(history.body)
        if len(history_items) >= 2500:
            raise VenueProtocolError("Bitfinex closed-order page may be truncated")
        matched = [
            item
            for item in history_items
            if self._order_ids_match(item, symbol, client_id, venue_order_id)
        ]
        if len(matched) > 1:
            raise VenueProtocolError("Bitfinex closed-order identity is ambiguous")
        return (
            self._verified_lookup(
                matched[0], history, symbol, client_id, venue_order_id, submitted_at
            )
            if matched
            else None
        )

    def open_orders(self, *, at: datetime, nonce: int) -> tuple[VenueOrderFact, ...]:
        """Read all active orders and reject any non-exchange spot exposure."""
        del at
        self._require_verified()
        response = self._request("/v2/auth/r/orders", b"{}", nonce=nonce)
        items = self._order_array(response.body)
        if len(items) > 4000:
            raise VenueProtocolError("Bitfinex active order count exceeds safe bound")
        facts = tuple(self._order_fact(item, response) for item in items)
        if len({fact.venue_order_id for fact in facts}) != len(facts):
            raise VenueProtocolError("Bitfinex active orders repeat an identity")
        if any(fact.status not in ("open", "partial") for fact in facts):
            raise VenueProtocolError("Bitfinex active order endpoint returned terminal state")
        return facts

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
        """Read one ascending time page, continuing a full page from its last millisecond.

        Bitfinex pages trade history by timestamp only, and a full page can stop
        inside a millisecond whose later trades it omitted. The continuation
        cursor is that millisecond, so the next page repeats its trades and the
        caller drops repeated fill identities. A full page that never leaves its
        first millisecond cannot advance and fails closed.
        """
        del at
        self._require_verified()
        self._validate_symbol(symbol)
        page_start = start_ms if cursor is None else self._cursor_milliseconds(cursor)
        if not (0 <= start_ms <= page_start <= end_ms) or not (1 <= limit <= 2500):
            raise ValueError("invalid Bitfinex fill window, limit, or cursor")
        path = "/v2/auth/r/trades/" + symbol + "/hist"
        response = self._request(
            path,
            VenueJson.encode(
                {
                    "start": page_start,
                    "end": end_ms,
                    "limit": limit,
                    "sort": 1,
                }
            ),
            nonce=nonce,
        )
        items = VenueJson.array(VenueJson.parse(response.body))
        if len(items) > limit:
            raise VenueProtocolError("Bitfinex trade page exceeds its requested limit")
        facts = tuple(self._fill_fact(VenueJson.array(item), response) for item in items)
        times = tuple(
            None if fact.source_at is None else VenueJson.epoch_milliseconds(fact.source_at)
            for fact in facts
        )
        if any(
            fact.symbol != symbol or time is None or not (page_start <= time <= end_ms)
            for fact, time in zip(facts, times, strict=True)
        ):
            raise VenueProtocolError("Bitfinex fill outside requested interval")
        if any(
            later is None or earlier is None or later < earlier
            for earlier, later in pairwise(times)
        ):
            raise VenueProtocolError("Bitfinex trade page is not in ascending time order")
        if len({fact.fill_id for fact in facts}) != len(facts):
            raise VenueProtocolError("Bitfinex trade page repeats an identity")
        if len(items) < limit:
            return VenueFillPage(fills=facts, next_cursor=None, complete=True)
        last = times[-1]
        if last is None or last == page_start:
            raise VenueProtocolError("Bitfinex trade page may omit same-millisecond fills")
        return VenueFillPage(fills=facts, next_cursor=str(last), complete=False)

    def balances(self, *, at: datetime, nonce: int) -> tuple[VenueBalance, ...]:
        """Read complete exchange-wallet currency balances; null availability fails."""
        del at
        self._require_verified()
        response = self._request("/v2/auth/r/wallets", b"{}", nonce=nonce)
        items = VenueJson.array(VenueJson.parse(response.body))
        result: list[VenueBalance] = []
        for item in items:
            wallet = VenueJson.array(item)
            wallet_type = VenueJson.text(VenueJson.indexed(wallet, 0))
            if wallet_type != "exchange":
                # Other wallet types remain outside this spot account; reject nonzero
                # balances rather than silently calling the physical account complete.
                if VenueJson.decimal(VenueJson.indexed(wallet, 2)) != 0:
                    raise VenueProtocolError("Bitfinex account has non-exchange wallet value")
                continue
            result.append(self._wallet_fact(wallet, response.body, response.received_at))
        if len({balance.currency for balance in result}) != len(result):
            raise VenueProtocolError("Bitfinex exchange wallet repeats currency")
        if any(balance.available is None for balance in result):
            raise VenueProtocolError("Bitfinex wallet availability is unknown")
        return tuple(result)

    def private_configuration(self) -> tuple[bytes, ...]:
        """Enable documented SEQ_ALL before private authentication."""
        return (VenueJson.encode({"event": "conf", "flags": 65536}),)

    def private_login(self, *, at: datetime, nonce: int) -> bytes:
        """Sign a caller-persisted strictly increasing private WebSocket nonce."""
        del at
        self._require_verified()
        self._native_nonce(nonce, offset=0)
        self.private_authenticated = False
        self.private_configured = False
        self.private_sequence = None
        native_nonce = str(2 * nonce)
        payload = "AUTH" + native_nonce
        signature = new(self.credentials.api_secret.encode(), payload.encode(), sha384).hexdigest()
        return VenueJson.encode(
            {
                "event": "auth",
                "apiKey": self.credentials.api_key,
                "authPayload": payload,
                "authNonce": native_nonce,
                "authSig": signature,
            }
        )

    def private_subscriptions(self) -> tuple[bytes, ...]:
        """Authentication automatically subscribes to Bitfinex account info."""
        return ()

    def decode_private(self, raw: bytes, *, received_at: datetime) -> VenueStreamEvent:
        """Enforce sequence continuity and parse private order/trade/wallet frames."""
        value = VenueJson.parse(raw)
        if isinstance(value, dict):
            control = VenueJson.mapping(value)
            name = VenueJson.text(VenueJson.field(control, "event"))
            if name == "conf" and control.get("status") == "OK" and control.get("flags") == 65536:
                self.private_configured = True
                return VenueStreamEvent(kind="heartbeat", received_at=received_at, raw=raw)
            if (
                name == "auth"
                and control.get("status") == "OK"
                and self.private_configured
                and str(VenueJson.integer(VenueJson.field(control, "userId")))
                == self.account_identity
            ):
                self.private_authenticated = True
                return VenueStreamEvent(kind="authenticated", received_at=received_at, raw=raw)
            if (
                name == "info"
                and control.get("version") == 2
                and control.get("code") is None
                and VenueJson.integer(
                    VenueJson.field(
                        VenueJson.mapping(VenueJson.field(control, "platform")), "status"
                    )
                )
                == 1
            ):
                return VenueStreamEvent(kind="heartbeat", received_at=received_at, raw=raw)
            return VenueStreamEvent(
                kind="recovery_required",
                received_at=received_at,
                raw=raw,
                reason="Bitfinex private control event",
            )
        frame = VenueJson.array(value)
        if not self.private_authenticated or VenueJson.integer(VenueJson.indexed(frame, 0)) != 0:
            return VenueStreamEvent(
                kind="recovery_required",
                received_at=received_at,
                raw=raw,
                reason="Bitfinex unauthenticated or unexpected channel",
            )
        sequence = VenueJson.integer(frame[-1])
        if self.private_sequence is not None and sequence != self.private_sequence + 1:
            return VenueStreamEvent(
                kind="recovery_required",
                received_at=received_at,
                raw=raw,
                reason="Bitfinex private sequence gap",
            )
        self.private_sequence = sequence
        kind = VenueJson.text(VenueJson.indexed(frame, 1))
        response = VenueHttpResponse(status=200, body=raw, received_at=received_at)
        if kind in ("hb", "te", "bu"):
            # A te lacks its final fee; the matching tu carries complete economics.
            # A bu is a periodic total valuation; REST reconciliation owns balances.
            return VenueStreamEvent(kind="heartbeat", received_at=received_at, raw=raw)
        if kind in self._EXPOSURE_AMOUNT_INDEX:
            # Authentication snapshots positions and funding even for a spot-only
            # account. Only a flat snapshot is harmless; any exposure needs recovery.
            index = self._EXPOSURE_AMOUNT_INDEX[kind]
            if all(
                VenueJson.decimal(VenueJson.indexed(VenueJson.array(item), index)) == 0
                for item in VenueJson.array(VenueJson.indexed(frame, 2))
            ):
                return VenueStreamEvent(kind="heartbeat", received_at=received_at, raw=raw)
            return VenueStreamEvent(
                kind="recovery_required",
                received_at=received_at,
                raw=raw,
                reason="Bitfinex margin or funding exposure",
            )
        if kind == "os":
            orders = tuple(
                self._order_fact(VenueJson.array(item), response)
                for item in VenueJson.array(VenueJson.indexed(frame, 2))
            )
            return VenueStreamEvent(
                kind="orders_snapshot", received_at=received_at, raw=raw, orders=orders
            )
        if kind in ("on", "ou", "oc"):
            order = self._order_fact(VenueJson.array(VenueJson.indexed(frame, 2)), response)
            return VenueStreamEvent(kind="order", received_at=received_at, raw=raw, orders=(order,))
        if kind == "tu":
            fill = self._fill_fact(VenueJson.array(VenueJson.indexed(frame, 2)), response)
            return VenueStreamEvent(kind="fill", received_at=received_at, raw=raw, fill=fill)
        if kind in ("ws", "wu"):
            wallets = VenueJson.array(VenueJson.indexed(frame, 2))
            entries = [VenueJson.array(item) for item in wallets] if kind == "ws" else [wallets]
            balances = tuple(
                self._wallet_fact(item, raw, received_at)
                for item in entries
                if VenueJson.text(VenueJson.indexed(item, 0)) == "exchange"
            )
            return VenueStreamEvent(
                kind="balance", received_at=received_at, raw=raw, balances=balances
            )
        if kind == "n":
            notice = VenueJson.array(VenueJson.indexed(frame, 2))
            if VenueJson.text(VenueJson.indexed(notice, 6)) == "SUCCESS":
                return VenueStreamEvent(kind="heartbeat", received_at=received_at, raw=raw)
        return VenueStreamEvent(
            kind="recovery_required",
            received_at=received_at,
            raw=raw,
            reason="unsupported Bitfinex private event",
        )

    def _require_verified(self) -> None:
        """Prevent commands against a live Bitfinex account on the shared host."""
        if not self.account_verified:
            raise VenueProtocolError("Bitfinex paper account must be qualified")

    @staticmethod
    def _validate_symbol(symbol: str) -> None:
        """Permit only native uppercase trading pairs in authenticated paths."""
        parts = symbol[1:].split(":")
        if (
            not symbol.startswith("t")
            or not 3 <= len(symbol) <= 30
            or len(parts) > 2
            or any(part.endswith("F0") for part in parts)
            or any(
                not part or not part.isascii() or not part.isalnum() or part.upper() != part
                for part in parts
            )
        ):
            raise ValueError("invalid Bitfinex spot symbol")

    @staticmethod
    def _client_number(client_id: str) -> int:
        """Enforce documented int45 client identity without lossy coercion."""
        if (
            not client_id.isascii()
            or not client_id.isdigit()
            or (client_id.startswith("0") and client_id != "0")
        ):
            raise ValueError("Bitfinex client ID must be canonical int45")
        number = int(client_id)
        if not 0 < number < 2**45:
            raise ValueError("Bitfinex client ID exceeds int45")
        return number

    @staticmethod
    def _validate_precision(order: VenueOrderRequest) -> None:
        """Reject values the API would silently round or truncate on submit."""
        for is_price, value in ((False, order.quantity), (True, order.limit_price)):
            parts = value.as_tuple()
            exponent = parts.exponent
            if type(exponent) is not int:
                raise ValueError("non-finite Bitfinex order decimal")
            significant = list(parts.digits)
            while significant and significant[-1] == 0:
                significant.pop()
                exponent += 1
            if exponent < -8:
                raise ValueError("Bitfinex order exceeds eight decimal places")
            if is_price and len(significant) > 5:
                raise ValueError("Bitfinex price exceeds five significant digits")

    @staticmethod
    def _cursor_milliseconds(cursor: str) -> int:
        """Read a canonical epoch-millisecond continuation without lossy coercion."""
        if (
            not cursor.isascii()
            or not cursor.isdigit()
            or (cursor.startswith("0") and cursor != "0")
        ):
            raise ValueError("invalid Bitfinex fill cursor")
        return int(cursor)

    @staticmethod
    def _venue_order_number(order_id: str) -> int:
        """Require a positive native numeric order identity."""
        if not order_id.isascii() or not order_id.isdigit() or int(order_id) <= 0:
            raise ValueError("invalid Bitfinex venue order ID")
        return int(order_id)

    @staticmethod
    def _native_nonce(nonce: int, *, offset: int) -> int:
        """Reserve two wire slots below the exchange's safe-integer ceiling."""
        if type(nonce) is not int or nonce <= 0 or offset not in (0, 1):
            raise ValueError("invalid Bitfinex durable nonce")
        native_nonce = 2 * nonce + offset
        if native_nonce > 9_007_199_254_740_991:
            raise ValueError("Bitfinex nonce exceeds native safe integer")
        return native_nonce

    def _request(self, path: str, body: bytes, *, nonce: int, offset: int = 0) -> VenueHttpResponse:
        """Reserve two native nonce slots per durable caller nonce for lookups."""
        native_nonce = self._native_nonce(nonce, offset=offset)
        signature = new(
            self.credentials.api_secret.encode(),
            b"/api" + path.encode() + str(native_nonce).encode() + body,
            sha384,
        ).hexdigest()
        self.throttle.acquire()
        response = self.transport.request(
            VenueHttpRequest(
                method="POST",
                path=path,
                body=body,
                headers=(
                    ("Content-Type", "application/json"),
                    ("bfx-apikey", self.credentials.api_key),
                    ("bfx-nonce", str(native_nonce)),
                    ("bfx-signature", signature),
                ),
            )
        )
        if (
            300 <= response.status < 400
            or response.status in (408, 425, 429)
            or response.status >= 500
        ):
            raise VenueOutcomeUnknownError("Bitfinex request throttled or unavailable")
        if response.status != 200:
            raise VenueRejectedError(f"Bitfinex REST status {response.status}")
        return response

    @staticmethod
    def _notification_order(raw: bytes, expected_type: str, *, nested: bool) -> list[object]:
        """Require a successful notification and its documented order payload."""
        notice = VenueJson.array(VenueJson.parse(raw))
        if VenueJson.text(VenueJson.indexed(notice, 1)) != expected_type:
            raise VenueProtocolError("Bitfinex order notification type mismatch")
        status = VenueJson.text(VenueJson.indexed(notice, 6))
        if status != "SUCCESS":
            raise VenueRejectedError("Bitfinex order request rejected")
        entry = VenueJson.array(VenueJson.indexed(notice, 4))
        if nested:
            if len(entry) != 1:
                raise VenueProtocolError("Bitfinex submit notification is ambiguous")
            return VenueJson.array(entry[0])
        return entry

    @staticmethod
    def _order_array(raw: bytes) -> list[list[object]]:
        """Require an array of complete native order arrays."""
        return [VenueJson.array(item) for item in VenueJson.array(VenueJson.parse(raw))]

    @staticmethod
    def _order_ids_match(
        item: list[object], symbol: str, client_id: str, venue_order_id: str | None
    ) -> bool:
        """Match native fields before normalizing a historical candidate."""
        cid = VenueJson.indexed(item, 2)
        return (
            VenueJson.text(VenueJson.indexed(item, 3)) == symbol
            and cid is not None
            and str(VenueJson.integer(cid)) == client_id
            and (
                venue_order_id is None
                or str(VenueJson.integer(VenueJson.indexed(item, 0))) == venue_order_id
            )
        )

    def _verified_lookup(
        self,
        item: list[object],
        response: VenueHttpResponse,
        symbol: str,
        client_id: str,
        venue_order_id: str | None,
        submitted_at: datetime,
    ) -> VenueOrderFact:
        """Reject a reused CID or a result from another native instrument."""
        fact = self._order_fact(item, response)
        if (
            fact.client_id != client_id
            or fact.symbol != symbol
            or (venue_order_id is not None and fact.venue_order_id != venue_order_id)
        ):
            raise VenueProtocolError("Bitfinex order lookup identity mismatch")
        if fact.source_at is not None and fact.source_at < submitted_at:
            raise VenueProtocolError("Bitfinex order predates durable submission")
        return fact

    @staticmethod
    def _order_fact(item: list[object], response: VenueHttpResponse) -> VenueOrderFact:
        """Normalize one EXCHANGE order and exact cumulative quantity."""
        order_type = VenueJson.text(VenueJson.indexed(item, 8))
        if order_type not in ("EXCHANGE LIMIT", "EXCHANGE IOC"):
            raise VenueProtocolError("Bitfinex account contains unsupported non-spot order")
        symbol = VenueJson.text(VenueJson.indexed(item, 3))
        BitfinexSpotAdapter._validate_symbol(symbol)
        status_text = VenueJson.text(VenueJson.indexed(item, 13))
        if status_text == "ACTIVE":
            status: VenueOrderStatus = "open"
        elif status_text.startswith("PARTIALLY FILLED"):
            status = "partial"
        elif status_text.startswith("EXECUTED"):
            status = "filled"
        elif status_text.startswith("CANCELED"):
            status = "cancelled"
        else:
            raise VenueProtocolError("unsupported Bitfinex order status")
        original_signed = VenueJson.decimal(VenueJson.indexed(item, 7))
        remaining_signed = VenueJson.decimal(VenueJson.indexed(item, 6))
        if original_signed == 0 or (
            remaining_signed != 0 and (original_signed > 0) != (remaining_signed > 0)
        ):
            raise VenueProtocolError("Bitfinex order quantity sign changed")
        original = original_signed.copy_abs()
        remaining = remaining_signed.copy_abs()
        flags = VenueJson.integer(VenueJson.indexed(item, 12))
        if flags & ~4096:
            raise VenueProtocolError("unsupported Bitfinex spot order flags")
        order_id = str(VenueJson.integer(VenueJson.indexed(item, 0)))
        cid = VenueJson.indexed(item, 2)
        client_id = str(VenueJson.integer(cid)) if cid is not None else "venue-untagged:" + order_id
        side: VenueSide = "buy" if original_signed > 0 else "sell"
        time_in_force: VenueTimeInForce = "ioc" if order_type == "EXCHANGE IOC" else "gtc"
        return VenueOrderFact(
            client_id=client_id,
            venue_order_id=order_id,
            symbol=symbol,
            side=side,
            original_quantity=original,
            filled_quantity=VenueExactDecimal.difference(original, remaining),
            remaining_quantity=remaining,
            limit_price=VenueJson.decimal(VenueJson.indexed(item, 16)),
            time_in_force=time_in_force,
            post_only=bool(flags & 4096),
            status=status,
            source_at=VenueJson.milliseconds(VenueJson.indexed(item, 4)),
            received_at=response.received_at,
            raw=response.body,
        )

    @staticmethod
    def _fill_fact(item: list[object], response: VenueHttpResponse) -> VenueFillFact:
        """Normalize native signed trade amount and negative venue fee."""
        symbol = VenueJson.text(VenueJson.indexed(item, 1))
        BitfinexSpotAdapter._validate_symbol(symbol)
        amount = VenueJson.decimal(VenueJson.indexed(item, 4))
        if amount == 0:
            raise VenueProtocolError("Bitfinex zero-size trade")
        order_type = VenueJson.text(VenueJson.indexed(item, 6), allow_empty=True)
        if order_type and order_type not in ("EXCHANGE LIMIT", "EXCHANGE IOC"):
            raise VenueProtocolError("Bitfinex trade is not supported spot execution")
        order_id = str(VenueJson.integer(VenueJson.indexed(item, 3)))
        cid = VenueJson.indexed(item, 11)
        client_id = str(VenueJson.integer(cid)) if cid is not None else "venue-untagged:" + order_id
        side: VenueSide = "buy" if amount > 0 else "sell"
        return VenueFillFact(
            fill_id="bitfinex:" + str(VenueJson.integer(VenueJson.indexed(item, 0))),
            client_id=client_id,
            venue_order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=amount.copy_abs(),
            price=VenueJson.decimal(VenueJson.indexed(item, 5)),
            fee=VenueJson.decimal(VenueJson.indexed(item, 9)).copy_negate(),
            fee_currency=VenueJson.text(VenueJson.indexed(item, 10)),
            source_at=VenueJson.milliseconds(VenueJson.indexed(item, 2)),
            received_at=response.received_at,
            raw=response.body,
        )

    @staticmethod
    def _wallet_fact(item: list[object], raw: bytes, received_at: datetime) -> VenueBalance:
        """Normalize an exchange wallet; a null available balance stays unknown.

        Bitfinex sends null availability until it is calculated, as it usually is
        in private wallet frames. The exact total is always required.
        """
        if VenueJson.text(VenueJson.indexed(item, 0)) != "exchange":
            raise VenueProtocolError("Bitfinex wallet is not exchange spot wallet")
        available = VenueJson.indexed(item, 4)
        return VenueBalance(
            currency=VenueJson.text(VenueJson.indexed(item, 1)),
            total=VenueJson.decimal(VenueJson.indexed(item, 2)),
            available=None if available is None else VenueJson.decimal(available),
            received_at=received_at,
            raw=raw,
        )
