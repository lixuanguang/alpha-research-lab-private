"""Publish captured public trades and prove research reads them exactly as live paper does."""

from __future__ import annotations

# standard library imports
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Literal
from uuid import UUID

# third party library imports
import msgspec
import pytest

# project library imports
from applications.publish_dataset import main as dataset_main
from configuration import CaptureConfig, UniverseSelection
from financial_units import ExactRatio
from market_data.adapters.sources import BookAdapters, SourceAdapters
from market_data.books import BookProjection, CaptureReplay
from market_data.contracts import ByteReader, CapturedTrades, CaptureRecord, CaptureRequest
from market_data.datasets import (
    CaptureInput,
    DatasetPublication,
    PublicTradeHistory,
    PublicTradeManifest,
    SnapshotStore,
)
from market_data.query import PublicTradeQuery
from market_data.storage import CaptureJournal, RawStore
from reference_data.instruments import InstrumentId
from research.exploration import (
    PublicTradeSelection,
    ResearchReader,
    ResearchSelection,
    SavedDecisionSource,
)
from research.observations import InputRequirement, LiveTradeDecisionSource, NumericField
from serialization import DomainCodec

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_START = datetime(2026, 9, 23, 12, tzinfo=UTC)
_LIMIT = 4_000_000
_OKX_ACK = b'{"event":"subscribe","arg":{"channel":"trades","instId":"BTC-USDT"}}'
_BITFINEX_CONF = b'{"event":"conf","status":"OK","flags":65536}'
_BITFINEX_SUBSCRIBED = (
    b'{"event":"subscribed","channel":"trades","chanId":7,"symbol":"tBTCUSD","pair":"BTCUSD"}'
)
Kind = Literal["session", "frame", "gap", "session_end", "end"]


