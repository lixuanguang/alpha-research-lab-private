"""Exercise installed book publication, query, consumer state and fresh-process cursor recovery."""

from __future__ import annotations

# standard library imports
import hashlib
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

# third party library imports
import msgspec

# project library imports
import market_data
from market_data.adapters.sources import BookAdapters, SourceAdapters
from market_data.books import BookDepth, BookProjection, CaptureReplay
from market_data.contracts import BookObservation, CaptureRequest
from market_data.datasets import BookHistory, BookInput, DatasetPublication
from market_data.replay import BookReplay, ReplayCursor, ReplayPhase
from market_data.storage import CaptureJournal, RawStore
from runtime import ImplementationIdentity
from serialization import DomainCodec

_CODEC = DomainCodec()
_LIMIT = 600_000_000


class ViewState(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Checkpoint the accepted snapshot, current exact state and last quality/session boundary."""

    snapshot: BookObservation | None = None
    current: BookObservation | None = None
    boundary: BookObservation | None = None


class BookView:
    """Use the same visible-spread consumer for captured, saved and chronological inputs."""

    def __init__(self, state: ViewState = ViewState()) -> None:
        """Start or restore explicit consumer state without a venue connection.

        Args:
            state: State saved alongside its completed shared cursor.
        """
        self.state = state
        self.rows: list[tuple[int, int | None, str, str, Decimal | None, str]] = []

    def observe(self, row: BookObservation) -> None:
        """Apply a complete canonical message and report only exploratory usable spreads.

        Args:
            row: Normalized message with native units, exact values and quality scope.
        """
        snapshot, current = self.state.snapshot, self.state.current
        if row.outcome == "session":
            snapshot = current = None
        if row.outcome in ("snapshot", "update"):
            current = row
        if row.outcome == "snapshot":
            snapshot = row
        self.state = ViewState(snapshot, current, row)
        spread = None
        if current is not None and row.status == "degraded":
            bids = [order.price for order in current.orders if order.side == "buy"]
            asks = [order.price for order in current.orders if order.side == "sell"]
            bids.extend(price for price, _ in current.bids)
            asks.extend(price for price, _ in current.asks)
            if bids and asks:
                spread = min(asks) - max(bids)
        self.rows.append(
            (row.position, row.epoch, row.outcome, row.status, spread, row.state_identity)
        )

    def consume(self, phase: ReplayPhase, instant: datetime, row: BookObservation | None) -> None:
        """Consume only the shared source phase; clock advancement grants no execution use.

        Args:
            phase: Shared source or consumer phase.
            instant: Conservative UTC availability clock.
            row: Atomic source message, absent for later phases.
        """
        if row is not None:
            assert phase == "source" and row.received_ns is not None
            delta = instant - datetime(1970, 1, 1, tzinfo=UTC)
            clock_ns = (
                delta.days * 86400 + delta.seconds
            ) * 1_000_000_000 + delta.microseconds * 1000
            assert row.received_ns <= clock_ns
            self.observe(row)


class Checkpoint(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Retain one fixture's replay identity and consumer state for isolated process restart."""

    snapshot_identity: str
    terminal: datetime
    cursor: ReplayCursor
    state: ViewState


class NativeQuoteParity:
    """Compare every installed native boundary with full independent order aggregation."""

    @staticmethod
    def verify(source: Path, request: CaptureRequest) -> dict[str, object]:
        """Reopen original frames without inventing delivery clocks or changing old identities."""
        replay = CaptureReplay(request.config, book_factory=BookAdapters.create)
        digest = hashlib.sha256()
        count = 0
        for position, record in enumerate(CaptureJournal(source, request).records()):
            outcome = replay.apply(record)
            row = BookProjection.capture(position, record, outcome, replay)
            quote = BookProjection.quote(
                position, record, outcome, replay, source_id=request.identity, available_ns=None
            )
            depth = BookDepth.from_observation(row)
            assert quote == depth.quote(
                row,
                venue=request.config.venue,
                instrument_id=request.config.instrument_id,
                source_id=request.identity,
                channel=request.config.channel,
                available_ns=None,
            )
            if row.orders:
                assert not row.bids and not row.asks
                for side, levels in (("buy", replay.book.bids), ("sell", replay.book.asks)):
                    prices = {order.price for order in row.orders if order.side == side}
                    assert set(levels) == prices
                    for price in prices:
                        matching = tuple(
                            order
                            for order in row.orders
                            if order.side == side and order.price == price
                        )
                        assert levels[price].order_count == len(matching)
                        assert Fraction(levels[price].size) == sum(
                            (Fraction(order.size) for order in matching), Fraction()
                        )
            if quote.market_state != "unavailable":
                count += 1
            assert quote.available_ns is None
            digest.update(_CODEC.encode_json(quote))
        saved = msgspec.json.decode(
            (source / "summary.json").read_bytes(), type=dict[str, msgspec.Raw]
        )
        for key in ("book_identity", "trace_identity"):
            assert replay.summary()[key] == msgspec.json.decode(saved[key], type=str)
        return {
            "quoted_boundaries": count,
            "quote_trace_sha256": digest.hexdigest(),
            "original_book_and_trace_equal": True,
            "availability": "unknown; receipt retained",
        }


def inspect(source: Path, output: Path) -> dict[str, object]:
    """Compose verified saved input, published history, the shared consumer and fresh restart.

    Args:
        source: Completed capture or archive directory.
        output: Fresh isolated evidence directory.

    Returns:
        Small identities, causal limits, exact consumer observations and checkpoint evidence.
    """
    output.mkdir()
    raw, snapshots = output / "raw", output / "snapshots"
    raw.mkdir()
    snapshots.mkdir()
    selected = BookInput.read(source, max_records=32)
    identity = DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).publish_books(
        (source,), RawStore(raw), snapshots, max_records=32, max_bytes=_LIMIT
    )
    payload = selected.admit(
        RawStore(raw), readers=SourceAdapters(), max_bytes=_LIMIT
    ).require_canonical()
    history = _CODEC.decode_json(payload, BookHistory)
    assert all(row.position == index for index, row in enumerate(history.observations))
    terminal = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
        microseconds=(max(row.received_ns or 0 for row in history.observations) + 999) // 1000 + 1
    )
    engine = BookReplay.read(
        snapshots,
        RawStore(raw),
        readers=SourceAdapters(),
        identity=identity,
        request_identity=selected.request.identity,
        batch_size=1,
        terminal=terminal,
        config_identity=selected.request.identity,
        max_bytes=_LIMIT,
    )
    assert tuple(row for batch in engine.batches() for row in batch) == history.observations
    expected, actual = BookView(), BookView()
    capture_path = source / "book-prefix.json"
    if capture_path.exists():
        captured = _CODEC.decode_json(capture_path.read_bytes(), BookHistory)
        assert captured == history
    for row in history.observations:
        if row.received_ns is not None:
            expected.observe(row)
    checkpoints: list[Checkpoint] = []
    while (cursor := engine.step(terminal, actual.consume)) is not None:
        checkpoints.append(Checkpoint(identity, terminal, cursor, actual.state))
    assert actual.rows == expected.rows
    assert actual.state == expected.state
    assert all(row.received_ns is None for row in history.observations) == (len(actual.rows) == 0)
    # Check every completed step with a different query batch size and serialized state.
    for checkpoint in checkpoints:
        restored = _CODEC.decode_json(_CODEC.encode_json(checkpoint), Checkpoint)
        view = BookView(restored.state)
        replay = BookReplay(
            payload,
            snapshot_identity=identity,
            batch_size=7,
            cursor=restored.cursor,
            terminal=terminal,
            config_identity=selected.request.identity,
            max_bytes=_LIMIT,
        )
        while replay.step(terminal, view.consume):
            pass
        assert view.state == actual.state and replay.cursor == engine.cursor
    chosen = next((item for item in checkpoints if item.state.snapshot is not None), checkpoints[0])
    (output / "canonical.json").write_bytes(payload)
    (output / "checkpoint.json").write_bytes(_CODEC.encode_json(chosen))
    process = subprocess.run(
        [sys.executable, "-I", str(Path(__file__).resolve()), "resume", str(output)],
        cwd=output,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert process.returncode == 0, (process.stdout, process.stderr)
    resumed = _CODEC.decode_json((output / "resumed.json").read_bytes(), ViewState)
    assert resumed == actual.state
    failures: list[str] = []
    try:
        BookReplay(
            payload,
            snapshot_identity="f" * 64,
            batch_size=7,
            cursor=chosen.cursor,
            terminal=terminal,
            config_identity=selected.request.identity,
            max_bytes=_LIMIT,
        )
    except ValueError as error:
        failures.append(str(error))
    assert len(failures) == 1
    summary: dict[str, object] = {
        "source": str(source),
        "raw_identity": selected.raw.sha256,
        "snapshot_identity": identity,
        "replay_identity": checkpoints[-1].cursor.identity,
        "canonical_sha256": hashlib.sha256(payload).hexdigest(),
        "query_records": len(history.observations),
        "scheduled_records": len(actual.rows),
        "completed_checkpoints": len(checkpoints),
        "fresh_process_resume": True,
        "live_prefix_compared": capture_path.exists(),
        "scope": history.scope,
        "depth": selected.capture.config.depth if selected.capture is not None else 400,
        "refusals": failures,
        "consumer_sample": actual.rows[:8],
        "checkpoint_epoch": None if chosen.state.boundary is None else chosen.state.boundary.epoch,
        "accepted_snapshot_position": None
        if chosen.state.snapshot is None
        else chosen.state.snapshot.position,
        "native_quotes": None
        if selected.capture is None
        else NativeQuoteParity.verify(source, selected.capture),
    }
    (output / "result.json").write_bytes(_CODEC.encode_json(summary))
    return summary


def main() -> None:
    """Run saved-input verification or resume only from explicitly retained fixture files."""
    if sys.argv[1] == "resume":
        output = Path(sys.argv[2])
        checkpoint = _CODEC.decode_json((output / "checkpoint.json").read_bytes(), Checkpoint)
        payload = (output / "canonical.json").read_bytes()
        history = _CODEC.decode_json(payload, BookHistory)
        view = BookView(checkpoint.state)
        if checkpoint.cursor.position is not None:
            assert view.state.boundary is not None
            assert view.state.boundary.position == checkpoint.cursor.position[-1]
        replay = BookReplay(
            payload,
            snapshot_identity=checkpoint.snapshot_identity,
            terminal=checkpoint.terminal,
            config_identity=history.input.request.identity,
            max_bytes=_LIMIT,
            batch_size=7,
            cursor=checkpoint.cursor,
        )
        while replay.step(checkpoint.terminal, view.consume):
            pass
        (output / "resumed.json").write_bytes(_CODEC.encode_json(view.state))
    else:
        output = Path(sys.argv[1])
        output.mkdir()
        results = [
            inspect(Path(source), output / str(index)) for index, source in enumerate(sys.argv[2:])
        ]
        report = {
            "installed_package": str(Path(market_data.__file__).resolve()),
            "inputs": results,
        }
        (output / "result.json").write_bytes(_CODEC.encode_json(report))
        print(_CODEC.encode_json(report).decode())


if __name__ == "__main__":
    main()
