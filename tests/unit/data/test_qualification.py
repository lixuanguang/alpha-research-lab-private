"""Exercise strict provider qualification with explicitly synthetic saved archive revisions."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

# third party library imports
import msgspec
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from applications.backtest import run_backtest
from applications.publish_dataset import main as dataset_main
from configuration import Configuration
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import ArchiveTrade, SourceRequest
from market_data.datasets import DatasetInput, DatasetManifest, DatasetPublication, SnapshotStore
from market_data.query import QueryMarketRow, QueryReader
from market_data.storage import RawFiles, RawStore
from market_data.validation import (
    Correction,
    EvidenceCitation,
    ProviderDocument,
    QualityPolicy,
    QualityReport,
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
from serialization import DomainCodec
from simulation import BacktestSpec, EconomicResult

_ROOT = Path(__file__).parents[3]
_START = datetime(2024, 6, 1, tzinfo=UTC)
_END = _START + timedelta(hours=1)
_CODEC = DomainCodec()


class _Inputs(msgspec.Struct, frozen=True):
    """Share explicitly synthetic evidence within one isolated test directory."""

    selected: DatasetInput
    request: SourceRequest
    raw: RawStore
    publisher: DatasetPublication
    snapshots: Path

    def report(self, selected: DatasetInput) -> QualityReport:
        """Return the actual shared admission outcome, including refused inputs."""
        return self.publisher.validate_partition(
            selected.acquisition,
            self.raw,
            max_bytes=1_000_000,
            policy=selected.policy,
            eligibility=selected.eligibility,
            corrections=selected.corrections,
            qualification=selected.qualification
            if isinstance(selected.qualification, SourceQualification)
            else None,
            prior_acquisitions=selected.acquisitions[1:],
        )


class TestSourceQualification:
    """Distinguish review trust from mechanically enforced integrity and causal constraints."""

    @pytest.fixture()
    def inputs(self, tmp_path: Path) -> _Inputs:
        """Create two independent archives and a fully retained hypothetical review.

        Args:
            tmp_path: Per-test writable directory.

        Returns:
            Strict selection retaining an original and one later correction.
        """
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        run = Configuration.read(_ROOT / "configs/data-jobs/binance-archive.json").resolve(
            "btc-archive", catalog, implementation_identity="a" * 64
        )
        request = SourceRequest.partition(run)[0]
        raw_path, snapshots = tmp_path / "raw", tmp_path / "snapshots"
        raw_path.mkdir()
        snapshots.mkdir()
        raw = RawStore(raw_path)
        publisher = DatasetPublication(SourceAdapters(), "a" * 64)
        acquisitions: list[AcquisitionManifest] = []
        for name, price in (("original", "100"), ("corrected", "101")):
            path = tmp_path / f"{name}.zip"
            with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr(
                    "BTCUSDT-trades-2024-06-01.csv",
                    f"12,{price},2,{int(price) * 2},1717200000000,true,true\n"
                    "13,102,2,204,1717200060000,true,true\n",
                )
            descriptor = RawFiles.describe(
                path,
                request=request.binding,
                retrieval_reference=f"synthetic:{name}",
                ts_received=_END,
                ts_ingested=_END,
            )
            raw.publish(path, descriptor=descriptor, request=request.binding, compress=False)
            acquisitions.append(AcquisitionManifest(run=run, completed=(descriptor,)))
        old, new = acquisitions
        old_rows = tuple(publisher.occurrences(old, raw, max_bytes=1_000_000))
        new_rows = tuple(publisher.occurrences(new, raw, max_bytes=1_000_000))
        payload = (
            b"SYNTHETIC SOFTWARE FIXTURE, NOT PROVIDER EVIDENCE. "
            b"Status/units available at 00:00; BTCUSDT trades throughout [00:00,01:00). "
            b"Complete count: 2 trades. Original ID12 price100 qty2 quote200 best_match=true "
            b"published00:00 available00:00:01; correction price101 quote202 "
            b"published00:01:50 available00:02. ID13 price102 qty2 quote204 "
            b"published00:01 available00:01:01. All revisions enumerated through01:00."
        )
        document = ProviderDocument(
            sha256=hashlib.sha256(payload).hexdigest(),
            issuer="synthetic fixture provider",
            reference="synthetic:review-test",
            published_at=_END,
            received_at=_END,
            payload=payload,
        )
        citation = EvidenceCitation(
            document_sha256=document.sha256, locator="entire synthetic record"
        )
        original = TradeRevision(occurrences=(old_rows[0],)).identity
        corrected = TradeRevision(occurrences=(new_rows[0],)).identity
        unchanged = TradeRevision(occurrences=(new_rows[1],)).identity
        qualification = SourceQualification(
            request_identity=request.identity,
            archive_sha256s=tuple(a.completed[0].sha256 for a in acquisitions),
            start=_START,
            end=_END,
            history_through=_END,
            trade_count=2,
            documents=(document,),
            instrument=citation,
            coverage=citation,
            revision_history=citation,
            versions=tuple(
                TradeAvailability(
                    version_identity=identity,
                    published_at=_START + timedelta(seconds=published),
                    available_at=_START + timedelta(seconds=available),
                    evidence=citation,
                )
                for identity, published, available in (
                    (original, 0, 1),
                    (corrected, 110, 120),
                    (unchanged, 60, 61),
                )
            ),
            reviewer="synthetic test reviewer",
            review_reference="synthetic:fixture-only",
            reviewed_at=_END,
        )
        selected = DatasetInput(
            acquisition=new,
            prior_acquisitions=(old,),
            qualification=qualification,
            policy=QualityPolicy(use="causal", known_at=_START, max_gap=timedelta(hours=1)),
            eligibility=EligibilityAssertions(
                catalog=catalog,
                assertions=(
                    EligibilityAssertion(
                        instrument_id=request.instrument.instrument_id,
                        valid_from=_START,
                        valid_to=_END,
                        ts_knowledge=_START,
                        state="included",
                        reason="synthetic fixture only",
                        evidence=EligibilityEvidence(
                            identity=document.sha256,
                            basis="source_evidence",
                            recorded_at=_END,
                            available_at=_START,
                        ),
                    ),
                ),
            ),
            corrections=(
                Correction(
                    supersedes=original,
                    replacement=corrected,
                    ts_published=_START + timedelta(seconds=110),
                    ts_available=_START + timedelta(seconds=120),
                    evidence_reference=document.sha256,
                ),
            ),
        )
        return _Inputs(selected, request, raw, publisher, snapshots)

    def test_publish_reopen_and_inclusive_correction_cutoffs(
        self, inputs: _Inputs, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Reproduce strict admission and retain the old value until the correction is usable."""
        selected = inputs.selected
        qualification = selected.qualification
        assert isinstance(qualification, SourceQualification)
        path = tmp_path / "qualification.json"
        path.write_bytes(_CODEC.encode_json(qualification))
        assert SourceQualification.read(path, max_bytes=1_000_000) == qualification
        report = inputs.report(selected)
        assert report.scope == "causal_qualified"
        assert report.invalid_count == report.gap_count == 0
        assert report.duplicate_count == 1
        assert "recorder coverage unknown" not in report.reasons
        identity = inputs.publisher.publish(
            (selected,), inputs.raw, inputs.snapshots, max_bytes=1_000_000
        )
        manifest = SnapshotStore(inputs.snapshots, inputs.raw, readers=SourceAdapters()).read(
            identity, max_bytes=1_000_000
        )
        assert manifest.tier == "qualified" and manifest.scope == "causal_qualified"
        assert manifest.canonical_schema == "canonical-trade-partition-qualified"
        assert manifest.availability_policy == "qualified-provider-reviewed"
        assert _CODEC.decode_json(_CODEC.encode_json(manifest), DatasetManifest) == manifest
        numbered = inputs.snapshots.parent / "numbered-manifest.json"
        numbered.write_bytes(
            _CODEC.encode_json(manifest).replace(b'"tier":"qualified"', b'"schema_version":"3"')
        )
        with pytest.raises(ValueError, match="unsupported dataset manifest schema"):
            DatasetManifest.read(
                numbered,
                identity=identity,
                partitions=inputs.snapshots / identity,
                store=inputs.raw,
                max_bytes=1_000_000,
                readers=SourceAdapters(),
            )
        binding = (
            inputs.request.instrument.source,
            "trade",
            inputs.request.instrument.instrument_id,
        )
        reader = QueryReader.read(
            inputs.snapshots,
            inputs.raw,
            readers=SourceAdapters(),
            identity=identity,
            max_bytes=1_000_000,
            precedence=(binding,),
        )
        for seconds, expected in (
            (0, ()),
            (1, (Decimal("100"),)),
            (119, (Decimal("100"),)),
            (120, (Decimal("101"),)),
        ):
            batches = tuple(
                reader.batches(
                    (binding[2],),
                    start=_START,
                    end=_START + timedelta(seconds=1),
                    known_at=_START + timedelta(seconds=seconds),
                    columns=("price", "revision"),
                    batch_size=1,
                )
            )
            rows = tuple(row for batch in batches for row in batch.rows)
            assert all(batch.evidence[0].scope == "causal_qualified" for batch in batches)
            assert (
                tuple(row.values[0] for row in rows if isinstance(row, QueryMarketRow)) == expected
            )
            for row in rows:
                assert isinstance(row, QueryMarketRow)
                version = row.values[1]
                assert isinstance(version, TradeRevision)
                event = version.occurrences[0].event
                assert isinstance(event, ArchiveTrade)
                assert event.ts_source_received is None and event.ts_knowledge is None
        economic = _CODEC.decode_json(
            (_ROOT / "configs/backtests/p1-btcusdt-return.json").read_bytes(), BacktestSpec
        )
        result = run_backtest(reader, economic)
        assert isinstance(result, EconomicResult)
        assert any("causal_qualified inputs" in item for item in result.limitations)
        assert (
            inputs.publisher.publish((selected,), inputs.raw, inputs.snapshots, max_bytes=1_000_000)
            == identity
        )
        serialized = tmp_path / "qualified-input.json"
        serialized.write_bytes(_CODEC.encode_json(selected))
        assert (
            dataset_main(
                [
                    "publish",
                    "--store",
                    str(inputs.snapshots.parent / "raw"),
                    "--snapshots",
                    str(inputs.snapshots),
                    "--max-bytes",
                    "1000000",
                    "--inputs",
                    str(serialized),
                ]
            )
            == 0
        )
        completion = msgspec.json.decode(
            capsys.readouterr().out.splitlines()[-1], type=dict[str, str | int | None]
        )
        assert isinstance(completion["snapshot_id"], str)
        assert completion["scope"] == "causal_qualified"
        assert completion["status"] == "complete"

    @pytest.mark.parametrize(
        "change",
        [
            "request",
            "archive",
            "interval",
            "count",
            "missing",
            "extra",
            "clock",
            "reference",
            "eligibility",
            "late_status",
            "gap",
        ],
    )
    def test_refuse_mismatched_or_incomplete_facts(self, inputs: _Inputs, change: str) -> None:
        """Reject specific evidence defects atomically, even when native rows are valid."""
        selected = inputs.selected
        evidence = selected.qualification
        assert isinstance(evidence, SourceQualification)
        if change == "request":
            evidence = replace(evidence, request_identity="b" * 64)
        elif change == "archive":
            evidence = replace(evidence, archive_sha256s=("b" * 64,))
        elif change == "interval":
            evidence = replace(evidence, start=_START + timedelta(seconds=1))
        elif change == "count":
            evidence = replace(evidence, trade_count=3)
        elif change == "missing":
            evidence = replace(evidence, versions=evidence.versions[1:])
        elif change == "extra":
            extra_versions: tuple[TradeAvailability, ...] = (
                *evidence.versions,
                replace(evidence.versions[0], version_identity="b" * 64),
            )
            evidence = replace(
                evidence,
                versions=extra_versions,
            )
        elif change == "clock":
            evidence = replace(
                evidence,
                versions=(
                    evidence.versions[0],
                    replace(evidence.versions[1], available_at=_START + timedelta(seconds=121)),
                    evidence.versions[2],
                ),
            )
        elif change == "reference":
            selected = replace(
                selected,
                corrections=(replace(selected.corrections[0], evidence_reference="unretained"),),
            )
        elif change == "eligibility":
            assertion = selected.eligibility.assertions[0]
            selected = replace(
                selected,
                eligibility=replace(
                    selected.eligibility,
                    assertions=(
                        replace(
                            assertion, evidence=replace(assertion.evidence, identity="unretained")
                        ),
                    ),
                ),
            )
        elif change == "late_status":
            selected = replace(
                selected,
                eligibility=replace(
                    selected.eligibility,
                    assertions=(
                        replace(
                            selected.eligibility.assertions[0],
                            ts_knowledge=_START + timedelta(seconds=1),
                        ),
                    ),
                ),
            )
        else:
            selected = replace(
                selected, policy=replace(selected.policy, max_gap=timedelta(seconds=1))
            )
        selected = replace(selected, qualification=evidence)
        report = inputs.report(selected)
        assert report.scope == "rejected" and report.canonical is None
        with pytest.raises(ValueError, match="publication refused"):
            inputs.publisher.publish((selected,), inputs.raw, inputs.snapshots, max_bytes=1_000_000)
        assert not tuple(inputs.snapshots.iterdir())

    def test_document_integrity_review_clocks_and_inventory(
        self, inputs: _Inputs, tmp_path: Path
    ) -> None:
        """Reject tampered documents, dangling citations, duplicate versions and future claims."""
        evidence = inputs.selected.qualification
        assert isinstance(evidence, SourceQualification)
        with pytest.raises(ValueError, match="bytes"):
            replace(evidence.documents[0], payload=b"altered")
        with pytest.raises(ValueError, match="not retained"):
            replace(evidence, coverage=replace(evidence.coverage, document_sha256="b" * 64))
        with pytest.raises(ValueError, match="duplicated"):
            duplicated: tuple[TradeAvailability, ...] = (*evidence.versions, evidence.versions[0])
            replace(evidence, versions=duplicated)
        with pytest.raises(ValueError, match="future interval"):
            replace(
                evidence,
                documents=(
                    replace(evidence.documents[0], published_at=_END - timedelta(seconds=1)),
                ),
            )
        with pytest.raises(ValueError, match="ordered clocks"):
            replace(evidence, reviewed_at=_END - timedelta(seconds=1))
        path = tmp_path / "evidence.json"
        path.write_bytes(_CODEC.encode_json(evidence))
        with pytest.raises(ValueError, match="max_bytes"):
            SourceQualification.read(path, max_bytes=10)
        force_setattr(evidence.documents[0], "payload", b"unsafe mutation")
        with pytest.raises(ValueError, match="bytes"):
            inputs.report(inputs.selected)

    def test_unknowns_and_old_schemas_remain_fail_closed(self, inputs: _Inputs) -> None:
        """No strict bundle is inferred from native rows, authored status or schema labels."""
        selected = replace(
            inputs.selected,
            qualification=None,
            prior_acquisitions=(),
            corrections=(),
        )
        report = inputs.report(selected)
        assert report.scope == "rejected"
        assert "strict causal admission requires reviewed provider qualification" in report.reasons
        with pytest.raises(ValueError, match="qualification"):
            replace(inputs.selected, policy=replace(inputs.selected.policy, use="exploratory"))
        manifest, _ = inputs.publisher.assemble((inputs.selected,), inputs.raw, max_bytes=1_000_000)
        with pytest.raises(ValueError, match="tier differs"):
            replace(manifest, tier="exploratory")

    @pytest.mark.parametrize("damage", ["missing", "changed"])
    def test_reopening_detects_damaged_original_archive(self, inputs: _Inputs, damage: str) -> None:
        """A revised archive cannot hide corruption or absence of its retained predecessor."""
        identity = inputs.publisher.publish(
            (inputs.selected,), inputs.raw, inputs.snapshots, max_bytes=1_000_000
        )
        prior = inputs.selected.acquisitions[1].completed[0]
        raw_path = inputs.snapshots.parent / "raw" / prior.sha256
        if damage == "missing":
            raw_path.unlink()
        else:
            raw_path.chmod(0o600)
            raw_path.write_bytes(b"tampered original archive")
        with pytest.raises(ValueError, match=r"publication refused.*input incomplete"):
            SnapshotStore(inputs.snapshots, inputs.raw, readers=SourceAdapters()).read(
                identity, max_bytes=1_000_000
            )

    def test_midwindow_withdrawal_is_not_hidden_by_early_policy_cutoff(
        self, inputs: _Inputs
    ) -> None:
        """Strict coverage cannot reuse start-of-hour status after a known trading suspension."""
        assertion = inputs.selected.eligibility.assertions[0]
        boundary = _START + timedelta(minutes=30)
        history = replace(
            inputs.selected.eligibility,
            assertions=(
                replace(assertion, valid_to=boundary),
                replace(assertion, valid_from=boundary, state="excluded", ts_knowledge=boundary),
            ),
        )
        report = inputs.report(replace(inputs.selected, eligibility=history))
        assert report.scope == "rejected"
        assert any(
            "historical source eligibility unavailable" in reason for reason in report.reasons
        )

    def test_prior_archive_requires_same_request_and_review(self, inputs: _Inputs) -> None:
        """Version history cannot import another selection or bypass the qualified boundary."""
        selected = inputs.selected
        with pytest.raises(ValueError, match="qualified acquisition history"):
            replace(selected, qualification=None)
        with pytest.raises(ValueError, match="duplicated"):
            replace(selected, prior_acquisitions=(selected.acquisition,))
        with pytest.raises(ValueError, match="foreign"):
            foreign = replace(
                selected.acquisitions[1],
                run=replace(
                    selected.acquisitions[1].run,
                    job=replace(selected.acquisitions[1].run.job, end=_END + timedelta(hours=1)),
                ),
                completed=(),
            )
            replace(selected, prior_acquisitions=(foreign,))
