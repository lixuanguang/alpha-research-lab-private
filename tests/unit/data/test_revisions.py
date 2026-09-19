"""Protect economic deduplication, correction evidence and causal version retention."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.configuration import Configuration
from alpha_research.data.normalization import Occurrence
from alpha_research.data.providers.binance.rows import ArchiveRow
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.providers.tardis.decoder import TardisDecoder
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.requests import SourceRequest
from alpha_research.data.revisions import Correction, RevisionConflictError, TradeRevision
from alpha_research.data.venues.binance.events import Trade
from alpha_research.data.venues.binance.payloads import BinancePayloadDecoder
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

    @staticmethod
    def _evidence(first: Occurrence, second: Occurrence, delay: int = 10) -> Correction:
        """Link economic payload identities with labeled synthetic correction evidence."""
        return Correction(
            supersedes=TradeRevision(occurrences=(first,)).identity,
            replacement=TradeRevision(occurrences=(second,)).identity,
            ts_published=_TIME + timedelta(seconds=delay),
            ts_available=_TIME + timedelta(seconds=delay + 1),
            evidence_reference="synthetic:mr10-correction",
        )

    def test_duplicate_scale_position_and_retry_lineage(self, original: Occurrence) -> None:
        """Inserted lines, decimal formatting and copied files cannot add economic trades."""
        shifted = self._changed(original, "100.000")
        assert original.identity != shifted.identity
        heads = TradeRevision.admit((original, shifted, original), policy="reject", corrections=())
        assert len(heads) == 1 and len(heads[0].occurrences) == 2
        assert {item.raw for item in heads[0].occurrences} == {original.raw, shifted.raw}
        assert heads[0].identity == TradeRevision(occurrences=(original,)).identity
        assert heads[0].ts_knowledge is None
        assert TradeRevision.admit((shifted, original), policy="reject", corrections=()) == heads
        assert _CODEC.decode_json(_CODEC.encode_json(heads[0]), TradeRevision) == heads[0]
        assert heads[0].key == (
            original.request.instrument.source,
            "binance",
            original.event.instrument_id,
            "trade",
            12,
        )

    def test_conflict_retains_payloads_and_recovery(self, original: Occurrence) -> None:
        """Reject an unlinked conflict with all lineage, then recover without service state."""
        changed = self._changed(original)
        policies: tuple[Literal["reject", "evidenced"], ...] = ("reject", "evidenced")
        for policy in policies:
            with pytest.raises(RevisionConflictError, match="unresolved trade") as failure:
                TradeRevision.admit((original, changed), policy=policy, corrections=())
            assert {item.occurrences[0].raw for item in failure.value.revisions} == {
                original.raw,
                changed.raw,
            }
        assert len(TradeRevision.admit((original,), policy="reject", corrections=())) == 1
        assert TradeRevision.admit((), policy="reject", corrections=()) == ()

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
            TradeRevision.admit((original, changed), policy="reject", corrections=())

    def test_late_correction_append_roundtrip_and_future_perturbation(
        self, original: Occurrence
    ) -> None:
        """Preserve original and intermediate envelopes while later corrections append heads."""
        changed = self._changed(original)
        later = self._changed(original, "102.00")
        first, second = self._evidence(original, changed), self._evidence(changed, later, 20)
        previous = TradeRevision.admit(
            (original, changed), policy="evidenced", corrections=(first,)
        )[0]
        head = TradeRevision.admit(
            (later, original, changed), policy="evidenced", corrections=(second, first)
        )[0]
        assert head.previous == previous
        assert previous.previous == TradeRevision(occurrences=(original,))
        assert previous.ts_knowledge == _TIME + timedelta(seconds=11)
        assert head.ts_knowledge == _TIME + timedelta(seconds=21)
        assert head.correction == second and previous.correction == first
        wire = _CODEC.encode_json(head)
        assert _CODEC.decode_json(wire, TradeRevision) == head
        assert b'"price":"100.00"' in wire and b'"price":"102.00"' in wire
        assert head.previous.ts_knowledge is not None and head.ts_knowledge is not None
        assert head.previous.ts_knowledge <= _TIME + timedelta(seconds=15) < head.ts_knowledge
        assert isinstance(original.event, ArchiveTrade)
        assert original.event.ts_knowledge is None

    def test_captured_knowledge_bounds_and_earlier_reconstruction(self, tmp_path: Path) -> None:
        """Never backdate a correction before either capture or prior effective knowledge."""
        request = self._request("fixture-inspection", "btc-fixture")
        original_raw = (_ROOT / "tests/fixtures/market_data/tardis/btcusdt.txt").read_bytes()
        decoder = TardisDecoder(
            BinancePayloadDecoder(request.manifest.instruments), request.instrument.source
        )
        items = []
        for raw in (
            original_raw,
            original_raw.replace(b'"p":"67540.01000000"', b'"p":"67541.01000000"'),
        ):
            path = tmp_path / "capture.txt"
            path.write_bytes(raw)
            origin = RawObject.from_file(
                path,
                request=request,
                retrieval_reference="synthetic:mr10-capture",
                ts_received=_TIME + timedelta(days=2),
                ts_ingested=_TIME + timedelta(days=2),
            )
            event = decoder.decode_line(
                raw.decode().strip(),
                source_sequence=0,
                source_digest=origin.sha256,
                local_received=origin.ts_received,
                local_ingested=origin.ts_ingested,
            )
            assert isinstance(event, Trade)
            items.append(
                Occurrence(request=request, origin=origin, position=0, raw=raw, event=event)
            )
        assert items[0].event != items[1].event
        evidence = self._evidence(items[0], items[1])
        head = TradeRevision.admit(items, policy="evidenced", corrections=(evidence,))[0]
        assert head.previous is not None
        capture = _TIME + timedelta(microseconds=4103)
        assert head.previous.ts_knowledge == capture
        assert head.ts_knowledge == evidence.ts_available
        early = replace(evidence, ts_published=_TIME, ts_available=_TIME)
        assert (
            TradeRevision.admit(items, policy="evidenced", corrections=(early,))[0].ts_knowledge
            == capture
        )
        assert isinstance(items[0].event, Trade)
        prior = replace(
            items[0],
            event=replace(
                items[0].event,
                provenance=replace(
                    items[0].event.provenance, ts_knowledge=_TIME + timedelta(seconds=30)
                ),
            ),
        )
        assert TradeRevision.admit((prior, items[1]), policy="evidenced", corrections=(evidence,))[
            0
        ].ts_knowledge == _TIME + timedelta(seconds=30)

    def test_instrument_and_source_separation(self, original: Occurrence) -> None:
        """Independent canonical instruments or source bindings never share a trade key."""
        request = original.request
        run = replace(request.manifest, instruments=request.manifest.catalog.instruments)
        other = SourceRequest.partition(run)[1]
        assert isinstance(original.event, ArchiveTrade)
        eth = replace(
            original,
            request=other,
            origin=replace(original.origin, request_identity=other.identity),
            event=replace(
                original.event,
                instrument_id=other.instrument.instrument_id,
                symbol=other.instrument.symbol,
            ),
        )
        heads = TradeRevision.admit((original, eth), policy="reject", corrections=())
        assert len(heads) == 2
        with pytest.raises(ValueError, match="economic versions"):
            TradeRevision.admit(
                (original, eth), policy="evidenced", corrections=(self._evidence(original, eth),)
            )

    def test_bad_links_and_policy(self, original: Occurrence) -> None:
        """Fail on missing, branched, cyclic, cross-trade and temporally reversed evidence."""
        changed, later = self._changed(original), self._changed(original, "102.00")
        evidence = self._evidence(original, changed)
        with pytest.raises(ValueError, match="reject policy"):
            TradeRevision.admit((original, changed), policy="reject", corrections=(evidence,))
        for links in (
            (replace(evidence, replacement="f" * 64),),
            (evidence, evidence),
            (evidence, self._evidence(original, later)),
            (evidence, self._evidence(later, changed)),
        ):
            with pytest.raises(ValueError, match="present, unique and unbranched"):
                TradeRevision.admit(
                    (original, changed, later), policy="evidenced", corrections=links
                )
        with pytest.raises(ValueError, match="cyclic"):
            TradeRevision.admit(
                (original, changed),
                policy="evidenced",
                corrections=(evidence, self._evidence(changed, original)),
            )
        with pytest.raises(ValueError, match="follow predecessor"):
            TradeRevision.admit(
                (original, changed, later),
                policy="evidenced",
                corrections=(evidence, self._evidence(changed, later, 5)),
            )

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("supersedes", "bad"),
            ("replacement", 42),
            ("evidence_reference", ""),
            ("evidence_reference", " padded "),
            ("ts_published", _TIME.replace(tzinfo=None)),
            ("ts_available", _TIME - timedelta(seconds=1)),
        ],
    )
    def test_unsafe_evidence_and_wire(
        self, original: Occurrence, field: str, value: object
    ) -> None:
        """Direct constructor bypasses cannot make invalid evidence admissible or serializable."""
        changed = self._changed(original)
        evidence = self._evidence(original, changed)
        msgspec.structs.force_setattr(evidence, field, value)
        with pytest.raises((ValueError, TypeError)):
            TradeRevision.admit((original, changed), policy="evidenced", corrections=(evidence,))
        with pytest.raises((ValueError, TypeError)):
            _CODEC.decode_json(_CODEC.encode_json(evidence), Correction)

    def test_invalid_envelopes_and_payload(self, original: Occurrence) -> None:
        """Reject mixed versions, unsafe nested values, unknown schema and stripped linkage."""
        changed = self._changed(original)
        with pytest.raises(ValueError, match="share an economic"):
            TradeRevision(occurrences=(original, changed))
        evidence = self._evidence(original, changed)
        head = TradeRevision.admit(
            (original, changed), policy="evidenced", corrections=(evidence,)
        )[0]
        with pytest.raises(ValueError, match="both predecessor"):
            replace(head, correction=None)
        with pytest.raises(ValueError, match="unknown field"):
            _CODEC.decode_json(_CODEC.encode_json(head)[:-1] + b',"extra":1}', TradeRevision)
        with pytest.raises(AttributeError):
            setattr(head, "previous", None)
        for field, value in (("schema_version", "2"), ("occurrences", []), ("previous", 42)):
            broken = replace(head)
            msgspec.structs.force_setattr(broken, field, value)
            with pytest.raises((ValueError, TypeError)):
                _ = broken.ts_knowledge
            with pytest.raises((ValueError, TypeError)):
                _CODEC.decode_json(_CODEC.encode_json(broken), TradeRevision)
        msgspec.structs.force_setattr(original.event, "price", Decimal("NaN"))
        with pytest.raises(ValueError, match="finite"):
            TradeRevision.admit((original,), policy="reject", corrections=())
