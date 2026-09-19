"""Exercise installed archive row reading from copied configuration outside the checkout."""

from __future__ import annotations

# standard library imports
import argparse
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

# project library imports
import alpha_research
from alpha_research.configuration import Configuration
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.providers.binance.rows import ArchiveRow, BinanceArchiveRows
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec


def main() -> None:
    """Read synthetic saved rows, round-trip lineage and reject missing or corrupted inputs.

    Raises:
        AssertionError: Installed behavior violates a retained acceptance case.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path)
    args = parser.parse_args()
    inputs: Path = args.inputs
    codec = DomainCodec()
    configuration = Configuration.read(inputs / "binance-archive.json")
    catalog = codec.decode_json(
        (inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
    )
    run = configuration.resolve("btc-archive", catalog)
    request = SourceRequest.partition(run)[0]
    payload = (
        b"12,100.00,2.0,200.000,1717200000000,true,true\r\n"
        b"11,101.00,3.0,303.000,1717200000000,false,true\n"
    )
    with TemporaryDirectory(dir=inputs) as temporary:
        directory = Path(temporary)
        source = directory / "source.zip"
        store = RawStore(directory)
        for content in (payload, b"", b'1,"unterminated\n', b"\xff,2,3,4,5,true,true\n"):
            with ZipFile(source, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("BTCUSDT-trades-2024-06-01.csv", content)
            descriptor = RawObject.from_file(
                source,
                request=request,
                retrieval_reference="synthetic:mr08-installed",
                ts_received=datetime(2026, 9, 16, tzinfo=UTC),
                ts_ingested=datetime(2026, 9, 16, tzinfo=UTC),
            )
            store.publish(source, descriptor=descriptor, request=request)
            manifest = AcquisitionManifest(run=run, completed=(descriptor,))
            checkpoint = directory / "manifest.json"
            manifest.save(checkpoint)
            restored = AcquisitionManifest.read(checkpoint, run=run, store=store)
            reader = BinanceArchiveRows.from_manifest(restored)[0]
            assert reader.recorder_coverage == "unknown"
            if content in (payload, b""):
                rows = tuple(reader.read(store, max_bytes=4096))
                assert b"".join(row.payload for row in rows) == content
                assert [row.position for row in rows] == list(range(len(rows)))
                for row in rows:
                    assert codec.decode_json(codec.encode_json(row), ArchiveRow) == row
                    assert row.origin == descriptor
                    assert (row.selection_start, row.selection_end) == (run.job.start, run.job.end)
            else:
                try:
                    tuple(reader.read(store, max_bytes=4096))
                except ValueError:
                    pass
                else:
                    raise AssertionError("invalid source accepted")
        absent = BinanceArchiveRows.from_manifest(AcquisitionManifest(run=run))[0]
        for missing in (absent, reader):
            (directory / descriptor.sha256).unlink(missing_ok=True)
            try:
                tuple(missing.read(store, max_bytes=4096))
            except FileNotFoundError:
                pass
            else:
                raise AssertionError("missing source accepted")
    print(f"Installed consumer passed: {alpha_research.__file__}")
    print(
        "Exact equal-time rows, origins/bounds, codec, empty CSV, "
        "invalid UTF-8/CSV and absence passed."
    )


if __name__ == "__main__":
    main()
