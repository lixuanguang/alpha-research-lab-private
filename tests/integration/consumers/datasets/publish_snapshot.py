"""Publish and recover explicit snapshots from an isolated installed wheel consumer."""

from __future__ import annotations

# standard library imports
import argparse
import subprocess
import sys
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
from market_data.datasets import DatasetPublication, SnapshotStore
from market_data.storage import RawFiles, RawStore
from market_data.validation import QualityPolicy
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import EligibilityAssertions
from runtime import ImplementationIdentity
from serialization import DomainCodec


class _Arguments(argparse.Namespace):
    """Type the external fixture directory at the command boundary."""

    inputs: Path


def main() -> None:
    """Verify pipeline publication, interruption recovery and retained snapshot identity.

    Raises:
        AssertionError: Installed imports, publication, recovery or rejection disagree.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path)
    inputs = parser.parse_args(namespace=_Arguments()).inputs.resolve()
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
    with TemporaryDirectory(prefix="publish-snapshot-") as temporary:
        root = Path(temporary)
        raw = root / "raw"
        raw.mkdir()
        published = root / "snapshots"
        published.mkdir()
        store = RawStore(raw)
        snapshots = SnapshotStore(published, store, readers=SourceAdapters())
        source = root / "source.zip"
        member = ZipInfo("BTCUSDT-trades-2024-06-01.csv")
        member.compress_type = ZIP_DEFLATED
        with ZipFile(source, "w") as archive:
            archive.writestr(member, b"12,100.00,2.0,200,1717200000000,true,true\n" * 2)
        descriptor = RawFiles.describe(
            source,
            request=request.binding,
            retrieval_reference="synthetic:mr15",
            ts_received=datetime(2026, 9, 17, tzinfo=UTC),
            ts_ingested=datetime(2026, 9, 17, tzinfo=UTC),
        )
        raw_path = store.publish(source, descriptor=descriptor, request=request.binding)
        acquisition = AcquisitionManifest(run=run, completed=(descriptor,))
        identity = DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).publish(
            (acquisition,),
            store,
            published,
            max_bytes=262_144,
            policy=policy,
            eligibility=history,
            corrections={},
        )
        original = snapshots.read(identity, max_bytes=262_144)
        print("Installed package:", market_data.__file__)
        print("Original snapshot:", identity, original.scope)
        for index, point in enumerate(("partial", "before", "after"), start=1):
            manifest, payloads = DatasetPublication(
                SourceAdapters(), ImplementationIdentity.sha256()
            ).assemble(
                (acquisition,),
                store,
                max_bytes=262_144,
                policy=replace(policy, max_gap=timedelta(minutes=index)),
                eligibility=history,
                corrections={},
            )
            working = root / point
            working.mkdir()
            (working / "manifest.json").write_bytes(codec.encode_json(manifest))
            for part, payload in zip(manifest.partitions, payloads, strict=True):
                (working / part.sha256).write_bytes(payload)
            child = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(inputs / "interrupt_snapshot.py"),
                    str(published),
                    str(raw),
                    str(working),
                    point,
                ],
                cwd=root,
                capture_output=True,
                check=False,
                timeout=30,
            )
            assert child.returncode == 75, child.stderr.decode()
            assert snapshots.read(identity, max_bytes=262_144) == original
            if point == "after":
                assert snapshots.read(manifest.identity, max_bytes=262_144) == manifest
            else:
                try:
                    snapshots.read(manifest.identity, max_bytes=262_144)
                except FileNotFoundError:
                    pass
                else:
                    raise AssertionError("interrupted build exposed a partial snapshot")
            for _ in range(2):
                assert snapshots.publish(manifest, payloads, max_bytes=262_144) == manifest.identity
            assert snapshots.read(manifest.identity, max_bytes=262_144) == manifest
            assert snapshots.read(identity, max_bytes=262_144) == original
            print("Recovered:", point, manifest.identity, "prior snapshot readable")
        for invalid in ("latest", "../raw", ".staging-incomplete"):
            try:
                snapshots.read(invalid, max_bytes=262_144)
            except ValueError:
                pass
            else:
                raise AssertionError("snapshot reader accepted a mutable tag or path")
        raw_bytes = raw_path.read_bytes()
        raw_path.unlink()
        try:
            snapshots.read(identity, max_bytes=262_144)
        except ValueError:
            pass
        else:
            raise AssertionError("snapshot reader ignored missing retained raw bytes")
        source.write_bytes(raw_bytes)
        store.publish(source, descriptor=descriptor, request=request.binding)
        assert snapshots.read(identity, max_bytes=262_144) == original
        print("Explicit IDs and missing raw-input refusal passed; restored original snapshot")


if __name__ == "__main__":
    main()
