"""Exercise installed functional APIs, four commands and historical snapshots in isolation."""

from __future__ import annotations

# standard library imports
import hashlib
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib import import_module
from importlib.metadata import distributions, version
from importlib.util import find_spec
from pathlib import Path

# project library imports
from financial_units import Currency, Money, QuantLibConventions
from market_data.adapters.providers.tardis import TardisDecoder
from market_data.adapters.sources import BookAdapters, SourceAdapters
from market_data.adapters.venues.binance import BinancePayloadDecoder, MarketEventCodec
from market_data.datasets import SnapshotStore
from market_data.replay import SavedCapture
from market_data.storage import RawStore
from reference_data.calendars import (
    CalendarAuthority,
    CalendarSourceVersion,
    ExchangeCalendarsAdapter,
    MarketIdentifierCode,
    Venue,
    VenueId,
)
from reference_data.catalogs import CatalogSnapshot
from runtime import ImplementationIdentity, InstalledIdentity, RuntimeFiles
from serialization import DomainCodec


def main() -> None:
    """Verify the artifact without governance, user-site imports or checkout source access."""
    inputs = Path(sys.argv[1]).resolve()
    prefix = Path(sys.prefix).resolve()
    assert version("alpha-research-lab")
    assert find_spec("alpha_research") is None
    assert find_spec("alpha_research_governance") is None
    assert "alpha-research-governance" not in {item.metadata["Name"] for item in distributions()}
    files = dict(RuntimeFiles.inputs())
    assert {name.split("/")[0] for name in files} == set(RuntimeFiles.roots)
    for root in RuntimeFiles.roots:
        assert f"{root}/py.typed" in files
    assert "financial_units/default_currencies.json" in files
    for name, path in files.items():
        assert path.resolve().is_relative_to(prefix)
        if name.endswith("/__init__.py"):
            module = import_module(name.removesuffix("/__init__.py").replace("/", "."))
            assert module.__file__ is not None
            assert Path(module.__file__).resolve() == path.resolve()
    event_codec = MarketEventCodec()
    domain_codec = DomainCodec()
    amount = Money(value=Decimal("1.25"), currency=Currency.from_code("USD"))
    assert domain_codec.decode_json(domain_codec.encode_json(amount), Money) == amount
    catalog = domain_codec.decode_json((inputs / "binance-spot.json").read_bytes(), CatalogSnapshot)
    source_decoder = TardisDecoder(
        BinancePayloadDecoder(catalog.instruments), "tardis.binance.spot"
    )
    event = source_decoder.decode_line(
        "",
        source_sequence=0,
        local_received=datetime(2024, 6, 1, tzinfo=UTC),
        disconnect_capture_time=datetime(2024, 6, 1, tzinfo=UTC),
    )
    assert event_codec.decode(event_codec.encode(event)) == event
    assert QuantLibConventions()
    venue = Venue(
        venue_id=VenueId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        mic=MarketIdentifierCode(value="XNYS"),
        operating_mic=MarketIdentifierCode(value="XNYS"),
        name="Smoke venue",
        timezone_name="America/New_York",
    )
    version_info = CalendarSourceVersion(
        calendar_version="smoke-v1",
        base_source="exchange_calendars",
        base_source_revision="4.13.2",
        adapter_name="exchange_calendars",
        adapter_version="4.13.2",
        authority=CalendarAuthority.SYNTHETIC_FIXTURE,
    )
    snapshot = ExchangeCalendarsAdapter().build_snapshot(
        venue=venue,
        calendar_name="XNYS",
        version=version_info,
        start=date(2024, 11, 27),
        end=date(2024, 11, 29),
    )
    assert snapshot.session_for_label(date(2024, 11, 27)).opens_at
    historical = inputs / "historical_snapshot"
    identity = "23378e41e37533c74a41a3ce5bfa4046aa659ae3bd4131b08321c72dc3a448b9"
    manifest = SnapshotStore(
        historical / "snapshots", RawStore(historical / "raw"), readers=SourceAdapters()
    ).read(identity, max_bytes=262_144)
    assert manifest.identity == identity
    assert manifest.normalization_identity != ImplementationIdentity.sha256()
    assert (
        domain_codec.encode_json(manifest)
        == (historical / "snapshots" / identity / "manifest.json").read_bytes()
    )
    for partition in manifest.partitions:
        assert (
            hashlib.sha256(
                (historical / "snapshots" / identity / partition.sha256).read_bytes()
            ).hexdigest()
            == partition.sha256
        )
    executable = Path(sys.executable).parent
    fixture = subprocess.run(
        [
            str(executable / "alpha-inspect-fixture"),
            "--config",
            str(inputs / "fixture-inspection.json"),
            "--catalog",
            str(inputs / "binance-spot.json"),
            "--fixture",
            str(inputs / "btcusdt.txt"),
            "--job",
            "btc-fixture",
            "--received",
            "2026-09-17T00:00:00+00:00",
            "--ingested",
            "2026-09-17T00:00:00+00:00",
            "--sequence",
            "0",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert "fixture_sha256" in fixture.stdout
    for script, run in (
        ("ingestion_workflow.py", "ingestion"),
        ("recovery_consumer.py", "recovery"),
    ):
        subprocess.run(
            [sys.executable, "-I", str(inputs / script), str(inputs), str(inputs / run)],
            check=True,
            timeout=60,
            stdout=subprocess.PIPE,
        )
    # The recovery consumer retains a complete synthetic journal. Replay through the
    # installed command must reproduce its single shared reconstruction implementation.
    capture = inputs / "recovery/lineage"
    replay = subprocess.run(
        [str(executable / "alpha-collect"), "replay", "--capture", str(capture)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    assert replay.stdout.strip() == domain_codec.encode_json(
        SavedCapture.read(capture, book_factory=BookAdapters.create).summary()
    )
    assert InstalledIdentity.sha256() != ImplementationIdentity.sha256()
    print("Functional APIs, resources, four commands, recovery and historical snapshot verified.")


if __name__ == "__main__":
    main()
