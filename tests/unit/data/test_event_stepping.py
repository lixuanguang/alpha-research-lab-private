"""Protect chronological phases, source ordering and completed-step replay recovery."""

from __future__ import annotations

# standard library imports
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Event

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace
from test_asof import TestAsOfSelector as _Scenario
from test_query import TestQueryReader as _QueryScenario

# project library imports
from alpha_research.data.asof import PointEvent
from alpha_research.data.events import Disconnect
from alpha_research.data.normalization import Occurrence
from alpha_research.data.query import QueryReader
from alpha_research.data.replay import Replay, ReplayCursor, ReplayPhase
from alpha_research.data.revisions import TradeRevision
from alpha_research.serialization import DomainCodec

type _TraceRow = tuple[datetime, ReplayPhase, int | str | None, Decimal | None]


class _Trace:
    """Retain only causal economic values, excluding whole-input provenance identities."""

    def __init__(self) -> None:
        """Start an independent callback trace."""
        self.rows: list[_TraceRow] = []

    def consume(self, phase: ReplayPhase, instant: datetime, item: PointEvent | None) -> None:
        """Record the source payload or the completed phase without executing economics."""
        label: int | str | None = None
        price = None
        if isinstance(item, TradeRevision):
            event = item.occurrences[0].event
            assert not isinstance(event, Disconnect)
            label, price = item.key[-1], event.price
        elif isinstance(item, Occurrence):
            label = "disconnect"
        self.rows.append((instant, phase, label, price))


