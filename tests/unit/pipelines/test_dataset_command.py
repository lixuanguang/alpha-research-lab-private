"""Exercise observable saved-acquisition publication and explicit snapshot inspection."""

from __future__ import annotations

# standard library imports
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.configuration import Configuration
from alpha_research.data.datasets import DatasetInput
from alpha_research.data.eligibility import EligibilityAssertions
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.quality import QualityPolicy
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.data.revisions import Correction, TradeRevision
from alpha_research.data.snapshots import SnapshotStore
from alpha_research.pipelines.dataset import dataset_main, iter_occurrences, publish_dataset
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_ROW = b"12,100.00,2.0,200,1717200000000,true,true\n"
_LIMIT = 262_144


class TestDatasetCommand:
    """Keep command failures isolated while exercising real storage and admission."""

    @staticmethod
    def _inputs(root: Path, *, symbol: str = "BTCUSDT", content: bytes = _ROW * 2) -> list[str]:
        """Save a small complete acquisition with explicit policy and evidence files."""
        raw = root / "raw"
        raw.mkdir(exist_ok=True)
        (root / "snapshots").mkdir(exist_ok=True)
        config = Configuration.read(_ROOT / "configs/data-jobs/binance-archive.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        config = replace(config, jobs=(replace(config.jobs[0], universe=symbol[:3].lower()),))
        run = config.resolve("btc-archive", catalog)
        request = SourceRequest.partition(run)[0]
        path = root / "source.zip"
        member = ZipInfo(f"{symbol}-trades-2024-06-01.csv")
        member.compress_type = ZIP_DEFLATED
        with ZipFile(path, "w") as archive:
            archive.writestr(member, content)
        descriptor = RawObject.from_file(
            path,
            request=request,
            retrieval_reference="synthetic:mr16",
            ts_received=datetime(2026, 9, 17, tzinfo=UTC),
            ts_ingested=datetime(2026, 9, 17, tzinfo=UTC),
        )
        RawStore(raw).publish(path, descriptor=descriptor, request=request)
        acquisition = AcquisitionManifest(run=run, completed=(descriptor,))
        acquisition.save(root / f"{symbol}.json")
        history = EligibilityAssertions.read(
            _ROOT / "tests/fixtures/mr12/eligibility.json", catalog=catalog
        )
        (root / "eligibility.json").write_bytes(_CODEC.encode_json(history))
        policy = QualityPolicy(
            use="exploratory", known_at=run.job.start, max_gap=timedelta(hours=1)
        )
        (root / "policy.json").write_bytes(_CODEC.encode_json(policy))
        return [
            "publish",
            "--store",
            str(raw),
            "--snapshots",
            str(root / "snapshots"),
            "--max-bytes",
            str(_LIMIT),
            "--policy",
            str(root / "policy.json"),
            "--eligibility",
            str(root / "eligibility.json"),
            "--manifests",
            str(root / f"{symbol}.json"),
        ]

    @staticmethod
    def _inspect(root: Path, identity: str) -> list[str]:
        """Select an explicit immutable ID with no acquisition or policy file access."""
        return [
            "inspect",
            "--store",
            str(root / "raw"),
            "--snapshots",
            str(root / "snapshots"),
            "--max-bytes",
            str(_LIMIT),
            "--snapshot-id",
            identity,
        ]

    @staticmethod
    def _records(output: str) -> list[dict[str, object]]:
        """Decode typed progress records without coupling assertions to field order."""
        records: list[dict[str, object]] = []
        for line in output.splitlines():
            record: object = json.loads(line)
            assert isinstance(record, dict)
            records.append({str(key): value for key, value in record.items()})
        return records

    def test_publish_repeat_duplicate_ranges_and_inspect(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Keep repeat manifests/content idempotent and report quality on both commands."""
        arguments = self._inputs(tmp_path)
        assert dataset_main(arguments) == 0
        result = capsys.readouterr()
        assert not result.err
        records = self._records(result.out)
        quality = next(row for row in records if row["status"] == "validated")
        assert (quality["invalid_count"], quality["gap_count"], quality["duplicate_count"]) == (
            0,
            0,
            1,
        )
        assert "recorder coverage unknown" in str(quality["reasons"])
        assert [row["status"] for row in records] == [
            "started",
            "started",
            "validated",
            "started",
            "persisted",
            "complete",
        ]
        identity = str(records[-1]["snapshot_id"])
        assert records[-1]["scope"] == "exploratory_degraded"
        before = {p.name: p.stat().st_ino for p in (tmp_path / "snapshots" / identity).iterdir()}
        assert dataset_main([*arguments, arguments[-1]]) == 0
        assert self._records(capsys.readouterr().out)[-1]["snapshot_id"] == identity
        assert {
            p.name: p.stat().st_ino for p in (tmp_path / "snapshots" / identity).iterdir()
        } == before
        (tmp_path / "policy.json").unlink()
        (tmp_path / "BTCUSDT.json").unlink()
        assert dataset_main(self._inspect(tmp_path, identity)) == 0
        inspected = self._records(capsys.readouterr().out)
        assert (
            next(row for row in inspected if row["status"] == "validated")["duplicate_count"] == 1
        )
        assert inspected[-1]["snapshot_id"] == identity

    def test_per_input_evidence_matches_python_publication(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Use the same ordered inputs and publication contract through Python and the CLI."""
        arguments = self._inputs(tmp_path)
        self._inputs(tmp_path, symbol="ETHUSDT")
        policy = _CODEC.decode_json((tmp_path / "policy.json").read_bytes(), QualityPolicy)
        history = _CODEC.decode_json(
            (tmp_path / "eligibility.json").read_bytes(), EligibilityAssertions
        )
        selected = tuple(
            DatasetInput(
                acquisition=_CODEC.decode_json(
                    (tmp_path / f"{symbol}.json").read_bytes(), AcquisitionManifest
                ),
                policy=replace(policy, max_gap=timedelta(minutes=30 + index)),
                eligibility=history,
            )
            for index, symbol in enumerate(("BTCUSDT", "ETHUSDT"))
        )
        paths = []
        for index, item in enumerate(selected):
            path = tmp_path / f"input-{index}.json"
            path.write_bytes(_CODEC.encode_json(item))
            paths.append(str(path))
        command = [*arguments[: arguments.index("--policy")], "--inputs", *paths]
        assert dataset_main(command) == 0
        identity = str(self._records(capsys.readouterr().out)[-1]["snapshot_id"])
        assert (
            publish_dataset(
                (*selected, selected[0]),
                RawStore(tmp_path / "raw"),
                tmp_path / "snapshots",
                max_bytes=_LIMIT,
            )
            == identity
        )
        manifest = SnapshotStore(tmp_path / "snapshots", RawStore(tmp_path / "raw")).read(
            identity, max_bytes=_LIMIT
        )
        assert tuple(part.policy for part in manifest.partitions) == tuple(
            item.policy for item in selected
        )
        assert dataset_main([*command, "--policy", str(tmp_path / "policy.json")]) == 2
        assert "retains its own" in capsys.readouterr().err
        with pytest.raises(ValueError, match="overlapping acquisitions"):
            publish_dataset(
                (selected[0], replace(selected[0], policy=selected[1].policy)),
                RawStore(tmp_path / "raw"),
                tmp_path / "snapshots",
                max_bytes=_LIMIT,
            )

    def test_second_instrument_and_late_failure_expose_no_prefix(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Select another instrument through configuration and reject a bad later partition."""
        btc = self._inputs(tmp_path)
        self._inputs(tmp_path, symbol="ETHUSDT", content=_ROW.replace(b"100.00", b"NaN"))
        combined = [*btc, str(tmp_path / "ETHUSDT.json")]
        assert dataset_main(combined) == 3
        failure = capsys.readouterr()
        assert '"invalid_count":1' in failure.out and '"status":"rejected"' in failure.out
        assert not list((tmp_path / "snapshots").iterdir())
        self._inputs(tmp_path, symbol="ETHUSDT")
        assert dataset_main(combined) == 0
        assert self._records(capsys.readouterr().out)[-1]["partitions"] == 2

    @pytest.mark.parametrize(
        "content",
        [
            b"bad,schema\n",
            _ROW.replace(b"1717200000000", b"1717286400000"),
            _ROW.replace(b"100.00", b"100.001"),
            _ROW.replace(b"2.0", b"0.0"),
        ],
    )
    def test_schema_time_units_quantity_fail_with_invalid_count(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], content: bytes
    ) -> None:
        """Retain observed input failures and never publish an accepted prefix."""
        assert dataset_main(self._inputs(tmp_path, content=content)) == 3
        output = capsys.readouterr()
        assert '"invalid_count":1' in output.out
        assert '"status":"failed"' in output.err and '"stage":"normalize"' in output.err
        assert not list((tmp_path / "snapshots").iterdir())

    @pytest.mark.parametrize(
        "failure", ["schema", "instrument", "policy", "eligibility", "missing", "limit"]
    )
    def test_strict_input_boundaries(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: str
    ) -> None:
        """Reject altered declarations, foreign bindings and unavailable or oversized inputs."""
        arguments = self._inputs(tmp_path)
        path = tmp_path / "BTCUSDT.json"
        expected = 3
        if failure == "schema":
            path.write_bytes(
                path.read_bytes().replace(b'"schema_version":"1"', b'"schema_version":"99"', 1)
            )
        elif failure == "instrument":
            path.write_bytes(
                path.read_bytes().replace(b'"symbol":"BTCUSDT"', b'"symbol":"ETHUSDT"')
            )
        elif failure == "policy":
            (tmp_path / "policy.json").write_text('{"use":"exploratory","unexpected":1}')
            expected = 2
        elif failure == "eligibility":
            path = tmp_path / "eligibility.json"
            path.write_bytes(
                path.read_bytes().replace(b'"price_tick":"0.01"', b'"price_tick":"0.1"')
            )
        elif failure == "missing":
            path.unlink()
            expected = 4
        else:
            arguments[arguments.index("--max-bytes") + 1] = "0"
            expected = 2
        assert dataset_main(arguments) == expected
        assert '"status":"failed"' in capsys.readouterr().err
        assert not list((tmp_path / "snapshots").iterdir())

    def test_gap_and_causal_policy_cannot_claim_validity(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exploratory gaps remain degraded; required causal coverage prevents publication."""
        arguments = self._inputs(tmp_path)
        path = tmp_path / "policy.json"
        policy = replace(
            _CODEC.decode_json(path.read_bytes(), QualityPolicy), max_gap=timedelta(minutes=5)
        )
        path.write_bytes(_CODEC.encode_json(policy))
        assert dataset_main(arguments) == 0
        records = self._records(capsys.readouterr().out)
        assert any(row.get("gap_count") == 1 for row in records)
        identity = str(records[-1]["snapshot_id"])
        path.write_bytes(_CODEC.encode_json(replace(policy, use="causal")))
        assert dataset_main(arguments) == 3
        output = capsys.readouterr()
        assert '"scope":"rejected"' in output.out and "coverage unknown" in output.err
        assert {p.name for p in (tmp_path / "snapshots").iterdir()} == {identity}

    @pytest.mark.parametrize(
        "failure, expected", [(OSError("disk unavailable"), 4), (KeyboardInterrupt(), 130)]
    )
    def test_interrupted_publication_reports_candidate_then_recovers(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        failure: BaseException,
        expected: int,
    ) -> None:
        """Report no durable success before rename and preserve the candidate ID for retry."""
        arguments = self._inputs(tmp_path)
        with patch("alpha_research.data.snapshots.os.rename", side_effect=failure):
            assert dataset_main(arguments) == expected
        result = capsys.readouterr()
        terminal = self._records(result.err)[-1]
        identity = str(terminal["snapshot_id"])
        assert terminal["stage"] == "publish" and "recovery" in terminal
        assert not any(
            row["status"] in {"persisted", "complete"} for row in self._records(result.out)
        )
        assert dataset_main(self._inspect(tmp_path, identity)) == 4
        capsys.readouterr()
        assert dataset_main(arguments) == 0
        assert self._records(capsys.readouterr().out)[-1]["snapshot_id"] == identity

    def test_corrections_are_explicit_and_prior_versions_survive(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Route evidence files to their named acquisition and reject unknown evidence keys."""
        arguments = self._inputs(tmp_path, content=_ROW + _ROW.replace(b"100.00", b"102.00"))
        assert dataset_main(arguments) == 3
        capsys.readouterr()
        acquisition = _CODEC.decode_json(
            (tmp_path / "BTCUSDT.json").read_bytes(), AcquisitionManifest
        )
        occurrences = tuple(
            iter_occurrences(acquisition, RawStore(tmp_path / "raw"), max_bytes=_LIMIT)
        )
        evidence = Correction(
            supersedes=TradeRevision(occurrences=occurrences[:1]).identity,
            replacement=TradeRevision(occurrences=occurrences[1:]).identity,
            ts_published=acquisition.run.job.end,
            ts_available=acquisition.run.job.end,
            evidence_reference="synthetic:mr16:correction",
        )
        path = tmp_path / "correction.json"
        path.write_bytes(_CODEC.encode_json(evidence))
        assert dataset_main([*arguments, "--correction", "foreign", str(path)]) == 3
        capsys.readouterr()
        assert dataset_main([*arguments, "--correction", acquisition.run.identity, str(path)]) == 0
        identity = str(self._records(capsys.readouterr().out)[-1]["snapshot_id"])
        manifest = SnapshotStore(tmp_path / "snapshots", RawStore(tmp_path / "raw")).read(
            identity, max_bytes=_LIMIT
        )
        assert manifest.partitions[0].corrections == (evidence,)
        assert (
            b'"previous":{'
            in (tmp_path / "snapshots" / identity / manifest.partitions[0].sha256).read_bytes()
        )

    @pytest.mark.parametrize("target", ["latest", "raw", "canonical"])
    def test_inspection_rejects_mutable_id_or_damaged_bytes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], target: str
    ) -> None:
        """Inspection cannot accept an alias or bypass retained raw/canonical verification."""
        assert dataset_main(self._inputs(tmp_path)) == 0
        identity = str(self._records(capsys.readouterr().out)[-1]["snapshot_id"])
        if target == "latest":
            identity = "latest"
        else:
            directory = tmp_path / "raw" if target == "raw" else tmp_path / "snapshots" / identity
            path = next(p for p in directory.iterdir() if len(p.name) == 64)
            path.chmod(0o644)
            path.write_bytes(b"mutated")
        assert dataset_main(self._inspect(tmp_path, identity)) == 3
        output = capsys.readouterr()
        assert '"status":"complete"' not in output.out and '"stage":"reopen"' in output.err

    def test_nonidentical_overlaps_fail_instead_of_duplicating_economics(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Keep different acquisition lineage from silently duplicating one selected range."""
        arguments = self._inputs(tmp_path)
        original = _CODEC.decode_json((tmp_path / "BTCUSDT.json").read_bytes(), AcquisitionManifest)
        changed = replace(
            original,
            completed=(
                replace(original.completed[0], retrieval_reference="synthetic:another-attempt"),
            ),
        )
        changed.save(tmp_path / "overlap.json")
        assert dataset_main([*arguments, str(tmp_path / "overlap.json")]) == 3
        assert "overlapping acquisitions" in capsys.readouterr().err
        assert not list((tmp_path / "snapshots").iterdir())

    def test_parent_sync_failure_never_acknowledges_but_complete_snapshot_recovers(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Distinguish visibility after rename from a successful durable acknowledgement."""
        arguments = self._inputs(tmp_path)
        failures: list[OSError | None] = [None, OSError("parent sync failed")]
        with patch.object(SnapshotStore, "_sync_directory", side_effect=failures):
            assert dataset_main(arguments) == 4
        output = capsys.readouterr()
        identity = str(self._records(output.err)[-1]["snapshot_id"])
        assert not any(
            row["status"] in {"persisted", "complete"} for row in self._records(output.out)
        )
        assert dataset_main(self._inspect(tmp_path, identity)) == 0
        capsys.readouterr()
        assert dataset_main(arguments) == 0
        assert self._records(capsys.readouterr().out)[-1]["snapshot_id"] == identity
