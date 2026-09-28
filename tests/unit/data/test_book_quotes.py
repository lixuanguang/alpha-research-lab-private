"""Verify exact native book aggregates and per-boundary quote availability."""

from __future__ import annotations

# standard library imports
import hashlib
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Literal

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from configuration import CaptureConfig
from market_data.adapters.sources import BookAdapters
from market_data.books import BookDepth, BookProjection, CaptureReplay
from market_data.contracts import (
    BookObservation,
    BookQuote,
    BookQuoteSide,
    CaptureRecord,
    Level,
    Order,
)
from serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_BITFINEX_CONF = b'{"event":"conf","status":"OK","flags":65536}'
_BITFINEX_ACK = (
    b'{"event":"subscribed","chanId":7,"channel":"book","symbol":"tBTCUSD",'
    b'"prec":"R0","freq":"F0","len":"25"}'
)
_OKX_ACK = b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}'


class _BookScenario:
    """Apply complete saved native boundaries through the production replay owner."""

    def __init__(self, venue: Literal["bitfinex", "okx"]) -> None:
        """Bind one maintained capture selection and an isolated replay epoch."""
        suffix = "usd" if venue == "bitfinex" else "usdt"
        self.config = CaptureConfig.read(_ROOT / f"configs/live/{venue}-btc-{suffix}.json")
        self.replay = CaptureReplay(self.config, book_factory=BookAdapters.create)
        self.position = 0

    def push(
        self,
        kind: Literal["session", "frame", "gap"],
        *,
        raw: bytes = b"",
        epoch: int = 0,
        reason: str = "",
        available_ns: int | None = None,
    ) -> tuple[BookObservation, BookQuote]:
        """Return canonical state and quote for the same entire native message."""
        record = CaptureRecord(
            kind=kind,
            epoch=epoch,
            received_ns=1_000_000_000 + self.position,
            raw=raw,
            reason=reason,
        )
        outcome = self.replay.apply(record)
        row = BookProjection.capture(self.position, record, outcome, self.replay)
        quote = BookProjection.quote(
            self.position,
            record,
            outcome,
            self.replay,
            source_id="saved-native-source",
            available_ns=available_ns,
        )
        self.position += 1
        return row, quote

    def acknowledge_bitfinex(self, epoch: int) -> None:
        """Admit the native sequenced order channel in one new session."""
        self.push("session", epoch=epoch)
        self.push("frame", epoch=epoch, raw=_BITFINEX_CONF)
        self.push("frame", epoch=epoch, raw=_BITFINEX_ACK)


