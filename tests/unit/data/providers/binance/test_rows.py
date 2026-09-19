"""Verify saved archive reading independently of transport and event decoding."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from configuration import Configuration, ResolvedManifest
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.providers.binance import ArchiveRow, BinanceArchiveRows
from market_data.contracts import SourceRequest
from market_data.storage import RawFiles, RawStore
from reference_data.catalogs import CatalogSnapshot
from runtime import ImplementationIdentity
from serialization import DomainCodec

_ROOT = Path(__file__).parents[5]
_CODEC = DomainCodec()
_FIRST = b'11,"100.00",2.0,200.000,1717200000000,true,true\r\n'
_SECOND = b"10,101.00,3.0,303.000,1717200000000,false,true\n"


class TestArchiveRows:
    """Exercise the installed raw boundary with synthetic archives and explicit requests."""

    @pytest.fixture()
    def run(self) -> ResolvedManifest:
        """Resolve the existing daily archive configuration without contacting a provider.

        Returns:
            One instrument/day retaining the configured narrower research hour.
        """
        configuration = Configuration.read(_ROOT / "configs/data-jobs/binance-archive.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        return configuration.resolve(
            "btc-archive", catalog, implementation_identity=ImplementationIdentity.sha256()
        )

    @staticmethod
    def _archive(
        content: bytes,
        *,
        name: str = "BTCUSDT-trades-2024-06-01.csv",
        compression: int = ZIP_DEFLATED,
    ) -> bytes:
        """Create exact synthetic source bytes, including intentionally invalid CSV."""
        with BytesIO() as output:
            with ZipFile(output, "w", compression=compression) as archive:
                archive.writestr(name, content)
            return output.getvalue()

    @staticmethod
    def _save(
        root: Path, run: ResolvedManifest, payload: bytes
    ) -> tuple[AcquisitionManifest, RawStore]:
        """Publish independently described bytes without acquisition or decoder construction."""
        request = SourceRequest.partition(run)[0]
        source = root / "source.zip"
        source.write_bytes(payload)
        descriptor = RawFiles.describe(
            source,
            request=request.binding,
            retrieval_reference="synthetic:mr08",
            ts_received=datetime(2026, 9, 16, tzinfo=UTC),
            ts_ingested=datetime(2026, 9, 16, tzinfo=UTC),
        )
        store = RawStore(root)
        store.publish(source, descriptor=descriptor, request=request.binding)
        return AcquisitionManifest(run=run, completed=(descriptor,)), store

    def test_exact_order_origins_selection_and_serialization(
        self, tmp_path: Path, run: ResolvedManifest
    ) -> None:
        """Preserve equal-time descending trade IDs, decimal text, quoting and newline bytes."""
        content = _FIRST + _SECOND + _SECOND.rstrip(b"\n")
        payload = self._archive(content)
        manifest, store = self._save(tmp_path, run, payload)
        reader = BinanceArchiveRows.from_manifest(manifest)[0]
        rows = tuple(reader.read(store, max_bytes=4096))
        assert reader.recorder_coverage == "unknown"
        assert [row.position for row in rows] == [0, 1, 2]
        assert [row.columns()[0] for row in rows] == ["11", "10", "10"]
        assert {row.columns()[4] for row in rows} == {"1717200000000"}
        assert b"".join(row.payload for row in rows) == content
        assert rows[0].columns()[1] == "100.00"
        assert reader.request.end - reader.request.start == timedelta(days=1)
        for row in rows:
            assert row.origin == manifest.completed[0]
            assert (row.selection_start, row.selection_end) == (run.job.start, run.job.end)
            assert _CODEC.decode_json(_CODEC.encode_json(row), ArchiveRow) == row
            with pytest.raises(AttributeError):
                setattr(row, "position", 99)
        assert _CODEC.decode_json(_CODEC.encode_json(reader), BinanceArchiveRows) == reader
        assert tuple(reader.read(store, max_bytes=4096)) == rows
        with store.open(descriptor=manifest.completed[0], request=reader.request.binding) as saved:
            assert saved.read() == payload

    def test_expected_partitions_missing_pending_and_empty(
        self, tmp_path: Path, run: ResolvedManifest
    ) -> None:
        """Distinguish empty CSV from incomplete manifests and missing completed objects."""
        run = replace(run, instruments=run.catalog.instruments)
        manifest, store = self._save(tmp_path, run, self._archive(b""))
        first, absent = BinanceArchiveRows.from_manifest(manifest)
        assert [first.request.instrument.symbol, absent.request.instrument.symbol] == [
            "BTCUSDT",
            "ETHUSDT",
        ]
        assert tuple(first.read(store, max_bytes=4096)) == ()
        assert first.recorder_coverage == absent.recorder_coverage == "unknown"
        with pytest.raises(FileNotFoundError, match="missing daily archive completion"):
            tuple(absent.read(store, max_bytes=4096))
        pending = replace(manifest, completed=(), pending=manifest.completed[0])
        pending_reader = BinanceArchiveRows.from_manifest(pending)[0]
        assert pending_reader.descriptor is None
        with pytest.raises(FileNotFoundError, match="completion"):
            tuple(pending_reader.read(store, max_bytes=4096))
        (tmp_path / manifest.completed[0].sha256).unlink()
        with pytest.raises(FileNotFoundError):
            tuple(first.read(store, max_bytes=4096))

    @pytest.mark.parametrize(
        "content",
        [
            b"\xff,1,2,3,4,true,true\n",
            b"\n",
            b"1,2,3\n",
            b"1,2,3,4,5,true,\n",
            b'1,"unterminated,3,4,5,true,true\n',
            b'1,"2"junk,3,4,5,true,true\n',
            b'1,"two\nlines",3,4,5,true,true\n',
        ],
    )
    def test_invalid_csv_reports_original_position(
        self, tmp_path: Path, run: ResolvedManifest, content: bytes
    ) -> None:
        """Reject malformed input after a valid prefix without silently dropping any row."""
        manifest, store = self._save(tmp_path, run, self._archive(_FIRST + content))
        reader = BinanceArchiveRows.from_manifest(manifest)[0]
        with pytest.raises(ValueError, match="row 1"):
            tuple(reader.read(store, max_bytes=4096))

    @pytest.mark.parametrize(
        "fault", ["empty-bytes", "truncated", "crc", "member", "extra", "compression", "encrypted"]
    )
    def test_invalid_zip_rejected_despite_verified_digest(
        self, tmp_path: Path, run: ResolvedManifest, fault: str
    ) -> None:
        """Separate trusted byte identity from container correctness and source-member binding."""
        payload = self._archive(_FIRST)
        if fault == "empty-bytes":
            payload = b""
        elif fault == "truncated":
            payload = payload[:-12]
        elif fault == "member":
            payload = self._archive(_FIRST, name="../wrong.csv")
        elif fault == "compression":
            payload = self._archive(_FIRST, compression=ZIP_STORED)
        elif fault == "extra":
            with BytesIO(payload) as output:
                with ZipFile(output, "a") as archive:
                    archive.writestr("extra.csv", _SECOND)
                payload = output.getvalue()
        else:
            mutated = bytearray(payload)
            offset = 16 if fault == "crc" else 8
            mutated[mutated.index(b"PK\x01\x02") + offset] ^= 1
            payload = bytes(mutated)
        manifest, store = self._save(tmp_path, run, payload)
        with pytest.raises(ValueError, match="ZIP"):
            tuple(BinanceArchiveRows.from_manifest(manifest)[0].read(store, max_bytes=4096))

    def test_integrity_limits_and_prefix_cleanup(
        self, tmp_path: Path, run: ResolvedManifest
    ) -> None:
        """Enforce compressed, expanded and per-row caps; reject stored mutation before output."""
        payload = self._archive(_FIRST * 100)
        manifest, store = self._save(tmp_path, run, payload)
        reader = BinanceArchiveRows.from_manifest(manifest)[0]
        for limit, reason in ((1, "compressed"), (len(payload), "expanded")):
            with pytest.raises(ValueError, match=reason):
                tuple(reader.read(store, max_bytes=limit))
        for limit in (0, -1, True):
            with pytest.raises(ValueError, match="positive integers"):
                tuple(reader.read(store, max_bytes=limit))
            with pytest.raises(ValueError, match="positive integers"):
                tuple(reader.read(store, max_bytes=8192, max_row_bytes=limit))
        with pytest.raises(ValueError, match="row 0"):
            tuple(reader.read(store, max_bytes=8192, max_row_bytes=len(_FIRST) - 1))
        iterator = reader.read(store, max_bytes=len(_FIRST) * 100, max_row_bytes=len(_FIRST))
        assert next(iterator).payload == _FIRST
        iterator.close()
        assert len(tuple(reader.read(store, max_bytes=8192))) == 100
        saved = tmp_path / manifest.completed[0].sha256
        saved.chmod(0o600)
        saved.write_bytes(b"X" + payload[1:])
        with pytest.raises(ValueError, match="SHA-256"):
            next(reader.read(store, max_bytes=8192))

    def test_unsafe_manifest_and_foreign_selection_fail_before_reading(
        self, tmp_path: Path, run: ResolvedManifest
    ) -> None:
        """Reuse prefix validation and reject forged bindings or fabricated recorder evidence."""
        manifest, store = self._save(tmp_path, run, self._archive(_FIRST))
        reader = BinanceArchiveRows.from_manifest(manifest)[0]
        with pytest.raises(ValueError, match="identity"):
            replace(reader, descriptor=replace(manifest.completed[0], request_identity="a" * 64))
        msgspec.structs.force_setattr(manifest, "completed", manifest.completed * 2)
        with pytest.raises(ValueError, match="exceeds"):
            BinanceArchiveRows.from_manifest(manifest)
        msgspec.structs.force_setattr(reader, "recorder_coverage", "complete")
        with pytest.raises(ValueError, match="unknown recorder coverage"):
            next(reader.read(store, max_bytes=4096))
        fixture = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        request = SourceRequest.partition(
            fixture.resolve(
                "btc-fixture", catalog, implementation_identity=ImplementationIdentity.sha256()
            )
        )[0]
        with pytest.raises(ValueError, match="Binance daily"):
            BinanceArchiveRows(request=request, descriptor=None)

    def test_row_constructor_and_wire_reject_invalid_metadata(
        self, tmp_path: Path, run: ResolvedManifest
    ) -> None:
        """Protect immutable raw-row metadata at direct construction and serialized boundaries."""
        manifest, store = self._save(tmp_path, run, self._archive(_FIRST))
        row = next(BinanceArchiveRows.from_manifest(manifest)[0].read(store, max_bytes=4096))
        with pytest.raises(ValueError, match="position"):
            replace(row, position=True)
        with pytest.raises(ValueError, match="position"):
            replace(row, position=-1)
        with pytest.raises(ValueError, match="UTC"):
            replace(row, selection_start=run.job.start.replace(tzinfo=None))
        with pytest.raises(ValueError, match="nonempty"):
            replace(row, selection_end=row.selection_start)
        with pytest.raises(ValueError, match="nonempty source"):
            replace(row, payload=b"")
        with pytest.raises(ValueError, match="unknown field"):
            _CODEC.decode_json(_CODEC.encode_json(row)[:-1] + b',"capture":true}', ArchiveRow)
        msgspec.structs.force_setattr(row.origin, "size_bytes", -1)
        with pytest.raises(ValueError, match="size_bytes"):
            _CODEC.decode_json(_CODEC.encode_json(row), ArchiveRow)