class TestReplay:
    """Compose the same admitted fixtures through public replay and query boundaries."""

    @staticmethod
    def _replay(
        reader: QueryReader,
        *,
        size: int = 1,
        cursor: ReplayCursor | None = None,
        config: str | None = None,
    ) -> Replay:
        """Keep the resolved configuration and inclusive terminal fixed across batch sizes."""
        request = _Scenario._request()
        return Replay(
            reader,
            (request.instrument.instrument_id,),
            start=request.start,
            end=request.end,
            terminal=request.start + timedelta(seconds=12),
            config_identity=request.manifest.identity if config is None else config,
            batch_size=size,
            cursor=cursor,
        )

    @staticmethod
    def _finish(replay: Replay, trace: _Trace) -> None:
        """Drain source and terminal steps without injecting a decision cadence."""
        while replay.step(_Scenario._request().start + timedelta(seconds=12), trace.consume):
            pass

    def test_revision_availability_phase_order_batch_invariance_and_terminal(self) -> None:
        """Read-ahead leaves the clock unset; original, gap and correction arrive separately."""
        request = _Scenario._request()
        traces: list[list[_TraceRow]] = []
        cursors: list[ReplayCursor | None] = []
        for size in (1, 8):
            replay = self._replay(_QueryScenario._reader(), size=size)
            assert replay.cursor is None
            assert replay.evidence[0].scope == "exploratory_degraded"
            assert len(replay.evidence) == 1
            trace = _Trace()
            # An additional fill-eligibility or expiry wakeup is processed before the gap.
            replay.step(request.start, trace.consume)
            replay.step(request.start + timedelta(seconds=2), trace.consume)
            assert replay.cursor is not None and replay.cursor.clock == request.start + timedelta(
                seconds=1
            )
            replay.step(request.start + timedelta(seconds=2), trace.consume)
            self._finish(replay, trace)
            traces.append(trace.rows)
            cursors.append(replay.cursor)
        assert traces[0] == traces[1] and cursors[0] == cursors[1]
        assert [
            (int((t - request.start).total_seconds()), label, price)
            for t, p, label, price in traces[0]
            if p == "source"
        ] == [(1, 12, Decimal("100")), (3, "disconnect", None), (10, 12, Decimal("101"))]
        for second in (0, 1, 2, 3, 10, 12):
            phases = [
                p for t, p, _, _ in traces[0] if t == request.start + timedelta(seconds=second)
            ]
            assert phases[-4:] == ["expiry", "fill", "decision", "mark"]
        assert replay.step(request.start, trace.consume) is None

    def test_equal_time_sources_complete_before_expiry_fill_decision(self) -> None:
        """Raw position wins over trade IDs and an equal-time control precedes all fill phases."""
        fixture = _Scenario()
        request = fixture._request()
        items = (
            fixture._item(request, trade_id=99),
            fixture._item(request, position=1, trade_id=1),
            fixture._item(request, position=2, disconnect=True),
        )
        payload = fixture._canonical(request, items)
        reader = QueryReader((payload,), precedence=(fixture._binding(request),), max_bytes=262_144)
        expected = None
        for size in (1, 2, 8):
            trace = _Trace()
            replay = self._replay(reader, size=size)
            cursor = replay.step(request.start + timedelta(seconds=1), trace.consume)
            assert cursor is not None and cursor.position is not None and cursor.position[3] == 2
            assert [row[2] for row in trace.rows[:3]] == [99, 1, "disconnect"]
            assert [row[1] for row in trace.rows] == ["source"] * 3 + [
                "expiry",
                "fill",
                "decision",
                "mark",
            ]
            assert expected is None or trace.rows == expected
            expected = trace.rows
            incomplete = replace(
                cursor, position=(cursor.position[0], cursor.position[1], cursor.position[2], 1, 0)
            )
            with pytest.raises(ValueError, match="incomplete"):
                self._replay(reader, cursor=incomplete)

    def test_cursor_roundtrip_resume_changed_configuration_and_input(self) -> None:
        """Resume every completed step across batch sizes, rejecting different bound histories."""
        reader = _QueryScenario._reader()
        replay, full = self._replay(reader), _Trace()
        self._finish(replay, full)
        replay, prefix = self._replay(reader), _Trace()
        codec = DomainCodec()
        while (cursor := replay.step(_Scenario._request().end, prefix.consume)) is not None:
            encoded = codec.encode_json(cursor)
            restored = codec.decode_json(encoded, ReplayCursor)
            assert restored == cursor
            resumed = self._replay(reader, size=8, cursor=restored)
            suffix = _Trace()
            self._finish(resumed, suffix)
            assert prefix.rows + suffix.rows == full.rows
            with pytest.raises(ValueError, match="incompatible"):
                self._replay(reader, cursor=restored, config="b" * 64)
            completed = resumed.cursor
            force_setattr(restored, "identity", "c" * 64)
            assert resumed.cursor == completed
        fixture = _Scenario()
        request = fixture._request()
        changed = QueryReader(
            (fixture._canonical(request, (fixture._item(request, price="102"),)),),
            precedence=(fixture._binding(request),),
            max_bytes=262_144,
        )
        with pytest.raises(ValueError, match="incompatible"):
            self._replay(changed, cursor=replay.cursor)

    def test_future_only_rows_duplicates_and_hashes_cannot_change_prefix(self) -> None:
        """Adding a future duplicate with earlier raw position cannot reorder today's prefix."""
        fixture = _Scenario()
        request = fixture._request()
        traces: list[list[_TraceRow]] = []
        for changed in (False, True):
            digest = "c" * 64 if changed else "a" * 64
            items = tuple(
                fixture._item(request, trade_id=t, position=i, digest=digest)
                for i, t in enumerate((99, 1))
            )
            if changed:
                items += (
                    fixture._item(request, trade_id=1, capture=11, digest="b" * 64),
                    fixture._item(request, position=1, capture=12, trade_id=100, digest="b" * 64),
                )
            reader = QueryReader(
                (fixture._canonical(request, items),),
                precedence=(fixture._binding(request),),
                max_bytes=262_144,
            )
            trace = _Trace()
            replay = self._replay(reader)
            self._finish(replay, trace)
            traces.append(
                [row for row in trace.rows if row[0] <= request.start + timedelta(seconds=1)]
            )
        assert traces[0] == traces[1]

    def test_unknown_archive_knowledge_and_membership_do_not_become_eligibility(self) -> None:
        """Retain unknown quality evidence while withholding unschedulable original events."""
        fixture = _Scenario()
        request = fixture._request(archive=True)
        reader = QueryReader(
            (fixture._canonical(request, (fixture._item(request),)),),
            precedence=(fixture._binding(request),),
            max_bytes=262_144,
        )
        trace = _Trace()
        replay = self._replay(reader)
        self._finish(replay, trace)
        assert [row[1] for row in trace.rows] == ["expiry", "fill", "decision", "mark"]
        assert "original trade availability unknown" in replay.evidence[0].reasons
        assert replay.cursor is not None and replay.cursor.position is None

    def test_callback_failure_reentrancy_and_unsafe_mutation(self) -> None:
        """Partial phases cannot checkpoint or continue; returned objects cannot poison reuse."""
        replay = self._replay(_QueryScenario._reader())
        request = _Scenario._request()
        trace = _Trace()
        cursor = replay.step(request.start, trace.consume)
        assert cursor is not None
        force_setattr(cursor, "clock", request.end)
        assert replay.cursor is not None and replay.cursor.clock == request.start
        with pytest.raises(AssertionError):
            replay.step(request.end, self._fail)
        with pytest.raises(RuntimeError, match="incomplete"):
            _ = replay.cursor
        with pytest.raises(RuntimeError, match="incomplete"):
            replay.step(request.end, trace.consume)

    @staticmethod
    def _fail(phase: ReplayPhase, instant: datetime, item: PointEvent | None) -> None:
        """Represent a failing consumer, whose partial state requires independent restoration."""
        raise AssertionError("synthetic callback failure")

    def test_invalid_clocks_ordering_and_cancellation(self) -> None:
        """Reject invalid wakeups, ambiguous logical positions and cancellation before stepping."""
        reader = _QueryScenario._reader()
        replay, trace = self._replay(reader), _Trace()
        request = _Scenario._request()
        with pytest.raises(TypeError, match="timezone-aware"):
            replay.step(datetime(2024, 6, 1), trace.consume)
        replay.step(request.start, trace.consume)
        with pytest.raises(ValueError, match="follow"):
            replay.step(request.start, trace.consume)
        with pytest.raises(ValueError, match="configuration"):
            self._replay(reader, config="latest")
        fixture = _Scenario()
        ambiguous = QueryReader(
            (
                fixture._canonical(
                    request,
                    (fixture._item(request), fixture._item(request, trade_id=13, digest="b" * 64)),
                ),
            ),
            precedence=(fixture._binding(request),),
            max_bytes=262_144,
        )
        with pytest.raises(ValueError, match="ambiguous"):
            self._replay(ambiguous)
        stop = Event()
        stop.set()
        with pytest.raises(InterruptedError, match="cancelled"):
            Replay(
                reader,
                (request.instrument.instrument_id,),
                start=request.start,
                end=request.end,
                terminal=request.end,
                config_identity=request.manifest.identity,
                batch_size=1,
                cancelled=stop.is_set,
            )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("identity", "latest"),
            ("clock", "2024-06-01T00:00:01"),
            ("position", ["2024-06-01T00:00:01Z", True, "2024-06-01T00:00:00Z", 0, 0]),
            ("position", ["2024-06-01T00:00:01Z", 0, "2024-06-01T00:00:00Z", -1, 0]),
            ("extra", "field"),
        ],
    )
    def test_cursor_codec_rejects_malformed_and_unsafe_values(
        self, field: str, value: object
    ) -> None:
        """Strict cached codecs and resume both revalidate untrusted checkpoint records."""
        replay = self._replay(_QueryScenario._reader())
        cursor = replay.step(_Scenario._request().end, _Trace().consume)
        assert cursor is not None
        wire: dict[str, object] = {
            "identity": cursor.identity,
            "clock": cursor.clock,
            "position": cursor.position,
        }
        wire[field] = value
        codec = DomainCodec()
        with pytest.raises((TypeError, ValueError)):
            codec.decode_json(codec.encode_json(wire), ReplayCursor)
        force_setattr(cursor, "identity", "latest")
        with pytest.raises(ValueError, match="SHA-256"):
            self._replay(_QueryScenario._reader(), cursor=cursor)

    def test_sources_cannot_mutate_future_revisions_and_reentrant_steps_fail(self) -> None:
        """Unsafe callback mutation stays local and a nested step cannot bypass phase order."""
        replay = self._replay(_QueryScenario._reader())
        trace = _Trace()
        terminal = _Scenario._request().start + timedelta(seconds=12)
        observer = _MutatingObserver(replay, trace, terminal)
        while replay.step(terminal, observer.consume):
            pass
        prices = [
            price for _, phase, _, price in trace.rows if phase == "source" and price is not None
        ]
        assert prices == [Decimal("100"), Decimal("101")]
        assert observer.refused == 3


class _MutatingObserver:
    """Deliberately challenge ownership while preserving an observable source trace."""

    def __init__(self, replay: Replay, trace: _Trace, terminal: datetime) -> None:
        """Bind the current replay and record callback reentrancy refusals."""
        self._replay, self._trace, self._terminal = replay, trace, terminal
        self.refused = 0

    def consume(self, phase: ReplayPhase, instant: datetime, item: PointEvent | None) -> None:
        """Read causal values before corrupting only the isolated callback copy."""
        self._trace.consume(phase, instant, item)
        if phase == "source":
            with pytest.raises(RuntimeError, match="incomplete"):
                self._replay.step(self._terminal, self._trace.consume)
            self.refused += 1
            if isinstance(item, TradeRevision):
                force_setattr(item, "schema_version", "unsafe")
