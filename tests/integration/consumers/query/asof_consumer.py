"""Exercise installed as-of selection from real published synthetic archive snapshots."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

# third party library imports
from msgspec.structs import replace

# project library imports
import market_data
from configuration import Configuration
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import ArchiveTrade, SourceRequest
from market_data.datasets import DatasetPublication
from market_data.query import AsOfSelector, InputBinding
from market_data.storage import RawFiles, RawStore
from market_data.validation import Correction, QualityPolicy, TradeRevision
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import EligibilityAssertions
from runtime import ImplementationIdentity
from serialization import DomainCodec


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
    installed = Path(market_data.__file__).resolve().parent
    assert "site-packages" in installed.parts
    codec = DomainCodec()
    config = Configuration.read(inputs / "binance-archive.json")
    catalog = codec.decode_json(
        (inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
    )
    history = EligibilityAssertions.read(inputs / "membership-corrections.json", catalog=catalog)
    start = datetime(2024, 6, 1, tzinfo=UTC)
    with TemporaryDirectory(prefix="asof-consumer-") as temporary:
        local = Path(temporary)
        (local / "raw").mkdir()
        (local / "snapshots").mkdir()
        store = RawStore(local / "raw")
        acquisitions: list[AcquisitionManifest] = []
        corrections: dict[str, tuple[Correction, ...]] = {}
        precedence: list[InputBinding] = []
        for universe in ("btc", "eth"):
            selected = replace(config, jobs=(replace(config.jobs[0], universe=universe),))
            run = selected.resolve(
                "btc-archive", catalog, implementation_identity=ImplementationIdentity.sha256()
            )
            request = SourceRequest.partition(run)[0]
            source = local / "source.zip"
            with ZipFile(source, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr(
                    f"{request.instrument.symbol}-trades-2024-06-01.csv",
                    b"12,100.00,2.0,200,1717200000000,true,true\n"
                    b"12,101.00,2.0,202,1717200000000,true,true\n",
                )
            origin = RawFiles.describe(
                source,
                request=request.binding,
                retrieval_reference="synthetic:mr17:installed",
                ts_received=datetime(2026, 9, 17, tzinfo=UTC),
                ts_ingested=datetime(2026, 9, 17, tzinfo=UTC),
            )
            store.publish(source, descriptor=origin, request=request.binding)
            acquisition = AcquisitionManifest(run=run, completed=(origin,))
            original, revised = tuple(
                DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).occurrences(
                    acquisition, store, max_bytes=262_144
                )
            )
            corrections[run.identity] = (
                Correction(
                    supersedes=TradeRevision(occurrences=(original,)).identity,
                    replacement=TradeRevision(occurrences=(revised,)).identity,
                    ts_published=start + timedelta(seconds=5),
                    ts_available=start + timedelta(seconds=10),
                    evidence_reference=f"synthetic:mr17:{universe}:availability",
                ),
            )
            acquisitions.append(acquisition)
            precedence.append(
                (request.instrument.source, run.job.stream, request.instrument.instrument_id)
            )
        snapshot_id = DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).publish(
            tuple(acquisitions),
            store,
            local / "snapshots",
            max_bytes=262_144,
            policy=QualityPolicy(use="exploratory", known_at=start, max_gap=timedelta(hours=1)),
            eligibility=history,
            corrections=corrections,
        )
        reader = AsOfSelector.read(
            local / "snapshots",
            store,
            readers=SourceAdapters(),
            identity=snapshot_id,
            max_bytes=262_144,
            precedence=tuple(precedence),
        )
        instruments = tuple(binding[2] for binding in precedence)
        counts = []
        for seconds, expected in ((0, 0), (5, 0), (9, 0), (10, 2), (43_200, 1), (9, 0)):
            rows = reader.select(
                instruments,
                start=start,
                end=start + timedelta(hours=1),
                known_at=start + timedelta(seconds=seconds),
            )
            assert len(rows) == expected
            for row in rows:
                assert isinstance(row, TradeRevision)
                assert row.previous is not None and row.previous.ts_knowledge is None
                assert row.ts_knowledge == start + timedelta(seconds=10)
                assert isinstance(row.occurrences[0].event, ArchiveTrade)
                assert row.occurrences[0].event.price == Decimal("101.00")
                assert codec.decode_json(codec.encode_json(row), TradeRevision) == row
            counts.append((seconds, len(rows)))
        retained = reader.history
        assert len(retained) == 2 and all(
            b"original trade availability unknown" in p for p in retained
        )
        try:
            AsOfSelector.read(
                local / "snapshots",
                store,
                readers=SourceAdapters(),
                identity="latest",
                max_bytes=262_144,
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
            AsOfSelector.read(
                local / "snapshots",
                store,
                readers=SourceAdapters(),
                identity=snapshot_id,
                max_bytes=262_144,
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
        print("Exact revision round trips, prior history, mutable-ID and tamper checks passed.")


if __name__ == "__main__":
    main()
