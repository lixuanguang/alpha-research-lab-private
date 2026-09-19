"""Exercise installed bounded queries from published synthetic archive snapshots."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import sys
import tracemalloc
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from zipfile import ZIP_DEFLATED, ZipFile

# third party library imports
from msgspec.structs import replace

# project library imports
import alpha_research
from alpha_research.configuration import Configuration
from alpha_research.data.asof import AsOfSelector, InputBinding
from alpha_research.data.eligibility import EligibilityAssertions
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.quality import QualityPolicy
from alpha_research.data.query import QueryMarketRow, QueryReader
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.data.revisions import Correction, TradeRevision
from alpha_research.pipelines.dataset import iter_occurrences, publish_dataset
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec


class _Reads:
    """Observe actual open operations in the temporary snapshot through Python's audit hook."""

    def __init__(self, directory: Path) -> None:
        """Bind the measured directory without opening files."""
        self._directory = str(directory) + "/"
        self.manifest = 0
        self.canonical = 0

    def observe(self, event: str, arguments: tuple[object, ...]) -> None:
        """Count snapshot opens without intercepting or changing read behavior."""
        if event == "open" and arguments and isinstance(arguments[0], str):
            name = arguments[0]
            if name.startswith(self._directory):
                if name.endswith("/manifest.json"):
                    self.manifest += 1
                else:
                    self.canonical += 1


class _Arguments(argparse.Namespace):
    """Type the directory containing copied, non-secret configuration and evidence."""

    inputs: Path


