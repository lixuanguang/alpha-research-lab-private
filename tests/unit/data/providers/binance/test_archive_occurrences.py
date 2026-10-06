"""Verify bounded Binance archive occurrence composition and generator cleanup."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from configuration import Configuration, ResolvedManifest
from market_data.adapters.providers.binance import BinanceArchiveOccurrences, BinanceArchiveRows
from market_data.contracts import (
    RawObject,
    RequestBinding,
    SourceRequest,
)
from market_data.storage import RawFiles, RawStore
from reference_data.catalogs import CatalogSnapshot
from runtime import ImplementationIdentity
from serialization import DomainCodec

_ROOT = Path(__file__).parents[5]
_CODEC = DomainCodec()
_VALID = b"12,100.00,2.0,200.000,1717200000000,true,true\n"


class _TrackingRawStore(RawStore):
    """Record the real stream returned by the raw-store read boundary."""

    def __init__(self, root: Path) -> None:
        """Bind a normal raw store and reserve the stream observation slot."""
        super().__init__(root)
        self.opened: BinaryIO | None = None

    def open(
        self,
        *,
        descriptor: RawObject,
        request: RequestBinding,
    ) -> BinaryIO:
        """Delegate verification and retain the actual opened file for assertions."""
        self.opened = super().open(descriptor=descriptor, request=request)
        return self.opened


class TestBinanceArchiveOccurrences:
    """Protect row decoding, research selection and abandoned-prefix cleanup."""

    @pytest.fixture()
    def run(self) -> ResolvedManifest:
        """Resolve the maintained daily archive selection without source access.

        Returns:
            One BTC daily archive request retaining a narrower research hour.
        """
        configuration = Configuration.read(_ROOT / "configs/data-jobs/binance-archive.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        return configuration.resolve(
            "btc-archive", catalog, implementation_identity=ImplementationIdentity.sha256()
        )

    @staticmethod
    def _save(
        root: Path, run: ResolvedManifest, content: bytes
    ) -> tuple[BinanceArchiveRows, _TrackingRawStore]:
        """Publish one synthetic daily archive and return its explicit row binding."""
        request = SourceRequest.partition(run)[0]
        source = root / "source.zip"
        member = ZipInfo(f"{request.instrument.symbol}-trades-{request.start.date()}.csv")
        member.compress_type = ZIP_DEFLATED
        with ZipFile(source, "w") as archive:
            archive.writestr(member, content)
        descriptor = RawFiles.describe(
            source,
            request=request.binding,
            retrieval_reference="synthetic:occurrences",
            ts_received=datetime(2026, 9, 16, tzinfo=UTC),
            ts_ingested=datetime(2026, 9, 16, tzinfo=UTC),
        )
        store = _TrackingRawStore(root)
        store.publish(source, descriptor=descriptor, request=request.binding, compress=False)
        return BinanceArchiveRows(request=request, descriptor=descriptor), store

    def test_decodes_invalid_row_after_research_endpoint(
        self, tmp_path: Path, run: ResolvedManifest
    ) -> None:
        """Decode a malformed daily row even when its timestamp is excluded."""
        narrowed = replace(run, job=replace(run.job, start=run.job.start + timedelta(minutes=1)))
        invalid = b"11,NaN,3.0,303.000,1717203600000,false,true\n"
        partition, store = self._save(tmp_path, narrowed, _VALID + invalid)

        with pytest.raises(ValueError, match=r"row 1.*price must be finite"):
            tuple(BinanceArchiveOccurrences(partition).read(store, max_bytes=4096))

    def test_closes_abandoned_prefix_and_preserves_raw_lineage(
        self, tmp_path: Path, run: ResolvedManifest
    ) -> None:
        """Close an abandoned prefix while retaining source position, bytes and clocks."""
        partition, store = self._save(tmp_path, run, _VALID + _VALID)
        reader = BinanceArchiveOccurrences(partition)
        occurrences = reader.read(store, max_bytes=4096)

        first = next(occurrences)
        occurrences.close()

        assert first.position == 0
        assert first.raw == _VALID
        assert first.origin == partition.descriptor
        assert first.origin.ts_received == datetime(2026, 9, 16, tzinfo=UTC)
        assert store.opened is not None and store.opened.closed
        assert len(tuple(reader.read(store, max_bytes=4096))) == 2
