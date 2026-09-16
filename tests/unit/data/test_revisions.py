"""Protect economic deduplication, correction evidence and causal version retention."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.configuration import Configuration
from alpha_research.data.normalization import Occurrence
from alpha_research.data.providers.binance.rows import ArchiveRow
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.requests import SourceRequest
from alpha_research.data.revisions import RevisionConflictError, TradeRevision
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_TIME = datetime(2024, 6, 1, tzinfo=UTC)


class TestTradeRevisions:
    """Exercise immutable version admission without network or historical availability claims."""

    @staticmethod
    def _request(config_name: str = "binance-archive", job: str = "btc-archive") -> SourceRequest:
        """Resolve a retained configuration and its actual authored catalog."""
        catalog_name = (
            "binance-archive-spot" if config_name == "binance-archive" else "binance-spot"
        )
        config = Configuration.read(_ROOT / f"configs/data-jobs/{config_name}.json")
        catalog = _CODEC.decode_json(
            (_ROOT / f"configs/reference/{catalog_name}.json").read_bytes(), CatalogSnapshot
        )
        return SourceRequest.partition(config.resolve(job, catalog))[0]

    @pytest.fixture()
    def original(self) -> Occurrence:
        """Decode one synthetic archive occurrence with explicitly absent capture.

        Returns:
            An exact individual trade bound to the maintained archive configuration.
        """
        request = self._request()
        row = ArchiveRow(
            origin=RawObject(
                sha256="a" * 64,
                size_bytes=100,
                request_identity=request.identity,
                retrieval_reference="synthetic:mr10",
                ts_received=_TIME + timedelta(days=2),
                ts_ingested=_TIME + timedelta(days=2),
            ),
            position=0,
            payload=b"12,100.00,2.0,200,1717200000000,true,true\n",
            selection_start=request.manifest.job.start,
            selection_end=request.manifest.job.end,
        )
        return Occurrence(
            request=request,
            origin=row.origin,
            position=0,
            raw=row.payload,
            event=ArchiveTrade.from_row(row, request),
        )

    @staticmethod
    def _changed(original: Occurrence, price: str = "101.00") -> Occurrence:
        """Decode changed bytes after an inserted line; retain a distinct raw origin."""
        assert isinstance(original.event, ArchiveTrade)
        payload = original.raw.replace(str(original.event.price).encode(), price.encode())
        row = ArchiveRow(
            origin=replace(original.origin, sha256="b" * 64),
            position=1,
            payload=payload,
            selection_start=original.request.manifest.job.start,
            selection_end=original.request.manifest.job.end,
        )
        return Occurrence(
            request=original.request,
            origin=row.origin,
            position=1,
            raw=payload,
            event=ArchiveTrade.from_row(row, original.request),
        )

    def test_duplicate_scale_position_and_retry_lineage(self, original: Occurrence) -> None:
        """Inserted lines, decimal formatting and copied files cannot add economic trades."""
        shifted = self._changed(original, "100.000")
        assert original.identity != shifted.identity
        heads = TradeRevision.admit((original, shifted, original))
        assert len(heads) == 1 and len(heads[0].occurrences) == 2
        assert {item.raw for item in heads[0].occurrences} == {original.raw, shifted.raw}
        assert heads[0].identity == TradeRevision(occurrences=(original,)).identity
        assert heads[0].ts_knowledge is None
        assert TradeRevision.admit((shifted, original)) == heads
        assert _CODEC.decode_json(_CODEC.encode_json(heads[0]), TradeRevision) == heads[0]
        assert heads[0].key == (
            original.request.instrument.source,
            "binance",
            original.event.instrument_id,
            "trade",
            12,
        )

    @pytest.mark.parametrize(
        ("index", "value"),
        [
            (2, b"3"),
            (3, b"201"),
            (4, b"1717200000001"),
            (5, b"false"),
            (6, b"false"),
        ],
    )
    def test_every_economic_field_participates(
        self, original: Occurrence, index: int, value: bytes
    ) -> None:
        """Do not silently merge differences in quantities, event time or source flags."""
        fields = original.raw.strip().split(b",")
        fields[index] = value
        row = ArchiveRow(
            origin=replace(original.origin, sha256="c" * 64),
            position=1,
            payload=b",".join(fields) + b"\n",
            selection_start=original.request.manifest.job.start,
            selection_end=original.request.manifest.job.end,
        )
        changed = replace(
            original,
            origin=row.origin,
            position=row.position,
            raw=row.payload,
            event=ArchiveTrade.from_row(row, original.request),
        )
        with pytest.raises(RevisionConflictError):
            TradeRevision.admit((original, changed))
