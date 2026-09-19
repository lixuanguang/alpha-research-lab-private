"""Exercise occurrence decoding from an installed wheel and copied configurations."""

from __future__ import annotations

# standard library imports
import argparse
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# project library imports
import market_data
from configuration import Configuration
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.providers.tardis import TardisDecoder
from market_data.adapters.sources import SourceAdapters
from market_data.adapters.venues.binance import BinancePayloadDecoder
from market_data.contracts import ArchiveTrade, Disconnect, Occurrence, SourceRequest
from market_data.datasets import DatasetPublication
from market_data.storage import RawFiles, RawStore
from reference_data.catalogs import CatalogSnapshot
from runtime import ImplementationIdentity
from serialization import DomainCodec


def main() -> None:
    """Rebuild occurrences, trace colliding positions and reject malformed saved inputs.

    Raises:
        AssertionError: An installed behavior differs from the acceptance contract.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path)
    args = parser.parse_args()
    inputs: Path = args.inputs
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
    row = b"12,100.00,2.0,199.999,1717200000000,true,true\r\n"
    first_identity = ""
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = RawStore(root)
        source = root / "source.zip"
        for content in (row, row + row, row.replace(b"100.00", b"NaN"), b""):
            member = ZipInfo("BTCUSDT-trades-2024-06-01.csv")
            member.compress_type = ZIP_DEFLATED
            with ZipFile(source, "w") as archive:
                archive.writestr(member, content)
            descriptor = RawFiles.describe(
                source,
                request=request.binding,
                retrieval_reference="synthetic:mr09-installed",
                ts_received=datetime(2026, 9, 16, tzinfo=UTC),
                ts_ingested=datetime(2026, 9, 16, tzinfo=UTC),
            )
            store.publish(source, descriptor=descriptor, request=request.binding)
            state = AcquisitionManifest(run=run, completed=(descriptor,))
            state.save(root / "manifest.json")
            restored = AcquisitionManifest.read(root / "manifest.json", run=run, store=store)
            if b"NaN" in content:
                try:
                    tuple(
                        DatasetPublication(
                            SourceAdapters(), ImplementationIdentity.sha256()
                        ).occurrences(restored, store, max_bytes=4096)
                    )
                except ValueError as error:
                    assert "row 0" in str(error)
                else:
                    raise AssertionError("invalid trade accepted")
                continue
            events = tuple(
                DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).occurrences(
                    restored, store, max_bytes=4096
                )
            )
            assert len(events) == content.count(b"\n")
            assert (
                tuple(
                    DatasetPublication(
                        SourceAdapters(), ImplementationIdentity.sha256()
                    ).occurrences(restored, store, max_bytes=4096)
                )
                == events
            )
            assert len({item.identity for item in events}) == len(events)
            for item in events:
                assert isinstance(item.event, ArchiveTrade)
                assert item.raw == row and item.origin == descriptor
                assert item.event.price == Decimal("100.00")
                assert item.event.quote_quantity == Decimal("199.999")
                assert item.event.ts_source_received is item.event.ts_knowledge is None
                assert codec.decode_json(codec.encode_json(item), Occurrence) == item
            if content == row:
                first_identity = events[0].identity
            elif content:
                assert events[0].position == 0 and events[0].identity != first_identity
        try:
            tuple(
                DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).occurrences(
                    AcquisitionManifest(run=run), store, max_bytes=4096
                )
            )
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("missing completion accepted")
        fixture = Configuration.read(inputs / "fixture-inspection.json")
        captured_catalog = codec.decode_json(
            (inputs / "binance-spot.json").read_bytes(), CatalogSnapshot
        )
        captured = fixture.resolve(
            "both-fixture",
            captured_catalog,
            implementation_identity=ImplementationIdentity.sha256(),
        )
        controls: list[Occurrence] = []
        source.write_bytes(b"\n")
        for binding in SourceRequest.partition(captured)[:2]:
            origin = RawFiles.describe(
                source,
                request=binding.binding,
                retrieval_reference="synthetic:mr09-control",
                ts_received=descriptor.ts_received,
                ts_ingested=descriptor.ts_ingested,
            )
            event = TardisDecoder(
                BinancePayloadDecoder(captured.instruments), binding.instrument.source
            ).decode_line(
                "",
                source_sequence=0,
                local_received=origin.ts_received,
                local_ingested=origin.ts_ingested,
                source_digest=origin.sha256,
                disconnect_capture_time=binding.end,
                disconnect_capture_reason="interval_end",
            )
            assert isinstance(event, Disconnect)
            controls.append(
                Occurrence(request=binding, origin=origin, position=0, raw=b"\n", event=event)
            )
        assert controls[0].event == controls[1].event
        assert controls[0].origin.sha256 == controls[1].origin.sha256
        assert controls[0].identity != controls[1].identity
    print(f"Installed consumer passed: {market_data.__file__}")
    print(
        "Exact trades, distinct files/positions, stable rebuilds, "
        "scoped controls, codec and failures passed."
    )


if __name__ == "__main__":
    main()
