"""Protect causal cutoff projection, scoped controls and retained revision history."""

from __future__ import annotations

# standard library imports
import time
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

# third party library imports
import msgspec
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from configuration import Configuration
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.providers.binance import ArchiveRow, BinanceArchiveTrades
from market_data.adapters.providers.tardis import TardisDecoder
from market_data.adapters.sources import SourceAdapters
from market_data.adapters.venues.binance import BinancePayloadDecoder
from market_data.contracts import (
    ArchiveTrade,
    Disconnect,
    Occurrence,
    RawObject,
    SourceRequest,
    Trade,
)
from market_data.datasets import DatasetPublication
from market_data.query import AsOfSelector, InputBinding, PointEvent, QueryReader
from market_data.storage import RawFiles, RawStore
from market_data.validation import Correction, QualityPolicy, TradeRevision
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import EligibilityAssertions
from runtime import ImplementationIdentity
from serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_WIRE: msgspec.json.Decoder[dict[str, object]] = msgspec.json.Decoder(dict[str, object])
_START = datetime(2024, 6, 1, tzinfo=UTC)
_LIMIT = 262_144


class TestAsOfSelector:
    """Use admitted synthetic bytes and actual published archives at the public boundary."""

    @staticmethod
    def _request(*, archive: bool = False, instrument: int = 0, minute: int = 0) -> SourceRequest:
        """Resolve retained configuration, selecting one instrument's partition by minute."""
        name = "binance-archive" if archive else "fixture-inspection"
        catalog_name = "binance-archive-spot" if archive else "binance-spot"
        config = Configuration.read(_ROOT / f"configs/data-jobs/{name}.json")
        catalog = _CODEC.decode_json(
            (_ROOT / f"configs/reference/{catalog_name}.json").read_bytes(), CatalogSnapshot
        )
        run = config.resolve(
            config.jobs[0].name, catalog, implementation_identity=ImplementationIdentity.sha256()
        )
        return SourceRequest.partition(
            replace(run, instruments=(catalog.instruments[instrument],))
        )[minute]

    @staticmethod
    def _history(request: SourceRequest) -> EligibilityAssertions:
        """Bind the maintained synthetic bitemporal history to the selected catalog."""
        history = _CODEC.decode_json(
            (_ROOT / "tests/fixtures/eligibility/membership-corrections.json").read_bytes(),
            EligibilityAssertions,
        )
        return replace(history, catalog=request.manifest.catalog)

    @staticmethod
    def _binding(request: SourceRequest) -> InputBinding:
        """Declare source/stream/subscription precedence explicitly."""
        return (
            request.instrument.source,
            request.manifest.job.stream,
            request.instrument.instrument_id,
        )

    @staticmethod
    def _item(
        request: SourceRequest,
        *,
        position: int = 0,
        capture: int = 1,
        price: str = "100.00",
        trade_id: int = 12,
        digest: str = "a" * 64,
        disconnect: bool = False,
    ) -> Occurrence:
        """Decode captured or archive bytes without synthesizing archive knowledge."""
        instant = _START + timedelta(seconds=capture)
        if request.manifest.job.provider == "binance-archive":
            raw = f"{trade_id},{price},2.0,200,1717200000000,true,true\n".encode()
        elif disconnect:
            raw = b"\n"
        else:
            symbol = request.instrument.symbol
            envelope = {
                "stream": f"{symbol.lower()}@trade",
                "data": {
                    "e": "trade",
                    "E": 1717200000000,
                    "T": 1717200000000,
                    "s": symbol,
                    "t": trade_id,
                    "p": price,
                    "q": "2.0",
                    "m": True,
                },
            }
            raw = (
                instant.isoformat().replace("+00:00", "Z").encode()
                + b" "
                + _CODEC.encode_json(envelope)
                + b"\n"
            )
        origin = RawObject(
            sha256=digest,
            size_bytes=4096,
            request_identity=request.identity,
            retrieval_reference="synthetic:mr17",
            ts_received=_START + timedelta(days=1),
            ts_ingested=_START + timedelta(days=1),
        )
        event: ArchiveTrade | Trade | Disconnect
        if request.manifest.job.provider == "binance-archive":
            event = BinanceArchiveTrades.from_row(
                ArchiveRow(
                    origin=origin,
                    position=position,
                    payload=raw,
                    selection_start=request.manifest.job.start,
                    selection_end=request.manifest.job.end,
                ),
                request,
            )
        else:
            decoder = TardisDecoder(
                BinancePayloadDecoder(request.manifest.instruments), request.instrument.source
            )
            decoded = decoder.decode_line(
                raw.decode().rstrip("\n"),
                source_sequence=position,
                local_received=origin.ts_received,
                local_ingested=origin.ts_ingested,
                source_digest=origin.sha256,
                disconnect_capture_time=instant,
            )
            assert isinstance(decoded, (Trade, Disconnect))
            event = decoded
        return Occurrence(request=request, origin=origin, position=position, raw=raw, event=event)

    @staticmethod
    def _correction(original: Occurrence, revised: Occurrence) -> Correction:
        """Keep publication distinct from later usable availability."""
        return Correction(
            supersedes=TradeRevision(occurrences=(original,)).identity,
            replacement=TradeRevision(occurrences=(revised,)).identity,
            ts_published=_START + timedelta(seconds=5),
            ts_available=_START + timedelta(seconds=10),
            evidence_reference="synthetic:mr17:correction",
        )

    def _canonical(
        self,
        request: SourceRequest,
        items: tuple[Occurrence, ...],
        *,
        corrections: tuple[Correction, ...] = (),
        history: EligibilityAssertions | None = None,
    ) -> bytes:
        """Generate canonical bytes through the existing complete quality admission."""
        return (
            QualityPolicy(use="exploratory", known_at=_START, max_gap=timedelta(hours=1))
            .validate(
                request,
                items,
                verifier=SourceAdapters.verifier(request),
                eligibility=self._history(request) if history is None else history,
                corrections=corrections,
            )
            .require_canonical()
        )

    @staticmethod
    def _select(
        selector: AsOfSelector, request: SourceRequest, seconds: int = 10
    ) -> tuple[PointEvent, ...]:
        """Query the entire business partition at an independent cutoff."""
        return selector.select(
            (request.instrument.instrument_id,),
            start=request.start,
            end=request.end,
            known_at=_START + timedelta(seconds=seconds),
        )

    def test_capture_correction_publication_and_earlier_reconstruction(self) -> None:
        """Filter effective availability before choosing the revision and retain original clocks."""
        request = self._request()
        original = self._item(request)
        revised = self._item(request, price="101.00", capture=2, digest="b" * 64)
        canonical = self._canonical(
            request, (original, revised), corrections=(self._correction(original, revised),)
        )
        selector = AsOfSelector(
            (canonical,), readers=SourceAdapters(), precedence=(self._binding(request),)
        )
        assert self._select(selector, request, 0) == ()
        for cutoff in (1, 5, 9):
            selected = self._select(selector, request, cutoff)
            assert isinstance(selected[0], TradeRevision)
            assert isinstance(selected[0].occurrences[0].event, Trade)
            assert selected[0].occurrences[0].event.price == Decimal("100.00")
        selected = self._select(selector, request)
        assert isinstance(selected[0], TradeRevision)
        assert isinstance(selected[0].occurrences[0].event, (Trade, ArchiveTrade))
        assert selected[0].occurrences[0].event.price == Decimal("101.00")
        assert selected[0].previous is not None
        assert not isinstance(selected[0].occurrences[0].event, ArchiveTrade)
        assert selected[0].occurrences[0].event.provenance.ts_knowledge == _START + timedelta(
            seconds=2
        )
        assert selector.history == (canonical,)
        assert self._select(selector, request, 1) == (selected[0].previous,)
        force_setattr(selected[0], "schema_version", "unsafe")
        assert self._select(selector, request)[0] != selected[0]

    def test_business_filter_after_revision_selection_has_no_old_value_fallback(self) -> None:
        """A known correction moved beyond the business window retires its earlier version."""
        request = self._request()
        original = self._item(request)
        revised = self._item(request, capture=20, price="101.00", digest="b" * 64)
        selector = AsOfSelector(
            (
                self._canonical(
                    request, (original, revised), corrections=(self._correction(original, revised),)
                ),
            ),
            readers=SourceAdapters(),
            precedence=(self._binding(request),),
        )
        for cutoff, count in ((10, 1), (20, 0)):
            result = selector.select(
                (request.instrument.instrument_id,),
                start=_START + timedelta(seconds=1),
                end=_START + timedelta(seconds=20),
                known_at=_START + timedelta(seconds=cutoff),
            )
            assert len(result) == count

    def test_window_keeps_exactly_the_whole_selection_valid_inside_it(self) -> None:
        """Windows filter the unwindowed selection, even when a correction moves a trade."""
        first, second = self._request(), self._request(minute=1)
        original = self._item(first, trade_id=25, capture=5, position=1)
        moved = self._item(first, trade_id=25, capture=40, price="101.00", digest="b" * 64)
        payloads = (
            self._canonical(
                first,
                (
                    self._item(first, trade_id=21, capture=1, position=0),
                    original,
                    self._item(first, trade_id=22, capture=10, position=2),
                    self._item(first, capture=20, position=3, disconnect=True),
                    self._item(first, trade_id=23, capture=30, position=4),
                    moved,
                    self._item(first, trade_id=24, capture=59, position=5),
                ),
                corrections=(self._correction(original, moved),),
            ),
            self._canonical(
                second,
                (
                    self._item(second, trade_id=31, capture=60, position=0),
                    self._item(second, trade_id=32, capture=90, position=1),
                    self._item(second, capture=100, position=2, disconnect=True),
                ),
            ),
        )
        selector = AsOfSelector(
            payloads, readers=SourceAdapters(), precedence=(self._binding(first),)
        )
        instruments = (first.instrument.instrument_id,)
        edges = tuple(
            _START + timedelta(seconds=second)
            for second in sorted(set(range(0, 121, 10)) | {1, 5, 39, 41, 59, 61, 99, 101})
        )
        selected_instants: set[datetime] = set()
        for known in (0, 5, 10, 39, 40, 100):
            known_at = _START + timedelta(seconds=known)
            whole = selector.select(
                instruments,
                start=_START - timedelta(days=1),
                end=_START + timedelta(days=1),
                known_at=known_at,
            )
            for start in edges:
                for end in edges[edges.index(start) + 1 :]:
                    # Controls keep no left edge; a revision's selected version must be inside.
                    expected = tuple(
                        item
                        for item in whole
                        if (
                            self._instant(item) <= end
                            if isinstance(item, Occurrence)
                            else start <= self._instant(item) < end
                        )
                    )
                    assert (
                        selector.select(instruments, start=start, end=end, known_at=known_at)
                        == expected
                    )
            selected_instants.update(
                self._instant(item) for item in whole if isinstance(item, TradeRevision)
            )
        # The corrected trade is selected at each of its two instants under some cutoff.
        assert {_START + timedelta(seconds=5), _START + timedelta(seconds=40)} <= selected_instants

    @staticmethod
    def _instant(item: PointEvent) -> datetime:
        """Return a captured control's or revision's earliest business instant."""
        occurrences = (item,) if isinstance(item, Occurrence) else item.occurrences
        instants = [
            occurrence.event.provenance.valid_from
            for occurrence in occurrences
            if isinstance(occurrence.event, (Trade, Disconnect))
        ]
        assert len(instants) == len(occurrences)
        return min(instants)

    @pytest.mark.performance
    def test_trailing_window_selection_ignores_older_partitions(self) -> None:
        """A fixed trailing window costs about the same however much history precedes it."""
        medians: list[float] = []
        for minutes in (15, 60):
            payloads = tuple(
                self._canonical(
                    request,
                    tuple(
                        self._item(
                            request,
                            trade_id=minute * 6 + index,
                            capture=minute * 60 + index * 10,
                            position=index,
                        )
                        for index in range(6)
                    ),
                )
                for minute in range(minutes)
                for request in (self._request(minute=minute),)
            )
            request = self._request()
            selector = AsOfSelector(
                payloads, readers=SourceAdapters(), precedence=(self._binding(request),)
            )
            end = _START + timedelta(minutes=minutes - 1, seconds=30)
            samples: list[float] = []
            for _ in range(9):
                started = time.perf_counter()
                selected = selector.select(
                    (request.instrument.instrument_id,),
                    start=end - timedelta(minutes=5),
                    end=end,
                    known_at=end,
                )
                samples.append(time.perf_counter() - started)
            assert len(selected) == 30
            medians.append(sorted(samples)[4])
        print(f"trailing selection at 15/60 minute partitions: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Walking and re-validating every earlier revision grew with the partition count.
        assert medians[1] < 2 * medians[0]

    @pytest.mark.performance
    def test_history_query_adds_no_cost_per_older_partition(self) -> None:
        """History mode's extra cost over cutoff mode does not grow with earlier partitions."""
        extras: list[float] = []
        for minutes in (15, 60):
            payloads = tuple(
                self._canonical(
                    request,
                    tuple(
                        self._item(
                            request,
                            trade_id=minute * 6 + index,
                            capture=minute * 60 + index * 10,
                            position=index,
                        )
                        for index in range(6)
                    ),
                )
                for minute in range(minutes)
                for request in (self._request(minute=minute),)
            )
            request = self._request()
            reader = QueryReader(
                payloads,
                readers=SourceAdapters(),
                precedence=(self._binding(request),),
                max_bytes=1_000_000_000,
            )
            end = _START + timedelta(minutes=minutes - 1, seconds=30)
            medians: dict[Literal["cutoff", "history"], float] = {}
            modes: tuple[Literal["cutoff", "history"], ...] = ("cutoff", "history")
            for mode in modes:
                samples: list[float] = []
                for _ in range(9):
                    started = time.perf_counter()
                    rows = [
                        row
                        for batch in reader.batches(
                            (request.instrument.instrument_id,),
                            start=end - timedelta(minutes=5),
                            end=end,
                            known_at=end,
                            columns=("identity", "revision"),
                            batch_size=1000,
                            mode=mode,
                        )
                        for row in batch.rows
                    ]
                    samples.append(time.perf_counter() - started)
                assert len(rows) == 30
                medians[mode] = sorted(samples)[4]
            extras.append(medians["history"] - medians["cutoff"])
        print(f"history extra at 15/60 minute partitions: {extras[0]:.6f}s/{extras[1]:.6f}s")
        # Walking every chain and re-validating each revision grew with the partition count.
        assert extras[1] < 1.8 * extras[0]

    def test_equal_captures_source_order_future_duplicates_and_digest_changes(self) -> None:
        """Equal-time order follows raw position, never trade ID, payload or whole-file hashes."""
        request = self._request()
        first = self._item(request, trade_id=99)
        second = self._item(request, trade_id=1, position=1)
        baseline = AsOfSelector(
            (self._canonical(request, (first, second)),),
            readers=SourceAdapters(),
            precedence=(self._binding(request),),
        )
        future_duplicate = self._item(request, trade_id=1, position=0, capture=30, digest="b" * 64)
        future = self._item(request, trade_id=123, position=1, capture=31, digest="b" * 64)
        changed = AsOfSelector(
            (self._canonical(request, (first, second, future_duplicate, future)),),
            readers=SourceAdapters(),
            precedence=(self._binding(request),),
        )
        for selector in (baseline, changed):
            assert [
                r.key[-1]
                for r in self._select(selector, request, 1)
                if isinstance(r, TradeRevision)
            ] == [99, 1]
            narrow = selector.select(
                (request.instrument.instrument_id,),
                start=_START + timedelta(seconds=1),
                end=_START + timedelta(seconds=2),
                known_at=_START + timedelta(seconds=1),
            )
            assert [r.key[-1] for r in narrow if isinstance(r, TradeRevision)] == [99, 1]
        rehashed = tuple(
            self._item(request, trade_id=t, position=i, digest="c" * 64)
            for i, t in enumerate((99, 1))
        )
        other = AsOfSelector(
            (self._canonical(request, rehashed),),
            readers=SourceAdapters(),
            precedence=(self._binding(request),),
        )
        assert [r.identity for r in self._select(other, request, 1)] == [
            r.identity for r in self._select(baseline, request, 1)
        ]

    def test_scoped_disconnects_boundary_state_and_explicit_binding_precedence(self) -> None:
        """Instrument-less controls affect only their binding and survive the query's left edge."""
        btc, eth = self._request(), self._request(instrument=1)
        payloads = tuple(
            self._canonical(
                request, (self._item(request), self._item(request, position=1, disconnect=True))
            )
            for request in (btc, eth)
        )
        precedence = (self._binding(eth), self._binding(btc))
        selector = AsOfSelector(payloads, readers=SourceAdapters(), precedence=precedence)
        selected = selector.select(
            (btc.instrument.instrument_id,),
            start=_START + timedelta(seconds=2),
            end=btc.end,
            known_at=_START + timedelta(seconds=1),
        )
        assert len(selected) == 1 and isinstance(selected[0], Occurrence)
        assert isinstance(selected[0].event, Disconnect) and selected[0].event.instrument_id is None
        assert selected[0].request == btc
        both = selector.select(
            (btc.instrument.instrument_id, eth.instrument.instrument_id),
            start=_START,
            end=btc.end,
            known_at=_START + timedelta(seconds=1),
        )
        assert [
            r.key[2] if isinstance(r, TradeRevision) else r.request.instrument.instrument_id
            for r in both
        ] == [eth.instrument.instrument_id] * 2 + [btc.instrument.instrument_id] * 2
        assert self._select(selector, btc, 0) == ()
        terminal = self._item(btc, position=2, capture=60, disconnect=True, digest="c" * 64)
        terminal_selector = AsOfSelector(
            (self._canonical(btc, (self._item(btc), terminal)),),
            readers=SourceAdapters(),
            precedence=(self._binding(btc),),
        )
        assert len(self._select(terminal_selector, btc, 59)) == 1
        assert len(self._select(terminal_selector, btc, 60)) == 2

    def test_invalid_instruments_and_recovery(self) -> None:
        """Unknown, repeated and empty instrument selections fail without retaining query state."""
        request, other = self._request(), self._request(instrument=1)
        selector = AsOfSelector(
            (self._canonical(request, (self._item(request),)),),
            readers=SourceAdapters(),
            precedence=(self._binding(request),),
        )
        for instruments in (
            (),
            (other.instrument.instrument_id,),
            (request.instrument.instrument_id, request.instrument.instrument_id),
        ):
            with pytest.raises(ValueError, match="unique supported"):
                selector.select(instruments, start=request.start, end=request.end, known_at=_START)
        assert len(self._select(selector, request)) == 1

    def test_future_universe_changes_unknown_and_half_open_validity(self) -> None:
        """Known exclusions and withdrawn validity cannot rewrite an earlier included universe."""
        request = self._request()
        history = self._history(request)
        original = self._canonical(
            request,
            (self._item(request),),
            history=replace(history, assertions=history.assertions[:-1]),
        )
        corrected = self._canonical(request, (self._item(request),), history=history)
        for payload in (original, corrected):
            selector = AsOfSelector(
                (payload,), readers=SourceAdapters(), precedence=(self._binding(request),)
            )
            assert len(self._select(selector, request, 1)) == 1
        assert self._select(selector, request, 12 * 3600) == ()
        unknown = AsOfSelector(
            (
                self._canonical(
                    request, (self._item(request),), history=replace(history, assertions=())
                ),
            ),
            readers=SourceAdapters(),
            precedence=(self._binding(request),),
        )
        assert self._select(unknown, request) == () and b'"unknown"' in unknown.history[0]
        endpoint = replace(history.assertions[0], valid_to=_START + timedelta(seconds=1))
        excluded = self._canonical(
            request,
            (self._item(request),),
            history=replace(history, assertions=(endpoint,)),
        )
        assert (
            self._select(
                AsOfSelector(
                    (excluded,), readers=SourceAdapters(), precedence=(self._binding(request),)
                ),
                request,
            )
            == ()
        )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("schema_version", "2"),
            ("scope", "valid"),
            ("reasons", []),
            ("revisions", []),
            ("unknown", True),
        ],
    )
    def test_canonical_tampering_fails_before_selection(self, field: str, value: object) -> None:
        """A recomputed or caller-authored canonical claim cannot bypass admission."""
        request = self._request()
        payload = self._canonical(request, (self._item(request),))
        decoded = _WIRE.decode(payload)
        decoded[field] = value
        with pytest.raises(ValueError):
            AsOfSelector(
                (_CODEC.encode_json(decoded),),
                readers=SourceAdapters(),
                precedence=(self._binding(request),),
            )

    def test_ambiguous_positions_overlaps_and_incomplete_precedence_fail(self) -> None:
        """Competing raw versions and unspecified logical order cannot use hashes to break ties."""
        request = self._request()
        first, second = self._item(request), self._item(request, trade_id=13, digest="b" * 64)
        payload = self._canonical(request, (first, second))
        binding = self._binding(request)
        selector = AsOfSelector((payload,), readers=SourceAdapters(), precedence=(binding,))
        with pytest.raises(ValueError, match="ambiguous economic"):
            self._select(selector, request)
        with pytest.raises(ValueError, match="overlapping"):
            AsOfSelector((payload, payload), readers=SourceAdapters(), precedence=(binding,))
        for precedence in ((), (binding, binding)):
            with pytest.raises(ValueError, match="precedence"):
                AsOfSelector((payload,), readers=SourceAdapters(), precedence=precedence)

    @pytest.mark.parametrize(
        "start,end,cutoff",
        [
            (_START, _START, _START),
            (_START, _START - timedelta(seconds=1), _START),
            (_START, _START + timedelta(seconds=1), datetime(2024, 6, 1)),
            (
                _START,
                _START + timedelta(seconds=1),
                _START.astimezone(timezone(timedelta(hours=1))),
            ),
        ],
    )
    def test_invalid_query_clocks(self, start: datetime, end: datetime, cutoff: datetime) -> None:
        """Require explicit positive business windows and aware UTC decision cutoffs."""
        request = self._request()
        selector = AsOfSelector(
            (self._canonical(request, (self._item(request),)),),
            readers=SourceAdapters(),
            precedence=(self._binding(request),),
        )
        with pytest.raises((ValueError, TypeError)):
            selector.select(
                (request.instrument.instrument_id,), start=start, end=end, known_at=cutoff
            )

    def test_published_archive_unknown_original_and_evidenced_correction(
        self, tmp_path: Path
    ) -> None:
        """Read a snapshot without replacing unknown availability with event time."""
        request = self._request(archive=True)
        source = tmp_path / "source.zip"
        original, revised = self._item(request), self._item(request, position=1, price="101.00")
        with ZipFile(source, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("BTCUSDT-trades-2024-06-01.csv", original.raw + revised.raw)
        raw_directory, snapshots = tmp_path / "raw", tmp_path / "snapshots"
        raw_directory.mkdir()
        snapshots.mkdir()
        raw = RawStore(raw_directory)
        origin = RawFiles.describe(
            source,
            request=request.binding,
            retrieval_reference="synthetic:mr17",
            ts_received=_START + timedelta(days=1),
            ts_ingested=_START + timedelta(days=1),
        )
        raw.publish(source, descriptor=origin, request=request.binding)
        acquisition = AcquisitionManifest(run=request.manifest, completed=(origin,))
        policy = QualityPolicy(use="exploratory", known_at=_START, max_gap=timedelta(hours=1))
        corrections = {acquisition.run.identity: (self._correction(original, revised),)}
        identity = DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).publish(
            (acquisition,),
            raw,
            snapshots,
            max_bytes=_LIMIT,
            policy=policy,
            eligibility=self._history(request),
            corrections=corrections,
        )
        selector = AsOfSelector.read(
            snapshots,
            raw,
            readers=SourceAdapters(),
            identity=identity,
            max_bytes=_LIMIT,
            precedence=(self._binding(request),),
        )
        assert self._select(selector, request, 9) == ()
        selected = self._select(selector, request)
        assert len(selected) == 1 and isinstance(selected[0], TradeRevision)
        assert isinstance(selected[0].occurrences[0].event, (Trade, ArchiveTrade))
        assert selected[0].occurrences[0].event.price == Decimal("101.00")
        assert selected[0].previous is not None and selected[0].previous.ts_knowledge is None
        assert b"original trade availability unknown" in selector.history[0]
        manifest, _ = DatasetPublication(
            SourceAdapters(), ImplementationIdentity.sha256()
        ).assemble(
            (acquisition,),
            raw,
            max_bytes=_LIMIT,
            policy=policy,
            eligibility=self._history(request),
            corrections=corrections,
        )
        assert manifest.identity == identity
        for invalid_id in ("latest", "0" * 64):
            with pytest.raises((ValueError, FileNotFoundError)):
                AsOfSelector.read(
                    snapshots,
                    raw,
                    readers=SourceAdapters(),
                    identity=invalid_id,
                    max_bytes=_LIMIT,
                    precedence=(self._binding(request),),
                )
        canonical = snapshots / identity / manifest.partitions[0].sha256
        canonical.chmod(0o644)
        canonical.write_bytes(b"{}")
        with pytest.raises(ValueError, match="SHA-256"):
            AsOfSelector.read(
                snapshots,
                raw,
                readers=SourceAdapters(),
                identity=identity,
                max_bytes=_LIMIT,
                precedence=(self._binding(request),),
            )
