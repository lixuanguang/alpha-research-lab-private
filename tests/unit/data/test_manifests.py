"""Protect persisted acquisition schemas, input binding and atomic checkpoint failure."""

from __future__ import annotations

# standard library imports
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from configuration import Configuration, ResolvedManifest
from market_data.acquisition import AcquisitionManifest
from market_data.contracts import RawObject, SourceRequest
from market_data.storage import RawStore
from reference_data.catalogs import CatalogSnapshot
from runtime import ImplementationIdentity
from serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()


class TestAcquisitionManifest:
    """Verify untrusted manifests and write-ahead state through retained codecs and files."""

    @pytest.fixture()
    def run(self) -> ResolvedManifest:
        """Resolve a bounded three-minute historical job from retained fixture inputs.

        Returns:
            Explicit resolved run with synthetic rights and stable input bindings.
        """
        configuration = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        run = configuration.resolve(
            "btc-fixture", catalog, implementation_identity=ImplementationIdentity.sha256()
        )
        return replace(
            run,
            job=replace(
                run.job,
                mode="historical",
                pipeline="acquisition.fetch",
                end=run.job.start + timedelta(minutes=3),
            ),
        )

    @staticmethod
    def _descriptor(request: SourceRequest) -> RawObject:
        """Bind the standard empty-byte digest to one independently selected partition."""
        return RawObject(
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            size_bytes=0,
            request_identity=request.identity,
            retrieval_reference="synthetic:mr06",
            ts_received=datetime(2026, 9, 15, tzinfo=UTC),
            ts_ingested=datetime(2026, 9, 15, tzinfo=UTC),
        )

    def test_roundtrip_pending_and_completed_original_clocks(
        self,
        tmp_path: Path,
        run: ResolvedManifest,
    ) -> None:
        """Require verified saved bytes only for completed entries and preserve exact metadata."""
        path = tmp_path / "manifest.json"
        store = RawStore(tmp_path)
        requests = SourceRequest.partition(run)
        descriptor = self._descriptor(requests[0])
        state = AcquisitionManifest.read(path, run=run, store=store)
        state.prepare(path, descriptor)
        pending = AcquisitionManifest.read(path, run=run, store=store)
        assert pending.pending == descriptor and not pending.completed
        completed = replace(state, completed=(descriptor,))
        completed.save(path)
        with pytest.raises(FileNotFoundError):
            AcquisitionManifest.read(path, run=run, store=store)
        source = tmp_path / "empty"
        source.write_bytes(b"")
        store.publish(source, descriptor=descriptor, request=requests[0].binding)
        restored = AcquisitionManifest.read(path, run=run, store=store)
        assert restored == completed
        assert _CODEC.encode_json(restored) == path.read_bytes()
        with pytest.raises(AttributeError):
            setattr(restored, "completed", ())
        altered = replace(run, job=replace(run.job, source_revision="another-revision"))
        with pytest.raises(ValueError, match="run identity"):
            AcquisitionManifest.read(path, run=altered, store=store)

    @pytest.mark.parametrize(
        "change",
        [
            "unknown",
            "schema",
            "duplicate",
            "order",
            "pending",
            "digest",
            "clock",
            "too-many",
            "truncated",
        ],
    )
    def test_malformed_saved_manifest_fails_closed(
        self,
        tmp_path: Path,
        run: ResolvedManifest,
        change: str,
    ) -> None:
        """Reject foreign, reordered, unsafe and truncated records before trusting any progress."""
        first, second, third = map(self._descriptor, SourceRequest.partition(run))
        state = AcquisitionManifest(run=run, completed=(first, second), pending=third)
        if change == "unknown":
            payload = _CODEC.encode_json(state)[:-1] + b',"extra":1}'
        elif change == "truncated":
            payload = _CODEC.encode_json(state)[:-1]
        else:
            if change == "schema":
                msgspec.structs.force_setattr(state, "schema_version", "2")
            elif change == "duplicate":
                msgspec.structs.force_setattr(state, "completed", (first, first))
            elif change == "order":
                msgspec.structs.force_setattr(state, "completed", (second, first))
            elif change == "pending":
                msgspec.structs.force_setattr(state, "pending", first)
            elif change == "digest":
                msgspec.structs.force_setattr(first, "sha256", "BAD")
            elif change == "clock":
                msgspec.structs.force_setattr(
                    first, "ts_ingested", first.ts_received - timedelta(seconds=1)
                )
            else:
                msgspec.structs.force_setattr(state, "completed", (first, second, third, first))
            with pytest.raises(ValueError):
                state.save(tmp_path / "unsafe.json")
            payload = _CODEC.encode_json(state)
        path = tmp_path / "manifest.json"
        path.write_bytes(payload)
        with pytest.raises(ValueError):
            AcquisitionManifest.read(path, run=run, store=RawStore(tmp_path))
        assert path.read_bytes() == payload

    def test_failed_checkpoint_preserves_prior_complete_document(
        self,
        tmp_path: Path,
        run: ResolvedManifest,
    ) -> None:
        """Do not expose a truncated checkpoint when staging sync or replacement fails."""
        state = AcquisitionManifest(run=run)
        path = tmp_path / "manifest.json"
        state.save(path)
        original = path.read_bytes()
        descriptor = self._descriptor(SourceRequest.partition(run)[0])
        for operation in ("fsync", "replace"):
            with patch.object(os, operation, side_effect=OSError("injected checkpoint failure")):
                with pytest.raises(OSError, match="checkpoint failure"):
                    state.prepare(path, descriptor)
            assert path.read_bytes() == original
            assert not list(tmp_path.glob(".checkpoint-*"))
        state.prepare(path, descriptor)
        assert (
            AcquisitionManifest.read(path, run=run, store=RawStore(tmp_path)).pending == descriptor
        )

    def test_daily_views_preserve_requests_clocks_and_original_checkpoint(self) -> None:
        """Narrow only complete daily inputs and retain the original multi-instrument run."""
        config = Configuration.read(_ROOT / "configs/data-jobs/binance-archive.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        config = replace(config, jobs=(replace(config.jobs[0], universe="both"),))
        run = config.resolve(
            "btc-archive", catalog, implementation_identity=ImplementationIdentity.sha256()
        )
        requests = SourceRequest.partition(run)
        descriptors = tuple(map(self._descriptor, requests))
        original = AcquisitionManifest(run=run, completed=descriptors)
        before = _CODEC.encode_json(original)
        views = original.partitions()
        assert _CODEC.encode_json(original) == before
        for view, request, descriptor in zip(views, requests, descriptors, strict=True):
            assert view.run.job == run.job and view.run.catalog == run.catalog
            assert view.run.implementation_identity == run.implementation_identity
            assert view.completed == (descriptor,)
            assert SourceRequest.partition(view.run)[0].identity == request.identity
            assert view.partitions() == (view,)
            assert _CODEC.decode_json(_CODEC.encode_json(view), AcquisitionManifest) == view
        for partial in (
            replace(original, completed=()),
            replace(original, completed=descriptors[:1]),
            replace(original, completed=descriptors[:1], pending=descriptors[1]),
        ):
            with pytest.raises(ValueError, match="complete daily acquisition"):
                partial.partitions()

    def test_minute_acquisition_cannot_be_projected_as_daily(self, run: ResolvedManifest) -> None:
        """Keep unsupported saved adapters outside the daily publication extension."""
        original = AcquisitionManifest(
            run=run, completed=tuple(map(self._descriptor, SourceRequest.partition(run)))
        )
        with pytest.raises(ValueError, match="complete daily acquisition"):
            original.partitions()
