"""Verify manifest identity, complete saved-input verification and fail-closed admission."""

from __future__ import annotations

# standard library imports
import hashlib
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from alpha_research.configuration import Configuration
from alpha_research.data.datasets import DatasetInput, DatasetManifest
from alpha_research.data.eligibility import EligibilityAssertions
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.quality import QualityPolicy
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.data.revisions import Correction, TradeRevision
from alpha_research.pipelines.dataset import assemble_dataset, iter_occurrences
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_RAW = b"12,100.00,2.0,200,1717200000000,true,true\n"
_LIMIT = 262_144


class TestDatasetManifest:
    """Use real saved synthetic archives, retaining all admission and reference contracts."""

    @staticmethod
    def _acquisition(
        root: Path,
        *,
        symbol: str = "BTCUSDT",
        content: bytes = _RAW,
        catalog_evidence: str | None = None,
    ) -> AcquisitionManifest:
        """Save deterministic source bytes for one resolved instrument without source access."""
        config = Configuration.read(_ROOT / "configs/data-jobs/binance-archive.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        if catalog_evidence is not None:
            catalog = replace(catalog, evidence=catalog_evidence)
        run = config.resolve("btc-archive", catalog)
        instrument = next(item for item in catalog.instruments if item.symbol == symbol)
        run = replace(run, instruments=(instrument,))
        request = SourceRequest.partition(run)[0]
        source = root / "source.zip"
        member = ZipInfo(f"{symbol}-trades-2024-06-01.csv")
        member.compress_type = ZIP_DEFLATED
        with ZipFile(source, "w") as archive:
            archive.writestr(member, content)
        descriptor = RawObject.from_file(
            source,
            request=request,
            retrieval_reference="synthetic:mr14",
            ts_received=datetime(2026, 9, 16, tzinfo=UTC),
            ts_ingested=datetime(2026, 9, 16, tzinfo=UTC),
        )
        RawStore(root).publish(source, descriptor=descriptor, request=request)
        return AcquisitionManifest(run=run, completed=(descriptor,))

    @staticmethod
    def _build(
        root: Path,
        acquisitions: tuple[AcquisitionManifest, ...],
        *,
        corrections: tuple[Correction, ...] = (),
    ) -> tuple[DatasetManifest, tuple[bytes, ...]]:
        """Assemble admitted partitions with the retained synthetic eligibility history."""
        history = EligibilityAssertions.read(
            _ROOT / "tests/fixtures/mr12/eligibility.json", catalog=acquisitions[0].run.catalog
        )
        policy = QualityPolicy(
            use="exploratory", known_at=acquisitions[0].run.job.start, max_gap=timedelta(hours=1)
        )
        return assemble_dataset(
            acquisitions,
            RawStore(root),
            max_bytes=_LIMIT,
            policy=policy,
            eligibility=history,
            corrections={acquisitions[0].run.identity: corrections} if corrections else {},
        )

    @staticmethod
    def _save(root: Path, manifest: DatasetManifest, payloads: tuple[bytes, ...]) -> Path:
        """Write working files without pretending they are an atomically published snapshot."""
        for partition, payload in zip(manifest.partitions, payloads, strict=True):
            (root / partition.sha256).write_bytes(payload)
        path = root / "dataset.json"
        path.write_bytes(_CODEC.encode_json(manifest))
        return path

    @staticmethod
    def _read(root: Path, manifest: DatasetManifest, *, max_bytes: int = _LIMIT) -> DatasetManifest:
        """Verify the saved expected identity from explicit local storage locations."""
        return DatasetManifest.read(
            root / "dataset.json",
            identity=manifest.identity,
            partitions=root,
            store=RawStore(root),
            max_bytes=max_bytes,
        )

    def test_per_input_catalogs_and_policy_survive_assembly_and_reopening(
        self, tmp_path: Path
    ) -> None:
        """Keep independent partition evidence instead of applying one catalog to every input."""
        first = self._acquisition(tmp_path)
        second = self._acquisition(
            tmp_path, symbol="ETHUSDT", catalog_evidence="synthetic:independent-source-catalog"
        )
        history = _CODEC.decode_json(
            (_ROOT / "tests/fixtures/mr12/eligibility.json").read_bytes(), EligibilityAssertions
        )
        selected = tuple(
            DatasetInput(
                acquisition=acquisition,
                policy=QualityPolicy(
                    use="exploratory",
                    known_at=acquisition.run.job.start,
                    max_gap=timedelta(minutes=30 + index),
                ),
                eligibility=replace(history, catalog=acquisition.run.catalog),
            )
            for index, acquisition in enumerate((first, second))
        )
        manifest, payloads = assemble_dataset(selected, RawStore(tmp_path), max_bytes=_LIMIT)
        assert tuple(part.acquisition for part in manifest.partitions) == (first, second)
        assert tuple(part.eligibility for part in manifest.partitions) == tuple(
            item.eligibility for item in selected
        )
        assert len({part.eligibility.catalog.identity for part in manifest.partitions}) == 2
        self._save(tmp_path, manifest, payloads)
        assert self._read(tmp_path, manifest) == manifest
        with pytest.raises(ValueError, match="not both"):
            assemble_dataset(
                selected, RawStore(tmp_path), max_bytes=_LIMIT, policy=selected[0].policy
            )
        with pytest.raises(ValueError, match="explicit policy"):
            assemble_dataset((first,), RawStore(tmp_path), max_bytes=_LIMIT)
        legacy = self._build(tmp_path, (first,))
        per_input = DatasetInput(
            acquisition=first,
            policy=legacy[0].partitions[0].policy,
            eligibility=legacy[0].partitions[0].eligibility,
        )
        assert assemble_dataset((per_input,), RawStore(tmp_path), max_bytes=_LIMIT) == legacy

    def test_rebuild_order_roundtrip_and_relocation(self, tmp_path: Path) -> None:
        """Keep equivalent saved inputs stable and bind the ordered full resolved universe."""
        first = self._acquisition(tmp_path)
        second = self._acquisition(tmp_path, symbol="ETHUSDT")
        # Same mutable job/universe name, different actual instrument and raw request binding.
        assert first.run.job == second.run.job
        result = self._build(tmp_path, (first, second))
        manifest, payloads = result
        assert self._build(tmp_path, (first, second)) == result
        assert self._build(tmp_path, (second, first))[0].identity != manifest.identity
        assert (
            self._build(tmp_path, (first,))[0].identity
            != self._build(tmp_path, (second,))[0].identity
        )
        path = self._save(tmp_path, manifest, payloads)
        assert self._read(tmp_path, manifest) == manifest
        assert _CODEC.decode_json(_CODEC.encode_json(manifest), DatasetManifest) == manifest
        relocated = tmp_path / "relocated"
        relocated.mkdir()
        for item in tmp_path.iterdir():
            if item.is_file():
                shutil.copyfile(item, relocated / item.name)
        path.write_bytes(b" \n" + path.read_bytes() + b"\n")
        assert self._read(tmp_path, manifest).identity == self._read(relocated, manifest).identity
        assert all(part.policy.use == "exploratory" for part in manifest.partitions)

    def test_semantic_inputs_change_identity_and_stale_bytes_fail(self, tmp_path: Path) -> None:
        """Bind policy, eligibility, catalog, raw provenance and normalization implementation."""
        acquisition = self._acquisition(tmp_path)
        manifest, payloads = self._build(tmp_path, (acquisition,))
        partition = manifest.partitions[0]
        changed_policy = replace(partition.policy, max_gap=timedelta(minutes=5))
        changed, changed_bytes = assemble_dataset(
            (acquisition,),
            RawStore(tmp_path),
            max_bytes=_LIMIT,
            policy=changed_policy,
            eligibility=partition.eligibility,
            corrections={},
        )
        assert changed.identity != manifest.identity and changed_bytes != payloads
        self._save(tmp_path, changed, changed_bytes)
        assert self._read(tmp_path, changed) == changed
        variants = (
            replace(partition, policy=changed_policy),
            replace(
                partition,
                eligibility=replace(
                    partition.eligibility, assertions=partition.eligibility.assertions[:-1]
                ),
            ),
            replace(
                partition,
                acquisition=replace(
                    acquisition,
                    completed=(
                        replace(
                            acquisition.completed[0],
                            retrieval_reference="synthetic:changed-provenance",
                        ),
                    ),
                ),
            ),
        )
        for variant in variants:
            changed = replace(manifest, partitions=(variant,))
            assert changed.identity != manifest.identity
            self._save(tmp_path, changed, payloads)
            with pytest.raises(ValueError, match="differs from retained"):
                self._read(tmp_path, changed)
        assert replace(manifest, normalization_identity="b" * 64).identity != manifest.identity
        new_catalog = replace(acquisition.run.catalog, evidence="changed-reference")
        new_run = replace(acquisition.run, catalog=new_catalog)
        new_origin = replace(
            acquisition.completed[0], request_identity=SourceRequest.partition(new_run)[0].identity
        )
        linked = replace(
            partition,
            acquisition=replace(acquisition, run=new_run, completed=(new_origin,)),
            eligibility=replace(partition.eligibility, catalog=new_catalog),
        )
        assert replace(manifest, partitions=(linked,)).identity != manifest.identity

    @pytest.mark.parametrize("target", ["manifest", "canonical", "raw"])
    def test_missing_and_mutated_files_fail(self, tmp_path: Path, target: str) -> None:
        """Never treat a missing saved manifest or a damaged referenced file as a new dataset."""
        acquisition = self._acquisition(tmp_path)
        manifest, payloads = self._build(tmp_path, (acquisition,))
        path = self._save(tmp_path, manifest, payloads)
        if target == "canonical":
            path = tmp_path / manifest.partitions[0].sha256
        elif target == "raw":
            path = tmp_path / acquisition.completed[0].sha256
        original = path.read_bytes()
        path.chmod(0o644)
        path.unlink()
        with pytest.raises((FileNotFoundError, ValueError)):
            self._read(tmp_path, manifest)
        path.write_bytes(b"mutated")
        with pytest.raises(ValueError):
            self._read(tmp_path, manifest)
        path.write_bytes(original)
        assert self._read(tmp_path, manifest) == manifest

    def test_rehashed_forged_canonical_and_identity_mismatch(self, tmp_path: Path) -> None:
        """A matching file digest cannot upgrade quality scope or fabricate canonical content."""
        manifest, payloads = self._build(tmp_path, (self._acquisition(tmp_path),))
        payload = payloads[0].replace(b"exploratory_degraded", b"valid")
        forged = replace(
            manifest,
            partitions=(
                replace(manifest.partitions[0], sha256=hashlib.sha256(payload).hexdigest()),
            ),
        )
        path = self._save(tmp_path, forged, (payload,))
        with pytest.raises(ValueError, match="differs from retained"):
            self._read(tmp_path, forged)
        with pytest.raises(ValueError, match="identity mismatch"):
            DatasetManifest.read(
                path,
                identity=manifest.identity,
                partitions=tmp_path,
                store=RawStore(tmp_path),
                max_bytes=_LIMIT,
            )

    def test_versions_scope_nested_mutation_and_size_limits(self, tmp_path: Path) -> None:
        """Reject unknown versions, unsafe direct copies and extra fields before use."""
        manifest, payloads = self._build(tmp_path, (self._acquisition(tmp_path),))
        path = self._save(tmp_path, manifest, payloads)
        invalid: tuple[tuple[str, object], ...] = (
            ("schema_version", "2"),
            ("canonical_schema", "future"),
            ("correction_policy", "latest"),
            ("availability_policy", "backfill"),
            ("scope", "causal"),
            ("normalization_identity", "mutable-name"),
            ("partitions", ()),
            ("partitions", [manifest.partitions[0]]),
        )
        for field, value in invalid:
            damaged = replace(manifest)
            force_setattr(damaged, field, value)
            with pytest.raises(ValueError):
                damaged.__post_init__()
            path.write_bytes(_CODEC.encode_json(damaged))
            if field != "partitions" or value == ():
                with pytest.raises(ValueError):
                    self._read(tmp_path, manifest)
        path.write_bytes(_CODEC.encode_json(manifest)[:-1] + b',"built_at":"today"}')
        with pytest.raises(ValueError, match="unknown field"):
            self._read(tmp_path, manifest)
        self._save(tmp_path, manifest, payloads)
        for limit in (0, -1, True, 10):
            with pytest.raises(ValueError, match="max_bytes"):
                self._read(tmp_path, manifest, max_bytes=limit)
        with pytest.raises(ValueError, match="partition size"):
            self._read(tmp_path, manifest, max_bytes=path.stat().st_size)
        damaged_partition = replace(manifest.partitions[0])
        force_setattr(damaged_partition, "sha256", "../../foreign")
        with pytest.raises(ValueError, match="SHA-256"):
            replace(manifest, partitions=(damaged_partition,))
        force_setattr(manifest.partitions[0].policy, "use", "causal")
        with pytest.raises(ValueError, match="exploratory"):
            _ = manifest.identity

    def test_rejected_duplicate_empty_or_unknown_correction_inputs(self, tmp_path: Path) -> None:
        """Return no assembled prefix after a late quality failure or an invalid selection."""
        good = self._acquisition(tmp_path)
        bad = self._acquisition(tmp_path, symbol="ETHUSDT", content=_RAW.replace(b"100.00", b"NaN"))
        with pytest.raises(ValueError, match="publication refused"):
            self._build(tmp_path, (good, bad))
        assert self._build(tmp_path, (good, good)) == self._build(tmp_path, (good,))
        manifest, _ = self._build(tmp_path, (good,))
        policy, history = manifest.partitions[0].policy, manifest.partitions[0].eligibility
        for acquisitions, corrections, use in (
            ((), {}, policy),
            ((good,), {"foreign": ()}, policy),
            ((good,), {}, replace(policy, use="causal")),
        ):
            with pytest.raises(ValueError):
                assemble_dataset(
                    acquisitions,
                    RawStore(tmp_path),
                    max_bytes=_LIMIT,
                    policy=use,
                    eligibility=history,
                    corrections=corrections,
                )
        with pytest.raises(ValueError, match="complete"):
            replace(manifest.partitions[0], acquisition=AcquisitionManifest(run=good.run))
        assert not (tmp_path / "dataset.json").exists()

    def test_corrections_preserve_prior_versions_and_availability(self, tmp_path: Path) -> None:
        """Reopen evidenced revisions with all raw lineage and effective later knowledge."""
        acquisition = self._acquisition(tmp_path, content=_RAW + _RAW.replace(b"100.00", b"102.00"))
        occurrences = tuple(iter_occurrences(acquisition, RawStore(tmp_path), max_bytes=_LIMIT))
        correction = Correction(
            supersedes=TradeRevision(occurrences=occurrences[:1]).identity,
            replacement=TradeRevision(occurrences=occurrences[1:]).identity,
            ts_published=acquisition.run.job.start + timedelta(days=1),
            ts_available=acquisition.run.job.start + timedelta(days=1, seconds=1),
            evidence_reference="synthetic:mr14:correction",
        )
        manifest, payloads = self._build(tmp_path, (acquisition,), corrections=(correction,))
        self._save(tmp_path, manifest, payloads)
        assert self._read(tmp_path, manifest) == manifest
        assert b'"previous":{' in payloads[0] and b"2024-06-02T00:00:01Z" in payloads[0]
        assert manifest.partitions[0].corrections == (correction,)
        with pytest.raises(ValueError, match="publication refused"):
            self._build(tmp_path, (acquisition,))