def main() -> None:
    """Publish two configured instruments and reconstruct their independently known revisions.

    Raises:
        AssertionError: Installed imports, integrity or temporal selection violates its contract.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path)
    inputs = parser.parse_args(namespace=_Arguments()).inputs.resolve()
    installed = Path(alpha_research.__file__).resolve().parent
    assert "site-packages" in installed.parts
    codec = DomainCodec()
    config = Configuration.read(inputs / "binance-archive.json")
    catalog = codec.decode_json(
        (inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
    )
    history = EligibilityAssertions.read(inputs / "membership-corrections.json", catalog=catalog)
    start = datetime(2024, 6, 1, tzinfo=UTC)
    with TemporaryDirectory(prefix="query-consumer-") as temporary:
        local = Path(temporary)
        (local / "raw").mkdir()
        (local / "snapshots").mkdir()
        store = RawStore(local / "raw")
        acquisitions: list[AcquisitionManifest] = []
        corrections: dict[str, tuple[Correction, ...]] = {}
        precedence: list[InputBinding] = []
        for universe in ("btc", "eth"):
            selected = replace(config, jobs=(replace(config.jobs[0], universe=universe),))
            run = selected.resolve("btc-archive", catalog)
            request = SourceRequest.partition(run)[0]
            source = local / "source.zip"
            with ZipFile(source, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr(
                    f"{request.instrument.symbol}-trades-2024-06-01.csv",
                    b"".join(
                        f"{trade_id},{price},2.0,200,1717200000000,true,true\n".encode()
                        for trade_id in range(32)
                        for price in ("100.00", "101.00")
                    ),
                )
            origin = RawObject.from_file(
                source,
                request=request,
                retrieval_reference="synthetic:mr19:installed",
                ts_received=datetime(2026, 9, 17, tzinfo=UTC),
                ts_ingested=datetime(2026, 9, 17, tzinfo=UTC),
            )
            store.publish(source, descriptor=origin, request=request)
            acquisition = AcquisitionManifest(run=run, completed=(origin,))
            occurrences = tuple(iter_occurrences(acquisition, store, max_bytes=4_194_304))
            corrections[run.identity] = tuple(
                Correction(
                    supersedes=TradeRevision(occurrences=(original,)).identity,
                    replacement=TradeRevision(occurrences=(revised,)).identity,
                    ts_published=start + timedelta(seconds=5),
                    ts_available=start + timedelta(seconds=10),
                    evidence_reference=f"synthetic:mr19:{universe}:availability",
                )
                for original, revised in zip(occurrences[::2], occurrences[1::2], strict=True)
            )
            acquisitions.append(acquisition)
            precedence.append(
                (request.instrument.source, run.job.stream, request.instrument.instrument_id)
            )
        snapshot_id = publish_dataset(
            tuple(acquisitions),
            store,
            local / "snapshots",
            max_bytes=4_194_304,
            policy=QualityPolicy(use="exploratory", known_at=start, max_gap=timedelta(hours=1)),
            eligibility=history,
            corrections=corrections,
        )
        reader = AsOfSelector.read(
            local / "snapshots",
            store,
            identity=snapshot_id,
            max_bytes=4_194_304,
            precedence=tuple(precedence),
        )
        instruments = tuple(binding[2] for binding in precedence)
        counts = []
        for seconds, expected in ((0, 0), (5, 0), (9, 0), (10, 64), (43_200, 32), (9, 0)):
            rows = reader.select(
                instruments,
                start=start,
                end=start + timedelta(hours=1),
                known_at=start + timedelta(seconds=seconds),
            )
            assert len(rows) == expected
            for point in rows:
                assert isinstance(point, TradeRevision)
                assert point.previous is not None and point.previous.ts_knowledge is None
                assert point.ts_knowledge == start + timedelta(seconds=10)
                assert isinstance(point.occurrences[0].event, ArchiveTrade)
                assert point.occurrences[0].event.price == Decimal("101.00")
                assert codec.decode_json(codec.encode_json(point), TradeRevision) == point
            counts.append((seconds, len(rows)))
        retained = reader.history
        reads = _Reads(local / "snapshots" / snapshot_id)
        sys.addaudithook(reads.observe)
        tracemalloc.start()
        query = QueryReader.read(
            local / "snapshots",
            store,
            identity=snapshot_id,
            max_bytes=4_194_304,
            precedence=tuple(precedence),
        )
        assert (reads.manifest, reads.canonical) == (1, 4)
        rows_seen = 0
        binding_counts: dict[InputBinding, int] = {}
        query_id = ""
        for batch in query.batches(
            instruments,
            start=start,
            end=start + timedelta(hours=1),
            known_at=start + timedelta(seconds=10),
            columns=("price", "quantity", "ts_knowledge"),
            batch_size=7,
        ):
            assert len(batch.rows) <= 7 and len(batch.evidence) == 2
            query_id = batch.identity
            for row in batch.rows:
                assert isinstance(row, QueryMarketRow)
                assert row.binding in precedence
                binding_counts[row.binding] = binding_counts.get(row.binding, 0) + 1
                assert row.values == (
                    Decimal("101.00"),
                    Decimal("2.0"),
                    start + timedelta(seconds=10),
                )
            rows_seen += len(batch.rows)
        assert binding_counts == dict.fromkeys(precedence, 32)
        assert rows_seen == 64 and (reads.manifest, reads.canonical) == (1, 4)
        stop = Event()
        stream = query.batches(
            instruments,
            start=start,
            end=start + timedelta(hours=1),
            known_at=start + timedelta(hours=12),
            columns=("revision",),
            batch_size=1,
            mode="history",
            cancelled=stop.is_set,
        )
        first = next(stream)
        row = first.rows[0]
        assert isinstance(row, QueryMarketRow) and isinstance(row.values[0], TradeRevision)
        revision = row.values[0]
        assert revision.previous is not None and revision.previous.ts_knowledge is None
        stop.set()
        try:
            next(stream)
        except InterruptedError:
            pass
        else:
            raise AssertionError("query ignored cancellation")
        assert list(stream) == []
        closed = query.batches(
            instruments,
            start=start,
            end=start + timedelta(hours=1),
            known_at=start,
            columns=("revision",),
            batch_size=1,
            mode="history",
        )
        unknown = next(closed).rows[0]
        assert isinstance(unknown, QueryMarketRow) and isinstance(unknown.values[0], TradeRevision)
        assert unknown.values[0].ts_knowledge is None
        closed.close()
        assert list(closed) == [] and (reads.manifest, reads.canonical) == (1, 4)
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print("Query:", query_id, "rows:", rows_seen, "batch bound:", 7)
        print("Snapshot opens: manifest=", reads.manifest, "canonical=", reads.canonical)
        print(
            "Canonical bytes:",
            sum(map(len, retained)),
            "traced current/peak:",
            current_bytes,
            peak_bytes,
        )
        try:
            QueryReader.read(
                local / "snapshots",
                store,
                identity=snapshot_id,
                max_bytes=max(map(len, retained)),
                precedence=tuple(precedence),
            )
        except ValueError as error:
            assert "aggregate max_bytes" in str(error)
        else:
            raise AssertionError("query exceeded aggregate input budget")
        assert len(retained) == 2 and all(
            b"original trade availability unknown" in p for p in retained
        )
        try:
            QueryReader.read(
                local / "snapshots",
                store,
                identity="latest",
                max_bytes=4_194_304,
                precedence=tuple(precedence),
            )
        except ValueError:
            pass
        else:
            raise AssertionError("mutable snapshot identifier accepted")
        path = local / "snapshots" / snapshot_id / hashlib.sha256(retained[0]).hexdigest()
        path.chmod(0o644)
        path.write_bytes(b"{}")
        try:
            QueryReader.read(
                local / "snapshots",
                store,
                identity=snapshot_id,
                max_bytes=4_194_304,
                precedence=tuple(precedence),
            )
        except ValueError:
            pass
        else:
            raise AssertionError("damaged snapshot accepted")
        assert reader.history == retained
        print("Installed package:", installed)
        print("Published synthetic snapshot:", snapshot_id)
        print("Seconds / known eligible versions:", counts)
        print(
            "Projection, lineage, cancellation, close, budget, exact codecs, "
            "mutable-ID and tamper checks passed."
        )


if __name__ == "__main__":
    main()
