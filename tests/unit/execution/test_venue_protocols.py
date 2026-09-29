"""Exercise authenticated spot protocol facts against independent native payloads."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

# third party library imports
import msgspec
import pytest

# project library imports
from execution.venues import (
    BitfinexSpotAdapter,
    OKXSpotAdapter,
    VenueCredentials,
    VenueHttpRequest,
    VenueHttpResponse,
    VenueOrderRequest,
    VenueOutcomeUnknownError,
    VenueProtocolError,
    VenueRejectedError,
)


class ScriptedVenueTransport:
    """Return exact native bytes while recording signed requests."""

    def __init__(self, *replies: bytes, statuses: tuple[int, ...] = ()) -> None:
        """Stage one response per expected REST request."""
        self.replies = list(replies)
        self.statuses = list(statuses)
        self.requests: list[VenueHttpRequest] = []

    def request(self, request: VenueHttpRequest) -> VenueHttpResponse:
        """Capture the method, path, headers, and body without network access."""
        self.requests.append(request)
        if not self.replies:
            raise AssertionError("unexpected venue request")
        return VenueHttpResponse(
            status=self.statuses.pop(0) if self.statuses else 200,
            body=self.replies.pop(0),
            received_at=datetime(2026, 9, 26, 12, 0, tzinfo=UTC),
        )


class TestOKXSpotProtocol:
    """Verify demo isolation, exact cash spot economics, and bounded recovery."""

    at = datetime(2020, 1, 1, tzinfo=UTC)
    recent = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)

    @staticmethod
    def _envelope(items: list[object]) -> bytes:
        """Build a native OKX success envelope independently of adapter code."""
        payload: dict[str, object] = {"code": "0", "data": items, "msg": ""}
        return msgspec.json.encode(payload)

    @staticmethod
    def _order(
        *, instrument_type: str = "SPOT", state: str = "partially_filled"
    ) -> dict[str, object]:
        """Represent a two-unit cash order with a quarter-unit partial fill."""
        return {
            "instType": instrument_type,
            "tdMode": "cash",
            "instId": "ETH-USDT",
            "ordId": "987",
            "clOrdId": "abc123",
            "side": "buy",
            "ordType": "limit",
            "state": state,
            "sz": "2",
            "accFillSz": "0.25",
            "px": "125.125",
            "cTime": "1790423999000",
        }

    def test_demo_signature_order_payload_and_ack_is_not_final(self) -> None:
        """Use a fixed HMAC vector and native request fields for a posted order."""
        transport = ScriptedVenueTransport(
            self._envelope([{"acctLv": "1", "uid": "4455"}]),
            self._envelope([{"sCode": "0", "ordId": "987", "clOrdId": "abc123"}]),
        )
        adapter = OKXSpotAdapter(VenueCredentials("key", "secret", "pass"), transport)
        with pytest.raises(VenueProtocolError, match="qualified"):
            adapter.submit(
                VenueOrderRequest("abc123", "ETH-USDT", "buy", Decimal("2"), Decimal("125.125")),
                at=self.at,
                nonce=1,
            )
        profile = adapter.qualify_account(at=self.at, nonce=1)
        assert profile.environment == "okx_demo"
        assert profile.account_identity == "4455"
        assert adapter.capability_profiles[0].qualification == "fixture"
        assert "open_orders" in adapter.capability_profiles[0].operations
        headers = dict(transport.requests[0].headers)
        assert transport.requests[0].path == "/api/v5/account/config"
        assert headers["OK-ACCESS-SIGN"] == "RDbllvyIpiUV0nlJTv+TMpO09XL1aD+CVm8SDXBCeAI="
        assert headers["x-simulated-trading"] == "1"
        ack = adapter.submit(
            VenueOrderRequest(
                "abc123", "ETH-USDT", "buy", Decimal("2"), Decimal("125.125"), post_only=True
            ),
            at=self.at,
            nonce=2,
        )
        assert ack.operation == "submit" and ack.venue_order_id == "987"
        assert msgspec.json.decode(transport.requests[1].body, type=dict[str, str]) == {
            "instId": "ETH-USDT",
            "tdMode": "cash",
            "clOrdId": "abc123",
            "side": "buy",
            "ordType": "post_only",
            "sz": "2",
            "px": "125.125",
        }

    def test_partial_order_and_native_fee_precision(self) -> None:
        """A partial fill remains open and an OKX negative fee becomes cost."""
        fill = {
            "instType": "SPOT",
            "instId": "ETH-USDT",
            "ordId": "987",
            "clOrdId": "abc123",
            "billId": "456",
            "side": "buy",
            "fillSz": "0.000000000000000003",
            "fillPx": "125.125",
            "fee": "-0.000000000000000001",
            "feeCcy": "ETH",
            "fillTime": "1790424000000",
        }
        transport = ScriptedVenueTransport(
            self._envelope([{"acctLv": "1", "uid": "4455"}]),
            self._envelope([self._order()]),
            self._envelope([fill]),
        )
        adapter = OKXSpotAdapter(VenueCredentials("key", "secret", "pass"), transport)
        adapter.qualify_account(at=self.recent, nonce=1)
        order = adapter.order(
            "ETH-USDT",
            "abc123",
            submitted_at=datetime(2026, 9, 26, 11, tzinfo=UTC),
            venue_order_id="987",
            at=self.recent,
            nonce=2,
        )
        assert order is not None
        assert order.status == "partial"
        assert order.filled_quantity == Decimal("0.25")
        assert order.remaining_quantity == Decimal("1.75")
        assert b'"accFillSz":"0.25"' in order.raw
        page = adapter.fills(
            symbol="ETH-USDT",
            start_ms=1790423999000,
            end_ms=1790424001000,
            limit=100,
            cursor=None,
            at=self.recent,
            nonce=3,
        )
        assert page.complete and page.next_cursor is None
        assert page.fills[0].fee == Decimal("0.000000000000000001")
        assert page.fills[0].fee_currency == "ETH"
        assert page.fills[0].quantity == Decimal("0.000000000000000003")

    def test_unknown_order_lookup_is_absent_and_other_codes_reject(self) -> None:
        """OKX's documented 51603 means absent; any other nonzero code stays a rejection."""
        transport = ScriptedVenueTransport(
            self._envelope([{"acctLv": "1", "uid": "4455"}]),
            b'{"code":"51603","data":[],"msg":"Order does not exist"}',
            b'{"code":"51000","data":[],"msg":"Parameter ordId error"}',
        )
        adapter = OKXSpotAdapter(VenueCredentials("key", "secret", "pass"), transport)
        adapter.qualify_account(at=self.recent, nonce=1)
        submitted_at = datetime(2026, 9, 26, 11, tzinfo=UTC)
        absent = adapter.order(
            "ETH-USDT",
            "abc123",
            submitted_at=submitted_at,
            venue_order_id=None,
            at=self.recent,
            nonce=2,
        )
        assert absent is None
        with pytest.raises(VenueRejectedError, match="51000"):
            adapter.order(
                "ETH-USDT",
                "abc123",
                submitted_at=submitted_at,
                venue_order_id=None,
                at=self.recent,
                nonce=3,
            )

    def test_account_wide_orders_reject_other_products(self) -> None:
        """A non-spot pending order cannot disappear behind a spot filter."""
        transport = ScriptedVenueTransport(
            self._envelope([{"acctLv": "1", "uid": "4455"}]),
            self._envelope([self._order(instrument_type="SWAP")]),
        )
        adapter = OKXSpotAdapter(VenueCredentials("key", "secret", "pass"), transport)
        adapter.qualify_account(at=self.recent, nonce=1)
        with pytest.raises(VenueProtocolError, match="non-cash-spot"):
            adapter.open_orders(at=self.recent, nonce=2)
        assert transport.requests[1].path == "/api/v5/trade/orders-pending?limit=100"

    def test_private_login_and_error_requires_recovery(self) -> None:
        """Demo stream authenticates explicitly and surfaces control errors."""
        adapter = OKXSpotAdapter(
            VenueCredentials("key", "secret", "pass"), ScriptedVenueTransport()
        )
        login = adapter.private_login(at=self.at, nonce=1)
        assert b'"op":"login"' in login
        assert b'"timestamp":"1577836800"' in login
        first = adapter.decode_private(b'{"event":"login","code":"0"}', received_at=self.recent)
        assert first.kind == "authenticated"
        failure = adapter.decode_private(
            b'{"event":"error","code":"60009"}', received_at=self.recent
        )
        assert failure.kind == "recovery_required"

    def test_invalid_account_identity_and_redirect_never_admit_commands(self) -> None:
        """An incomplete profile cannot set the account gate; a redirect is uncertain."""
        missing = ScriptedVenueTransport(self._envelope([{"acctLv": "1", "uid": ""}]))
        adapter = OKXSpotAdapter(VenueCredentials("key", "secret", "pass"), missing)
        with pytest.raises(VenueProtocolError, match="venue text"):
            adapter.qualify_account(at=self.at, nonce=1)
        with pytest.raises(VenueProtocolError, match="qualified"):
            adapter.submit(
                VenueOrderRequest("abc123", "ETH-USDT", "buy", Decimal("1"), Decimal("125")),
                at=self.at,
                nonce=2,
            )
        redirect = OKXSpotAdapter(
            VenueCredentials("key", "secret", "pass"),
            ScriptedVenueTransport(b"", statuses=(302,)),
        )
        with pytest.raises(VenueOutcomeUnknownError):
            redirect.qualify_account(at=self.at, nonce=3)


