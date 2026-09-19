"""Exercise saved duplicate/correction admission from an isolated installed runtime."""

from __future__ import annotations

# standard library imports
import argparse
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# project library imports
import alpha_research
from alpha_research.configuration import Configuration
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.data.revisions import Correction, RevisionConflictError, TradeRevision
from alpha_research.pipelines.dataset import admit_saved_trades, iter_occurrences
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec


def main() -> None:
    """Reopen verified originals and revisions, retaining lineage and explicit failures.

    Raises:
        AssertionError: Installed behavior violates the revision admission contract.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path)
    arguments = parser.parse_args()
    inputs: Path = arguments.inputs
    assert "site-packages" in Path(alpha_research.__file__).parts
    codec = DomainCodec()
    configuration = Configuration.read(inputs / "binance-archive.json")
    catalog = codec.decode_json(
        (inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
    )
    run = configuration.resolve("btc-archive", catalog)
    request = SourceRequest.partition(run)[0]
    first = b"12,100.00,2.0,200,1717200000000,true,true\n"
    inserted = b"11,99.00,1.0,99,1717200000000,false,true\n"
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = RawStore(root)
        manifests = []
        for index, content in enumerate(
            (first, inserted + first, inserted + first.replace(b"100.00", b"101.00"))
        ):
            path = root / "source.zip"
            member = ZipInfo("BTCUSDT-trades-2024-06-01.csv")
            member.compress_type = ZIP_DEFLATED
            with ZipFile(path, "w") as archive:
                archive.writestr(member, content)
            descriptor = RawObject.from_file(
                path,
                request=request,
                retrieval_reference="synthetic:mr10-installed",
                ts_received=datetime(2026, 9, 16, tzinfo=UTC),
                ts_ingested=datetime(2026, 9, 16, tzinfo=UTC),
            )
            store.publish(path, descriptor=descriptor, request=request)
            manifest = AcquisitionManifest(run=run, completed=(descriptor,))
            manifest_path = root / f"manifest-{index}.json"
            manifest.save(manifest_path)
            manifests.append(AcquisitionManifest.read(manifest_path, run=run, store=store))
        heads = admit_saved_trades(
            tuple(manifests[:2]), store, max_bytes=4096, policy="reject", corrections=()
        )
        original = next(head for head in heads if head.key[-1] == 12)
        assert len(heads) == 2 and len(original.occurrences) == 2
        assert {item.position for item in original.occurrences} == {0, 1}
        assert original.ts_knowledge is None
        revised = tuple(iter_occurrences(manifests[2], store, max_bytes=4096))[1]
        evidence = Correction(
            supersedes=original.identity,
            replacement=TradeRevision(occurrences=(revised,)).identity,
            ts_published=request.start + timedelta(days=1),
            ts_available=request.start + timedelta(days=1, seconds=1),
            evidence_reference="synthetic:mr10-installed-correction",
        )
        try:
            admit_saved_trades(
                tuple(manifests), store, max_bytes=4096, policy="evidenced", corrections=()
            )
        except RevisionConflictError as error:
            assert len(error.revisions) == 3
        else:
            raise AssertionError("unevidenced conflict accepted")
        admitted = admit_saved_trades(
            tuple(manifests), store, max_bytes=4096, policy="evidenced", corrections=(evidence,)
        )
        corrected = next(head for head in admitted if head.key[-1] == 12)
        assert corrected.previous == original and corrected.ts_knowledge == evidence.ts_available
        assert isinstance(corrected.occurrences[0].event, ArchiveTrade)
        assert corrected.occurrences[0].event.price == Decimal("101.00")
        restored = codec.decode_json(codec.encode_json(corrected), TradeRevision)
        assert restored == corrected and restored.previous == original
        assert (
            admit_saved_trades(
                tuple(reversed(manifests)),
                store,
                max_bytes=4096,
                policy="evidenced",
                corrections=(evidence,),
            )
            == admitted
        )
        try:
            admit_saved_trades(
                (manifests[0], AcquisitionManifest(run=run)),
                store,
                max_bytes=4096,
                policy="reject",
                corrections=(),
            )
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("incomplete saved input accepted")
    print(f"Installed revision admission consumer passed: {alpha_research.__file__}")
    print(
        "Shifted-row duplicates, complete lineage, evidenced correction, prior version, "
        "exact codec round trip, deterministic rebuild and required failures passed."
    )


if __name__ == "__main__":
    main()
