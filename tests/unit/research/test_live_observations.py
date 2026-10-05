"""Prove live book inputs preserve native clocks, health and bounded restart behavior."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from functools import partial
from pathlib import Path
from typing import Literal, cast

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from configuration import CaptureConfig
from financial_units import ExactRatio
from market_data.adapters.sources import BookAdapters
from market_data.books import BookProjection, CaptureReplay
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest
from research.observations import InputRequirement, LiveBookDecisionSource, NumericField
from serialization import DomainCodec

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


class _CountedBookDecodes:
    """Count one codec's book-history restorations without replacing strict decoding.

    Installed as ``DomainCodec.decode_json`` it binds the codec like a method.
    """

    def __init__(
        self, decode: Callable[[DomainCodec, bytes | str, type], object], codec: DomainCodec
    ) -> None:
        """Bind the original decoder and the codec whose book decodes are counted."""
        self._decode = decode
        self._codec = codec
        self.decodes = 0

    def __get__(self, instance: DomainCodec, owner: type[DomainCodec]) -> partial[object]:
        """Bind the counter to the codec it is called on."""
        return partial(self, instance)

    def __call__[T](self, codec: DomainCodec, data: bytes | str, target: type[T]) -> T:
        """Count a selected book restoration, then decode as before."""
        if codec is self._codec and target is BookObservation:
            self.decodes += 1
        return cast(T, self._decode(codec, data, target))


class _CountedProjections:
    """Count exact book projections while preserving the production calculation."""

    def __init__(self, project: Callable[[BookObservation], dict[str, ExactRatio] | None]) -> None:
        """Bind the original projection with none counted."""
        self._project = project
        self.projections = 0

    def __call__(self, row: BookObservation) -> dict[str, ExactRatio] | None:
        """Count one projection and compute it as before."""
        self.projections += 1
        return self._project(row)


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
            self.request, (self.requirement,), history_capacity=history_capacity
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

    @pytest.mark.parametrize("venue", ("okx", "bitfinex"))
    def test_historical_native_books_survive_later_updates_and_invalidation(
        self,
        venue: Literal["okx", "bitfinex"],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Historical reads restore every native value once and carry its original clocks."""
        scenario = _LiveScenario(venue, "receipt")
        scenario.push("session", 999_000_000)
        if venue == "okx":
            scenario.push("frame", 999_500_000, raw=_OKX_ACK)
            snapshot = _OKX_SNAPSHOT.replace(
                b'[["100","2","0","2"]]',
                b'[["100","2","0","2"],["99","3","0","4"]]',
            )
            update = _OKX_UPDATE
            control = b"pong"
        else:
            scenario.push("frame", 999_250_000, raw=b'{"event":"conf","status":"OK","flags":65536}')
            scenario.push("frame", 999_500_000, raw=_BITFINEX_ACK)
            snapshot = b"[7,[[1,100,2],[2,101,-1],[3,99,3]],1]"
            update = b"[7,[1,100,1],2]"
            control = b'[7,"hb",3]'
        first = scenario.push("frame", 1_000_000_001, raw=snapshot)
        second = scenario.push("frame", 1_001_000_001, raw=update)
        scenario.push("frame", 1_002_000_001, raw=control)
        scenario.push("gap", 1_003_000_001, reason="disconnect_unknown_loss")
        assert scenario.source.latest_book is None
        entity = str(scenario.request.config.instrument_id)
        assert (
            scenario.source.current_book(entity, _EPOCH + timedelta(microseconds=1_003_001)) is None
        )
        counted = _CountedBookDecodes(DomainCodec.decode_json, scenario.source._codec)
        monkeypatch.setattr(DomainCodec, "decode_json", counted)
        codec = DomainCodec()
        first_at = _EPOCH + timedelta(microseconds=1_000_001)
        first_decision = scenario.source.read(entity, first_at)
        restored_first = scenario.source.book_at(entity, first_at)
        assert restored_first is not None and restored_first == first
        assert codec.encode_json(restored_first) == codec.encode_json(first)
        assert scenario.source.read(entity, first_at) is first_decision
        assert counted.decodes == 1
        second_at = _EPOCH + timedelta(microseconds=1_001_001)
        scenario.source.read(entity, second_at)
        restored_second = scenario.source.book_at(entity, second_at)
        assert restored_second is not None and restored_second == second
        assert codec.encode_json(restored_second) == codec.encode_json(second)
        assert counted.decodes == 2
        carried_at = _EPOCH + timedelta(microseconds=1_002_001)
        carried = scenario.source.read(entity, carried_at).observations[0]
        assert scenario.source.book_at(entity, carried_at) is restored_second
        assert carried.event_at == second_at and carried.available_at == second_at
        assert counted.decodes == 2
        missing_at = _EPOCH + timedelta(microseconds=1_003_001)
        assert scenario.source.read(entity, missing_at).observations[0].value is None
        assert scenario.source.book_at(entity, missing_at) is None

    def test_exact_imbalance_is_projected_only_for_selected_cutoff(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every delivered book stays causal without repeating depth arithmetic eagerly."""
        scenario = _LiveScenario("okx", "event")
        counted = _CountedProjections(LiveBookDecisionSource._book_values)
        monkeypatch.setattr(LiveBookDecisionSource, "_book_values", staticmethod(counted))
        entity = str(scenario.request.config.instrument_id)
        scenario.push("session", 999_000_000)
        scenario.push("frame", 999_500_000, raw=_OKX_ACK)
        market = scenario.push("frame", 1_000_000_001, raw=_OKX_SNAPSHOT)
        assert (
            scenario.source.current_book(entity, _EPOCH + timedelta(microseconds=1_000_001))
            == market
        )
        assert counted.projections == 0
        at = _EPOCH + timedelta(microseconds=1_000_001)
        selected = scenario.source.read(entity, at)
        assert selected.observations[0].value == ExactRatio(numerator="1", denominator="3")
        assert scenario.source.read(entity, at) is selected
        assert counted.projections == 1
        scenario.push("frame", 2_000_000_000, raw=b"pong")
        assert counted.projections == 1
        carried = scenario.source.read(entity, _EPOCH + timedelta(seconds=2))
        assert carried.observations[0].value == selected.observations[0].value
        assert counted.projections == 2

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
        quote = source.current_quote(entity, cutoff)
        assert quote is not None
        assert quote.venue == "okx"
        assert quote.instrument_id == scenario.request.config.instrument_id
        assert quote.source_id == scenario.request.identity
        assert quote.channel == "books"
        assert quote.available_ns == 1_000_001_000
        assert quote.market_state == "two_sided"
        assert quote.bid is not None and quote.bid.price == 100
        assert quote.bid.quantity == 2 and quote.bid.order_count == 2
        assert quote.ask is not None and quote.ask.price == 101
        assert quote.ask.quantity == 1 and quote.ask.order_count == 1
        scenario.push("frame", 1_000_000_500, raw=_OKX_UPDATE)
        assert source.read(entity, cutoff) is decided
        assert source.book_at(entity, cutoff) == book
        assert source.current_book(entity, cutoff) == source.latest_book
        assert source.current_book(entity, cutoff) != book
        updated_quote = source.current_quote(entity, cutoff)
        assert updated_quote is not None and updated_quote.bid is not None
        assert updated_quote.bid.quantity == 1
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
        carried_quote = scenario.source.current_quote(entity, _EPOCH + timedelta(seconds=2))
        assert carried_quote is not None and carried_quote.available_ns == 1_000_001_000
        stale = scenario.source.read(entity, _EPOCH + timedelta(seconds=17)).observations[0]
        assert stale.value is None and stale.reason == "stale_market_progress"
        assert scenario.source.book_at(entity, _EPOCH + timedelta(seconds=17)) is None
        assert scenario.source.current_book(entity, _EPOCH + timedelta(seconds=17)) is None
        assert scenario.source.current_quote(entity, _EPOCH + timedelta(seconds=17)) is None
        scenario.push("gap", 18_000_000_000, reason="disconnect_unknown_loss")
        assert scenario.source.latest_book is None
        assert scenario.source.current_quote(entity, _EPOCH + timedelta(seconds=18)) is None
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
            scenario.request, (scenario.requirement,), history_capacity=16
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
                (replace(scenario.requirement, clock="event"),),
                history_capacity=16,
            )

    def test_touch_fields_share_one_book_and_refuse_mismatched_contracts(self) -> None:
        """Ask, bid and touch sizes come from the same book as imbalance, in declared order."""
        scenario = _LiveScenario("okx", "receipt")
        fields = (
            NumericField(name="ask", units="quote/base"),
            NumericField(name="bid", units="quote/base"),
            NumericField(name="ask_size", units="base"),
            NumericField(name="bid_size", units="base"),
            NumericField(name="imbalance", units="dimensionless"),
        )
        requirements = tuple(replace(scenario.requirement, field=field) for field in fields)
        source = LiveBookDecisionSource(scenario.request, requirements, history_capacity=16)
        scenario.source = source
        entity = str(scenario.request.config.instrument_id)
        scenario.push("session", 999_000_000)
        scenario.push("frame", 999_500_000, raw=_OKX_ACK)
        scenario.push("frame", 1_000_000_001, raw=_OKX_SNAPSHOT)
        decided = source.read(entity, _EPOCH + timedelta(microseconds=1_000_001))
        assert tuple(row.input for row in decided.observations) == requirements
        quote = source.current_quote(entity, _EPOCH + timedelta(microseconds=1_000_001))
        assert quote is not None and quote.bid is not None and quote.ask is not None
        values = {row.input.field.name: row.value for row in decided.observations}
        assert values["ask"] == ExactRatio.from_fraction(Fraction(quote.ask.price))
        assert values["bid"] == ExactRatio.from_fraction(Fraction(quote.bid.price))
        assert values["ask_size"] == ExactRatio.from_fraction(Fraction(quote.ask.quantity))
        assert values["bid_size"] == ExactRatio.from_fraction(Fraction(quote.bid.quantity))
        assert values["imbalance"] == ExactRatio(numerator="1", denominator="3")
        assert len({row.lineage for row in decided.observations}) == 1
        for invalid in (
            (replace(requirements[0], field=NumericField(name="ask", units="base")),),
            (requirements[0], replace(requirements[1], max_age_us=1)),
            (requirements[0], requirements[0]),
            (replace(requirements[0], field=NumericField(name="spread", units="quote/base")),),
        ):
            with pytest.raises(ValueError, match="unsupported live book"):
                LiveBookDecisionSource(scenario.request, invalid, history_capacity=16)

    def test_bitfinex_sequenced_controls_carry_only_proved_old_market(self) -> None:
        """Native heartbeats preserve L3 value and age without becoming market rows."""
        scenario = _LiveScenario("bitfinex", "receipt")
        entity = str(scenario.request.config.instrument_id)
        scenario.push("session", 1_000_000_000)
        scenario.push(
            "frame",
            1_001_000_000,
            raw=b'{"event":"conf","status":"OK","flags":65536}',
        )
        scenario.push("frame", 1_002_000_000, raw=_BITFINEX_ACK)
        market = scenario.push("frame", 1_003_000_000, raw=b"[7,[[1,100,2],[2,101,-1]],1]")
        assert market.outcome == "snapshot"
        boundaries = (
            (5_000_000_000, b'[7,"hb",2]', "heartbeat"),
            (6_000_000_000, b'{"event":"info","version":2}', "control"),
            (10_000_000_000, b'[7,"hb",3]', "heartbeat"),
        )
        for received_ns, raw, outcome in boundaries:
            boundary = scenario.push("frame", received_ns, raw=raw)
            assert boundary.outcome == outcome
            assert boundary.state_identity != market.state_identity
            assert boundary.orders == ()
            assert boundary.bids == ()
            assert boundary.asks == ()
            assert scenario.source.latest_book == market
            at = _EPOCH + timedelta(microseconds=received_ns // 1_000)
            observed = scenario.source.read(entity, at).observations[0]
            assert observed.value == ExactRatio(numerator="1", denominator="3")
            assert observed.event_at == _EPOCH + timedelta(microseconds=1_003_000)
            assert observed.available_at == observed.event_at
            assert scenario.source.book_at(entity, at) == market
            quote = scenario.source.current_quote(entity, at)
            assert quote is not None and quote.available_ns == 1_003_000_000
        stale_at = _EPOCH + timedelta(seconds=17)
        assert (
            scenario.source.read(entity, stale_at).observations[0].reason == "stale_market_progress"
        )
        assert scenario.source.current_quote(entity, stale_at) is None

    def test_bitfinex_boundary_refuses_changed_identity_and_sequence_gap(self) -> None:
        """A control carry requires the exact native L3 hash at its validated sequence."""
        scenario = _LiveScenario("bitfinex", "receipt")
        entity = str(scenario.request.config.instrument_id)
        scenario.push("session", 1_000_000_000)
        scenario.push(
            "frame",
            1_001_000_000,
            raw=b'{"event":"conf","status":"OK","flags":65536}',
        )
        scenario.push("frame", 1_002_000_000, raw=_BITFINEX_ACK)
        scenario.push("frame", 1_003_000_000, raw=b"[7,[[1,100,2],[2,101,-1]],1]")
        record = CaptureRecord(kind="frame", epoch=0, received_ns=5_000_000_000, raw=b'[7,"hb",2]')
        outcome = scenario.replay.apply(record)
        row = BookProjection.capture(len(scenario.records), record, outcome, scenario.replay)
        scenario.source.accept(record, replace(row, state_identity="0" * 64))
        assert scenario.source.latest_book is None
        assert scenario.source.current_quote(entity, _EPOCH + timedelta(seconds=5)) is None
        assert (
            scenario.source.read(entity, _EPOCH + timedelta(seconds=5)).observations[0].value
            is None
        )

        gap = _LiveScenario("bitfinex", "receipt")
        gap.push("session", 1_000_000_000)
        gap.push("frame", 1_001_000_000, raw=b'{"event":"conf","status":"OK","flags":65536}')
        gap.push("frame", 1_002_000_000, raw=_BITFINEX_ACK)
        gap.push("frame", 1_003_000_000, raw=b"[7,[[1,100,2],[2,101,-1]],1]")
        invalid = gap.push("frame", 5_000_000_000, raw=b'[7,"hb",4]')
        assert invalid.outcome == "invalid_frame"
        assert gap.source.latest_book is None
        assert gap.source.current_quote(entity, _EPOCH + timedelta(seconds=5)) is None

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

    def test_public_accept_revalidates_a_mutated_book(self) -> None:
        """Direct callers cannot enter the trusted observer path with invalid depth."""
        scenario = _LiveScenario("okx", "receipt")
        scenario.push("session", 999_000_000)
        scenario.push("frame", 999_500_000, raw=_OKX_ACK)
        record = CaptureRecord(kind="frame", epoch=0, received_ns=1_000_000_001, raw=_OKX_SNAPSHOT)
        outcome = scenario.replay.apply(record)
        row = BookProjection.capture(2, record, outcome, scenario.replay)
        force_setattr(row, "state_identity", "bad")
        with pytest.raises(ValueError, match="book state or quality"):
            scenario.source.accept(record, row)

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
        delayed_quote = scenario.source.current_quote(entity, delivery_at)
        assert delayed_quote is not None and delayed_quote.available_ns == 2_000_000_000
        new_request = replace(scenario.request, recording_id="c" * 36)
        restarted = LiveBookDecisionSource(
            new_request, (scenario.requirement,), history_capacity=16
        )
        assert restarted.identity == scenario.source.identity
        assert (
            restarted.read(entity, _EPOCH + timedelta(milliseconds=900)).observations[0].reason
            == "no_live_input"
        )
        changed = LiveBookDecisionSource(
            replace(new_request, config=replace(new_request.config, idle_seconds=14)),
            (scenario.requirement,),
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
            other = LiveBookDecisionSource(
                new_request, (scenario.requirement,), history_capacity=16
            )
            record = CaptureRecord(kind="session", epoch=0, received_ns=2_000_000_000)
            replay = CaptureReplay(new_request.config, book_factory=BookAdapters.create)
            outcome = replay.apply(record)
            other.accept(
                record,
                BookProjection.capture(0, record, outcome, replay),
                available_at=_EPOCH + timedelta(seconds=1),
            )