class TestBitfinexSpotProtocol:
    """Verify paper account qualification, signed commands, and sequence recovery."""

    at = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)

    @staticmethod
    def _paper_info(enabled: int = 1) -> bytes:
        """Set the documented User Info PPT_ENABLED slot at index 21."""
        values: list[object] = [None] * 22
        values[0] = 7788
        values[21] = enabled
        return msgspec.json.encode(values)

    @staticmethod
    def _order(*, status: str = "ACTIVE", order_type: str = "EXCHANGE LIMIT") -> list[object]:
        """Build the documented 32-field native order array."""
        values: list[object] = [None] * 32
        values[0] = 987
        values[2] = 1234
        values[3] = "tETHUSD"
        values[4] = 1790424000000
        values[5] = 1790424000000
        values[6] = 1.5
        values[7] = 2
        values[8] = order_type
        values[12] = 0
        values[13] = status
        values[16] = 125.12
        return values

    def test_paper_flag_is_required_and_signature_uses_exact_body(self) -> None:
        """A live account is blocked; paper qualification uses fixed HMAC vector."""
        live_transport = ScriptedVenueTransport(self._paper_info(enabled=0))
        live = BitfinexSpotAdapter(VenueCredentials("key", "secret"), live_transport)
        with pytest.raises(VenueProtocolError, match="paper account"):
            live.qualify_account(at=self.at, nonce=1234)
        with pytest.raises(VenueProtocolError, match="qualified"):
            live.submit(
                VenueOrderRequest("1234", "tETHUSD", "buy", Decimal("1"), Decimal("125")),
                at=self.at,
                nonce=1235,
            )
        paper_transport = ScriptedVenueTransport(self._paper_info())
        paper = BitfinexSpotAdapter(VenueCredentials("key", "secret"), paper_transport)
        qualified = paper.qualify_account(at=self.at, nonce=1234)
        assert qualified.environment == "bitfinex_paper"
        assert qualified.account_identity == "7788"
        headers = dict(paper_transport.requests[0].headers)
        assert paper_transport.requests[0].path == "/v2/auth/r/info/user"
        assert headers["bfx-nonce"] == "2468"
        assert headers["bfx-signature"] == (
            "2efd0c6a6b850438c6b2702709d1fc34adfb895a48eee16a9665ab64af750f633"
            "cd1e78fc1940bc92b2376a75f5e86ae"
        )

    def test_ioc_submit_cancel_ack_and_partial_cancel_state(self) -> None:
        """A cancel notification does not erase the partially executed quantity."""
        partial = self._order(status="CANCELED was: PARTIALLY FILLED")
        submit = [
            1790424000000,
            "on-req",
            None,
            None,
            [self._order(order_type="EXCHANGE IOC")],
            None,
            "SUCCESS",
            "",
        ]
        cancel = [1790424000001, "oc-req", None, None, partial, None, "SUCCESS", ""]
        history_items: list[object] = [partial]
        transport = ScriptedVenueTransport(
            self._paper_info(),
            msgspec.json.encode(submit),
            msgspec.json.encode(cancel),
            msgspec.json.encode(history_items),
        )
        adapter = BitfinexSpotAdapter(VenueCredentials("key", "secret"), transport)
        adapter.qualify_account(at=self.at, nonce=1)
        with pytest.raises(ValueError, match="five significant"):
            adapter.submit(
                VenueOrderRequest("1234", "tETHUSD", "buy", Decimal("2"), Decimal("125.125")),
                at=self.at,
                nonce=2,
            )
        ack = adapter.submit(
            VenueOrderRequest(
                "1234",
                "tETHUSD",
                "buy",
                Decimal("2"),
                Decimal("125.12"),
                time_in_force="ioc",
            ),
            at=self.at,
            nonce=2,
        )
        assert ack.operation == "submit"
        assert msgspec.json.decode(transport.requests[1].body, type=dict[str, str | int]) == {
            "type": "EXCHANGE IOC",
            "symbol": "tETHUSD",
            "amount": "2",
            "price": "125.12",
            "cid": 1234,
            "flags": 0,
        }
        cancel_ack = adapter.cancel(
            "tETHUSD",
            "1234",
            submitted_at=self.at,
            venue_order_id="987",
            at=self.at,
            nonce=3,
        )
        assert cancel_ack.operation == "cancel" and cancel_ack.venue_order_id == "987"
        fact = adapter.order(
            "tETHUSD",
            "1234",
            submitted_at=self.at,
            venue_order_id="987",
            at=self.at,
            nonce=4,
        )
        assert fact is not None
        assert fact.status == "cancelled"
        assert fact.filled_quantity == Decimal("0.5")
        assert fact.remaining_quantity == Decimal("1.5")

    def test_decimal_trade_fee_and_full_page_rejection(self) -> None:
        """Preserve wire decimal precision and refuse ambiguous timestamp paging."""
        # Native response bytes intentionally contain JSON numbers, not strings.
        raw = (
            b'[[55,"tETHUSD",1790424000000,987,-0.000000000000000003,'
            b'125.125,"EXCHANGE LIMIT",125.125,1,-0.000000000000000001,"USD",1234]]'
        )
        transport = ScriptedVenueTransport(self._paper_info(), raw)
        adapter = BitfinexSpotAdapter(VenueCredentials("key", "secret"), transport)
        adapter.qualify_account(at=self.at, nonce=1)
        page = adapter.fills(
            symbol="tETHUSD",
            start_ms=1790424000000,
            end_ms=1790424000000,
            limit=2,
            cursor=None,
            at=self.at,
            nonce=2,
        )
        assert page.complete and page.fills[0].quantity == Decimal("0.000000000000000003")
        assert page.fills[0].fee == Decimal("0.000000000000000001")
        assert page.fills[0].fee_currency == "USD"
        full = ScriptedVenueTransport(self._paper_info(), raw)
        full_adapter = BitfinexSpotAdapter(VenueCredentials("key", "secret"), full)
        full_adapter.qualify_account(at=self.at, nonce=3)
        with pytest.raises(VenueProtocolError, match="same-millisecond"):
            full_adapter.fills(
                symbol="tETHUSD",
                start_ms=1790424000000,
                end_ms=1790424000000,
                limit=1,
                cursor=None,
                at=self.at,
                nonce=4,
            )
        assert page.fills[0].fill_id == "bitfinex:55"

    @staticmethod
    def _trade(identity: int, milliseconds: int) -> list[object]:
        """Build one documented native trade array at an exact source millisecond."""
        return [
            identity,
            "tETHUSD",
            milliseconds,
            987,
            "0.01",
            "125.12",
            "EXCHANGE LIMIT",
            "125.12",
            1,
            "-0.01",
            "USD",
            1234,
        ]

    def test_trade_history_continues_from_the_last_page_millisecond(self) -> None:
        """A full page restarts inside its last millisecond instead of dropping fills."""
        start = 1790424000000
        pages: list[list[object]] = [
            [self._trade(1, start), self._trade(2, start + 1), self._trade(3, start + 1)],
            [self._trade(2, start + 1), self._trade(3, start + 1), self._trade(4, start + 2)],
            [self._trade(4, start + 2)],
        ]
        transport = ScriptedVenueTransport(
            self._paper_info(), *(msgspec.json.encode(page) for page in pages)
        )
        adapter = BitfinexSpotAdapter(VenueCredentials("key", "secret"), transport)
        adapter.qualify_account(at=self.at, nonce=1)
        cursor: str | None = None
        identities: list[str] = []
        for nonce in (2, 3, 4):
            page = adapter.fills(
                symbol="tETHUSD",
                start_ms=start,
                end_ms=start + 5,
                limit=3,
                cursor=cursor,
                at=self.at,
                nonce=nonce,
            )
            identities.extend(fill.fill_id for fill in page.fills)
            cursor = page.next_cursor
        assert page.complete and cursor is None
        assert identities == [f"bitfinex:{item}" for item in (1, 2, 3, 2, 3, 4, 4)]
        bodies = [
            msgspec.json.decode(request.body, type=dict[str, int])
            for request in transport.requests[1:]
        ]
        assert [body["start"] for body in bodies] == [start, start + 1, start + 2]
        assert all(body["sort"] == 1 and body["end"] == start + 5 for body in bodies)
        for invalid in ("01790424000001", "later", str(start - 1), str(start + 6)):
            with pytest.raises(ValueError, match="cursor"):
                adapter.fills(
                    symbol="tETHUSD",
                    start_ms=start,
                    end_ms=start + 5,
                    limit=3,
                    cursor=invalid,
                    at=self.at,
                    nonce=5,
                )
        assert len(transport.requests) == 4

    def test_trade_history_page_must_ascend_within_its_window(self) -> None:
        """A descending or out-of-window native page cannot become a continuation."""
        start = 1790424000000
        descending: list[object] = [self._trade(2, start + 1), self._trade(1, start)]
        transport = ScriptedVenueTransport(self._paper_info(), msgspec.json.encode(descending))
        adapter = BitfinexSpotAdapter(VenueCredentials("key", "secret"), transport)
        adapter.qualify_account(at=self.at, nonce=1)
        with pytest.raises(VenueProtocolError, match="ascending"):
            adapter.fills(
                symbol="tETHUSD",
                start_ms=start,
                end_ms=start + 5,
                limit=3,
                cursor=None,
                at=self.at,
                nonce=2,
            )

    def test_derivative_symbol_is_rejected_before_send_and_on_account_read(self) -> None:
        """A shared native endpoint cannot admit perpetual-futures symbols as spot."""
        derivative = self._order()
        derivative[3] = "tBTCF0:USTF0"
        orders: list[object] = [derivative]
        transport = ScriptedVenueTransport(self._paper_info(), msgspec.json.encode(orders))
        adapter = BitfinexSpotAdapter(VenueCredentials("key", "secret"), transport)
        adapter.qualify_account(at=self.at, nonce=1)
        with pytest.raises(ValueError, match="spot symbol"):
            adapter.submit(
                VenueOrderRequest("1234", "tBTCF0:USTF0", "buy", Decimal("1"), Decimal("125")),
                at=self.at,
                nonce=2,
            )
        assert len(transport.requests) == 1
        with pytest.raises(ValueError, match="spot symbol"):
            adapter.open_orders(at=self.at, nonce=3)

    def test_sequence_gap_requires_recovery(self) -> None:
        """A missing private event is visible before another order can be trusted."""
        adapter = BitfinexSpotAdapter(
            VenueCredentials("key", "secret"), ScriptedVenueTransport(self._paper_info())
        )
        adapter.qualify_account(at=self.at, nonce=1)
        assert adapter.private_configuration()[0] == b'{"event":"conf","flags":65536}'
        login = adapter.private_login(at=self.at, nonce=10)
        assert b'"authPayload":"AUTH20"' in login
        assert msgspec.json.decode(login, type=dict[str, object])["authNonce"] == "20"
        assert (
            adapter.decode_private(
                b'{"event":"conf","status":"OK","flags":65536}', received_at=self.at
            ).kind
            == "heartbeat"
        )
        assert (
            adapter.decode_private(
                b'{"event":"auth","status":"OK","userId":7788}', received_at=self.at
            ).kind
            == "authenticated"
        )
        assert adapter.decode_private(b'[0,"hb",7]', received_at=self.at).kind == "heartbeat"
        assert (
            adapter.decode_private(b'[0,"hb",9]', received_at=self.at).kind == "recovery_required"
        )

    def _authenticated(self) -> BitfinexSpotAdapter:
        """Qualify, configure and authenticate a paper private session at sequence zero."""
        adapter = BitfinexSpotAdapter(
            VenueCredentials("key", "secret"), ScriptedVenueTransport(self._paper_info())
        )
        adapter.qualify_account(at=self.at, nonce=1)
        adapter.private_login(at=self.at, nonce=2)
        adapter.decode_private(b'{"event":"conf","status":"OK","flags":65536}', received_at=self.at)
        authenticated = adapter.decode_private(
            b'{"event":"auth","status":"OK","userId":7788}', received_at=self.at
        )
        assert authenticated.kind == "authenticated"
        return adapter

    @staticmethod
    def _snapshot_entry(kind: str, amount: str) -> list[object]:
        """Build one position or funding entry with its documented amount slot."""
        values: list[object] = [None] * 22
        index = {"ps": 2, "fos": 4, "fcs": 5, "fls": 5}[kind]
        values[0] = "tETHUSD" if kind == "ps" else 55
        values[index] = amount
        return values

    def test_flat_account_snapshots_and_valuations_are_heartbeats(self) -> None:
        """Documented post-auth snapshots of a spot-only account keep the session."""
        adapter = self._authenticated()
        frames: list[list[object]] = [
            [0, "ps", []],
            [0, "ps", [self._snapshot_entry("ps", "0")]],
            [0, "fos", []],
            [0, "fcs", [self._snapshot_entry("fcs", "0")]],
            [0, "fls", []],
            [0, "bu", ["10000.5", "10000.5"]],
        ]
        for sequence, frame in enumerate(frames, start=1):
            numbered: list[object] = [*frame, sequence]
            event = adapter.decode_private(msgspec.json.encode(numbered), received_at=self.at)
            assert event.kind == "heartbeat", frame[1]

    def test_wallet_frames_accept_unknown_availability(self) -> None:
        """A null available balance is unknown, while the exact total is retained."""
        adapter = self._authenticated()
        snapshot = adapter.decode_private(
            b'[0,"ws",[["exchange","USD",10000.5,0,null],["margin","USD",0,0,null]],1]',
            received_at=self.at,
        )
        assert snapshot.kind == "balance"
        assert [(item.currency, item.total, item.available) for item in snapshot.balances] == [
            ("USD", Decimal("10000.5"), None)
        ]
        update = adapter.decode_private(
            b'[0,"wu",["exchange","ETH",0.5,0,null],2]', received_at=self.at
        )
        assert [(item.total, item.available) for item in update.balances] == [
            (Decimal("0.5"), None)
        ]
        wallets: list[object] = [["exchange", "USD", "10000.5", 0, None]]
        transport = ScriptedVenueTransport(self._paper_info(), msgspec.json.encode(wallets))
        rest = BitfinexSpotAdapter(VenueCredentials("key", "secret"), transport)
        rest.qualify_account(at=self.at, nonce=1)
        with pytest.raises(VenueProtocolError, match="availability"):
            rest.balances(at=self.at, nonce=2)

    @pytest.mark.parametrize("kind", ["ps", "fos", "fcs", "fls"])
    def test_margin_or_funding_exposure_requires_recovery(self, kind: str) -> None:
        """A nonzero position or funding entry cannot be absorbed as a heartbeat."""
        adapter = self._authenticated()
        entries: list[object] = [self._snapshot_entry(kind, "0"), self._snapshot_entry(kind, "0.5")]
        frame: list[object] = [0, kind, entries, 1]
        event = adapter.decode_private(msgspec.json.encode(frame), received_at=self.at)
        assert event.kind == "recovery_required"

    def test_private_auth_rejects_another_physical_account(self) -> None:
        """A paper socket for a different user cannot inherit REST qualification."""
        adapter = BitfinexSpotAdapter(
            VenueCredentials("key", "secret"), ScriptedVenueTransport(self._paper_info())
        )
        adapter.qualify_account(at=self.at, nonce=1)
        adapter.private_login(at=self.at, nonce=2)
        adapter.decode_private(b'{"event":"conf","status":"OK","flags":65536}', received_at=self.at)
        mismatch = adapter.decode_private(
            b'{"event":"auth","status":"OK","userId":1234}', received_at=self.at
        )
        assert mismatch.kind == "recovery_required"
        maintenance = adapter.decode_private(
            b'{"event":"info","version":2,"platform":{"status":0}}', received_at=self.at
        )
        assert maintenance.kind == "recovery_required"

    def test_cumulative_quantity_ignores_ambient_decimal_precision(self) -> None:
        """Tiny partial fills survive a process-wide low Decimal precision."""
        order = self._order(status="PARTIALLY FILLED @ 125")
        order[6] = "1.000000000000000001"
        order[7] = "1.000000000000000003"
        history_items: list[object] = [order]
        transport = ScriptedVenueTransport(self._paper_info(), msgspec.json.encode(history_items))
        adapter = BitfinexSpotAdapter(VenueCredentials("key", "secret"), transport)
        adapter.qualify_account(at=self.at, nonce=1)
        with localcontext() as context:
            context.prec = 3
            fact = adapter.order(
                "tETHUSD",
                "1234",
                submitted_at=self.at,
                venue_order_id="987",
                at=self.at,
                nonce=2,
            )
        assert fact is not None
        assert fact.filled_quantity == Decimal("0.000000000000000002")
        assert fact.remaining_quantity == Decimal("1.000000000000000001")

    def test_closed_order_outside_retention_fails_before_history_lookup(self) -> None:
        """Active orders prove any age; two-week closed history cannot prove absence."""
        active_items: list[object] = [self._order()]
        transport = ScriptedVenueTransport(
            self._paper_info(), msgspec.json.encode(active_items), b"[]"
        )
        adapter = BitfinexSpotAdapter(VenueCredentials("key", "secret"), transport)
        adapter.qualify_account(at=self.at, nonce=1)
        submitted_at = datetime(2026, 9, 26, 12, tzinfo=UTC)
        resting = adapter.order(
            "tETHUSD",
            "1234",
            submitted_at=submitted_at,
            venue_order_id="987",
            at=submitted_at + timedelta(days=20),
            nonce=2,
        )
        assert resting is not None and resting.status == "open"
        with pytest.raises(VenueProtocolError, match="retention"):
            adapter.order(
                "tETHUSD",
                "1234",
                submitted_at=submitted_at,
                venue_order_id="987",
                at=submitted_at + timedelta(days=20),
                nonce=4,
            )
        assert [item.path for item in transport.requests[1:]] == ["/v2/auth/r/orders"] * 2
