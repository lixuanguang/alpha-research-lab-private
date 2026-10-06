"""Verify the live feature publisher follows growing journals on their receipt clocks."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from pathlib import Path

# third party library imports
import pytest

# project library imports
from applications.execute.feature_publisher import StreamSchedule
from configuration import CaptureConfig
from market_data.adapters.sources import BookAdapters
from market_data.books import BookProjection, CaptureReplay
from market_data.contracts import CaptureRecord, CaptureRequest
from market_data.storage import CaptureJournal, CaptureRecording, RecordingFollower
from research.features import FeatureAccessError
from research.observations import (
    DecisionInputs,
    DecisionSource,
    InputRequirement,
    LiveBookDecisionSource,
    NumericField,
    NumericHistorySource,
)
from runtime.live_inputs import FollowedFeed, LiveInputs
from serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_AT = datetime(2025, 1, 1, tzinfo=UTC)
_BASE_NS = int(_AT.timestamp()) * 1_000_000_000


class OKXJournal:
    """Author a growing OKX books journal whose records arrive at chosen receipt offsets."""

    def __init__(self, root: Path, recording_id: str) -> None:
        """Start a fresh single-journal recording with a session and acknowledgement."""
        self.request = CaptureRequest(
            config=CaptureConfig.read(_ROOT / "configs/live/okx-btc-usdt.json"),
            recording_id=recording_id,
            implementation_identity="a" * 64,
        )
        self.journal = CaptureJournal(root / recording_id / recording_id, self.request)
        self.journal.start()
        self.sequence = 1
        self.records: list[CaptureRecord] = []
        self.append(CaptureRecord(kind="session", epoch=0, received_ns=_BASE_NS))
        self.append(
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=_BASE_NS + 1,
                raw=b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}',
            )
        )

    def append(self, record: CaptureRecord) -> None:
        """Durably append one record."""
        self.journal.append(record)
        self.records.append(record)

    def clock(self, milliseconds: int) -> None:
        """Append an idle clock at a receipt offset."""
        self.append(
            CaptureRecord(kind="clock", epoch=0, received_ns=_BASE_NS + milliseconds * 1_000_000)
        )

    def book(self, milliseconds: int, bid: str) -> None:
        """Append a snapshot first, then single-level bid updates, at a receipt offset."""
        action = "snapshot" if self.sequence == 1 else "update"
        asks = [["60001.5", "2", "0", "1"]] if action == "snapshot" else []
        payload = {
            "arg": {"channel": "books", "instId": "BTC-USDT"},
            "action": action,
            "data": [
                {
                    "seqId": self.sequence,
                    "prevSeqId": -1 if action == "snapshot" else self.sequence - 1,
                    "ts": str(int(_AT.timestamp()) * 1000 + milliseconds),
                    "bids": [["60000.5", bid, "0", "1"]],
                    "asks": asks,
                    "checksum": 0,
                }
            ],
        }
        self.sequence += 1
        self.append(
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=_BASE_NS + milliseconds * 1_000_000,
                raw=DomainCodec().encode_json(payload),
            )
        )

    @property
    def recording(self) -> CaptureRecording:
        """Reopen the recording as a consumer does."""
        return CaptureRecording.read(self.journal.root)

    @staticmethod
    def requirement(name: str) -> InputRequirement:
        """Name one receipt-clock touch imbalance input."""
        return InputRequirement(
            name=name,
            family="book",
            clock="receipt",
            field=NumericField(name="imbalance", units="dimensionless"),
            max_age_us=30_000_000,
        )

    def feed(self, name: str) -> FollowedFeed:
        """Follow a journal into a fresh live book source."""
        source = LiveBookDecisionSource(
            self.request, (OKXJournal.requirement(name),), history_capacity=1000
        )
        return FollowedFeed(
            RecordingFollower(self.recording), source, natives=BookAdapters.create, batch=2
        )

    def saved(self, name: str, cutoffs: tuple[datetime, ...]) -> list[DecisionInputs]:
        """Reconstruct the whole saved journal on receipt clocks and read each cutoff."""
        source = LiveBookDecisionSource(
            self.request, (OKXJournal.requirement(name),), history_capacity=1000
        )
        replay = CaptureReplay(self.request.config, book_factory=BookAdapters.create)
        reads: list[DecisionInputs] = []
        pending = list(cutoffs)
        for position, record in enumerate(self.records):
            while (
                pending
                and record.received_ns
                > (pending[0] - _AT) // timedelta(microseconds=1) * 1000 + _BASE_NS
            ):
                reads.append(source.read(_ENTITY, pending.pop(0)))
            source.accept(
                record, BookProjection.capture(position, record, replay.apply(record), replay)
            )
        reads.extend(source.read(_ENTITY, at) for at in pending)
        return reads


class Publication:
    """Record each published cutoff and the joined inputs read at it."""

    def __init__(
        self, inputs: DecisionSource, *, latest: datetime | None = None, failures: int = 0
    ) -> None:
        """Bind the source read at each cutoff and an optional prior snapshot."""
        self.inputs = inputs
        self.published: list[tuple[datetime, DecisionInputs]] = []
        self._latest = latest
        self._failures = failures

    def publish(self, at: datetime) -> None:
        """Read the inputs at ``at``, or fail once per configured failure."""
        if self._failures:
            self._failures -= 1
            raise FeatureAccessError("Feast worker could not complete the request")
        self.published.append((at, self.inputs.read(_ENTITY, at)))

    def latest(self) -> datetime | None:
        """Return the prior snapshot cutoff."""
        return self.published[-1][0] if self.published else self._latest


_ENTITY = str(CaptureConfig.read(_ROOT / "configs/live/okx-btc-usdt.json").instrument_id)


class TestLiveInputs:
    """Join sources into one ordered projection and replay followed journals exactly."""

    def test_joined_sources_answer_requirements_in_declared_order(self) -> None:
        """Each requirement comes from the source declaring it; undeclared ones are refused."""
        first, second = OKXJournal.requirement("first"), OKXJournal.requirement("second")
        history = NumericHistorySource((), (second,))
        book = NumericHistorySource((), (first,))
        joined = LiveInputs((second, first), (book, history))
        read = joined.read(_ENTITY, _AT)
        assert tuple(row.input for row in read.observations) == (second, first)
        assert joined.identity == LiveInputs((second, first), (book, history)).identity
        assert joined.identity != LiveInputs((first, second), (book, history)).identity
        for requirements in ((), (first, first), (first, OKXJournal.requirement("third"))):
            with pytest.raises(ValueError, match="distinct requirements"):
                LiveInputs(requirements, (book, history))

    def test_followed_feed_equals_saved_receipt_reconstruction(self, tmp_path: Path) -> None:
        """Following a journal while it grows reads what its saved reconstruction reads."""
        journal = OKXJournal(tmp_path, "00000000-0000-4000-8000-000000000061")
        feed = journal.feed("book")
        journal.book(100, "1")
        while feed.next_available_at() is not None:
            feed.accept()
        journal.book(1500, "3")
        journal.book(2500, "5")
        while feed.next_available_at() is not None:
            feed.accept()
        cutoffs = (_AT, _AT + timedelta(seconds=1), _AT + timedelta(seconds=2))
        assert [feed.source.read(_ENTITY, at) for at in cutoffs] == journal.saved("book", cutoffs)
        assert not feed.finished
        journal.journal.finish(_BASE_NS)
        assert feed.finished and feed.accepted == len(journal.records)
        with pytest.raises(ValueError, match="no durable record pending"):
            feed.accept()


class TestStreamSchedule:
    """Publish grid instants only once every followed feed has passed them."""

    @staticmethod
    def _schedule(
        tmp_path: Path, publication_latest: datetime | None = None, *, failures: int = 0
    ) -> tuple[StreamSchedule, Publication, OKXJournal, OKXJournal]:
        """Follow two growing journals into one joined source on a one-second grid."""
        book = OKXJournal(tmp_path / "book", "00000000-0000-4000-8000-000000000062")
        other = OKXJournal(tmp_path / "other", "00000000-0000-4000-8000-000000000063")
        feeds = (book.feed("book"), other.feed("other"))
        inputs = LiveInputs(
            (OKXJournal.requirement("book"), OKXJournal.requirement("other")),
            tuple(feed.source for feed in feeds),
        )
        publication = Publication(inputs, latest=publication_latest, failures=failures)
        schedule = StreamSchedule(
            publication,
            feeds,
            starts_at=_AT,
            cadence=timedelta(seconds=1),
            max_lag=timedelta(seconds=5),
        )
        return schedule, publication, book, other

    def test_instants_publish_after_every_feed_passes_them(self, tmp_path: Path) -> None:
        """Inputs at each published instant equal both journals' saved reconstruction."""
        schedule, publication, book, other = self._schedule(tmp_path)
        book.book(100, "1")
        book.book(2100, "2")
        other.book(200, "4")
        assert schedule.advance(_AT + timedelta(seconds=3))
        assert [at for at, _ in publication.published] == [_AT]
        other.book(2500, "6")
        assert schedule.advance(_AT + timedelta(seconds=3))
        cutoffs = (_AT, _AT + timedelta(seconds=1), _AT + timedelta(seconds=2))
        assert [at for at, _ in publication.published] == list(cutoffs)
        expected = zip(book.saved("book", cutoffs), other.saved("other", cutoffs), strict=True)
        assert [inputs.observations for _, inputs in publication.published] == [
            (first.observations[0], second.observations[0]) for first, second in expected
        ]
        assert not schedule.advance(_AT + timedelta(seconds=3))
        assert (schedule.published, schedule.skipped, schedule.next_at) == (
            3,
            0,
            _AT + timedelta(seconds=3),
        )

    def test_unpassed_instants_are_skipped_beyond_the_lag(self, tmp_path: Path) -> None:
        """A quiet feed holds publication, then instants older than the lag are skipped."""
        schedule, publication, book, other = self._schedule(tmp_path)
        book.book(100, "1")
        other.book(200, "4")
        book.book(20_100, "2")
        assert schedule.advance(_AT + timedelta(seconds=20))
        assert [at for at, _ in publication.published] == []
        assert schedule.skipped == 15 and schedule.next_at == _AT + timedelta(seconds=15)
        other.book(16_500, "6")
        assert schedule.advance(_AT + timedelta(seconds=20))
        assert [at for at, _ in publication.published] == [
            _AT + timedelta(seconds=15),
            _AT + timedelta(seconds=16),
        ]

    def test_a_quiet_feed_passes_instants_on_its_clocks(self, tmp_path: Path) -> None:
        """Clocks on a quiet feed let each instant publish with the saved inputs."""
        schedule, publication, book, other = self._schedule(tmp_path)
        book.book(100, "1")
        other.book(200, "4")
        book.book(2_100, "2")
        assert schedule.advance(_AT + timedelta(seconds=3))
        assert [at for at, _ in publication.published] == [_AT]
        for milliseconds in (450, 700, 950, 1_200, 1_450, 1_700, 1_950, 2_200):
            other.clock(milliseconds)
        assert schedule.advance(_AT + timedelta(seconds=3))
        cutoffs = (_AT, _AT + timedelta(seconds=1), _AT + timedelta(seconds=2))
        assert [at for at, _ in publication.published] == list(cutoffs)
        expected = zip(book.saved("book", cutoffs), other.saved("other", cutoffs), strict=True)
        assert [inputs.observations for _, inputs in publication.published] == [
            (first.observations[0], second.observations[0]) for first, second in expected
        ]
        assert publication.published[-1][1].observations[1].value is not None

    def test_failed_publication_is_retried(self, tmp_path: Path) -> None:
        """A failed publication keeps its instant due until it succeeds."""
        schedule, publication, book, other = self._schedule(tmp_path, failures=1)
        book.book(100, "1")
        other.book(1200, "4")
        book.book(3100, "2")
        other.book(3200, "6")
        assert schedule.advance(_AT + timedelta(seconds=4)) is True
        assert schedule.failures == 1 and schedule.last_error is not None
        assert publication.published == []
        schedule.advance(_AT + timedelta(seconds=4))
        assert [at for at, _ in publication.published] == [
            _AT + timedelta(seconds=second) for second in range(4)
        ]

    def test_restart_starts_after_the_streams_latest_snapshot(self, tmp_path: Path) -> None:
        """Records before the latest snapshot rebuild state without republishing."""
        schedule, publication, book, other = self._schedule(
            tmp_path, publication_latest=_AT + timedelta(seconds=1)
        )
        book.book(100, "1")
        other.book(200, "4")
        book.book(3100, "2")
        other.book(3200, "6")
        schedule.advance(_AT + timedelta(seconds=4))
        assert [at for at, _ in publication.published] == [
            _AT + timedelta(seconds=2),
            _AT + timedelta(seconds=3),
        ]

    def test_schedule_finishes_with_its_recordings(self, tmp_path: Path) -> None:
        """Completed, fully accepted recordings end the schedule."""
        schedule, _, book, other = self._schedule(tmp_path)
        book.book(100, "1")
        other.book(200, "4")
        schedule.advance(_AT + timedelta(seconds=1))
        assert not schedule.finished
        book.journal.finish(_BASE_NS)
        other.journal.finish(_BASE_NS)
        schedule.advance(_AT + timedelta(seconds=1))
        assert schedule.finished
