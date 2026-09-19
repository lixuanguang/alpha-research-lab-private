"""Verify installed event stepping against a small, fully admitted synthetic partition."""

from __future__ import annotations

# standard library imports
import sys
import tracemalloc
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

# project library imports
import alpha_research
from alpha_research.configuration import Configuration
from alpha_research.data.asof import PointEvent
from alpha_research.data.events import Disconnect
from alpha_research.data.normalization import Occurrence
from alpha_research.data.query import QueryReader
from alpha_research.data.replay import Replay, ReplayCursor, ReplayPhase
from alpha_research.data.requests import SourceRequest
from alpha_research.data.revisions import TradeRevision
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec


class _Trace:
    """Observe exact values and phases, with no strategy, fills or accounting implementation."""

    def __init__(self) -> None:
        """Retain the source clock and ordered phase trace."""
        self.rows: list[tuple[datetime, ReplayPhase, str]] = []

    def consume(self, phase: ReplayPhase, instant: datetime, item: PointEvent | None) -> None:
        """Record values without substituting raw capture for revision availability."""
        label = ""
        if isinstance(item, TradeRevision):
            event = item.occurrences[0].event
            assert not isinstance(event, Disconnect)
            assert type(event.price) is Decimal
            label = str(event.price)
        elif isinstance(item, Occurrence):
            assert isinstance(item.event, Disconnect) and item.event.instrument_id is None
            label = "disconnect"
        self.rows.append((instant, phase, label))


def main() -> None:
    """Run installed imports, batch parity, scheduled wakeups, cursor recovery and failures.

    Raises:
        AssertionError: A shared ordering, phase or checkpoint invariant fails.
    """
    directory = Path(sys.argv[1]).resolve()
    installed = Path(alpha_research.__file__).resolve()
    assert "site-packages" in installed.parts and not installed.is_relative_to(directory)
    codec = DomainCodec()
    catalog = codec.decode_json((directory / "binance-spot.json").read_bytes(), CatalogSnapshot)
    run = Configuration.read(directory / "fixture-inspection.json").resolve("btc-fixture", catalog)
    request = SourceRequest.partition(run)[0]
    start, terminal = request.start, request.start + timedelta(seconds=12)
    payload = (directory / "canonical.json").read_bytes()
    reader = QueryReader(
        (payload,),
        precedence=((request.instrument.source, "trade", request.instrument.instrument_id),),
        max_bytes=262_144,
    )
    traces: list[list[tuple[datetime, ReplayPhase, str]]] = []
    cursors: list[ReplayCursor | None] = []
    restored: ReplayCursor
    tracemalloc.start()
    for size in (1, 8):
        replay = Replay(
            reader,
            (request.instrument.instrument_id,),
            start=start,
            end=request.end,
            terminal=terminal,
            config_identity=run.identity,
            batch_size=size,
        )
        trace = _Trace()
        assert replay.cursor is None
        replay.step(start, trace.consume)
        replay.step(start + timedelta(seconds=2), trace.consume)
        checkpoint = replay.cursor
        assert checkpoint is not None and checkpoint.clock == start + timedelta(seconds=1)
        restored = codec.decode_json(codec.encode_json(checkpoint), ReplayCursor)
        replay = Replay(
            reader,
            (request.instrument.instrument_id,),
            start=start,
            end=request.end,
            terminal=terminal,
            config_identity=run.identity,
            batch_size=8,
            cursor=restored,
        )
        replay.step(start + timedelta(seconds=2), trace.consume)
        while replay.step(terminal, trace.consume) is not None:
            pass
        traces.append(trace.rows)
        cursors.append(replay.cursor)
        assert replay.evidence[0].scope == "exploratory_degraded"
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert traces[0] == traces[1] and cursors[0] == cursors[1]
    sources = [
        (int((t - start).total_seconds()), value) for t, p, value in traces[0] if p == "source"
    ]
    assert sources == [(1, "100.00"), (3, "disconnect"), (10, "101.00")]
    for second in (0, 1, 2, 3, 10, 12):
        assert [p for t, p, _ in traces[0] if t == start + timedelta(seconds=second)][-4:] == [
            "expiry",
            "fill",
            "decision",
            "mark",
        ]
    try:
        Replay(
            reader,
            (request.instrument.instrument_id,),
            start=start,
            end=request.end,
            terminal=terminal,
            config_identity="b" * 64,
            batch_size=1,
            cursor=restored,
        )
    except ValueError as error:
        print("Changed configuration refused:", error)
    else:
        raise AssertionError("incompatible checkpoint accepted")
    print("Installed package:", installed)
    print("Source seconds and exact prices:", sources)
    print("Batch sizes 1/8 and resumed trace agree; callback rows:", len(traces[0]))
    print("Canonical bytes:", len(payload), "; traced replay peak bytes:", peak)
    print("Completed cursor:", codec.encode_json(cursors[0]).decode())


if __name__ == "__main__":
    main()