class TestIncrementalBookDepth:
    """Compare cached L3 totals to independent full aggregation after each update."""

    @staticmethod
    def _exact_sum(sizes: list[Decimal]) -> Decimal:
        """Sum rationals and rebuild the exact finite decimal without Decimal arithmetic."""
        total = sum((Fraction(size) for size in sizes), Fraction())
        denominator = total.denominator
        twos = 0
        fives = 0
        while denominator % 2 == 0:
            denominator //= 2
            twos += 1
        while denominator % 5 == 0:
            denominator //= 5
            fives += 1
        assert denominator == 1
        scale = max(twos, fives)
        factor = 1
        for _ in range(scale):
            factor *= 10
        coefficient = total.numerator * factor // total.denominator
        return Decimal((0, tuple(int(digit) for digit in str(coefficient)), -scale))

    @classmethod
    def _expected_levels(
        cls, orders: tuple[Order, ...], side: Literal["buy", "sell"]
    ) -> tuple[tuple[Decimal, Level], ...]:
        """Regroup every expected order by side and price without reading cached levels."""
        prices = sorted({order.price for order in orders if order.side == side})
        return tuple(
            (
                price,
                Level(
                    cls._exact_sum(
                        [
                            order.size
                            for order in orders
                            if order.side == side and order.price == price
                        ]
                    ),
                    sum(order.side == side and order.price == price for order in orders),
                ),
            )
            for price in prices
        )

    @staticmethod
    def _legacy_identity(orders: tuple[Order, ...], sequence: int, ready: bool) -> str:
        """Recompute the pre-aggregate order-only fingerprint from canonical orders."""
        codec = DomainCodec()
        fingerprint = 0
        for order in orders:
            fingerprint ^= int.from_bytes(hashlib.sha256(codec.encode_json(order)).digest())
        return hashlib.sha256(
            codec.encode_json((fingerprint, len(orders), sequence, ready))
        ).hexdigest()

    def test_bitfinex_lifecycle_matches_full_aggregation_under_low_precision(self) -> None:
        """Cover shared price, side/price/size amendments and deletion of best and last."""
        scenario = _BookScenario("bitfinex")
        scenario.acknowledge_bitfinex(0)
        tiny = Decimal("0.000000000000000001")
        huge = Decimal("999999999999999999.000000000000000001")
        expected: dict[str, Order] = {
            "1": Order("1", "buy", Decimal(100), tiny),
            "2": Order("2", "buy", Decimal(100), huge),
            "3": Order("3", "buy", Decimal(99), Decimal(3)),
            "4": Order("4", "sell", Decimal(102), Decimal(4)),
        }
        snapshot = (
            b"[7,[[1,100,0.000000000000000001],"
            b"[2,100,999999999999999999.000000000000000001],"
            b"[3,99,3],[4,102,-4]],1]"
        )
        changes: tuple[tuple[bytes, Order | None, str], ...] = (
            (b"[7,[5,100,0.2],2]", Order("5", "buy", Decimal(100), Decimal("0.2")), "5"),
            (b"[7,[2,101,2],3]", Order("2", "buy", Decimal(101), Decimal(2)), "2"),
            (b"[7,[5,100,-0.25],4]", Order("5", "sell", Decimal(100), Decimal("0.25")), "5"),
            (b"[7,[3,99,1],5]", Order("3", "buy", Decimal(99), Decimal(1)), "3"),
            (b"[7,[2,0,1],6]", None, "2"),
            (b"[7,[1,0,1],7]", None, "1"),
            (b"[7,[3,0,1],8]", None, "3"),
            (b"[7,[4,0,-1],9]", None, "4"),
            (b"[7,[5,0,-1],10]", None, "5"),
        )
        with localcontext() as context:
            context.prec = 6
            row, quote = scenario.push("frame", raw=snapshot)
            assert quote.bid == BookQuoteSide(
                Decimal(100), Decimal("999999999999999999.000000000000000002"), 2
            )
            self._assert_boundary(scenario, row, quote, tuple(expected.values()), 1)
            for sequence, (raw, replacement, order_id) in enumerate(changes, start=2):
                if replacement is None:
                    expected.pop(order_id)
                else:
                    expected[order_id] = replacement
                row, quote = scenario.push("frame", raw=raw)
                self._assert_boundary(scenario, row, quote, tuple(expected.values()), sequence)
        assert quote.market_state == "empty"
        assert quote.bid is None and quote.ask is None

    def _assert_boundary(
        self,
        scenario: _BookScenario,
        row: BookObservation,
        quote: BookQuote,
        orders: tuple[Order, ...],
        sequence: int,
    ) -> None:
        """Compare native cache, saved representation, quote and legacy identity."""
        bids = self._expected_levels(orders, "buy")
        asks = self._expected_levels(orders, "sell")
        assert scenario.replay.book.orders == {order.order_id: order for order in orders}
        assert scenario.replay.book.bids == dict(bids)
        assert scenario.replay.book.asks == dict(asks)
        assert set(row.orders) == set(orders)
        assert tuple(order.order_id for order in row.orders) == tuple(
            sorted(order.order_id for order in orders)
        )
        assert row.bids == () and row.asks == ()
        assert row.state_identity == self._legacy_identity(orders, sequence, True)
        assert quote.state_identity == row.state_identity
        assert quote.venue == "bitfinex" and quote.channel == scenario.config.channel
        assert quote.instrument_id == scenario.config.instrument_id
        assert quote.source_id == "saved-native-source"
        assert quote.position == row.position
        assert quote.epoch == row.epoch == 0 and quote.sequence == row.sequence == sequence
        assert quote.received_ns == row.received_ns and quote.available_ns is None
        assert quote.source_time == row.source_time is None
        assert quote.status == row.status and quote.reason == row.reason
        assert BookDepth.from_observation(row) == BookDepth(bids, asks)
        assert BookDepth.from_native(scenario.replay.book) == BookDepth(bids, asks)
        projected = BookDepth.project(row)
        assert projected.orders == () and projected.bids == bids and projected.asks == asks
        assert projected.state_identity == row.state_identity
        assert quote.bid == (
            None
            if not bids
            else BookQuoteSide(bids[-1][0], bids[-1][1].size, bids[-1][1].order_count)
        )
        assert quote.ask == (
            None if not asks else BookQuoteSide(asks[0][0], asks[0][1].size, asks[0][1].order_count)
        )
        assert BookDepth.touch_quote(
            row,
            venue=scenario.config.venue,
            instrument_id=scenario.config.instrument_id,
            source_id="saved-native-source",
            channel=scenario.config.channel,
            available_ns=None,
        ) == BookDepth.from_observation(row).quote(
            row,
            venue=scenario.config.venue,
            instrument_id=scenario.config.instrument_id,
            source_id="saved-native-source",
            channel=scenario.config.channel,
            available_ns=None,
        )

    def test_partial_snapshot_gap_and_new_snapshot_hide_unusable_depth(self) -> None:
        """Partial mutation and unknown continuity expose no executable quote."""
        scenario = _BookScenario("bitfinex")
        scenario.acknowledge_bitfinex(0)
        row, quote = scenario.push("frame", raw=b"[7,[[1,100,1],[2,0,-1]],1]")
        assert row.outcome == "invalid_frame"
        assert scenario.replay.book.orders == {"1": Order("1", "buy", Decimal(100), Decimal(1))}
        assert row.orders == () and row.bids == () and row.asks == ()
        assert BookDepth.from_native(scenario.replay.book) == BookDepth((), ())
        assert quote.market_state == "unavailable"
        assert quote.bid is None and quote.ask is None

        scenario.acknowledge_bitfinex(1)
        row, quote = scenario.push("frame", epoch=1, raw=b"[7,[[3,101,2],[4,102,-1]],1]")
        assert quote.market_state == "two_sided"
        assert quote.bid == BookQuoteSide(Decimal(101), Decimal(2), 1)
        assert quote.ask == BookQuoteSide(Decimal(102), Decimal(1), 1)
        assert row.epoch == 1 and quote.epoch == 1

        row, quote = scenario.push("gap", epoch=1, reason="unknown_loss")
        assert row.orders == () and quote.market_state == "unavailable"
        assert quote.bid is None and quote.ask is None
        scenario.acknowledge_bitfinex(2)
        _, quote = scenario.push("frame", epoch=2, raw=b"[7,[[5,103,3]],1]")
        assert quote.market_state == "one_sided"
        assert quote.bid == BookQuoteSide(Decimal(103), Decimal(3), 1)
        assert quote.ask is None


