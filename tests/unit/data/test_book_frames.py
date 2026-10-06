"""Protect exact book deltas and the bounded compressed frame container."""

from __future__ import annotations

# standard library imports
import io
from decimal import Decimal

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from market_data.contracts import BookObservation, Level, Order
from market_data.datasets import BookFrameDecoder, BookFrameEncoder, StoredBookRow
from serialization import DomainCodec, FrameReader, FrameWriter

_STATE = "a" * 64


class _Rows:
    """Build and round-trip rows from exact text."""

    @staticmethod
    def row(
        position: int,
        *,
        bids: tuple[tuple[str, str], ...] = (),
        asks: tuple[tuple[str, str], ...] = (),
        orders: tuple[Order, ...] = (),
        outcome: str = "update",
    ) -> BookObservation:
        """Build one captured row from exact price and size text."""
        return BookObservation(
            position,
            0,
            position + 1,
            None,
            position,
            outcome,
            "degraded",
            "visible",
            _STATE,
            orders=orders,
            bids=tuple((Decimal(price), Level(Decimal(size), 1)) for price, size in bids),
            asks=tuple((Decimal(price), Level(Decimal(size), 1)) for price, size in asks),
        )

    @staticmethod
    def text(row: BookObservation) -> bytes:
        """Encode a row exactly, so ``1.0`` and ``1`` differ."""
        return DomainCodec().encode_json(row)

    @staticmethod
    def round_trip(
        rows: tuple[BookObservation, ...], starts: tuple[bool, ...]
    ) -> tuple[tuple[StoredBookRow, ...], tuple[BookObservation, ...]]:
        """Encode through JSON and decode again, with the given frame starts."""
        codec, encoder, decoder = DomainCodec(), BookFrameEncoder(), BookFrameDecoder()
        stored = tuple(
            codec.decode_json(
                codec.encode_json(encoder.encode(row, frame_start=start)), StoredBookRow
            )
            for row, start in zip(rows, starts, strict=True)
        )
        rebuilt = tuple(
            decoder.decode(value, frame_start=start)
            for value, start in zip(stored, starts, strict=True)
        )
        return stored, rebuilt


class TestBookDeltas:
    """A rebuilt row equals the original exactly, including decimal text."""

    def test_l2_changes_removals_and_text_round_trip_exactly(self) -> None:
        """Sets, removals, a changed size text and a changed price text all rebuild."""
        rows = (
            _Rows.row(
                0, bids=(("99", "1"), ("100", "2")), asks=(("101", "1"),), outcome="snapshot"
            ),
            _Rows.row(1, bids=(("99", "1"), ("100", "3")), asks=(("101", "1"),)),
            _Rows.row(2, bids=(("100", "3"),), asks=(("101", "1"), ("102", "4"))),
            _Rows.row(3, bids=(("100", "3.0"),), asks=(("101", "1"), ("102", "4"))),
            _Rows.row(4, bids=(("100.0", "3.0"),), asks=(("101", "1"), ("102", "4"))),
        )
        stored, rebuilt = _Rows.round_trip(rows, (True, False, False, False, False))
        assert tuple(map(_Rows.text, rebuilt)) == tuple(map(_Rows.text, rows))
        assert stored[0].whole and not any(value.whole for value in stored[1:])
        assert stored[1].bids == ((Decimal("100"), Level(Decimal("3"), 1)),) and not stored[1].asks
        assert stored[2].removed_bids == (Decimal("99"),)
        assert stored[4].removed_bids == (Decimal("100"),)

    def test_control_rows_and_representation_changes_store_whole(self) -> None:
        """An empty state never reads as an empty book, and L2 to L3 restarts the base."""
        order = Order("b", "buy", Decimal("100"), Decimal("1"))
        rows = (
            _Rows.row(0, bids=(("100", "1"),), outcome="snapshot"),
            _Rows.row(1, outcome="gap"),
            _Rows.row(2, bids=(("100", "1"),), outcome="snapshot"),
            _Rows.row(3, orders=(order,), outcome="snapshot"),
            _Rows.row(4, orders=(order, Order("c", "sell", Decimal("101"), Decimal("2")))),
            _Rows.row(5, orders=(replace(order, size=Decimal("1.5")),)),
        )
        stored, rebuilt = _Rows.round_trip(rows, (True, False, False, False, False, False))
        assert tuple(map(_Rows.text, rebuilt)) == tuple(map(_Rows.text, rows))
        assert [value.whole for value in stored] == [True, True, True, True, False, False]
        assert stored[5].removed_orders == ("c",)

    def test_frame_start_stores_whole_and_resets_the_decoder(self) -> None:
        """A row opening a frame never depends on the frame before it."""
        rows = (
            _Rows.row(0, bids=(("100", "1"),), outcome="snapshot"),
            _Rows.row(1, bids=(("100", "2"),)),
            _Rows.row(2, bids=(("100", "3"),)),
        )
        stored, rebuilt = _Rows.round_trip(rows, (True, False, True))
        assert [value.whole for value in stored] == [True, False, True]
        assert tuple(map(_Rows.text, rebuilt)) == tuple(map(_Rows.text, rows))

    @pytest.mark.parametrize(
        ("previous", "delta", "frame_start", "message"),
        [
            (
                None,
                StoredBookRow(1, 0, 2, None, 1, "update", "degraded", "v", _STATE),
                True,
                "previous state",
            ),
            (
                _Rows.row(0, outcome="gap"),
                StoredBookRow(1, 0, 2, None, 1, "update", "degraded", "v", _STATE),
                False,
                "previous state",
            ),
            (
                _Rows.row(0, bids=(("100", "1"),), outcome="snapshot"),
                StoredBookRow(
                    1,
                    0,
                    2,
                    None,
                    1,
                    "update",
                    "degraded",
                    "v",
                    _STATE,
                    removed_bids=(Decimal("99"),),
                ),
                False,
                "absent entry",
            ),
            (
                _Rows.row(0, bids=(("100", "1"),), outcome="snapshot"),
                StoredBookRow(
                    1,
                    0,
                    2,
                    None,
                    1,
                    "update",
                    "degraded",
                    "v",
                    _STATE,
                    removed_bids=(Decimal("100"),),
                ),
                False,
                "empty its state",
            ),
            (
                _Rows.row(0, bids=(("100", "1"),), outcome="snapshot"),
                StoredBookRow(
                    1, 0, 2, None, 1, "update", "degraded", "v", _STATE, removed_orders=("a",)
                ),
                False,
                "cannot change orders",
            ),
            (
                _Rows.row(
                    0, orders=(Order("a", "buy", Decimal("1"), Decimal("1")),), outcome="snapshot"
                ),
                StoredBookRow(
                    1,
                    0,
                    2,
                    None,
                    1,
                    "update",
                    "degraded",
                    "v",
                    _STATE,
                    removed_bids=(Decimal("1"),),
                ),
                False,
                "cannot change levels",
            ),
        ],
    )
    def test_decoder_refuses_a_delta_without_its_base(
        self,
        previous: BookObservation | None,
        delta: StoredBookRow,
        frame_start: bool,
        message: str,
    ) -> None:
        """A malformed delta is refused, never applied to the wrong base."""
        decoder = BookFrameDecoder()
        if previous is not None:
            decoder.decode(BookFrameEncoder().encode(previous, frame_start=True), frame_start=True)
        with pytest.raises(ValueError, match=message):
            decoder.decode(delta, frame_start=frame_start)

    def test_rows_out_of_canonical_order_store_whole_and_rebuild_as_given(self) -> None:
        """A best-first row cannot be a delta base, so it and its successor store whole."""
        first = BookObservation(
            0,
            0,
            1,
            None,
            0,
            "snapshot",
            "degraded",
            "visible",
            _STATE,
            bids=(
                (Decimal("101"), Level(Decimal("1"), 1)),
                (Decimal("100"), Level(Decimal("1"), 1)),
            ),
        )
        rows = (
            first,
            _Rows.row(1, bids=(("100", "1"), ("101", "2"))),
            _Rows.row(2, bids=(("101", "2"),)),
        )
        stored, rebuilt = _Rows.round_trip(rows, (True, False, False))
        assert [value.whole for value in stored] == [True, True, False]
        assert tuple(map(_Rows.text, rebuilt)) == tuple(map(_Rows.text, rows))


