"""Exercise installed feature/label studies over saved, evidenced synthetic archive revisions."""

from __future__ import annotations

# standard library imports
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
import research.features
from applications.explore import inspect_experiment
from configuration import Configuration
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import SourceRequest
from market_data.datasets import DatasetPublication
from market_data.storage import RawFiles, RawStore
from market_data.validation import Correction, QualityPolicy, TradeRevision
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import EligibilityAssertions
from research.experiments import AttemptStore, SampleInterval, TemporalSplit, TimeWindow
from research.exploration import EdaQuery, FeatureStudy, ResearchSelection, TradeSelection
from research.features import TrailingReturn, WindowPolicy
from research.labels import ForwardReturn
from serialization import DomainCodec

_START = datetime(2024, 6, 1, tzinfo=UTC)
_CODEC = DomainCodec()
_LIMIT = 262_144


class _StudyFixture:
    """Bind actual native archive decoding, correction evidence and retained stores."""

    def __init__(self, inputs: Path, output: Path) -> None:
        """Bind copied fixture configuration and a fresh outside-checkout output directory."""
        self.inputs, self.output = inputs, output
        self.raw = RawStore(output / "raw")

    def publish(self) -> ResearchSelection:
        """Publish two independent instruments with explicit synthetic revision availability."""
        config = Configuration.read(self.inputs / "binance-archive.json")
        catalog = _CODEC.decode_json(
            (self.inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        run = config.resolve("spot-comparison", catalog, implementation_identity="a" * 64)
        descriptors = []
        publisher = DatasetPublication(SourceAdapters(), "a" * 64)
        for instrument, prices in zip(
            run.instruments, (("100.03", "100.04", "100.05"), ("20", "22", "24")), strict=True
        ):
            request = SourceRequest.partition(replace(run, instruments=(instrument,)))[0]
            rows = b""
            for trade_id, (second, price) in enumerate(zip((0, 9, 19), prices, strict=True)):
                event_ms = 1717200000000 + second * 1000
                for value in ("1.00", price):
                    rows += f"{trade_id},{value},2.0,2,{event_ms},true,true\n".encode()
            source = self.output / f"{instrument.symbol}.zip"
            member = ZipInfo(f"{instrument.symbol}-trades-2024-06-01.csv")
            member.compress_type = ZIP_DEFLATED
            with ZipFile(source, "w") as archive:
                archive.writestr(member, rows)
            origin = RawFiles.describe(
                source,
                request=request.binding,
                retrieval_reference="synthetic:diagnostic-revisions",
                ts_received=_START + timedelta(days=1),
                ts_ingested=_START + timedelta(days=1),
            )
            self.raw.publish(source, descriptor=origin, request=request.binding)
            descriptors.append(origin)
        acquisition = AcquisitionManifest(run=run, completed=tuple(descriptors))
        corrections: list[Correction] = []
        for partition in acquisition.partitions():
            occurrences = tuple(publisher.occurrences(partition, self.raw, max_bytes=_LIMIT))
            for index, second in enumerate((0, 9, 19)):
                corrections.append(
                    Correction(
                        supersedes=TradeRevision(occurrences=(occurrences[2 * index],)).identity,
                        replacement=TradeRevision(
                            occurrences=(occurrences[2 * index + 1],)
                        ).identity,
                        ts_published=_START + timedelta(seconds=second + 1),
                        ts_available=_START + timedelta(seconds=second + 1),
                        evidence_reference="synthetic:diagnostic-correction-availability",
                    )
                )
        identity = publisher.publish(
            (acquisition,),
            self.raw,
            self.output / "snapshots",
            max_bytes=_LIMIT,
            policy=QualityPolicy(use="exploratory", known_at=_START, max_gap=timedelta(hours=1)),
            eligibility=EligibilityAssertions.read(
                self.inputs / "membership-corrections.json", catalog=catalog
            ),
            corrections={run.identity: tuple(corrections)},
        )
        return ResearchSelection(
            inputs=(
                TradeSelection(
                    name="prices",
                    query=EdaQuery(
                        snapshot_id=identity,
                        precedence=tuple(
                            (item.source, "trade", item.instrument_id) for item in run.instruments
                        ),
                        instruments=tuple(item.instrument_id for item in run.instruments),
                        start=_START,
                        end=_START + timedelta(seconds=30),
                        known_at=_START + timedelta(seconds=30),
                        columns=("revision",),
                        mode="cutoff",
                        batch_size=1,
                        max_bytes=_LIMIT,
                    ),
                ),
            )
        )

    def study(self, selection: ResearchSelection) -> FeatureStudy:
        """Configure one decision, two instruments and independently delayed forward outcomes."""
        return FeatureStudy(
            family="price-diagnostic",
            question="Inspect exact trailing and forward observed returns",
            selection=selection,
            partition="validation",
            decisions=TimeWindow(
                start=_START + timedelta(seconds=10), end=_START + timedelta(seconds=11)
            ),
            split=TemporalSplit(
                training=None,
                fit_cutoff=None,
                fit_mode="none",
                samples=(),
                embargo_us=0,
                rationale="Fixed diagnostic; label information ends before the holdout.",
                validation=TimeWindow(start=_START, end=_START + timedelta(minutes=1)),
                holdout=TimeWindow(
                    start=_START + timedelta(minutes=2), end=_START + timedelta(minutes=3)
                ),
            ),
            feature=TrailingReturn(
                policy=WindowPolicy(
                    lookback_us=10_000_000, min_trades=2, max_staleness_us=2_000_000
                ),
                cadence_us=10_000_000,
                processing_delay_us=0,
            ),
            label=ForwardReturn(
                horizon_us=10_000_000,
                availability_delay_us=1_000_000,
                policy=WindowPolicy(
                    lookback_us=10_000_000, min_trades=1, max_staleness_us=2_000_000
                ),
            ),
        )


def main() -> None:
    """Publish real saved fixtures or reproduce the completed study in a fresh installed process.

    Raises:
        AssertionError: Numeric, causal, identity, installed or retained-attempt behavior differs.
    """
    inputs, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    assert "site-packages" in Path(research.features.__file__).parts
    if len(sys.argv) == 3:
        output.mkdir()
        (output / "raw").mkdir()
        (output / "snapshots").mkdir()
        fixture = _StudyFixture(inputs, output)
        study = fixture.study(fixture.publish())
        (output / "study.json").write_bytes(_CODEC.encode_json(study))
    history = inspect_experiment(
        output / "study.json",
        output / "snapshots",
        RawStore(output / "raw"),
        attempts=output / "attempts",
    )
    assert history.status == "completed"
    payload = history.events[-1].result
    assert payload is not None
    result = msgspec.json.decode(payload, type=dict[str, msgspec.Raw])
    # NamedTuple result rows are arrays. Independent JSON checks avoid importing formula logic.
    features = msgspec.json.decode(
        result["features"], type=tuple[tuple[str, tuple[msgspec.Raw, ...]], ...]
    )
    labels = msgspec.json.decode(
        result["labels"], type=tuple[tuple[str, tuple[msgspec.Raw, ...]], ...]
    )
    assert [msgspec.json.decode(item[1][-1], type=dict[str, str]) for item in features] == [
        {"numerator": "1", "denominator": "10003"},
        {"numerator": "1", "denominator": "10"},
    ]
    assert [msgspec.json.decode(item[1][-1], type=dict[str, str]) for item in labels] == [
        {"numerator": "1", "denominator": "10004"},
        {"numerator": "1", "denominator": "11"},
    ]
    samples = msgspec.json.decode(result["samples"], type=tuple[SampleInterval, ...])
    assert len(samples) == 2 and all(
        sample.label_available_at == _START + timedelta(seconds=21) for sample in samples
    )
    assert tuple(item[0] for item in features) == tuple(item[0] for item in labels)
    if len(sys.argv) == 3:
        subprocess.run(
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                str(inputs),
                str(output),
                "reopen",
            ],
            check=True,
            timeout=60,
        )
    else:
        retained = AttemptStore(output / "attempts").histories()
        assert len(retained) == 2
        assert retained[0].start.run_identity == retained[1].start.run_identity
        assert retained[0].events[-1].result == retained[1].events[-1].result
    (output / "result.json").write_bytes(payload)
    print("Installed two-instrument feature/label study and fresh-process parity verified.")


if __name__ == "__main__":
    main()
