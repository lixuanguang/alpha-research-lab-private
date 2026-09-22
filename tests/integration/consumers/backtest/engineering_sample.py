"""Prove frozen economic parameters on synthetic witnessed saved inputs, never empirical alpha."""

from __future__ import annotations

# standard library imports
import hashlib
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from applications.backtest import run_configured
from configuration import Configuration
from financial_units import ExactRatio
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import ArchiveCapture, ArchiveTrade, CaptureSlice, SourceRequest
from market_data.datasets import DatasetInput, DatasetPublication
from market_data.storage import RawFiles, RawStore
from market_data.validation import (
    EvidenceCitation,
    ProviderDocument,
    QualityPolicy,
    SourceQualification,
    TradeAvailability,
    TradeRevision,
)
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import (
    EligibilityAssertion,
    EligibilityAssertions,
    EligibilityEvidence,
)
from research.experiments import (
    AttemptStore,
    BacktestRun,
    BenchmarkPeriod,
    ClearMLDestination,
    ClearMLPublication,
    EconomicReport,
    PublicationReceipt,
    ReportPolicy,
    ResultManifest,
    TimeWindow,
)
from serialization import DomainCodec
from simulation import BacktestSpec, EconomicResult


class _EngineeringSample:
    """Exercise existing saved-input, attempt, report and recovery owners outside a checkout."""

    @staticmethod
    def prepare(inputs: Path, output: Path, *, qualified: bool = False) -> None:
        """Publish native-verified synthetic inputs with hypothetical eligibility."""
        codec = DomainCodec()
        spec = codec.decode_json((inputs / "p1-btcusdt-return-v1.json").read_bytes(), BacktestSpec)
        catalog = codec.decode_json(
            (inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        run = Configuration.read(inputs / "binance-archive.json").resolve(
            "btc-archive",
            catalog,
            implementation_identity="a" * 64,
        )
        request = SourceRequest.partition(run)[0]
        observations: tuple[tuple[int, str], ...] = (
            (50, "100"),
            (110, "110"),
            (121, "111"),
            (170, "105"),
            (181, "104"),
        )
        observations += tuple((60 * minute + 50, "105") for minute in range(3, 60))
        rows: list[bytes] = []
        native: list[list[bytes]] = [[] for _ in range(6)]
        for trade_id, (second, price) in enumerate(observations):
            timestamp = 1717200000000 + second * 1000
            rows.append(
                f"{trade_id},{price},2,{Decimal(price) * 2},{timestamp},true,true\n".encode()
            )
            instant = (
                (spec.start + timedelta(seconds=second, microseconds=1))
                .isoformat()
                .replace("+00:00", "Z")
            )
            native[second // 600].append(
                (
                    f'{instant} {{"stream":"btcusdt@trade","data":{{"e":"trade",'
                    f'"E":{timestamp},"s":"BTCUSDT","t":{trade_id},"p":"{price}",'
                    f'"q":"2","T":{timestamp},"m":true}}}}\n'
                ).encode()
            )
        source = output / "synthetic.zip"
        member = ZipInfo("BTCUSDT-trades-2024-06-01.csv")
        member.compress_type = ZIP_DEFLATED
        with ZipFile(source, "w") as archive:
            archive.writestr(member, b"".join(rows))
        origin = RawFiles.describe(
            source,
            request=request.binding,
            retrieval_reference="synthetic:engineering-sample",
            ts_received=spec.end,
            ts_ingested=spec.end,
        )
        raw = RawStore(output / "raw")
        (output / "raw").mkdir()
        (output / "snapshots").mkdir()
        raw.publish(source, descriptor=origin, request=request.binding)
        capture = ArchiveCapture(
            request_identity=request.identity,
            archive_sha256=origin.sha256,
            access_reference="synthetic native fixture; no empirical source assertion",
            slices=tuple(
                CaptureSlice(
                    start=spec.start + timedelta(minutes=10 * i),
                    minutes=10,
                    received_at=spec.end,
                    payload=b"".join(lines),
                )
                for i, lines in enumerate(native)
            ),
        )
        # The source_evidence branch is exercised with fabricated fixture facts only.
        # This record must never be attached to the actual Binance archive.
        eligibility = EligibilityAssertions(
            catalog=catalog,
            assertions=(
                EligibilityAssertion(
                    instrument_id=spec.binding[2],
                    valid_from=spec.start,
                    valid_to=spec.end,
                    ts_knowledge=spec.start,
                    state="included",
                    reason="Synthetic software fixture only",
                    evidence=EligibilityEvidence(
                        identity="synthetic:reference-facts",
                        basis="source_evidence",
                        recorded_at=spec.end,
                        available_at=spec.start,
                    ),
                ),
            ),
        )
        selected = DatasetInput(
            acquisition=AcquisitionManifest(run=run, completed=(origin,)),
            policy=QualityPolicy(
                use="witnessed", known_at=spec.start, max_gap=timedelta(seconds=60)
            ),
            eligibility=eligibility,
            capture=capture,
        )
        publisher = DatasetPublication(SourceAdapters(), "a" * 64)
        if qualified:
            payload = (
                b"SYNTHETIC PROVIDER REVIEW FIXTURE; not empirical evidence. "
                b"The attached native fixture and archive enumerate every original trade, "
                b"with no revisions through 01:00 UTC. Complete [00:00,01:00) coverage. "
                b"Instrument status and selected units were available at 00:00. "
                b"Each full archive version was published at event time and available 1us later."
            )
            document = ProviderDocument(
                sha256=hashlib.sha256(payload).hexdigest(),
                issuer="synthetic test provider",
                reference="synthetic:installed-admission",
                published_at=spec.end,
                received_at=spec.end,
                payload=payload,
            )
            citation = EvidenceCitation(
                document_sha256=document.sha256, locator="entire fixture statement"
            )
            facts: list[TradeAvailability] = []
            for item in publisher.occurrences(selected.acquisition, raw, max_bytes=4_000_000):
                assert isinstance(item.event, ArchiveTrade)
                facts.append(
                    TradeAvailability(
                        version_identity=TradeRevision(occurrences=(item,)).identity,
                        published_at=item.event.ts_event,
                        available_at=item.event.ts_event + timedelta(microseconds=1),
                        evidence=citation,
                    )
                )
            selected = replace(
                selected,
                policy=replace(selected.policy, use="causal"),
                eligibility=replace(
                    eligibility,
                    assertions=(
                        replace(
                            eligibility.assertions[0],
                            evidence=replace(
                                eligibility.assertions[0].evidence, identity=document.sha256
                            ),
                        ),
                    ),
                ),
                qualification=SourceQualification(
                    request_identity=request.identity,
                    archive_sha256s=(origin.sha256,),
                    start=spec.start,
                    end=spec.end,
                    history_through=spec.end,
                    trade_count=len(facts),
                    documents=(document,),
                    instrument=citation,
                    coverage=citation,
                    revision_history=citation,
                    versions=tuple(facts),
                    reviewer="synthetic fixture reviewer",
                    review_reference="synthetic:installed-test",
                    reviewed_at=spec.end,
                ),
            )
        bad = replace(selected, capture=replace(capture, archive_sha256="b" * 64))
        try:
            publisher.publish((bad,), raw, output / "snapshots", max_bytes=4_000_000)
        except ValueError:
            assert not tuple((output / "snapshots").iterdir())
        else:
            raise AssertionError("mismatched evidence published a snapshot")
        identity = publisher.publish((selected,), raw, output / "snapshots", max_bytes=4_000_000)
        if qualified:
            input_path = output / "dataset-input.json"
            input_path.write_bytes(codec.encode_json(selected))
            command = subprocess.run(
                [
                    str(Path(sys.executable).with_name("alpha-dataset")),
                    "publish",
                    "--inputs",
                    str(input_path),
                    "--store",
                    str(output / "raw"),
                    "--snapshots",
                    str(output / "snapshots"),
                    "--max-bytes",
                    "4000000",
                ],
                cwd=output,
                check=True,
                capture_output=True,
                timeout=20,
            )
            completion = msgspec.json.decode(
                command.stdout.splitlines()[-1], type=dict[str, str | int | None]
            )
            published = completion["snapshot_id"]
            assert isinstance(published, str) and completion["scope"] == "causal_qualified"
            assert completion["status"] == "complete"
            identity = published
            (output / "publication.jsonl").write_bytes(command.stdout)
        zero = ExactRatio.from_fraction(Fraction(0))
        for name in ("p1-btcusdt-return-v1", "p1-btcusdt-no-trade-v1"):
            economics = codec.decode_json((inputs / f"{name}.json").read_bytes(), BacktestSpec)
            configuration = BacktestRun(
                schema_version="configured-engineering-sample-v1",
                family=name,
                snapshot_id=identity,
                economics=economics,
                split=None,
                engineering_sample=TimeWindow(start=economics.start, end=economics.end),
                report=ReportPolicy(
                    benchmark_name="frozen non-interest-bearing cash control",
                    benchmark=tuple(
                        BenchmarkPeriod(end=spec.start + timedelta(minutes=i), value=zero)
                        for i in range(1, 61)
                    ),
                    cadence_seconds=60,
                    periods_per_year=525600,
                    annual_risk_free=zero,
                ),
            )
            (output / f"{name}.json").write_bytes(codec.encode_json(configuration))
            (output / name).mkdir()

    @staticmethod
    def unavailable(self: ClearMLPublication, attempt_id: str) -> PublicationReceipt:
        """Leave publication queued while exercising real local reports and attempt transitions."""
        raise ConnectionError("synthetic unavailable transport; local output remains durable")

    @staticmethod
    def execute(output: Path, *, resume: bool, qualified: bool = False) -> None:
        """Reopen installed saved inputs and compare reports across independent fresh processes."""
        codec = DomainCodec()
        destination = ClearMLDestination(
            project="engineering-sample",
            api_uri="http://127.0.0.1:18008",
            files_uri="http://127.0.0.1:18081",
        )
        for name in ("p1-btcusdt-return-v1", "p1-btcusdt-no-trade-v1"):
            attempts = output / name
            spec = BacktestRun.read(output / f"{name}.json")
            for stage in ("resume", "repeat") if resume else ("complete", "checkpoint"):
                before = {h.start.attempt_id for h in AttemptStore(attempts).histories()}
                with patch.object(ClearMLPublication, "publish", _EngineeringSample.unavailable):
                    try:
                        run_configured(
                            output / f"{name}.json",
                            output / "snapshots",
                            output / "raw",
                            attempts=attempts,
                            max_bytes=4_000_000,
                            tracking=destination,
                            stop_at=spec.economics.start + timedelta(seconds=120)
                            if stage == "checkpoint"
                            else None,
                            resume=output / f"{name}-checkpoint.json"
                            if stage == "resume"
                            else None,
                        )
                    except ConnectionError:
                        pass
                    else:
                        raise AssertionError("publication failure was hidden")
                store = AttemptStore(attempts)
                history = next(h for h in store.histories() if h.start.attempt_id not in before)
                attempt = history.start.attempt_id
                assert history.start.spec.split is None
                assert not any(event.status == "holdout_consumed" for event in history.events)
                if stage == "checkpoint":
                    assert history.status == "abandoned"
                    (output / f"{name}-checkpoint.json").write_bytes(
                        store.artifact(attempt, "checkpoint")
                    )
                    continue
                assert history.status == "completed"
                manifest = ResultManifest.read(store, attempt)
                result = codec.decode_json(
                    store.artifact(attempt, "economic-reference"), EconomicResult
                )
                report = codec.decode_json(store.artifact(attempt, "report"), EconomicReport)
                expected = Decimal("1000") if "no-trade" in name else Decimal("999.99276500")
                assert result.terminal.nav.value == expected
                balance = result.checkpoint.state.trace[-1].balance
                assert balance.cash.value == expected and balance.holding.value == 0
                if "no-trade" in name:
                    assert not result.checkpoint.state.ledger.fills
                    assert balance.fees.value == balance.slippage.value == 0
                else:
                    assert len(result.checkpoint.state.ledger.fills) == 2
                    assert balance.fees.value == Decimal("0.000215")
                    assert balance.slippage.value == Decimal("0.00002")
                    assert result.terminal.gross.value == Fraction(-7, 1000)
                    assert result.terminal.gross.value - Fraction(balance.fees.value) - Fraction(
                        balance.slippage.value
                    ) == Fraction(result.terminal.net.value)
                assert Decimal(report.net_profit) == expected - Decimal("1000")
                assert any("engineering sample" in item for item in report.limitations)
                assert any("upstream completeness" in item for item in report.limitations)
                if qualified:
                    assert any("causal_qualified inputs" in item for item in report.limitations)
                    assert any("external review" in item for item in report.limitations)
                record = codec.encode_json(manifest)
                expected_path = output / f"{name}-expected.json"
                if stage == "complete":
                    expected_path.write_bytes(record)
                else:
                    assert expected_path.read_bytes() == record
                print(
                    name,
                    stage,
                    "NAV",
                    result.terminal.nav.value,
                    "manifest",
                    hashlib.sha256(record).hexdigest(),
                )


def main() -> None:
    """Compose saved synthetic witnessed publication and fresh-process frozen-parameter proof.

    Raises:
        AssertionError: Native admission, numerical reconciliation or reproduction differs.
    """
    inputs, output = Path(sys.argv[1]), Path(sys.argv[2])
    if len(sys.argv) > 3:
        _EngineeringSample.execute(output, resume=True, qualified=sys.argv[3] == "qualified")
        return
    for qualified in (False, True):
        destination = output.with_name(output.name + "-qualified") if qualified else output
        destination.mkdir()
        _EngineeringSample.prepare(inputs, destination, qualified=qualified)
        _EngineeringSample.execute(destination, resume=False, qualified=qualified)
        subprocess.run(
            [
                sys.executable,
                "-I",
                __file__,
                str(inputs),
                str(destination),
                "qualified" if qualified else "resume",
            ],
            check=True,
            cwd=destination,
        )


if __name__ == "__main__":
    main()