class CapturedTradesFixture:
    """Author trades captures for both venues and read them live and saved."""

    @staticmethod
    def config(venue: Literal["okx", "bitfinex"]) -> CaptureConfig:
        """Select one venue's BTC public trades feed with a five-second idle bound."""
        okx = venue == "okx"
        return CaptureConfig(
            venue=venue,
            symbol="BTC-USDT" if okx else "tBTCUSD",
            instrument_id=InstrumentId(
                UUID(
                    "00000000-0000-4000-8000-000000000001"
                    if okx
                    else "00000000-0000-4000-8000-000000000002"
                )
            ),
            base_currency="BTC",
            quote_currency="USDT" if okx else "USD",
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

    @classmethod
    def request(cls, venue: Literal["okx", "bitfinex"]) -> CaptureRequest:
        """Bind the feed to a recording whose research universe includes its instrument."""
        config = cls.config(venue)
        selected = (config.instrument_id,)
        return CaptureRequest(
            config=config,
            recording_id="00000000-0000-0000-0000-000000000011"
            if venue == "okx"
            else "00000000-0000-0000-0000-000000000012",
            implementation_identity="a" * 64,
            universes=UniverseSelection(
                collection=selected, research=selected, strategy=(), authorized_trading=()
            ),
        )

    @staticmethod
    def ns(at: datetime) -> int:
        """Return exact Unix nanoseconds of a UTC instant."""
        return (at - _EPOCH) // timedelta(microseconds=1) * 1000

    @staticmethod
    def okx(trade_id: int, at: datetime, size: str, side: str, price: str = "100") -> bytes:
        """Encode one OKX trade at venue time ``at``."""
        return DomainCodec().encode_json(
            {
                "arg": {"channel": "trades", "instId": "BTC-USDT"},
                "data": [
                    {
                        "instId": "BTC-USDT",
                        "tradeId": str(trade_id),
                        "ts": str((at - _EPOCH) // timedelta(milliseconds=1)),
                        "px": price,
                        "sz": size,
                        "side": side,
                        "count": "1",
                    }
                ],
            }
        )

    @classmethod
    def records(cls, venue: Literal["okx", "bitfinex"]) -> tuple[tuple[Kind, datetime, bytes], ...]:
        """Author two sessions separated by a gap, with trades, idle time and an end."""
        at = _START
        if venue == "okx":
            first: tuple[tuple[Kind, datetime, bytes], ...] = (
                ("frame", at, _OKX_ACK),
                (
                    "frame",
                    at + timedelta(seconds=1),
                    cls.okx(1, at + timedelta(seconds=1), "0.5", "buy"),
                ),
                (
                    "frame",
                    at + timedelta(seconds=3),
                    cls.okx(2, at + timedelta(seconds=3), "0.2", "sell", "101"),
                ),
                (
                    "frame",
                    at + timedelta(seconds=4),
                    cls.okx(3, at + timedelta(seconds=4), "0.1", "buy"),
                ),
            )
            second: tuple[tuple[Kind, datetime, bytes], ...] = (
                ("frame", at + timedelta(seconds=15), _OKX_ACK),
                (
                    "frame",
                    at + timedelta(seconds=17),
                    cls.okx(4, at + timedelta(seconds=17), "0.3", "sell"),
                ),
                *(("frame", at + timedelta(seconds=s), b"pong") for s in (19, 23, 27)),
            )
        else:
            ms = (at - _EPOCH) // timedelta(milliseconds=1)
            first = (
                ("frame", at, _BITFINEX_CONF),
                ("frame", at, _BITFINEX_SUBSCRIBED),
                (
                    "frame",
                    at + timedelta(seconds=1),
                    f"[7,[[2,{ms + 900},-0.2,101],[1,{ms + 500},0.5,100]],1]".encode(),
                ),
                (
                    "frame",
                    at + timedelta(seconds=4),
                    f'[7,"te",[3,{ms + 4000},0.1,100],2]'.encode(),
                ),
                (
                    "frame",
                    at + timedelta(seconds=4),
                    f'[7,"tu",[3,{ms + 4000},0.1,100],3]'.encode(),
                ),
            )
            # The reconnect snapshot repeats trade 3, which research keeps once.
            second = (
                ("frame", at + timedelta(seconds=15), _BITFINEX_CONF),
                ("frame", at + timedelta(seconds=15), _BITFINEX_SUBSCRIBED),
                (
                    "frame",
                    at + timedelta(milliseconds=15500),
                    f"[7,[[4,{ms + 15200},-0.2,101],[3,{ms + 4000},0.1,100]],1]".encode(),
                ),
                (
                    "frame",
                    at + timedelta(seconds=17),
                    f'[7,"te",[5,{ms + 17000},-0.3,100],2]'.encode(),
                ),
                *(
                    ("frame", at + timedelta(seconds=s), f'[7,"hb",{n}]'.encode())
                    for n, s in ((3, 19), (4, 23), (5, 27))
                ),
            )
        return (
            ("session", at, b""),
            *first,
            ("gap", at + timedelta(seconds=12), b""),
            ("session_end", at + timedelta(seconds=12), b""),
            ("session", at + timedelta(seconds=14), b""),
            *second,
            ("end", at + timedelta(seconds=30), b""),
        )

    @classmethod
    def capture_records(cls, venue: Literal["okx", "bitfinex"]) -> tuple[CaptureRecord, ...]:
        """Number sessions into epochs and encode every record."""
        epoch, records = -1, []
        for kind, at, raw in cls.records(venue):
            epoch += kind == "session"
            records.append(
                CaptureRecord(
                    kind=kind,
                    epoch=epoch,
                    received_ns=cls.ns(at),
                    raw=raw,
                    reason="connection_lost"
                    if kind == "gap"
                    else ("message_limit" if kind == "end" else ""),
                )
            )
        return tuple(records)

    @classmethod
    def capture(cls, root: Path, venue: Literal["okx", "bitfinex"]) -> Path:
        """Write one complete trades capture directory."""
        records = cls.capture_records(venue)
        journal = CaptureJournal(root, cls.request(venue))
        journal.start()
        for record in records:
            journal.append(record)
        journal.finish(records[0].received_ns)
        return root

    @staticmethod
    def requirements(units: str) -> tuple[InputRequirement, ...]:
        """Select every trade field over a ten-second window."""
        return tuple(
            InputRequirement(
                name="trades", family="trade", clock="event", field=field, max_age_us=10_000_000
            )
            for field in (
                NumericField(name="price", units=f"{units}/BTC"),
                NumericField(name="quantity", units="BTC"),
                NumericField(name="signed_quantity", units="BTC"),
                NumericField(name="signed_flow", units="BTC"),
            )
        )


class TestCapturedTrades:
    """Publish, reopen and read captured trades with the live source's rules."""

    @staticmethod
    def publish(root: Path, venue: Literal["okx", "bitfinex"]) -> tuple[Path, RawStore, str]:
        """Publish one trades capture through the single capture path."""
        capture = CapturedTradesFixture.capture(root / venue, venue)
        (root / "raw").mkdir(exist_ok=True)
        (root / "snapshots").mkdir(exist_ok=True)
        raw = RawStore(root / "raw")
        publication = DatasetPublication(SourceAdapters(), "b" * 64).publish_captures(
            (capture,), raw, root / "snapshots", max_records=1000, max_bytes=_LIMIT
        )
        assert publication.books is None and len(publication.trades) == 1
        return root / "snapshots", raw, publication.single

    @pytest.mark.parametrize("venue", ["okx", "bitfinex"])
    def test_live_and_saved_trades_agree_at_every_cutoff(
        self, tmp_path: Path, venue: Literal["okx", "bitfinex"]
    ) -> None:
        """Values and missing fields match across synchronization, a gap and a reconnect."""
        snapshots, raw, identity = self.publish(tmp_path, venue)
        request = CapturedTradesFixture.request(venue)
        entity = str(request.config.instrument_id)
        requirements = CapturedTradesFixture.requirements(request.config.quote_currency)
        query = PublicTradeQuery(
            snapshot_id=identity,
            instruments=(request.config.instrument_id,),
            start=_START - timedelta(minutes=1),
            end=_START + timedelta(minutes=1),
            known_at=_START + timedelta(seconds=40),
            max_bytes=_LIMIT,
        )
        saved = SavedDecisionSource(
            ResearchReader(snapshots, raw, readers=SourceAdapters()),
            ResearchSelection(inputs=(PublicTradeSelection(name="trades", query=query),)),
            requirements,
        )
        live = LiveTradeDecisionSource(
            request, requirements, tapes=BookAdapters.trades, history_capacity=1000
        )
        replay = CaptureReplay(request.config, book_factory=BookAdapters.create)
        records = CapturedTradesFixture.capture_records(venue)
        compared, present = 0, 0
        cutoffs = [_START + timedelta(milliseconds=250 * step) for step in range(4 * 36)]
        index = 0
        for at in cutoffs:
            while index < len(records) and records[index].received_ns <= CapturedTradesFixture.ns(
                at
            ):
                record = records[index]
                live.accept(
                    record, BookProjection.capture(index, record, replay.apply(record), replay)
                )
                index += 1
            live_values = [row.value for row in live.read(entity, at).observations]
            saved_values = [row.value for row in saved.read(entity, at).observations]
            assert saved_values == live_values, at
            compared += 1
            present += sum(value is not None for value in live_values)
        assert compared == len(cutoffs) and present > 0
        # The window that crosses the gap is incomplete, then the new session covers it.
        crossing = _START + timedelta(seconds=17)
        flow = saved.read(entity, crossing).observations[3]
        assert flow.value is None
        assert saved.read(entity, _START + timedelta(seconds=26)).observations[3].value == (
            ExactRatio.from_fraction(Fraction(-3, 10))
        )

    def test_coverage_boundaries_follow_the_live_rule(self, tmp_path: Path) -> None:
        """Coverage opens at synchronization and closes at the gap, session end and end."""
        snapshots, raw, identity = self.publish(tmp_path, "okx")
        manifest = SnapshotStore(
            snapshots, raw, readers=SourceAdapters(), manifest_type=PublicTradeManifest
        ).read(identity, max_bytes=_LIMIT)
        partition = manifest.partitions[0]
        history = DomainCodec().decode_json(
            (snapshots / identity / partition.sha256).read_bytes(), PublicTradeHistory
        )
        ns = CapturedTradesFixture.ns
        opened = [boundary.covered_from_ns for boundary in history.boundaries]
        reopened = ns(_START + timedelta(seconds=15))
        assert opened == [None, *[ns(_START)] * 4, None, None, None, *[reopened] * 5, None]
        assert [row.trade.trade_id for row in history.observations] == ["1", "2", "3", "4"]
        assert all(row.capture is not None and row.receipt is None for row in history.observations)

    def test_cli_publishes_books_and_trades_together(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``alpha-dataset capture-publish`` names each snapshot, and discovery lists it."""
        capture = CapturedTradesFixture.capture(tmp_path / "okx", "okx")
        (tmp_path / "raw").mkdir()
        (tmp_path / "snapshots").mkdir()
        assert (
            dataset_main(
                [
                    "capture-publish",
                    "--captures",
                    str(capture),
                    "--store",
                    str(tmp_path / "raw"),
                    "--snapshots",
                    str(tmp_path / "snapshots"),
                    "--max-records",
                    "1000",
                    "--max-bytes",
                    str(_LIMIT),
                ]
            )
            == 0
        )
        published = msgspec.json.decode(capsys.readouterr().out, type=dict[str, object])
        assert published["status"] == "complete"
        assert (
            dataset_main(
                [
                    "discover",
                    "--snapshots",
                    str(tmp_path / "snapshots"),
                    "--max-entries",
                    "10",
                    "--max-bytes",
                    str(_LIMIT),
                ]
            )
            == 0
        )
        assert '"public-trades"' in capsys.readouterr().out

    def test_published_history_must_equal_its_replay(self, tmp_path: Path) -> None:
        """An audit refuses a snapshot when the tape replay differs from the retained history.

        A plain reopen checks digests only, so it reads the history as published.
        """
        snapshots, raw, identity = self.publish(tmp_path, "okx")
        store = SnapshotStore(
            snapshots, raw, readers=_DroppingReaders(), manifest_type=PublicTradeManifest
        )
        assert store.read(identity, max_bytes=_LIMIT).identity == identity
        with pytest.raises(ValueError, match="differs from retained source"):
            store.read(identity, max_bytes=_LIMIT, rederive=True)

    def test_trades_capture_requires_declared_universes(self, tmp_path: Path) -> None:
        """A captured trades partition cannot be published without its universes."""
        request = msgspec.structs.replace(CapturedTradesFixture.request("okx"), universes=None)
        journal = CaptureJournal(tmp_path / "capture", request)
        journal.start()
        records = CapturedTradesFixture.capture_records("okx")
        for record in records:
            journal.append(record)
        journal.finish(records[0].received_ns)
        (tmp_path / "raw").mkdir()
        (tmp_path / "snapshots").mkdir()
        with pytest.raises(ValueError, match="declared universes"):
            DatasetPublication(SourceAdapters(), "b" * 64).publish_captures(
                (tmp_path / "capture",),
                RawStore(tmp_path / "raw"),
                tmp_path / "snapshots",
                max_records=1000,
                max_bytes=_LIMIT,
            )


class _DroppingReaders(SourceAdapters):
    """Replay a trades capture but lose its last trade, as a changed decoder would."""

    @staticmethod
    def trades(selection: CaptureInput, store: ByteReader) -> Iterator[CapturedTrades]:
        """Yield the true replay with the final trade removed."""
        messages = list(SourceAdapters.trades(selection, store))
        last = max(index for index, item in enumerate(messages) if item.trades)
        messages[last] = msgspec.structs.replace(messages[last], trades=messages[last].trades[:-1])
        yield from messages
