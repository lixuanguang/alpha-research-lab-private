"""Verify partition admission through a fresh installed consumer and saved raw inputs."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
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
from market_data.datasets import DatasetPublication
from market_data.storage import RawFiles, RawStore
from market_data.validation import QualityPolicy, QualityReport
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import EligibilityAssertions
from runtime import ImplementationIdentity
from serialization import DomainCodec


def main() -> None:
    """Check deterministic admission and fail-closed installed saved-input behavior.

    Raises:
        AssertionError: The installed quality boundary violates its declared scope.
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
    policy = QualityPolicy(use="exploratory", known_at=run.job.start, max_gap=timedelta(minutes=5))
    first = b"12,100.00,2.0,200,1717200000000,true,true\n"
    second = b"13,101.00,1.0,101,1717201200000,false,true\n"
    reports: list[QualityReport] = []
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = RawStore(root)
        for label, content in (
            ("duplicate-and-gap", first + first + second),
            ("invalid-price", first + second.replace(b"101.00", b"NaN") + first),
            ("zero-trade-quantity", first.replace(b",2.0,", b",0,")),
            ("conflicting-correction", first + first.replace(b"100.00", b"101.00")),
        ):
            source = root / "source.zip"
            member = ZipInfo("BTCUSDT-trades-2024-06-01.csv")
            member.compress_type = ZIP_DEFLATED
            with ZipFile(source, "w") as archive:
                archive.writestr(member, content)
            descriptor = RawFiles.describe(
                source,
                request=request.binding,
                retrieval_reference=f"synthetic:mr13:{label}",
                ts_received=datetime(2026, 9, 16, tzinfo=UTC),
                ts_ingested=datetime(2026, 9, 16, tzinfo=UTC),
            )
            store.publish(source, descriptor=descriptor, request=request.binding)
            state = AcquisitionManifest(run=run, completed=(descriptor,))
            state.save(root / "acquisition.json")
            saved = AcquisitionManifest.read(root / "acquisition.json", run=run, store=store)
            report = DatasetPublication(
                SourceAdapters(), ImplementationIdentity.sha256()
            ).validate_partition(saved, store, max_bytes=4096, policy=policy, eligibility=history)
            reports.append(report)
            assert codec.decode_json(codec.encode_json(report), QualityReport) == report
            if label == "duplicate-and-gap":
                assert (report.invalid_count, report.gap_count, report.duplicate_count) == (0, 2, 1)
                canonical = report.require_canonical()
                assert report.scope == "exploratory_degraded"
                assert (
                    DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256())
                    .validate_partition(
                        saved, store, max_bytes=4096, policy=policy, eligibility=history
                    )
                    .canonical
                    == canonical
                )
                strict = DatasetPublication(
                    SourceAdapters(), ImplementationIdentity.sha256()
                ).validate_partition(
                    saved,
                    store,
                    max_bytes=4096,
                    policy=replace(policy, use="causal"),
                    eligibility=history,
                )
                assert strict.canonical is None
                print(f"Canonical SHA-256: {hashlib.sha256(canonical).hexdigest()}")
            else:
                assert report.canonical is None
                try:
                    report.require_canonical()
                except ValueError as error:
                    assert "publication refused" in str(error)
                else:
                    raise AssertionError("invalid partition became publishable")
            print(
                label, report.scope, report.invalid_count, report.gap_count, report.duplicate_count
            )
        missing = DatasetPublication(
            SourceAdapters(), ImplementationIdentity.sha256()
        ).validate_partition(
            AcquisitionManifest(run=run), store, max_bytes=4096, policy=policy, eligibility=history
        )
        assert missing.canonical is None and missing.invalid_count == 1
    assert len(reports) == 4
    print(f"Installed partition validation consumer passed: {market_data.__file__}")


if __name__ == "__main__":
    main()
