"""Exercise native L2 identity, exact aggregation and OKX-specific sequence rules."""

from __future__ import annotations

# standard library imports
from decimal import Decimal

# third party library imports
import pytest

# project library imports
from market_data.adapters.venues.okx import OKXBook
from serialization import DomainCodec


class TestOKXBook:
    """Check source semantics using small hand-authored independent wire records."""

    @staticmethod
    def frame(action: str, previous: int, sequence: int, bids: list[list[str]]) -> bytes:
        """Encode one synthetic book message with fixed native identity.

        Args:
            action: Snapshot or update action.
            previous: Supplied predecessor sequence.
            sequence: Supplied current sequence.
            bids: Native four-field aggregate price rows.

        Returns:
            Exact synthetic message bytes.
        """
        return DomainCodec().encode_json(
            {
                "arg": {"channel": "books", "instId": "BTC-USDT"},
                "action": action,
                "data": [
                    {
                        "seqId": sequence,
                        "prevSeqId": previous,
                        "ts": "1788825600004",
                        "bids": bids,
                        "asks": [],
                        "checksum": 0,
                    }
                ],
            }
        )

    @staticmethod
    def book() -> OKXBook:
        """Start an acknowledged test book.

        Returns:
            Empty acknowledged native book.
        """
        book = OKXBook("BTC-USDT")
        book.apply(b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}')
        return book

    def test_absolute_sizes_deletion_empty_update_and_reset(self) -> None:
        """Sequence jumps and linked maintenance resets are legal; quantities replace totals."""
        book = self.book()
        book.apply(
            self.frame("snapshot", -1, 10, [["100", "0.123456789012345678901234567890", "0", "2"]])
        )
        assert book.bids[Decimal(100)].size == Decimal("0.123456789012345678901234567890")
        book.apply(self.frame("update", 10, 20, [["100", "0.2", "0", "1"]]))
        assert book.bids[Decimal(100)].size == Decimal("0.2")
        assert book.apply(self.frame("update", 20, 20, [])) == "heartbeat"
        assert book.apply(b"pong") == "heartbeat"
        book.apply(self.frame("update", 20, 3, []))
        assert book.sequence_resets == 1
        book.apply(self.frame("update", 3, 8, [["100", "0", "0", "0"]]))
        assert book.bids == {}

    @pytest.mark.parametrize("previous,sequence", [(9, 12), (11, 12), (10, 10)])
    def test_gap_or_duplicate_with_mutation(self, previous: int, sequence: int) -> None:
        """Require the exact predecessor and reject repeated sequence with changed levels."""
        book = self.book()
        book.apply(self.frame("snapshot", -1, 10, []))
        with pytest.raises(ValueError):
            book.apply(self.frame("update", previous, sequence, [["100", "1", "0", "1"]]))

    @pytest.mark.parametrize(
        "row",
        [
            ["100", "1"],
            ["100", "-1", "0", "1"],
            ["100", "1", "0", "0"],
            ["NaN", "1", "0", "1"],
            ["100", "1", "2", "1"],
        ],
    )
    def test_malformed_level(self, row: list[str]) -> None:
        """Fail incompatible schemas and nonpositive or nonfinite aggregate state."""
        with pytest.raises(ValueError):
            self.book().apply(self.frame("snapshot", -1, 10, [row]))

    def test_identity_acknowledgement_and_snapshot_required(self) -> None:
        """Reject an unacknowledged feed, alien product and update before snapshot."""
        with pytest.raises(ValueError):
            OKXBook("BTC-USDT").apply(self.frame("snapshot", -1, 1, []))
        with pytest.raises(ValueError):
            OKXBook("BTC-USD").apply(
                b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}'
            )
        with pytest.raises(ValueError):
            self.book().apply(self.frame("update", 0, 1, []))
        with pytest.raises(ValueError):
            self.book().apply(b'{"event":"error","code":"64003"}')

    def test_bounded_price_depth(self) -> None:
        """Keep the best visible 400 prices rather than accumulating stale outside depth."""
        book = self.book()
        book.apply(self.frame("snapshot", -1, 1, [[str(i), "1", "0", "1"] for i in range(1, 401)]))
        book.apply(self.frame("update", 1, 2, [["401", "2", "0", "3"]]))
        assert len(book.bids) == 400
        assert min(book.bids) == 2
        assert book.bids[Decimal(401)].order_count == 3

    def test_archive_missing_clock_and_no_invented_sequence(self) -> None:
        """Archive snapshots do not acquire a synthetic per-record clock or sequence."""
        book = OKXBook("BTC-USDT")
        book.apply_archive(
            b'{"instId":"BTC-USDT","action":"snapshot","asks":[],"bids":[["100","1","2"]]}'
        )
        assert book.sequence is None and book.source_time is None
        with pytest.raises(ValueError):
            book.apply_archive(
                b'{"instId":"BTC-USDT","action":"update","seqId":1,"asks":[],"bids":[]}'
            )

    def test_state_identity_ignores_equivalent_decimal_spelling(self) -> None:
        """A source's alternate price scale must remove the actual prior level fingerprint."""
        book, fresh = self.book(), self.book()
        book.apply(self.frame("snapshot", -1, 1, [["100.00", "0.30", "0", "1"]]))
        book.apply(self.frame("update", 1, 2, [["100", "0.2", "0", "2"]]))
        fresh.apply(self.frame("snapshot", -1, 2, [["100.000", "0.200", "0", "2"]]))
        assert book.identity == fresh.identity

    def test_atomic_rejection_keeps_both_sides_and_reset_count(self) -> None:
        """A malformed second side cannot expose a changed bid or a partial sequence reset."""
        book = self.book()
        book.apply(self.frame("snapshot", -1, 10, [["100", "1", "0", "1"]]))
        before = book.identity
        invalid = self.frame("update", 10, 3, [["100", "2", "0", "1"]]).replace(
            b'"asks":[]', b'"asks":[["0","1","0","1"]]'
        )
        with pytest.raises(ValueError):
            book.apply(invalid)
        assert book.identity == before and book.sequence_resets == 0
        assert book.bids[Decimal(100)].size == 1

    def test_rejected_frame_does_not_advance_source_clock(self) -> None:
        """A malformed future frame must not make a subsequent valid frame look stale."""
        book = self.book()
        book.apply(self.frame("snapshot", -1, 10, [["100", "1", "0", "1"]]))
        invalid = self.frame("update", 10, 11, [["100", "-1", "0", "1"]]).replace(
            b"1788825600004", b"1788825600020"
        )
        with pytest.raises(ValueError):
            book.apply(invalid)
        assert book.source_time == "1788825600004"

        valid = self.frame("update", 10, 11, [["100", "2", "0", "1"]]).replace(
            b"1788825600004", b"1788825600010"
        )
        assert book.apply(valid) == "update"
        assert book.source_time == "1788825600010"
