"""Prove live book inputs preserve native clocks, health and bounded restart behavior."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from configuration import CaptureConfig
from financial_units import ExactRatio
from market_data.adapters.sources import BookAdapters
from market_data.books import BookProjection, CaptureReplay
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest
from research.observations import InputRequirement, LiveBookDecisionSource, NumericField

_ROOT = Path(__file__).parents[3]
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_OKX_ACK = b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}'
_OKX_SNAPSHOT = (
    b'{"arg":{"channel":"books","instId":"BTC-USDT"},"action":"snapshot",'
    b'"data":[{"prevSeqId":-1,"seqId":10,"ts":"1000",'
    b'"asks":[["101","1","0","1"]],"bids":[["100","2","0","2"]]}]}'
)
_OKX_UPDATE = (
    b'{"arg":{"channel":"books","instId":"BTC-USDT"},"action":"update",'
    b'"data":[{"prevSeqId":10,"seqId":11,"ts":"1000",'
    b'"asks":[],"bids":[["100","1","0","1"]]}]}'
)
_BITFINEX_ACK = (
    b'{"event":"subscribed","chanId":7,"channel":"book","symbol":"tBTCUSD",'
    b'"prec":"R0","freq":"F0","len":"25"}'
)


class _LiveScenario:
    """Drive actual venue reconstruction and canonical projection at each message."""

    def __init__(
        self,
        venue: Literal["okx", "bitfinex"],
        clock: Literal["event", "receipt"],
        *,
        history_capacity: int = 16,
    ) -> None:
        """Bind a maintained public source selection and named dimensionless input."""
        config = CaptureConfig.read(
            _ROOT / "configs" / "live" / f"{venue}-btc-{'usdt' if venue == 'okx' else 'usd'}.json"
        )
        self.request = CaptureRequest(
            config=config,
            recording_id="a" * 36,
            implementation_identity="b" * 64,
        )
        self.requirement = InputRequirement(
            name=f"{venue}-book",
            family="book",
            clock=clock,
            field=NumericField(name="imbalance", units="dimensionless"),
            max_age_us=30_000_000,
        )
        self.replay = CaptureReplay(config, book_factory=BookAdapters.create)
        self.source = LiveBookDecisionSource(
            self.request, self.requirement, history_capacity=history_capacity
        )
        self.records: list[CaptureRecord] = []

    def push(
        self,
        kind: Literal["session", "frame", "snapshot", "gap", "session_end", "end"],
        ns: int,
        *,
        raw: bytes = b"",
        epoch: int = 0,
        reason: str = "",
        available_at: datetime | None = None,
    ) -> BookObservation:
        """Apply one exact record through the installed decoder and projection."""
        record = CaptureRecord(kind=kind, epoch=epoch, received_ns=ns, raw=raw, reason=reason)
        outcome = self.replay.apply(record)
        row = BookProjection.capture(len(self.records), record, outcome, self.replay)
        self.source.accept(record, row, available_at=available_at)
        self.records.append(record)
        return row


class TestLiveBookDecisionSource:
    """Exercise exact numeric values, healthy controls, failures and replay recovery."""

    def test_okx_event_clock_identity_receipt_and_frozen_cutoff(self) -> None:
        """A source is bindable before receipt and does not revise an issued cutoff."""
        scenario = _LiveScenario("okx", "event")
        source = scenario.source
        identity = source.identity
        entity = str(scenario.request.config.instrument_id)
        assert source.requirements == (scenario.requirement,)
        assert (
            source.read(entity, _EPOCH + timedelta(milliseconds=900)).observations[0].reason
            == "no_live_input"
        )
        scenario.push("session", 999_000_000)
        scenario.push("frame", 999_500_000, raw=_OKX_ACK)
        book = scenario.push("frame", 1_000_000_001, raw=_OKX_SNAPSHOT)
        cutoff = _EPOCH + timedelta(microseconds=1_000_001)
        decided = source.read(entity, cutoff)
        observed = decided.observations[0]
        assert observed.event_at == _EPOCH + timedelta(seconds=1)
        assert observed.available_at == cutoff
        assert observed.value == ExactRatio(numerator="1", denominator="3")
        assert observed.reason == "visible_depth_only;recorder_coverage_unproven"
        assert f":{book.sequence}:degraded:" in observed.lineage
        assert f":{book.state_identity}:" in observed.lineage
        assert observed.lineage.endswith(hashlib.sha256(_OKX_SNAPSHOT).hexdigest())
        assert source.latest_book == book and source.identity == identity
        scenario.push("frame", 1_000_000_500, raw=_OKX_UPDATE)
        assert source.read(entity, cutoff) is decided
        assert source.book_at(entity, cutoff) == book
        assert source.current_book(entity, cutoff) == source.latest_book
        assert source.current_book(entity, cutoff) != book
        later = source.read(entity, _EPOCH + timedelta(microseconds=1_000_002))
        assert later.observations[0].value == ExactRatio(numerator="0", denominator="1")
        assert source.book_at(entity, later.decision_at) == source.latest_book
        with pytest.raises(ValueError, match="cutoff cannot move backwards"):
            source.read(entity, cutoff - timedelta(microseconds=1))

    def test_controls_staleness_gap_and_new_snapshot(self) -> None:
        """Heartbeat does not refresh a book; gap and restart require fresh native state."""
        scenario = _LiveScenario("okx", "event")
        entity = str(scenario.request.config.instrument_id)
        scenario.push("session", 999_000_000)
        scenario.push("frame", 999_500_000, raw=_OKX_ACK)
        book = scenario.push("frame", 1_000_000_001, raw=_OKX_SNAPSHOT)
        scenario.push("frame", 2_000_000_000, raw=b"pong")
        carried = scenario.source.read(entity, _EPOCH + timedelta(seconds=2)).observations[0]
        assert carried.value == ExactRatio(numerator="1", denominator="3")
        assert carried.event_at == _EPOCH + timedelta(seconds=1)
        assert carried.available_at == _EPOCH + timedelta(microseconds=1_000_001)
        assert scenario.source.latest_book == book
        stale = scenario.source.read(entity, _EPOCH + timedelta(seconds=17)).observations[0]
        assert stale.value is None and stale.reason == "stale_market_progress"
        assert scenario.source.book_at(entity, _EPOCH + timedelta(seconds=17)) is None
        assert scenario.source.current_book(entity, _EPOCH + timedelta(seconds=17)) is None
        scenario.push("gap", 18_000_000_000, reason="disconnect_unknown_loss")
        assert scenario.source.latest_book is None
        missing = scenario.source.read(entity, _EPOCH + timedelta(seconds=18)).observations[0]
        assert missing.value is None and "recovering" in missing.reason
        assert scenario.source.book_at(entity, _EPOCH + timedelta(seconds=18)) is None
        scenario.push("session_end", 19_000_000_000, reason="disconnect_unknown_loss")
        scenario.push("session", 20_000_000_000, epoch=1)
        scenario.push("frame", 20_100_000_000, epoch=1, raw=_OKX_ACK)
        fresh = _OKX_SNAPSHOT.replace(b'"ts":"1000"', b'"ts":"21000"')
        scenario.push("frame", 21_000_000_000, epoch=1, raw=fresh)
        restored = scenario.source.read(entity, _EPOCH + timedelta(seconds=21)).observations[0]
        assert restored.value == ExactRatio(numerator="1", denominator="3")
        assert ":1:" in restored.lineage

    def test_bitfinex_receipt_clock_and_journal_rebuild(self) -> None:
        """R0 has no exchange clock, while replaying the same journal restores identity."""
        scenario = _LiveScenario("bitfinex", "receipt")
        entity = str(scenario.request.config.instrument_id)
        frames = (
            b'{"event":"conf","status":"OK","flags":65536}',
            b'[7,"hb",1]',
            _BITFINEX_ACK,
            b"[7,[[1,100,2],[2,101,-1]],2]",
            b"[7,[1,100,1],3]",
        )
        scenario.push("session", 1_000_000_000)
        for index, frame in enumerate(frames, 1):
            scenario.push("frame", 1_000_000_000 + index * 1_000_000, raw=frame)
        at = _EPOCH + timedelta(milliseconds=1005)
        observed = scenario.source.read(entity, at).observations[0]
        assert observed.event_at == at and observed.available_at == at
        assert observed.value == ExactRatio(numerator="0", denominator="1")
        assert ":unknown:3:degraded:" in observed.lineage
        assert scenario.source.latest_book is not None
        replay = CaptureReplay(scenario.request.config, book_factory=BookAdapters.create)
        restored = LiveBookDecisionSource(
            scenario.request, scenario.requirement, history_capacity=16
        )
        for position, record in enumerate(scenario.records):
            outcome = replay.apply(record)
            restored.accept(record, BookProjection.capture(position, record, outcome, replay))
        assert restored.identity == scenario.source.identity
        assert (
            restored.read(entity, at).observations == scenario.source.read(entity, at).observations
        )
        with pytest.raises(ValueError, match="unsupported live book"):
            LiveBookDecisionSource(
                scenario.request,
                replace(scenario.requirement, clock="event"),
                history_capacity=16,
            )

    def test_capacity_and_mismatched_canonical_receipt(self) -> None:
        """Evicted history stays missing and mismatched source coordinates are refused."""
        scenario = _LiveScenario("okx", "receipt", history_capacity=1)
        entity = str(scenario.request.config.instrument_id)
        scenario.push("session", 999_000_000)
        scenario.push("frame", 999_500_000, raw=_OKX_ACK)
        assert (
            scenario.source.read(entity, _EPOCH + timedelta(microseconds=999_001))
            .observations[0]
            .reason
            == "no_live_input"
        )
        record = CaptureRecord(kind="frame", epoch=0, received_ns=1_000_000_001, raw=_OKX_SNAPSHOT)
        outcome = scenario.replay.apply(record)
        row = BookProjection.capture(2, record, outcome, scenario.replay)
        with pytest.raises(ValueError, match="ordered original receipt"):
            scenario.source.accept(record, replace(row, position=9))
        scenario.source.accept(record, row)
        assert scenario.source.read(
            entity, _EPOCH + timedelta(microseconds=1_000_001)
        ).observations[0].value == ExactRatio(numerator="1", denominator="3")

    def test_delivery_availability_and_restart_binding(self) -> None:
        """Delayed durable use cannot revise earlier decisions; a new run keeps its binding."""
        scenario = _LiveScenario("okx", "event")
        entity = str(scenario.request.config.instrument_id)
        scenario.push("session", 999_000_000)
        scenario.push("frame", 999_500_000, raw=_OKX_ACK)
        prior_at = _EPOCH + timedelta(milliseconds=1500)
        prior = scenario.source.read(entity, prior_at)
        delivery_at = _EPOCH + timedelta(seconds=2)
        scenario.push(
            "frame",
            1_000_000_001,
            raw=_OKX_SNAPSHOT,
            available_at=delivery_at,
        )
        assert scenario.source.read(entity, prior_at) is prior
        observed = scenario.source.read(entity, delivery_at).observations[0]
        assert observed.event_at == _EPOCH + timedelta(seconds=1)
        assert observed.available_at == delivery_at
        assert observed.value == ExactRatio(numerator="1", denominator="3")
        assert delivery_at.isoformat() in observed.lineage
        new_request = replace(scenario.request, recording_id="c" * 36)
        restarted = LiveBookDecisionSource(new_request, scenario.requirement, history_capacity=16)
        assert restarted.identity == scenario.source.identity
        assert (
            restarted.read(entity, _EPOCH + timedelta(milliseconds=900)).observations[0].reason
            == "no_live_input"
        )
        changed = LiveBookDecisionSource(
            replace(new_request, config=replace(new_request.config, idle_seconds=14)),
            scenario.requirement,
            history_capacity=16,
        )
        assert changed.identity != restarted.identity
        replay = CaptureReplay(new_request.config, book_factory=BookAdapters.create)
        for position, original in enumerate(scenario.records):
            outcome = replay.apply(original)
            row = BookProjection.capture(position, original, outcome, replay)
            restarted.accept(original, row, available_at=delivery_at)
        assert restarted.read(entity, delivery_at).observations[0].lineage != observed.lineage
        with pytest.raises(ValueError, match="availability precedes receipt"):
            other = LiveBookDecisionSource(new_request, scenario.requirement, history_capacity=16)
            record = CaptureRecord(kind="session", epoch=0, received_ns=2_000_000_000)
            replay = CaptureReplay(new_request.config, book_factory=BookAdapters.create)
            outcome = replay.apply(record)
            other.accept(
                record,
                BookProjection.capture(0, record, outcome, replay),
                available_at=_EPOCH + timedelta(seconds=1),
            )
