"""Verify pinned mixed-family access, causal boundaries, missingness and admission failures."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

# third party library imports
import msgspec
import pytest
from msgspec.structs import force_setattr, replace
from test_asof import TestAsOfSelector as _Trades
from test_book_datasets import TestBookDatasets as _Books

# project library imports
from applications.explore import inspect_eda, inspect_experiment
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import BookObservation, CaptureRequest
from market_data.datasets import BookInput, DatasetPublication, SnapshotCatalog
from market_data.query import BookMarketRow, BookQuery, BookQueryReader, QueryMarketRow
from market_data.storage import CaptureJournal, RawFiles, RawStore
from market_data.validation import QualityPolicy
from research.experiments import AttemptStore, TemporalSplit, TimeWindow
from research.exploration import (
    BookResearchInput,
    BookSelection,
    EdaQuery,
    ExplorationStudy,
    ResearchDataset,
    ResearchReader,
    ResearchSelection,
    TradeResearchInput,
    TradeSelection,
)
from research.studies import ClearMLDestination, ClearMLPublication
from serialization import DomainCodec

_LIMIT = 1_048_576
_CODEC = DomainCodec()
_START = datetime(2024, 6, 1, tzinfo=UTC)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class TestResearchAccess:
    """Publish real saved synthetic inputs through native readers and existing quality gates."""

    @staticmethod
    def _selection(root: Path) -> ResearchSelection:
        """Publish an unavailable archive original, evidenced correction and separate OKX book."""
        (root / "raw").mkdir()
        (root / "snapshots").mkdir()
        raw = RawStore(root / "raw")
        publisher = DatasetPublication(SourceAdapters(), "a" * 64)
        request = _Trades._request(archive=True)
        original = _Trades._item(request)
        revised = _Trades._item(request, position=1, price="101.00")
        source = root / "source.zip"
        with ZipFile(source, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("BTCUSDT-trades-2024-06-01.csv", original.raw + revised.raw)
        origin = RawFiles.describe(
            source,
            request=request.binding,
            retrieval_reference="synthetic:research-access",
            ts_received=_START + timedelta(days=1),
            ts_ingested=_START + timedelta(days=1),
        )
        raw.publish(source, descriptor=origin, request=request.binding)
        acquisition = AcquisitionManifest(run=request.manifest, completed=(origin,))
        identity = publisher.publish(
            (acquisition,),
            raw,
            root / "snapshots",
            max_bytes=_LIMIT,
            policy=QualityPolicy(use="exploratory", known_at=_START, max_gap=timedelta(hours=1)),
            eligibility=_Trades._history(request),
            corrections={acquisition.run.identity: (_Trades._correction(original, revised),)},
        )
        trade = EdaQuery(
            snapshot_id=identity,
            precedence=(_Trades._binding(request),),
            instruments=(request.instrument.instrument_id,),
            start=_START,
            end=_START + timedelta(days=2),
            known_at=_START + timedelta(seconds=10),
            columns=("price", "revision"),
            mode="cutoff",
            batch_size=1,
            max_bytes=_LIMIT,
        )
        capture = _Books._capture(root / "capture", gap=True)
        book_id = publisher.publish_books(
            (capture,), raw, root / "snapshots", max_records=16, max_bytes=_LIMIT
        )
        selected = BookInput.read(capture, max_records=16)
        book = BookQuery(
            snapshot_id=book_id,
            request_identity=selected.request.identity,
            instrument=selected.request.config.instrument_id,
            start=_EPOCH,
            end=_EPOCH + timedelta(seconds=1),
            known_at=trade.known_at,
            columns=("bids",),
            batch_size=1,
            max_bytes=_LIMIT,
        )
        return ResearchSelection(
            inputs=(
                TradeSelection(name="trades", query=trade),
                BookSelection(name="depth", query=book),
            )
        )

    @staticmethod
    def _reader(root: Path) -> ResearchReader:
        """Bind existing stores to the actual native admission adapters."""
        return ResearchReader(root / "snapshots", RawStore(root / "raw"), readers=SourceAdapters())

    @staticmethod
    def _prices(dataset: ResearchDataset) -> tuple[Decimal, ...]:
        """Extract independent exact expectations from typed trade values only."""
        result = dataset.inputs[0]
        assert isinstance(result, TradeResearchInput)
        values = tuple(
            row.values[0]
            for batch in result.batches
            for row in batch.rows
            if isinstance(row, QueryMarketRow)
        )
        assert all(isinstance(value, Decimal) for value in values)
        return tuple(value for value in values if isinstance(value, Decimal))

    def test_mixed_reopen_corrections_membership_and_missing_coverage(self, tmp_path: Path) -> None:
        """Old selection never acquires a late correction; all missing coverage remains visible."""
        selection = self._selection(tmp_path)
        trade, book = selection.inputs
        assert isinstance(trade, TradeSelection) and isinstance(book, BookSelection)
        reader = self._reader(tmp_path)
        earlier = replace(
            selection,
            inputs=(
                replace(trade, query=replace(trade.query, known_at=_START + timedelta(seconds=9))),
                replace(book, query=replace(book.query, known_at=_START + timedelta(seconds=9))),
            ),
        )
        old = reader.read(earlier)
        assert self._prices(old) == ()
        current = reader.read(selection)
        assert self._prices(current) == (Decimal("101.00"),)
        assert (
            reader.read(_CODEC.decode_json(_CODEC.encode_json(earlier), ResearchSelection)) == old
        )
        assert current.identity != old.identity
        result = current.inputs[0]
        assert isinstance(result, TradeResearchInput)
        assert result.coverage[0].selected_rows == 1
        assert (
            "requested interval extends outside saved request coverage"
            in result.coverage[0].reasons
        )
        assert result.batches[0].evidence[0].eligibility.assertions
        assert result.batches[0].evidence[0].request.instrument.quote_currency.code == "USDT"
        depth = current.inputs[1]
        assert isinstance(depth, BookResearchInput)
        markets = tuple(
            row for batch in depth.batches for row in batch.rows if isinstance(row, BookMarketRow)
        )
        assert len(markets) == 3
        level = markets[0].values[0][0]
        assert isinstance(level, tuple)
        assert level[1].size == Decimal("0.300000000000000001")
        assert any(
            isinstance(row, BookObservation) and row.outcome == "gap"
            for batch in depth.batches
            for row in batch.rows
        )
        assert depth.batches[0].evidence.request.config.quote_currency == "USDT"
        assert "historical eligibility unproven" in depth.batches[0].reasons[0]
        withdrawn = replace(
            selection,
            inputs=(
                replace(trade, query=replace(trade.query, known_at=_START + timedelta(hours=12))),
                replace(book, query=replace(book.query, known_at=_START + timedelta(hours=12))),
            ),
        )
        assert self._prices(reader.read(withdrawn)) == ()
        force_setattr(result.batches[0].evidence[0].eligibility.assertions[0], "state", "excluded")
        assert self._prices(reader.read(selection)) == (Decimal("101.00"),)

    def test_discovery_limits_staging_integrity_and_unavailable_raw(self, tmp_path: Path) -> None:
        """Discovery exposes identified metadata only; opening rechecks original bytes."""
        selection = self._selection(tmp_path)
        catalog = SnapshotCatalog(tmp_path / "snapshots")
        (tmp_path / "snapshots/.staging-unfinished").mkdir()
        entries = catalog.discover(max_entries=3, max_bytes=_LIMIT)
        assert tuple(entry.identity for entry in entries) == tuple(
            sorted(item.query.snapshot_id for item in selection.inputs)
        )
        for limits in ((2, _LIMIT), (3, 1), (True, _LIMIT)):
            with pytest.raises(ValueError):
                catalog.discover(max_entries=limits[0], max_bytes=limits[1])
        book = selection.inputs[1]
        assert isinstance(book, BookSelection)
        selected = BookInput.read(tmp_path / "capture", max_records=16)
        (tmp_path / "raw" / selected.raw.sha256).unlink()
        assert catalog.discover(max_entries=3, max_bytes=_LIMIT) == entries
        with pytest.raises(ValueError, match="publication refused"):
            self._reader(tmp_path).read(selection)
        path = tmp_path / "snapshots" / book.query.snapshot_id / "manifest.json"
        path.chmod(0o644)
        path.write_bytes(
            path.read_bytes().replace(
                b'"normalization_identity":"' + b"a" * 64, b'"normalization_identity":"' + b"b" * 64
            )
        )
        with pytest.raises(ValueError, match="identity mismatch"):
            catalog.discover(max_entries=3, max_bytes=_LIMIT)

    def test_book_cutoff_nanoseconds_controls_fields_and_unknown_archive(
        self, tmp_path: Path
    ) -> None:
        """Nanosecond receipts never round down; unavailable archives cannot become values."""
        selection = self._selection(tmp_path)
        selected = selection.inputs[1]
        assert isinstance(selected, BookSelection)
        raw = RawStore(tmp_path / "raw")
        query = replace(selected.query, known_at=_EPOCH)
        assert (
            BookQueryReader.read(
                tmp_path / "snapshots", raw, readers=SourceAdapters(), query=query
            )[0].rows
            == ()
        )
        known = replace(query, known_at=_EPOCH + timedelta(microseconds=1))
        rows = BookQueryReader.read(
            tmp_path / "snapshots", raw, readers=SourceAdapters(), query=known
        )
        assert sum(len(batch.rows) for batch in rows) == 7
        later_start = replace(known, start=_EPOCH + timedelta(microseconds=1))
        controls = BookQueryReader.read(
            tmp_path / "snapshots", raw, readers=SourceAdapters(), query=later_start
        )
        assert all(isinstance(row, BookObservation) for batch in controls for row in batch.rows)
        for invalid in (
            replace(known, columns=("orders",)),
            replace(known, request_identity="f" * 64),
            replace(known, max_bytes=1),
        ):
            with pytest.raises(ValueError):
                BookQueryReader.read(
                    tmp_path / "snapshots", raw, readers=SourceAdapters(), query=invalid
                )
        archive = _Books._archive(tmp_path / "archive")
        archive_id = DatasetPublication(SourceAdapters(), "a" * 64).publish_books(
            (archive,), raw, tmp_path / "snapshots", max_records=16, max_bytes=_LIMIT
        )
        archived = BookInput.read(archive, max_records=16)
        query = replace(
            selected.query, snapshot_id=archive_id, request_identity=archived.request.identity
        )
        unavailable = BookQueryReader.read(
            tmp_path / "snapshots", raw, readers=SourceAdapters(), query=query
        )
        assert unavailable[0].rows == ()
        assert (
            "original book availability unknown; no decision-eligible values"
            in unavailable[0].reasons
        )

    def test_configuration_identity_and_existing_eda_entry(self, tmp_path: Path) -> None:
        """The existing application reopens multi-input selections and refuses partial success."""
        selection = self._selection(tmp_path)
        trade, book = selection.inputs
        assert isinstance(trade, TradeSelection) and isinstance(book, BookSelection)
        resized = replace(
            selection,
            inputs=(
                replace(trade, query=replace(trade.query, batch_size=32, max_bytes=_LIMIT * 2)),
                replace(book, query=replace(book.query, batch_size=32)),
            ),
        )
        assert resized.identity == selection.identity
        assert (
            replace(selection, inputs=(replace(trade, name="other"), book)).identity
            != selection.identity
        )
        path = tmp_path / "selection.json"
        path.write_bytes(_CODEC.encode_json(selection))
        reports: list[dict[str, object]] = []
        report = inspect_eda(
            path, tmp_path / "snapshots", RawStore(tmp_path / "raw"), report=reports.append
        )
        assert [item["status"] for item in reports] == ["started", "complete"]
        assert report["dataset"] == self._reader(tmp_path).read(selection)
        assert report["selection_identity"] == selection.identity
        missing = replace(
            selection,
            inputs=(trade, replace(book, query=replace(book.query, snapshot_id="f" * 64))),
        )
        path.write_bytes(_CODEC.encode_json(missing))
        reports.clear()
        with pytest.raises(OSError):
            inspect_eda(
                path, tmp_path / "snapshots", RawStore(tmp_path / "raw"), report=reports.append
            )
        assert [item["status"] for item in reports] == ["started", "failed"]
        assert "dataset" not in reports[-1]
        for invalid in (
            (trade, trade),
            (trade, replace(book, query=replace(book.query, known_at=_START))),
            (),
        ):
            with pytest.raises(ValueError):
                replace(selection, inputs=invalid)
        with pytest.raises(ValueError, match="cutoff"):
            replace(trade, query=replace(trade.query, mode="history"))
        fields = msgspec.json.decode(_CODEC.encode_json(selection), type=dict[str, object])
        for change in (
            {"schema_version": "unknown"},
            {"inputs": [{"type": "macro", "name": "release"}]},
        ):
            with pytest.raises(ValueError):
                _CODEC.decode_json(_CODEC.encode_json(fields | change), ResearchSelection)

    def test_conflicting_quote_units_fail_before_returning_an_assembly(
        self, tmp_path: Path
    ) -> None:
        """A canonical instrument cannot silently mean USDT in trades and USD in depth."""
        selection = self._selection(tmp_path)
        trade, book = selection.inputs
        assert isinstance(trade, TradeSelection) and isinstance(book, BookSelection)
        original = BookInput.read(tmp_path / "capture", max_records=16)
        assert original.capture is not None
        request = CaptureRequest(
            config=replace(
                original.capture.config,
                symbol="BTC-USD",
                quote_currency="USD",
                instrument_id=trade.query.instruments[0],
            ),
            recording_id=original.capture.recording_id,
            implementation_identity=original.capture.implementation_identity,
        )
        destination = tmp_path / "conflicting"
        journal = CaptureJournal(destination, request)
        journal.start()
        for record in CaptureJournal(tmp_path / "capture", original.capture).records():
            journal.append(replace(record, raw=record.raw.replace(b"BTC-USDT", b"BTC-USD")))
        journal.finish(1)
        identity = DatasetPublication(SourceAdapters(), "a" * 64).publish_books(
            (destination,),
            RawStore(tmp_path / "raw"),
            tmp_path / "snapshots",
            max_records=16,
            max_bytes=_LIMIT,
        )
        changed = replace(
            book,
            query=replace(
                book.query,
                snapshot_id=identity,
                request_identity=request.identity,
                instrument=trade.query.instruments[0],
            ),
        )
        with pytest.raises(ValueError, match="quote units"):
            self._reader(tmp_path).read(replace(selection, inputs=(trade, changed)))

    def test_receipt_regression_cannot_reveal_future_reconstructed_state(
        self, tmp_path: Path
    ) -> None:
        """Native publication refuses an update stamped before its required snapshot."""
        selection = self._selection(tmp_path)
        selected = selection.inputs[1]
        assert isinstance(selected, BookSelection)
        original = BookInput.read(tmp_path / "capture", max_records=16)
        assert original.capture is not None
        destination = tmp_path / "regressing"
        journal = CaptureJournal(destination, original.capture)
        journal.start()
        for record in CaptureJournal(tmp_path / "capture", original.capture).records():
            received_ns = 2000 if record.received_ns == 4 else record.received_ns * 1000
            journal.append(replace(record, received_ns=received_ns))
        journal.finish(1)
        raw = RawStore(tmp_path / "raw")
        with pytest.raises(ValueError, match="partition publication refused"):
            DatasetPublication(SourceAdapters(), "a" * 64).publish_books(
                (destination,), raw, tmp_path / "snapshots", max_records=16, max_bytes=_LIMIT
            )
        assert self._reader(tmp_path).read(selection).identity == selection.identity

    @pytest.mark.parametrize("is_tracked", [False, True])
    def test_retained_study_failure_consumes_holdout_before_read(
        self, tmp_path: Path, is_tracked: bool
    ) -> None:
        """Persist failed reads and refuse changed final evaluation before exposing any values."""
        selection = self._selection(tmp_path)
        window = TimeWindow(start=_START, end=_START + timedelta(days=2))
        selected_inputs = tuple(
            replace(item, query=replace(item.query, start=window.start, end=window.end))
            for item in selection.inputs
        )
        selection = replace(selection, inputs=selected_inputs)
        study = ExplorationStudy(
            family="retained-inspection",
            question="Inspect declared final saved inputs",
            selection=selection,
            partition="holdout",
            split=TemporalSplit(
                training=None,
                fit_cutoff=None,
                fit_mode="none",
                samples=(),
                embargo_us=0,
                validation=TimeWindow(start=_START - timedelta(days=2), end=_START),
                holdout=window,
                rationale="No fitted transform or learned consumer is present.",
            ),
        )
        path = tmp_path / "study.json"
        path.write_bytes(_CODEC.encode_json(study))
        attempts = tmp_path / "attempts"
        raw = RawStore(tmp_path / "raw")
        tracking = (
            ClearMLDestination(
                project="unit", api_uri="http://127.0.0.1:18008", files_uri="http://127.0.0.1:18081"
            )
            if is_tracked
            else None
        )
        with patch.object(ClearMLPublication, "publish") as publish:
            with pytest.raises(OSError):
                inspect_experiment(
                    path, tmp_path / "missing", raw, attempts=attempts, tracking=tracking
                )
            history = AttemptStore(attempts).histories()[0]
            assert history.status == "failed" and history.events[0].status == "holdout_consumed"
            repeated = inspect_experiment(
                path, tmp_path / "snapshots", raw, attempts=attempts, tracking=tracking
            )
            assert repeated.status == "completed"
            assert repeated.start.run_identity == history.start.run_identity
            path.write_bytes(_CODEC.encode_json(replace(study, question="A tuned question")))
            with patch.object(ResearchReader, "read", side_effect=AssertionError("must not read")):
                with pytest.raises(ValueError, match="already consumed"):
                    inspect_experiment(
                        path, tmp_path / "snapshots", raw, attempts=attempts, tracking=tracking
                    )
            assert publish.call_count == (3 if is_tracked else 0)
        store = AttemptStore(attempts)
        for record in store.histories():
            assert ("clearml-destination" in store.artifacts(record.start.attempt_id)) == is_tracked
        assert {item.status for item in AttemptStore(attempts).histories()} == {
            "failed",
            "completed",
            "rejected",
        }
        with pytest.raises(ValueError, match="match"):
            replace(study, partition="validation")
