"""Build and inspect a tiny synthetic EDA sample through an isolated installed candidate."""

from __future__ import annotations

# standard library imports
import hashlib
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
import alpha_research
from alpha_research.configuration import Configuration
from alpha_research.data.asof import InputBinding, PointEvent
from alpha_research.data.eda import EdaQuery, QuerySummary
from alpha_research.data.eligibility import EligibilityAssertions
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.quality import QualityPolicy
from alpha_research.data.query import QueryBatch, QueryMarketRow, QueryReader
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.data.replay import Replay, ReplayPhase
from alpha_research.data.requests import SourceRequest
from alpha_research.data.revisions import Correction, TradeRevision
from alpha_research.financial_units import Multiplier, Price, Quantity, UnitError
from alpha_research.instrument_identity import InstrumentId, InstrumentIdentity, InstrumentKind
from alpha_research.pipelines.dataset import iter_occurrences, publish_dataset
from alpha_research.pipelines.eda import inspect_eda
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec


class _Evidence:
    """Retain attempt records, source steps and observed file opens."""

    def __init__(self, directory: Path) -> None:
        """Bind a new local acceptance directory."""
        self.directory = directory
        self.sources: list[tuple[datetime, str, Decimal]] = []
        self.opens: dict[str, int] = {}

    def report(self, record: dict[str, object]) -> None:
        """Append an attempt record without retaining projected market rows."""
        with (self.directory / "attempts.jsonl").open("ab") as output:
            output.write(DomainCodec().encode_json(record) + b"\n")

    def observe(self, event: str, arguments: tuple[object, ...]) -> None:
        """Count actual file opens under the sample stores, including cached reads."""
        if event == "open" and arguments and isinstance(arguments[0], str):
            path = Path(arguments[0])
            if path.is_relative_to(self.directory / "raw"):
                role = "raw"
            elif path.is_relative_to(self.directory / "snapshots"):
                role = "manifest" if path.name == "manifest.json" else "canonical"
            else:
                return
            self.opens[role] = self.opens.get(role, 0) + 1

    def consume(self, phase: ReplayPhase, instant: datetime, item: PointEvent | None) -> None:
        """Record only synthetic source observations, without economic or lifecycle behavior."""
        if phase == "source" and isinstance(item, TradeRevision):
            event = item.occurrences[0].event
            assert isinstance(event, ArchiveTrade)
            self.sources.append(
                (instant, str(item.occurrences[0].request.instrument.instrument_id), event.price)
            )


