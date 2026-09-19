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
import market_data
from configuration import Configuration
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import ArchiveTrade, SourceRequest
from market_data.datasets import DatasetPublication
from market_data.storage import RawFiles, RawStore
from market_data.validation import Correction, RevisionConflictError, TradeRevision
from reference_data.catalogs import CatalogSnapshot
from runtime import ImplementationIdentity
from serialization import DomainCodec


def main() -> None:
    """Reopen verified originals and revisions, retaining lineage and explicit failures.

    Raises:
        AssertionError: Installed behavior violates the revision admission contract.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path)
    arguments = parser.parse_args()
    inputs: Path = arguments.inputs
    assert "site-packages" in Path(market_data.__file__).parts
    codec = DomainCodec()
    configuration = Configuration.read(inputs / "binance-archive.json")
    catalog = codec.decode_json(
        (inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
    )
    run = configuration.resolve(
        "btc-archive", catalog, implementation_identity=ImplementationIdentity.sha256()
    )
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
            descriptor = RawFiles.describe(
                path,
                request=request.binding,
                retrieval_reference="synthetic:mr10-installed",
                ts_received=datetime(2026, 9, 16, tzinfo=UTC),
                ts_ingested=datetime(2026, 9, 16, tzinfo=UTC),
            )
            store.publish(path, descriptor=descriptor, request=request.binding)
            manifest = AcquisitionManifest(run=run, completed=(descriptor,))
            manifest_path = root / f"manifest-{index}.json"
            manifest.save(manifest_path)
            manifests.append(AcquisitionManifest.read(manifest_path, run=run, store=store))
        heads = DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).admit_trades(
            tuple(manifests[:2]), store, max_bytes=4096, policy="reject", corrections=()
        )
        original = next(head for head in heads if head.key[-1] == 12)
        assert len(heads) == 2 and len(original.occurrences) == 2
        assert {item.position for item in original.occurrences} == {0, 1}
        assert original.ts_knowledge is None
        revised = tuple(
            DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).occurrences(
                manifests[2], store, max_bytes=4096
            )
        )[1]
        evidence = Correction(
            supersedes=original.identity,
            replacement=TradeRevision(occurrences=(revised,)).identity,
            ts_published=request.start + timedelta(days=1),
            ts_available=request.start + timedelta(days=1, seconds=1),
            evidence_reference="synthetic:mr10-installed-correction",
        )
        try:
            DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).admit_trades(
                tuple(manifests), store, max_bytes=4096, policy="evidenced", corrections=()
            )
        except RevisionConflictError as error:
            assert len(error.revisions) == 3
        else:
            raise AssertionError("unevidenced conflict accepted")
        admitted = DatasetPublication(
            SourceAdapters(), ImplementationIdentity.sha256()
        ).admit_trades(
            tuple(manifests), store, max_bytes=4096, policy="evidenced", corrections=(evidence,)
        )
        corrected = next(head for head in admitted if head.key[-1] == 12)
        assert corrected.previous == original and corrected.ts_knowledge == evidence.ts_available
        assert isinstance(corrected.occurrences[0].event, ArchiveTrade)
        assert corrected.occurrences[0].event.price == Decimal("101.00")
        restored = codec.decode_json(codec.encode_json(corrected), TradeRevision)
        assert restored == corrected and restored.previous == original
        assert (
            DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).admit_trades(
                tuple(reversed(manifests)),
                store,
                max_bytes=4096,
                policy="evidenced",
                corrections=(evidence,),
            )
            == admitted
        )
        try:
            DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).admit_trades(
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
    print(f"Installed revision admission consumer passed: {market_data.__file__}")
    print(
        "Shifted-row duplicates, complete lineage, evidenced correction, prior version, "
        "exact codec round trip, deterministic rebuild and required failures passed."
    )


if __name__ == "__main__":
    main()
