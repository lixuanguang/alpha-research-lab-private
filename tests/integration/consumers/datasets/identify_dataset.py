"""Rebuild and verify a saved dataset manifest from an isolated installed consumer."""

from __future__ import annotations

# standard library imports
import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
from msgspec.structs import replace

# project library imports
import market_data
from configuration import Configuration
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import SourceRequest
from market_data.datasets import DatasetManifest, DatasetPublication
from market_data.storage import RawFiles, RawStore
from market_data.validation import QualityPolicy
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import EligibilityAssertions
from runtime import ImplementationIdentity
from serialization import DomainCodec


def main() -> None:
    """Check repeatable identity, scope and failure behavior without checkout imports.

    Raises:
        AssertionError: A saved-input, identity or refusal contract is violated.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path)
    arguments = parser.parse_args()
    inputs: Path = arguments.inputs
    assert "site-packages" in Path(market_data.__file__).parts
    codec = DomainCodec()
    config = Configuration.read(inputs / "binance-archive.json")
    catalog = codec.decode_json(
        (inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
    )
    run = config.resolve(
        "btc-archive", catalog, implementation_identity=ImplementationIdentity.sha256()
    )
    request = SourceRequest.partition(run)[0]
    history = EligibilityAssertions.read(inputs / "membership-corrections.json", catalog=catalog)
    policy = QualityPolicy(use="exploratory", known_at=run.job.start, max_gap=timedelta(hours=1))
    with TemporaryDirectory(prefix="identify-dataset-") as temporary:
        root = Path(temporary)
        store = RawStore(root)
        source = root / "source.zip"
        member = ZipInfo("BTCUSDT-trades-2024-06-01.csv")
        member.compress_type = ZIP_DEFLATED
        with ZipFile(source, "w") as archive:
            archive.writestr(member, b"12,100.00,2.0,200,1717200000000,true,true\n" * 2)
        descriptor = RawFiles.describe(
            source,
            request=request.binding,
            retrieval_reference="synthetic:mr14",
            ts_received=datetime(2026, 9, 16, tzinfo=UTC),
            ts_ingested=datetime(2026, 9, 16, tzinfo=UTC),
        )
        raw_path = store.publish(source, descriptor=descriptor, request=request.binding)
        AcquisitionManifest(run=run, completed=(descriptor,)).save(root / "acquisition.json")
        acquisition = AcquisitionManifest.read(root / "acquisition.json", run=run, store=store)
        builds: list[DatasetManifest] = []
        for selected_policy in (policy, policy, replace(policy, max_gap=timedelta(minutes=5))):
            manifest, payloads = DatasetPublication(
                SourceAdapters(), ImplementationIdentity.sha256()
            ).assemble(
                (acquisition,),
                store,
                max_bytes=262_144,
                policy=selected_policy,
                eligibility=history,
                corrections={},
            )
            for partition, payload in zip(manifest.partitions, payloads, strict=True):
                (root / partition.sha256).write_bytes(payload)
            (root / "dataset.json").write_bytes(codec.encode_json(manifest))
            assert (
                DatasetManifest.read(
                    root / "dataset.json",
                    readers=SourceAdapters(),
                    identity=manifest.identity,
                    partitions=root,
                    store=store,
                    max_bytes=262_144,
                )
                == manifest
            )
            builds.append(manifest)
            print(
                "Manifest / canonical / scope:",
                manifest.identity,
                manifest.partitions[0].sha256,
                manifest.scope,
            )
        assert builds[0] == builds[1] and builds[0].identity != builds[2].identity
        failures: list[str] = []
        manifest = builds[-1]
        saved = codec.encode_json(manifest)
        for label, payload in (
            (
                "unknown version",
                saved.replace(b'"schema_version":"1"', b'"schema_version":"99"', 1),
            ),
            (
                "unsupported scope",
                saved.replace(b'"scope":"exploratory_degraded"', b'"scope":"causal"'),
            ),
            ("identity mismatch", codec.encode_json(builds[0])),
        ):
            (root / "dataset.json").write_bytes(payload)
            try:
                DatasetManifest.read(
                    root / "dataset.json",
                    readers=SourceAdapters(),
                    identity=manifest.identity,
                    partitions=root,
                    store=store,
                    max_bytes=262_144,
                )
            except ValueError as error:
                failures.append(label)
                print(label, str(error))
            else:
                raise AssertionError(f"reader accepted {label}")
        (root / "dataset.json").write_bytes(saved)
        for path in (root / manifest.partitions[0].sha256, raw_path):
            original = path.read_bytes()
            path.chmod(0o644)
            path.unlink()
            try:
                DatasetManifest.read(
                    root / "dataset.json",
                    readers=SourceAdapters(),
                    identity=manifest.identity,
                    partitions=root,
                    store=store,
                    max_bytes=262_144,
                )
            except (ValueError, FileNotFoundError) as error:
                failures.append("missing bytes")
                print("missing bytes", str(error))
            else:
                raise AssertionError("reader accepted missing bytes")
            path.write_bytes(original)
        try:
            DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).assemble(
                (acquisition,),
                store,
                max_bytes=262_144,
                policy=replace(policy, use="causal"),
                eligibility=history,
                corrections={},
            )
        except ValueError as error:
            failures.append("causal admission")
            print("causal admission", str(error))
        else:
            raise AssertionError("assembly accepted causal use")
        assert len(failures) == 6
        assert (
            DatasetManifest.read(
                root / "dataset.json",
                readers=SourceAdapters(),
                identity=manifest.identity,
                partitions=root,
                store=store,
                max_bytes=262_144,
            )
            == manifest
        )
    print(f"Installed dataset identity consumer passed: {market_data.__file__}")


if __name__ == "__main__":
    main()