def main() -> None:
    """Publish two synthetic instruments, retain EDA evidence and replay without a notebook.

    Raises:
        AssertionError: An installed query, exact-unit or refusal contract fails.
    """
    inputs, local = (Path(value).resolve() for value in sys.argv[1:])
    installed = Path(alpha_research.__file__).resolve()
    assert "site-packages" in installed.parts and not installed.is_relative_to(inputs)
    local.mkdir()
    (local / "raw").mkdir()
    (local / "snapshots").mkdir()
    codec = DomainCodec()
    config = Configuration.read(inputs / "binance-archive.json")
    catalog = codec.decode_json(
        (inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
    )
    eligibility = EligibilityAssertions.read(
        inputs / "membership-corrections.json", catalog=catalog
    )
    start = datetime(2024, 6, 1, tzinfo=UTC)
    store = RawStore(local / "raw")
    acquisitions: list[AcquisitionManifest] = []
    corrections: dict[str, tuple[Correction, ...]] = {}
    precedence: list[InputBinding] = []
    for offset, universe in enumerate(("btc", "eth")):
        selected = replace(config, jobs=(replace(config.jobs[0], universe=universe),))
        run = selected.resolve("btc-archive", catalog)
        request = SourceRequest.partition(run)[0]
        source = local / f"{universe}.zip"
        with ZipFile(source, "w", compression=ZIP_DEFLATED) as archive:
            member = ZipInfo(
                f"{request.instrument.symbol}-trades-2024-06-01.csv", (2024, 6, 1, 0, 0, 0)
            )
            member.compress_type = ZIP_DEFLATED
            archive.writestr(
                member,
                b"".join(
                    (
                        f"{n},{100 + offset * 100 + n + revision}.00,2.0,200,"
                        f"{1717200000000 + n * 1000},true,true\n"
                    ).encode()
                    for n in range(3)
                    for revision in (0, 1)
                ),
            )
        origin = RawObject.from_file(
            source,
            request=request,
            retrieval_reference="synthetic:mr21",
            ts_received=start + timedelta(days=1),
            ts_ingested=start + timedelta(days=1),
        )
        store.publish(source, descriptor=origin, request=request)
        acquisition = AcquisitionManifest(run=run, completed=(origin,))
        items = tuple(iter_occurrences(acquisition, store, max_bytes=262_144))
        corrections[run.identity] = tuple(
            Correction(
                supersedes=TradeRevision(occurrences=(original,)).identity,
                replacement=TradeRevision(occurrences=(revised,)).identity,
                ts_published=start + timedelta(seconds=10 * (index + 1)),
                ts_available=start + timedelta(seconds=10 * (index + 1)),
                evidence_reference=f"synthetic:mr21:{universe}:{index}",
            )
            for index, (original, revised) in enumerate(zip(items[::2], items[1::2], strict=True))
        )
        acquisitions.append(acquisition)
        precedence.append(
            (request.instrument.source, run.job.stream, request.instrument.instrument_id)
        )
    snapshot = publish_dataset(
        tuple(acquisitions),
        store,
        local / "snapshots",
        max_bytes=262_144,
        policy=QualityPolicy(use="exploratory", known_at=start, max_gap=timedelta(hours=1)),
        eligibility=eligibility,
        corrections=corrections,
    )
    query = EdaQuery(
        snapshot_id=snapshot,
        precedence=tuple(precedence),
        instruments=tuple(b[2] for b in precedence),
        start=start,
        end=start + timedelta(seconds=3),
        known_at=start + timedelta(seconds=30),
        columns=("price", "quantity", "ts_knowledge", "revision"),
        mode="cutoff",
        batch_size=2,
        max_bytes=262_144,
    )
    path = local / "query.json"
    path.write_bytes(codec.encode_json(query))
    evidence = _Evidence(local)
    sys.addaudithook(evidence.observe)
    summary = inspect_eda(path, local / "snapshots", store, report=evidence.report)
    load_opens = dict(evidence.opens)
    assert summary["rows"] == 6 and summary["batches"] == 3 and summary["controls"] == 0
    assert summary["groups"] == (
        (precedence[0], 3, Decimal("101.00"), Decimal("103.00")),
        (precedence[1], 3, Decimal("201.00"), Decimal("203.00")),
    )
    assert load_opens["manifest"] == 1 and load_opens["canonical"] == 4
    path.write_bytes(codec.encode_json(replace(query, batch_size=8)))
    repeated = inspect_eda(path, local / "snapshots", store, report=evidence.report)
    assert repeated["summary_identity"] == summary["summary_identity"]
    assert repeated["query_identity"] == summary["query_identity"]
    assert repeated["config_identity"] != summary["config_identity"]
    path.write_bytes(codec.encode_json(query))
    reader = QueryReader.read(
        local / "snapshots",
        store,
        identity=snapshot,
        max_bytes=query.max_bytes,
        precedence=query.precedence,
    )
    replay = Replay(
        reader,
        query.instruments,
        start=query.start,
        end=query.end,
        terminal=query.known_at,
        config_identity=hashlib.sha256(codec.encode_json(query)).hexdigest(),
        batch_size=1,
    )
    while replay.step(query.known_at, evidence.consume) is not None:
        pass
    assert [int((instant - start).total_seconds()) for instant, _, _ in evidence.sources] == [
        10,
        10,
        20,
        20,
        30,
        30,
    ]
    assert [price for _, _, price in evidence.sources] == list(
        map(Decimal, ("101", "201", "102", "202", "103", "203"))
    )
    assert replay.cursor is not None
    (local / "replay.json").write_bytes(
        codec.encode_json({"sources": evidence.sources, "cursor": replay.cursor})
    )
    fields = msgspec.json.decode(
        (inputs / "contract.json").read_bytes(), type=dict[str, msgspec.Raw]
    )
    instrument = codec.decode_json(fields["instrument_id"], InstrumentId)
    contract = InstrumentIdentity(
        instrument_id=instrument,
        instrument_kind=InstrumentKind.CONTRACT,
        economic_instrument_id=codec.decode_json(fields["economic_root"], InstrumentId),
    )
    quantity = codec.decode_json(fields["quantity"], Quantity)
    price = codec.decode_json(fields["price"], Price)
    multiplier = Multiplier(
        value=codec.decode_json(fields["units_per_contract"], Decimal),
        input_dimension=quantity.dimension,
        output_dimension=price.per,
    )
    assert contract.instrument_id == quantity.dimension.instrument_id
    amount = price.amount(multiplier.apply(quantity))
    assert amount.value == Decimal("420025.00")
    synthetic = QuerySummary.collect(
        (
            QueryBatch(
                "f" * 64,
                "cutoff",
                ("price", "quantity"),
                (
                    QueryMarketRow(
                        ("synthetic.future", "trade", instrument), (price.value, quantity.value)
                    ),
                ),
                (),
            ),
        )
    )
    assert synthetic["rows"] == 1 and synthetic["evidence"] == ()
    try:
        price.amount(quantity)
    except UnitError as error:
        print("Contract unit refusal:", error)
    else:
        raise AssertionError("implicit contract multiplier accepted")
    failures = []
    unsupported = local / "unsupported-family.json"
    unsupported.write_bytes(
        (inputs / "binance-archive.json")
        .read_bytes()
        .replace(b'"product": "spot"', b'"product": "future"')
    )
    try:
        Configuration.read(unsupported)
    except ValueError as error:
        failures.append(("spot adapter with future product", str(error)))
    else:
        raise AssertionError("spot adapter accepted a future product")
    query_fields = msgspec.json.decode(codec.encode_json(query), type=dict[str, object])
    for label, change in (
        ("lifecycle", {"lifecycle": "cash_settlement"}),
        ("adapter", {"adapter": "futures"}),
        ("unsupported instrument", {"instruments": (instrument,)}),
        ("byte budget", {"max_bytes": 1}),
    ):
        bad_path = local / "invalid.json"
        bad_path.write_bytes(codec.encode_json(query_fields | change))
        try:
            inspect_eda(bad_path, local / "snapshots", store, report=evidence.report)
        except ValueError as error:
            failures.append((label, str(error)))
        else:
            raise AssertionError(f"accepted unsupported {label}")
    (local / "extension.json").write_bytes(
        codec.encode_json(
            {
                "family": "synthetic_future",
                "projection_only": True,
                "summary": synthetic,
                "quantity": quantity,
                "units_per_contract": multiplier.value,
                "amount": amount,
                "failures": failures,
            }
        )
    )
    print("Installed package:", installed)
    print("Query/summary:", summary["query_identity"], summary["summary_identity"])
    print(
        "Rows/batches:",
        summary["rows"],
        summary["batches"],
        "; query seconds:",
        summary["query_seconds"],
    )
    print(
        "Process peak RSS / input blocks:",
        summary["process_peak_rss_bytes"],
        summary["process_input_blocks"],
    )
    print("Verified query opens:", load_opens, "; replay source rows:", len(evidence.sources))
    print("Synthetic contract: 2 contracts x 50 units x 4200.25 USD =", amount.value, "USD")
    print("Required refusals:", failures)
    print("Retained sample, resolved query and attempt records:", local)


if __name__ == "__main__":
    main()