class TestFrames:
    """Frames round-trip records and refuse any damaged or oversized frame."""

    @staticmethod
    def _stored(records: tuple[bytes, ...]) -> bytes:
        """Write records to an in-memory stream."""
        output = io.BytesIO()
        writer = FrameWriter(output)
        for record in records:
            writer.add(record)
        writer.close()
        return output.getvalue()

    def test_records_round_trip_with_frame_starts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A frame closes at its record bound, and the reader reports where frames start."""
        monkeypatch.setattr(FrameWriter, "max_records", 2)
        output = io.BytesIO()
        writer = FrameWriter(output)
        starts = []
        for record in (b"a", b"b", b"c"):
            starts.append(writer.at_frame_start)
            writer.add(record)
        digest = writer.close()
        assert starts == [True, False, True]
        assert writer.stored_bytes == len(output.getvalue()) and len(digest) == 64
        output.seek(0)
        assert list(FrameReader.records(output)) == [(True, b"a"), (False, b"b"), (True, b"c")]

    def test_writer_refuses_records_it_cannot_frame(self) -> None:
        """An empty record or one holding a newline would change record boundaries."""
        writer = FrameWriter(io.BytesIO())
        for record in (b"", b"a\nb"):
            with pytest.raises(ValueError, match="newline-free"):
                writer.add(record)

    @pytest.mark.parametrize(
        ("cut", "message"),
        [
            ("header", "truncated frame header"),
            ("payload", "truncated frame"),
            ("zeros", "corrupt frame"),
            ("stored-length", "outside bounds"),
            ("size", "differs from its header"),
        ],
    )
    def test_reader_refuses_damaged_frames(self, cut: str, message: str) -> None:
        """No record is exposed from a frame that fails its header or decompression."""
        stored = self._stored((b"first", b"second"))
        damaged = {
            "header": stored[:5],
            "payload": stored[:-3],
            "zeros": stored[:8] + bytes(len(stored) - 8),
            "stored-length": (2**31).to_bytes(4, "big") + stored[4:],
            "size": stored[:4] + (1).to_bytes(4, "big") + stored[8:],
        }[cut]
        with pytest.raises(ValueError, match=message):
            list(FrameReader.records(io.BytesIO(damaged)))