class TestBookQuoteContract:
    """Check native identity, clocks, states, strict decoding and absolute L2 semantics."""

    @staticmethod
    def _okx_frame(
        action: Literal["snapshot", "update"],
        previous: int,
        sequence: int,
        bids: list[list[str]],
        asks: list[list[str]],
    ) -> bytes:
        """Encode a compact native OKX book message with absolute price levels."""
        return DomainCodec().encode_json(
            {
                "arg": {"channel": "books", "instId": "BTC-USDT"},
                "action": action,
                "data": [
                    {
                        "prevSeqId": previous,
                        "seqId": sequence,
                        "ts": "1000",
                        "bids": bids,
                        "asks": asks,
                    }
                ],
            }
        )

    def test_okx_absolute_l2_and_original_quote_coordinates(self) -> None:
        """Absolute L2 changes replace totals and preserve explicit unknown availability."""
        scenario = _BookScenario("okx")
        scenario.push("session")
        scenario.push("frame", raw=_OKX_ACK)
        row, quote = scenario.push(
            "frame",
            raw=self._okx_frame(
                "snapshot", -1, 10, [["100", "3", "0", "2"]], [["101", "4", "0", "3"]]
            ),
        )
        assert row.orders == () and row.bids == ((Decimal(100), Level(Decimal(3), 2)),)
        assert quote.bid == BookQuoteSide(Decimal(100), Decimal(3), 2)
        assert quote.ask == BookQuoteSide(Decimal(101), Decimal(4), 3)
        assert quote.venue == "okx" and quote.channel == "books"
        assert quote.instrument_id == scenario.config.instrument_id
        assert quote.source_id == "saved-native-source"
        assert quote.position == row.position == 2
        assert quote.epoch == row.epoch == 0 and quote.sequence == row.sequence == 10
        assert quote.source_time == row.source_time == "1000"
        assert quote.received_ns == row.received_ns == 1_000_000_002
        assert quote.available_ns is None
        assert quote.state_identity == row.state_identity
        assert quote.market_state == "two_sided"
        self._assert_touch_matches_depth(scenario, row, None)

        row, quote = scenario.push(
            "frame",
            raw=self._okx_frame("update", 10, 11, [["100", "0.2", "0", "1"]], []),
            available_ns=1_000_000_010,
        )
        assert quote.bid == BookQuoteSide(Decimal(100), Decimal("0.2"), 1)
        assert quote.available_ns == 1_000_000_010
        self._assert_touch_matches_depth(scenario, row, 1_000_000_010)
        row, quote = scenario.push(
            "frame",
            raw=self._okx_frame("update", 11, 12, [], [["101", "0", "0", "0"]]),
        )
        assert quote.market_state == "one_sided" and quote.ask is None
        self._assert_touch_matches_depth(scenario, row, None)
        row, quote = scenario.push(
            "frame",
            raw=self._okx_frame("update", 12, 13, [["100", "0", "0", "0"]], []),
        )
        assert quote.market_state == "empty" and quote.bid is None and quote.ask is None
        self._assert_touch_matches_depth(scenario, row, None)
        row, _ = scenario.push("gap", reason="unknown_loss")
        self._assert_touch_matches_depth(scenario, row, None)

    def test_public_touch_revalidates_a_mutated_book(self) -> None:
        """Direct quote callers cannot bypass complete-boundary checks."""
        scenario = _BookScenario("okx")
        scenario.push("session")
        scenario.push("frame", raw=_OKX_ACK)
        row, _ = scenario.push(
            "frame",
            raw=self._okx_frame(
                "snapshot", -1, 10, [["100", "1", "0", "1"]], [["101", "2", "0", "1"]]
            ),
        )
        force_setattr(row, "state_identity", "bad")
        with pytest.raises(ValueError, match="book state or quality"):
            BookDepth.touch_quote(
                row,
                venue=scenario.config.venue,
                instrument_id=scenario.config.instrument_id,
                source_id="saved-native-source",
                channel=scenario.config.channel,
                available_ns=None,
            )

    @staticmethod
    def _assert_touch_matches_depth(
        scenario: _BookScenario, row: BookObservation, available_ns: int | None
    ) -> None:
        """Preserve exact complete-boundary quote coordinates and touch amounts."""
        actual = BookDepth.touch_quote(
            row,
            venue=scenario.config.venue,
            instrument_id=scenario.config.instrument_id,
            source_id="saved-native-source",
            channel=scenario.config.channel,
            available_ns=available_ns,
        )
        expected = BookDepth.from_observation(row).quote(
            row,
            venue=scenario.config.venue,
            instrument_id=scenario.config.instrument_id,
            source_id="saved-native-source",
            channel=scenario.config.channel,
            available_ns=available_ns,
        )
        assert actual == expected

    def test_quote_states_round_trip_and_reject_malformed_fields(self) -> None:
        """Keep locked/crossed states explicit and reject malformed encoded quotes."""
        scenario = _BookScenario("okx")
        scenario.push("session")
        scenario.push("frame", raw=_OKX_ACK)
        _, quote = scenario.push(
            "frame",
            raw=self._okx_frame(
                "snapshot", -1, 10, [["100", "1", "0", "1"]], [["101", "2", "0", "1"]]
            ),
        )
        codec = DomainCodec()
        encoded = codec.encode_json(quote)
        assert codec.decode_json(encoded, BookQuote) == quote
        assert (
            replace(quote, ask=BookQuoteSide(Decimal(100), Decimal(2), 1)).market_state == "locked"
        )
        assert (
            replace(quote, ask=BookQuoteSide(Decimal(99), Decimal(2), 1)).market_state == "crossed"
        )
        with pytest.raises(ValueError, match="native source and instrument"):
            replace(quote, venue="")
        assert quote.received_ns is not None
        with pytest.raises(ValueError, match="original clocks"):
            replace(quote, available_ns=quote.received_ns - 1)
        with pytest.raises(ValueError, match="positive exact price"):
            BookQuoteSide(Decimal(0), Decimal(1), 1)
        with pytest.raises(ValueError, match="aggregate levels"):
            BookQuoteSide(Decimal(100), Decimal(0), 1)
        with pytest.raises(ValueError, match="unavailable book quote"):
            replace(quote, status="recovering")
        with pytest.raises(ValueError):
            codec.decode_json(encoded[:-1] + b',"unknown":1}', BookQuote)
        with pytest.raises(ValueError):
            codec.decode_json(
                encoded.replace(b'"available_ns":null', b'"available_ns":-1'), BookQuote
            )
