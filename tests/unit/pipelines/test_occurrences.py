"""Verify persisted archive composition, selection and raw occurrence identities."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.configuration import Configuration, ResolvedManifest
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.normalization import Occurrence
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.pipelines.dataset import iter_occurrences
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_FIRST = b"12,100.00,2.0,200.000,1717200000000,true,true\r\n"
_SECOND = b"11,101.00,3.0,303.000,1717200000000,false,true\n"


class TestPersistedOccurrences:
    """Exercise the saved-input workflow independently of acquisition and network access."""

    @pytest.fixture()
    def run(self) -> ResolvedManifest:
        """Resolve the maintained archive selection.

        Returns:
            One selected BTC instrument with full-day raw input and a research hour.
        """
        config = Configuration.read(_ROOT / "configs/data-jobs/binance-archive.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        return config.resolve("btc-archive", catalog)

    @staticmethod
    def _save(
        root: Path, run: ResolvedManifest, contents: tuple[bytes, ...]
    ) -> AcquisitionManifest:
        """Publish deterministic synthetic ZIP inputs using the retained storage boundary."""
        descriptors: list[RawObject] = []
        for request, content in zip(SourceRequest.partition(run), contents, strict=True):
            path = root / "source.zip"
            member = ZipInfo(f"{request.instrument.symbol}-trades-{request.start.date()}.csv")
            member.compress_type = ZIP_DEFLATED
            with ZipFile(path, "w") as archive:
                archive.writestr(member, content)
            descriptor = RawObject.from_file(
                path,
                request=request,
                retrieval_reference="synthetic:mr09",
                ts_received=datetime(2026, 9, 16, tzinfo=UTC),
                ts_ingested=datetime(2026, 9, 16, tzinfo=UTC),
            )
            RawStore(root).publish(path, descriptor=descriptor, request=request)
            descriptors.append(descriptor)
        state = AcquisitionManifest(run=run, completed=tuple(descriptors))
        state.save(root / "manifest.json")
        return state

    def test_order_half_open_selection_rebuild_and_raw_preservation(
        self, tmp_path: Path, run: ResolvedManifest
    ) -> None:
        """Keep equal-time duplicates distinct, exclude the endpoint and repeat from saved bytes."""
        before = _FIRST
        inside = _SECOND.replace(b"1717200000000", b"1717200060000")
        endpoint = _FIRST.replace(b"1717200000000", b"1717203600000")
        run = replace(run, job=replace(run.job, start=run.job.start + timedelta(minutes=1)))
        state = self._save(tmp_path, run, (before + inside + inside + endpoint,))
        store = RawStore(tmp_path)
        occurrences = tuple(iter_occurrences(state, store, max_bytes=4096))
        assert [item.position for item in occurrences] == [1, 2]
        assert occurrences[0].raw == occurrences[1].raw == inside
        assert len({item.identity for item in occurrences}) == 2
        assert occurrences[0].event == occurrences[1].event
        reopened = AcquisitionManifest.read(tmp_path / "manifest.json", run=run, store=store)
        assert tuple(iter_occurrences(reopened, store, max_bytes=4096)) == occurrences
        for item in occurrences:
            assert _CODEC.decode_json(_CODEC.encode_json(item), Occurrence) == item
            assert isinstance(item.event, ArchiveTrade)
            assert item.event.ts_knowledge is item.event.ts_source_received is None
            assert item.origin == state.completed[0]
        with store.open(descriptor=state.completed[0], request=occurrences[0].request) as saved:
            assert saved.read() == (tmp_path / "source.zip").read_bytes()

    def test_files_and_independent_bindings_cannot_collide(
        self, tmp_path: Path, run: ResolvedManifest
    ) -> None:
        """Scope sequence zero by digest and request, leaving economic deduplication to MR10."""
        first = self._save(tmp_path, run, (_FIRST,))
        second = self._save(tmp_path, run, (_FIRST + _SECOND,))
        store = RawStore(tmp_path)
        a = next(iter_occurrences(first, store, max_bytes=4096))
        b = next(iter_occurrences(second, store, max_bytes=4096))
        assert a.position == b.position == 0 and a.event == b.event
        assert a.identity != b.identity and a.message_identity != b.message_identity
        same_message = replace(a, record_index=1)
        assert same_message.message_identity == a.message_identity
        assert same_message.identity != a.identity
        run = replace(run, instruments=run.catalog.instruments)
        both = self._save(tmp_path, run, (_FIRST, _FIRST))
        bound = tuple(iter_occurrences(both, store, max_bytes=4096))
        assert bound[0].position == bound[1].position == 0
        assert bound[0].request.instrument.symbol == "BTCUSDT"
        assert bound[1].request.instrument.symbol == "ETHUSDT"
        assert len({item.identity for item in bound}) == 2
        assert bound[0].identity == a.identity
        assert (
            replace(a, origin=replace(a.origin, retrieval_reference="retry-copy")).identity
            == a.identity
        )
        with pytest.raises(ValueError, match="instrument"):
            replace(a, event=bound[1].event)
        with pytest.raises(ValueError, match="binding"):
            replace(a, request=bound[1].request)
        with pytest.raises(ValueError, match="outside the resolved universe"):
            replace(a.request, instrument=run.instruments[1])

    def test_missing_incompatible_and_empty_inputs(
        self, tmp_path: Path, run: ResolvedManifest
    ) -> None:
        """Keep absent input distinct from an empty archive and refuse incompatible adapters."""
        store = RawStore(tmp_path)
        with pytest.raises(FileNotFoundError, match="completion"):
            tuple(iter_occurrences(AcquisitionManifest(run=run), store, max_bytes=4096))
        state = self._save(tmp_path, run, (b"",))
        assert tuple(iter_occurrences(state, store, max_bytes=4096)) == ()
        config = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        fixture = config.resolve("btc-fixture", catalog)
        tardis = replace(
            fixture, job=replace(fixture.job, mode="historical", pipeline="acquisition.fetch")
        )
        with pytest.raises(ValueError, match="Binance daily"):
            tuple(iter_occurrences(AcquisitionManifest(run=tardis), store, max_bytes=4096))
        (tmp_path / state.completed[0].sha256).unlink()
        with pytest.raises(FileNotFoundError):
            tuple(iter_occurrences(state, store, max_bytes=4096))

    def test_failures_outside_selection_and_iterator_recovery(
        self, tmp_path: Path, run: ResolvedManifest
    ) -> None:
        """Decode excluded rows too, propagate corruption, close prefixes and recover on retry."""
        invalid = _SECOND.replace(b"1717200000000", b"1717203600000").replace(b"101.00", b"NaN")
        state = self._save(tmp_path, run, (_FIRST + invalid,))
        store = RawStore(tmp_path)
        iterator = iter_occurrences(state, store, max_bytes=4096)
        first = next(iterator)
        with pytest.raises(ValueError, match=r"row 1.*price must be finite"):
            next(iterator)
        iterator.close()
        valid = self._save(tmp_path, run, (_FIRST + _SECOND,))
        iterator = iter_occurrences(valid, store, max_bytes=4096)
        assert next(iterator).event == first.event
        iterator.close()
        assert len(tuple(iter_occurrences(valid, store, max_bytes=4096))) == 2
        path = tmp_path / valid.completed[0].sha256
        path.chmod(0o600)
        payload = path.read_bytes()
        path.write_bytes(bytes([payload[0] ^ 1]) + payload[1:])
        with pytest.raises(ValueError, match="SHA-256"):
            next(iter_occurrences(valid, store, max_bytes=4096))

    def test_envelope_constructor_wire_and_unsafe_metadata(
        self, tmp_path: Path, run: ResolvedManifest
    ) -> None:
        """Fail closed on schema, origin, sequence, raw bytes and unsafe event replacements."""
        state = self._save(tmp_path, run, (_FIRST,))
        item = next(iter_occurrences(state, RawStore(tmp_path), max_bytes=4096))
        for field, value in (
            ("schema_version", "2"),
            ("position", True),
            ("record_index", -1),
            ("raw", b""),
        ):
            damaged = replace(item)
            msgspec.structs.force_setattr(damaged, field, value)
            with pytest.raises((ValueError, TypeError)):
                _ = damaged.identity
            with pytest.raises((ValueError, TypeError)):
                _CODEC.decode_json(_CODEC.encode_json(damaged), Occurrence)
        with pytest.raises(TypeError, match="position"):
            replace(item, position=True)
        with pytest.raises(ValueError, match="record_index"):
            replace(item, record_index=-1)
        with pytest.raises(ValueError, match="unknown field"):
            _CODEC.decode_json(_CODEC.encode_json(item)[:-1] + b',"extra":1}', Occurrence)
        with pytest.raises(AttributeError):
            setattr(item, "position", 99)
