"""Authenticate and normalize OKX demo spot order/account protocols."""

from __future__ import annotations

# standard library imports
from base64 import b64encode
from datetime import UTC, datetime
from hashlib import sha256
from hmac import new
from typing import Literal
from urllib.parse import urlencode

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


class OKXSpotAdapter:
    """Translate admitted physical orders to the authenticated OKX demo API."""

    def __init__(self, credentials: VenueCredentials, transport: VenueHttpTransport) -> None:
        """Bind explicit demo credentials and a caller-selected transport."""
        credentials.__post_init__()
        if not credentials.passphrase:
            raise ValueError("OKX demo API requires an API passphrase")
        self.credentials = credentials
        self.transport = transport
        self.throttle = VenueRateLimiter(requests=5, seconds=2.0)
        self.account_verified = False
        self.private_authenticated = False

    @property
    def capability_profiles(self) -> tuple[CapabilityProfile, ...]:
        """Advertise spot test execution and account reads to the component registry."""
        return (
            CapabilityProfile(
                name="okx_demo_spot_execution",
                kind="execution",
                implementation_identity="execution.venues.okx",
                version="1",
                products=("spot",),
                venues=("okx",),
                calendars=("24x7", "continuous"),
                modes=("venue_test",),
                operations=("submit", "cancel", "order", "open_orders", "fills", "balances"),
                order_types=("gtc", "ioc", "post-only"),
                lifecycle=("partial_fill", "cancel_confirmed", "reconcile"),
                qualification="fixture",
            ),
            CapabilityProfile(
                name="okx_demo_spot_account",
                kind="account",
                implementation_identity="execution.venues.okx",
                version="1",
                products=("spot",),
                venues=("okx",),
                calendars=("24x7", "continuous"),
                modes=("venue_test",),
                operations=("balances", "open_orders", "fills"),
                qualification="fixture",
            ),
        )

    def qualify_account(self, *, at: datetime, nonce: int) -> VenueCapabilityProfile:
        """Read the demo account's mode and require cash-funded spot mode."""
        del nonce
        self.account_verified = False
        response = self._request("GET", "/api/v5/account/config", b"", at=at)
        entry = self._single(response.body)
        if VenueJson.text(VenueJson.field(entry, "acctLv")) != "1":
            raise VenueProtocolError("OKX demo account is not in spot mode")
        account_identity = VenueJson.text(VenueJson.field(entry, "uid"))
        profile = VenueCapabilityProfile(
            venue="okx",
            environment="okx_demo",
            account_identity=account_identity,
            account_verified=True,
        )
        self.account_verified = True
        return profile

    def wait_for_request_slot(self) -> None:
        """Wait for local request capacity so a dispatch fence never holds a sleep."""
        self.throttle.wait()

    def submit(
        self, order: VenueOrderRequest, *, at: datetime, nonce: int, deadline: float
    ) -> VenueCommandAck:
        """Submit one limit, IOC, or post-only cash spot order once, ending by ``deadline``."""
        del nonce
        self._require_verified()
        order.__post_init__()
        self._validate_symbol(order.symbol)
        self._validate_client_id(order.client_id)
        order_type = (
            "post_only" if order.post_only else "ioc" if order.time_in_force == "ioc" else "limit"
        )
        body = VenueJson.encode(
            {
                "instId": order.symbol,
                "tdMode": "cash",
                "clOrdId": order.client_id,
                "side": order.side,
                "ordType": order_type,
                "sz": str(order.quantity),
                "px": str(order.limit_price),
            }
        )
        response = self._request("POST", "/api/v5/trade/order", body, at=at, deadline=deadline)
        data = self._single(response.body)
        self._check_command(data)
        if VenueJson.text(VenueJson.field(data, "clOrdId")) != order.client_id:
            raise VenueProtocolError("OKX submit client identity mismatch")
        return VenueCommandAck(
            operation="submit",
            client_id=order.client_id,
            venue_order_id=VenueJson.text(VenueJson.field(data, "ordId")),
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
        """Ask OKX to cancel; confirmation must come from order state."""
        del submitted_at, nonce
        self._require_verified()
        self._validate_symbol(symbol)
        self._validate_client_id(client_id)
        payload = {"instId": symbol, "clOrdId": client_id}
        if venue_order_id is not None:
            payload["ordId"] = venue_order_id
        response = self._request(
            "POST", "/api/v5/trade/cancel-order", VenueJson.encode(payload), at=at
        )
        data = self._single(response.body)
        self._check_command(data)
        if VenueJson.text(VenueJson.field(data, "clOrdId")) != client_id:
            raise VenueProtocolError("OKX cancel client identity mismatch")
        return VenueCommandAck(
            operation="cancel",
            client_id=client_id,
            venue_order_id=VenueJson.text(VenueJson.field(data, "ordId")),
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
        open_seen_at: datetime | None = None,
    ) -> VenueOrderFact | None:
        """Look up a stable identity, preferring the venue's immutable order ID."""
        del nonce, open_seen_at
        self._require_verified()
        self._validate_symbol(symbol)
        self._validate_client_id(client_id)
        query = {"instId": symbol}
        query["ordId" if venue_order_id is not None else "clOrdId"] = venue_order_id or client_id
        response = self._request("GET", "/api/v5/trade/order?" + urlencode(query), b"", at=at)
        envelope = VenueJson.mapping(VenueJson.parse(response.body))
        if VenueJson.text(VenueJson.field(envelope, "code")) == "51603":
            # OKX reports an unknown order identity as this top-level code, not
            # as empty data; absence is not finality, and callers treat it so.
            return None
        items = self._entries(response.body)
        if not items:
            return None
        if len(items) != 1:
            raise VenueProtocolError("OKX order lookup is ambiguous")
        fact = self._order_fact(items[0], response)
        if (
            fact.client_id != client_id
            or fact.symbol != symbol
            or (venue_order_id is not None and fact.venue_order_id != venue_order_id)
        ):
            raise VenueProtocolError("OKX order lookup identity mismatch")
        if fact.source_at is not None and fact.source_at < submitted_at:
            raise VenueProtocolError("OKX order predates durable submission")
        return fact

    def open_orders(self, *, at: datetime, nonce: int) -> tuple[VenueOrderFact, ...]:
        """Read all incomplete orders, rejecting hidden non-spot account exposure."""
        del nonce
        self._require_verified()
        result: list[VenueOrderFact] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(64):
            query = {"limit": "100"}
            if cursor is not None:
                query["after"] = cursor
            response = self._request(
                "GET", "/api/v5/trade/orders-pending?" + urlencode(query), b"", at=at
            )
            entries = self._entries(response.body)
            for entry in entries:
                fact = self._order_fact(entry, response)
                if fact.venue_order_id in seen or fact.status not in ("open", "partial"):
                    raise VenueProtocolError("OKX open order page is inconsistent")
                seen.add(fact.venue_order_id)
                result.append(fact)
            if len(entries) < 100:
                return tuple(result)
            next_cursor = result[-1].venue_order_id
            if next_cursor == cursor:
                raise VenueProtocolError("OKX open order pagination did not advance")
            cursor = next_cursor
        raise VenueProtocolError("OKX open order pagination exceeded bound")

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
        """Read one bill-ID-paginated spot fill page within a caller-bound interval."""
        del nonce
        self._require_verified()
        self._validate_symbol(symbol)
        if not (0 <= start_ms <= end_ms) or not (1 <= limit <= 100):
            raise ValueError("invalid OKX fill window or limit")
        if VenueJson.epoch_milliseconds(at) - start_ms > 89 * 86_400_000:
            raise VenueProtocolError("OKX fill window exceeds conservative history retention")
        query = {
            "instType": "SPOT",
            "instId": symbol,
            "begin": str(start_ms),
            "end": str(end_ms),
            "limit": str(limit),
        }
        if cursor is not None:
            if not cursor.isdigit():
                raise ValueError("invalid OKX fill cursor")
            query["after"] = cursor
        response = self._request(
            "GET", "/api/v5/trade/fills-history?" + urlencode(query), b"", at=at
        )
        entries = self._entries(response.body)
        fills = tuple(self._fill_fact(entry, response) for entry in entries)
        if any(
            fill.symbol != symbol
            or fill.source_at is None
            or not (start_ms <= VenueJson.epoch_milliseconds(fill.source_at) <= end_ms)
            for fill in fills
        ):
            raise VenueProtocolError("OKX fill outside requested spot interval")
        if len({fill.fill_id for fill in fills}) != len(fills):
            raise VenueProtocolError("OKX fill page repeats an identity")
        complete = len(entries) < limit
        next_cursor = None if complete else fills[-1].fill_id.removeprefix("okx:")
        if not complete and next_cursor == cursor:
            raise VenueProtocolError("OKX fill pagination did not advance")
        return VenueFillPage(fills=fills, next_cursor=next_cursor, complete=complete)

    def balances(self, *, at: datetime, nonce: int) -> tuple[VenueBalance, ...]:
        """Read every demo trading-account cash currency and reject liabilities."""
        del nonce
        self._require_verified()
        response = self._request("GET", "/api/v5/account/balance", b"", at=at)
        accounts = self._entries(response.body)
        if len(accounts) != 1:
            raise VenueProtocolError("OKX balance account count is ambiguous")
        details = VenueJson.array(VenueJson.field(accounts[0], "details"))
        result: list[VenueBalance] = []
        for value in details:
            entry = VenueJson.mapping(value)
            liability = VenueJson.decimal(VenueJson.field(entry, "liab"))
            if liability != 0:
                raise VenueProtocolError("OKX spot account has borrowed currency")
            result.append(
                VenueBalance(
                    currency=VenueJson.text(VenueJson.field(entry, "ccy")),
                    total=VenueJson.decimal(VenueJson.field(entry, "cashBal")),
                    available=VenueJson.decimal(VenueJson.field(entry, "availBal")),
                    received_at=response.received_at,
                    raw=response.body,
                )
            )
        if len({balance.currency for balance in result}) != len(result):
            raise VenueProtocolError("OKX balance repeats a currency")
        return tuple(result)

    def private_configuration(self) -> tuple[bytes, ...]:
        """OKX demo private stream needs no pre-login configuration."""
        return ()

    def private_login(self, *, at: datetime, nonce: int) -> bytes:
        """Sign the documented private WebSocket verification path."""
        del nonce
        seconds = str(int(at.timestamp()))
        signature = self._signature(seconds + "GET/users/self/verify")
        return VenueJson.encode(
            {
                "op": "login",
                "args": [
                    {
                        "apiKey": self.credentials.api_key,
                        "passphrase": self.credentials.passphrase,
                        "timestamp": seconds,
                        "sign": signature,
                    }
                ],
            }
        )

    def private_subscriptions(self) -> tuple[bytes, ...]:
        """Subscribe to all spot order changes and the account cash channel."""
        return (
            VenueJson.encode(
                {
                    "op": "subscribe",
                    "args": [
                        {"channel": "orders", "instType": "SPOT"},
                        {"channel": "account"},
                    ],
                }
            ),
        )

    def decode_private(self, raw: bytes, *, received_at: datetime) -> VenueStreamEvent:
        """Decode one authenticated frame, forcing recovery on unsupported changes."""
        value = VenueJson.mapping(VenueJson.parse(raw))
        event = value.get("event")
        if event is not None:
            name = VenueJson.text(event)
            if name == "login" and value.get("code") == "0":
                self.private_authenticated = True
                return VenueStreamEvent(kind="authenticated", received_at=received_at, raw=raw)
            if (
                name == "subscribe"
                and value.get("code") in (None, "0")
                and self.private_authenticated
            ):
                return VenueStreamEvent(kind="heartbeat", received_at=received_at, raw=raw)
            return VenueStreamEvent(
                kind="recovery_required",
                received_at=received_at,
                raw=raw,
                reason="OKX private control event",
            )
        if not self.private_authenticated:
            return VenueStreamEvent(
                kind="recovery_required",
                received_at=received_at,
                raw=raw,
                reason="OKX private data before login",
            )
        channel = VenueJson.text(
            VenueJson.field(VenueJson.mapping(VenueJson.field(value, "arg")), "channel")
        )
        items = VenueJson.array(VenueJson.field(value, "data"))
        response = VenueHttpResponse(status=200, body=raw, received_at=received_at)
        if channel == "orders":
            orders = tuple(self._order_fact(VenueJson.mapping(item), response) for item in items)
            return VenueStreamEvent(kind="order", received_at=received_at, raw=raw, orders=orders)
        if channel == "account":
            balances: list[VenueBalance] = []
            for item in items:
                account = VenueJson.mapping(item)
                for detail in VenueJson.array(VenueJson.field(account, "details")):
                    entry = VenueJson.mapping(detail)
                    balances.append(
                        VenueBalance(
                            currency=VenueJson.text(VenueJson.field(entry, "ccy")),
                            total=VenueJson.decimal(VenueJson.field(entry, "cashBal")),
                            available=VenueJson.decimal(VenueJson.field(entry, "availBal")),
                            received_at=received_at,
                            raw=raw,
                        )
                    )
            return VenueStreamEvent(
                kind="balance", received_at=received_at, raw=raw, balances=tuple(balances)
            )
        return VenueStreamEvent(
            kind="recovery_required",
            received_at=received_at,
            raw=raw,
            reason="unsupported OKX private channel",
        )

    def _require_verified(self) -> None:
        """Block commands until the demo account mode has been observed."""
        if not self.account_verified:
            raise VenueProtocolError("OKX demo account mode must be qualified")

    @staticmethod
    def _validate_symbol(symbol: str) -> None:
        """Keep the declared native spot identifier out of arbitrary request paths."""
        parts = symbol.split("-")
        if len(parts) != 2 or any(not part.isalnum() or part.upper() != part for part in parts):
            raise ValueError("invalid OKX spot symbol")

    @staticmethod
    def _validate_client_id(client_id: str) -> None:
        """Enforce OKX's 32-character native client-ID grammar."""
        if not 1 <= len(client_id) <= 32 or not client_id.isascii() or not client_id.isalnum():
            raise ValueError("invalid OKX client order ID")

    def _signature(self, message: str) -> str:
        """Compute the documented HMAC-SHA256/Base64 signature."""
        return b64encode(
            new(self.credentials.api_secret.encode(), message.encode(), sha256).digest()
        ).decode()

    def _request(
        self,
        method: Literal["GET", "POST"],
        path: str,
        body: bytes,
        *,
        at: datetime,
        deadline: float | None = None,
    ) -> VenueHttpResponse:
        """Sign exact request bytes and classify definite protocol failures."""
        if at.tzinfo is None or at.utcoffset() != UTC.utcoffset(None):
            raise ValueError("OKX request time must be UTC")
        self.throttle.acquire()
        timestamp = at.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        signature = self._signature(timestamp + method + path + body.decode("utf-8"))
        request = VenueHttpRequest(
            method=method,
            path=path,
            headers=(
                ("Content-Type", "application/json"),
                ("OK-ACCESS-KEY", self.credentials.api_key),
                ("OK-ACCESS-SIGN", signature),
                ("OK-ACCESS-TIMESTAMP", timestamp),
                ("OK-ACCESS-PASSPHRASE", self.credentials.passphrase or ""),
                ("x-simulated-trading", "1"),
            ),
            body=body,
        )
        response = self.transport.request(request, deadline=deadline)
        if (
            300 <= response.status < 400
            or response.status in (408, 425, 429)
            or response.status >= 500
        ):
            raise VenueOutcomeUnknownError("OKX request throttled or unavailable")
        if response.status != 200:
            raise VenueRejectedError(f"OKX REST status {response.status}")
        return response

    @staticmethod
    def _entries(raw: bytes) -> list[dict[str, object]]:
        """Require successful OKX envelope and data array."""
        envelope = VenueJson.mapping(VenueJson.parse(raw))
        code = VenueJson.text(VenueJson.field(envelope, "code"))
        if code != "0":
            raise VenueRejectedError(f"OKX API code {code}")
        return [
            VenueJson.mapping(item) for item in VenueJson.array(VenueJson.field(envelope, "data"))
        ]

    @classmethod
    def _single(cls, raw: bytes) -> dict[str, object]:
        """Require exactly one command or account result."""
        entries = cls._entries(raw)
        if len(entries) != 1:
            raise VenueProtocolError("OKX expected one response item")
        return entries[0]

    @staticmethod
    def _check_command(entry: dict[str, object]) -> None:
        """Distinguish a venue refusal from a request acknowledgement."""
        code = VenueJson.text(VenueJson.field(entry, "sCode"))
        if code != "0":
            raise VenueRejectedError(f"OKX order code {code}")

    @staticmethod
    def _order_fact(entry: dict[str, object], response: VenueHttpResponse) -> VenueOrderFact:
        """Normalize one complete cash-spot order state."""
        if (
            VenueJson.text(VenueJson.field(entry, "instType")) != "SPOT"
            or VenueJson.text(VenueJson.field(entry, "tdMode")) != "cash"
        ):
            raise VenueProtocolError("OKX account contains non-cash-spot order")
        order_type = VenueJson.text(VenueJson.field(entry, "ordType"))
        if order_type not in ("limit", "ioc", "post_only"):
            raise VenueProtocolError("unsupported OKX spot order mechanics")
        time_in_force: VenueTimeInForce = "ioc" if order_type == "ioc" else "gtc"
        state = VenueJson.text(VenueJson.field(entry, "state"))
        statuses: dict[str, VenueOrderStatus] = {
            "live": "open",
            "partially_filled": "partial",
            "filled": "filled",
            "canceled": "cancelled",
            "mmp_canceled": "cancelled",
        }
        if state not in statuses:
            raise VenueProtocolError("unsupported OKX order state")
        side_text = VenueJson.text(VenueJson.field(entry, "side"))
        if side_text not in ("buy", "sell"):
            raise VenueProtocolError("unsupported OKX order side")
        side: VenueSide = "buy" if side_text == "buy" else "sell"
        original = VenueJson.decimal(VenueJson.field(entry, "sz"))
        filled = VenueJson.decimal(VenueJson.field(entry, "accFillSz"))
        order_id = VenueJson.text(VenueJson.field(entry, "ordId"))
        client_id = (
            VenueJson.text(VenueJson.field(entry, "clOrdId"), allow_empty=True)
            or "venue-untagged:" + order_id
        )
        return VenueOrderFact(
            client_id=client_id,
            venue_order_id=order_id,
            symbol=VenueJson.text(VenueJson.field(entry, "instId")),
            side=side,
            original_quantity=original,
            filled_quantity=filled,
            remaining_quantity=VenueExactDecimal.difference(original, filled),
            limit_price=VenueJson.decimal(VenueJson.field(entry, "px")),
            time_in_force=time_in_force,
            post_only=order_type == "post_only",
            status=statuses[state],
            source_at=VenueJson.milliseconds(VenueJson.field(entry, "cTime")),
            received_at=response.received_at,
            raw=response.body,
        )

    @staticmethod
    def _fill_fact(entry: dict[str, object], response: VenueHttpResponse) -> VenueFillFact:
        """Normalize signed OKX fees into positive cost/negative rebate."""
        if VenueJson.text(VenueJson.field(entry, "instType")) != "SPOT":
            raise VenueProtocolError("OKX fill is not spot")
        side_text = VenueJson.text(VenueJson.field(entry, "side"))
        if side_text not in ("buy", "sell"):
            raise VenueProtocolError("unsupported OKX fill side")
        side: VenueSide = "buy" if side_text == "buy" else "sell"
        order_id = VenueJson.text(VenueJson.field(entry, "ordId"))
        client_id = (
            VenueJson.text(VenueJson.field(entry, "clOrdId"), allow_empty=True)
            or "venue-untagged:" + order_id
        )
        return VenueFillFact(
            fill_id="okx:" + VenueJson.text(VenueJson.field(entry, "billId")),
            client_id=client_id,
            venue_order_id=order_id,
            symbol=VenueJson.text(VenueJson.field(entry, "instId")),
            side=side,
            quantity=VenueJson.decimal(VenueJson.field(entry, "fillSz")),
            price=VenueJson.decimal(VenueJson.field(entry, "fillPx")),
            fee=VenueJson.decimal(VenueJson.field(entry, "fee")).copy_negate(),
            fee_currency=VenueJson.text(VenueJson.field(entry, "feeCcy")),
            source_at=VenueJson.milliseconds(VenueJson.field(entry, "fillTime")),
            received_at=response.received_at,
            raw=response.body,
        )
