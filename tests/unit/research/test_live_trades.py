"""Exercise causal live trade fields, coverage and refusal on a hand-authored OKX tape."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from typing import Literal
from uuid import UUID

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from configuration import CaptureConfig
from financial_units import ExactRatio
from market_data.adapters.sources import BookAdapters
from market_data.books import BookProjection, CaptureReplay
from market_data.contracts import CaptureRecord, CaptureRequest
from reference_data.instruments import InstrumentId
from research.observations import InputRequirement, LiveTradeDecisionSource, NumericField
from serialization import DomainCodec

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_START = datetime(2026, 9, 23, 12, tzinfo=UTC)
_ENTITY = "00000000-0000-4000-8000-000000000001"
_ACK = b'{"event":"subscribe","arg":{"channel":"trades","instId":"BTC-USDT"}}'


class _Tape:
    """Apply records through the collector's replay and the live source together."""

    def __init__(self, *, window_seconds: int = 10, trade_capacity: int = 100) -> None:
        """Bind an OKX BTC-USDT trades feed and every supported field."""
        self.config = CaptureConfig(
            venue="okx",
            symbol="BTC-USDT",
            instrument_id=InstrumentId(UUID(_ENTITY)),
            base_currency="BTC",
            quote_currency="USDT",
            channel="trades",
            depth=0,
            duration_seconds=3600,
            max_messages=1000,
            max_bytes=1_000_000,
            max_frame_bytes=100_000,
            queue_capacity=100,
            max_orders=1,
            retries=1,
            idle_seconds=5,
            clock_interval_ms=250,
        )
        self.requirements = tuple(
            InputRequirement(
                name="flow",
                family="trade",
                clock="event",
                field=field,
                max_age_us=window_seconds * 1_000_000,
            )
            for field in (
                NumericField(name="price", units="USDT/BTC"),
                NumericField(name="quantity", units="BTC"),
                NumericField(name="signed_quantity", units="BTC"),
                NumericField(name="signed_flow", units="BTC"),
            )
        )
        self.request = CaptureRequest(
            config=self.config,
            recording_id="00000000-0000-0000-0000-000000000097",
            implementation_identity="a" * 64,
        )
        self.source = LiveTradeDecisionSource(
            self.request,
            self.requirements,
            tapes=BookAdapters.trades,
            history_capacity=100,
            trade_capacity=trade_capacity,
        )
        self.replay = CaptureReplay(self.config, book_factory=BookAdapters.create)
        self.position = 0
        self.epoch = -1

    def record(
        self,
        kind: Literal["session", "frame", "gap", "session_end"],
        at: datetime,
        raw: bytes = b"",
        *,
        delivered: datetime | None = None,
    ) -> None:
        """Persist, reconstruct and deliver one boundary received at ``at``."""
        if kind == "session":
            self.epoch += 1
        record = CaptureRecord(
            kind=kind,
            epoch=self.epoch,
            received_ns=(at - _EPOCH) // timedelta(microseconds=1) * 1000,
            raw=raw,
            reason="connection_lost" if kind == "gap" else "",
        )
        row = BookProjection.capture(self.position, record, self.replay.apply(record), self.replay)
        self.source.accept(record, row, available_at=delivered)
        self.position += 1

    @staticmethod
    def push(trade_id: int, at: datetime, size: str, side: str) -> bytes:
        """Encode one OKX trade at venue time ``at``."""
        return DomainCodec().encode_json(
            {
                "arg": {"channel": "trades", "instId": "BTC-USDT"},
                "data": [
                    {
                        "instId": "BTC-USDT",
                        "tradeId": str(trade_id),
                        "ts": str((at - _EPOCH) // timedelta(milliseconds=1)),
                        "px": "100",
                        "sz": size,
                        "side": side,
                        "count": "1",
                    }
                ],
            }
        )

    def values(self, at: datetime) -> list[ExactRatio | None]:
        """Read every field's value at one cutoff."""
        return [row.value for row in self.source.read(_ENTITY, at).observations]

    def reasons(self, at: datetime) -> list[str]:
        """Read every field's reason at one cutoff."""
        return [row.reason for row in self.source.read(_ENTITY, at).observations]


class TestLiveTradeDecisionSource:
    """Check windows, coverage, liveness and causality against independent arithmetic."""

    @staticmethod
    def ratio(value: str) -> ExactRatio:
        """Return an exact ratio from decimal text."""
        return ExactRatio.from_fraction(Fraction(value))

    def test_latest_trade_and_flow_use_only_known_trades_in_the_window(self) -> None:
        """Flow sums signed trades in ``(at - age, at]``; a late delivery is not yet known."""
        tape = _Tape()
        tape.record("session", _START)
        tape.record("frame", _START, _ACK)
        tape.record("frame", _START + timedelta(seconds=1), tape.push(1, _START, "0.5", "buy"))
        tape.record(
            "frame",
            _START + timedelta(seconds=11),
            tape.push(2, _START + timedelta(seconds=11), "0.2", "sell"),
        )
        tape.record(
            "frame",
            _START + timedelta(seconds=12),
            tape.push(3, _START + timedelta(seconds=12), "0.1", "buy"),
            delivered=_START + timedelta(seconds=14),
        )
        at = _START + timedelta(seconds=13)
        assert tape.values(at) == [
            self.ratio("100"),
            self.ratio("0.2"),
            self.ratio("-0.2"),
            self.ratio("-0.2"),
        ]
        later = _START + timedelta(seconds=14)
        assert tape.values(later)[2:] == [self.ratio("0.1"), self.ratio("-0.1")]
        assert tape.values(later) == tape.values(later)
        with pytest.raises(ValueError, match="backwards"):
            tape.source.read(_ENTITY, at)

    def test_flow_needs_a_covered_window_and_a_live_stream(self) -> None:
        """A window before synchronization, a quiet stream or a gap leaves fields missing."""
        tape = _Tape()
        tape.record("session", _START)
        tape.record("frame", _START, _ACK)
        tape.record(
            "frame",
            _START + timedelta(seconds=2),
            tape.push(1, _START + timedelta(seconds=2), "1", "buy"),
        )
        assert tape.reasons(_START + timedelta(seconds=3))[3] == "incomplete_trade_window"
        assert tape.values(_START + timedelta(seconds=3))[0] == self.ratio("100")
        assert set(tape.reasons(_START + timedelta(seconds=8))) == {"stale_trade_stream"}
        tape.record("frame", _START + timedelta(seconds=10), b"pong")
        assert tape.values(_START + timedelta(seconds=10))[3] == self.ratio("1")
        tape.record("gap", _START + timedelta(seconds=11))
        assert set(tape.reasons(_START + timedelta(seconds=11))) == {"trade_stream_unsynchronized"}
        tape.record("session_end", _START + timedelta(seconds=11))
        tape.record("session", _START + timedelta(seconds=12))
        tape.record("frame", _START + timedelta(seconds=12), _ACK)
        # The earlier session's trade stays known but has aged past the window.
        assert tape.reasons(_START + timedelta(seconds=13))[::3] == [
            "stale_input",
            "incomplete_trade_window",
        ]

    def test_dropped_trades_move_coverage_past_them(self) -> None:
        """Exceeding trade capacity never understates a flow window."""
        tape = _Tape(trade_capacity=1)
        tape.record("session", _START)
        tape.record("frame", _START, _ACK)
        tape.record(
            "frame",
            _START + timedelta(seconds=11),
            tape.push(1, _START + timedelta(seconds=11), "1", "buy"),
        )
        tape.record(
            "frame",
            _START + timedelta(seconds=12),
            tape.push(2, _START + timedelta(seconds=12), "1", "buy"),
        )
        assert tape.reasons(_START + timedelta(seconds=12))[3] == "incomplete_trade_window"

    def test_collector_reconstruction_and_projection_contracts_are_enforced(self) -> None:
        """A differing collector row, book feed, unit or unbound entity is refused."""
        tape = _Tape()
        record = CaptureRecord(kind="session", epoch=0, received_ns=1)
        row = BookProjection.capture(0, record, tape.replay.apply(record), tape.replay)
        with pytest.raises(ValueError, match="reconstruction"):
            tape.source.accept(record, replace(row, state_identity="0" * 64))
        with pytest.raises(ValueError, match="trades feed"):
            LiveTradeDecisionSource(
                replace(
                    tape.request,
                    config=replace(tape.config, channel="books", depth=400, max_orders=800),
                ),
                tape.requirements,
                tapes=BookAdapters.trades,
                history_capacity=10,
            )
        with pytest.raises(ValueError, match="projection"):
            LiveTradeDecisionSource(
                tape.request,
                (replace(tape.requirements[0], field=NumericField(name="price", units="USD/BTC")),),
                tapes=BookAdapters.trades,
                history_capacity=10,
            )
        assert {row.reason for row in tape.source.read("other", _START).observations} == {
            "entity_unbound"
        }
