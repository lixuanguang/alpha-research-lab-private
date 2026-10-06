"""Exercise immutable raw publication, verified readers and interrupted writers."""

from __future__ import annotations

# standard library imports
import gzip
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from configuration import Configuration
from market_data.contracts import RawObject, SourceRequest
from market_data.storage import RawFiles, RawStore
from reference_data.catalogs import CatalogSnapshot
from runtime import ImplementationIdentity
from serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()


class _CompetingPublisher:
    """Observe prepublication reads and inject a winning publisher at the link."""

    def __init__(self, descriptor: RawObject, request: SourceRequest, payload: bytes) -> None:
        """Bind expected input and the competing writer's bytes.

        Args:
            descriptor: Trusted byte descriptor for the attempted publication.
            request: Independently expected source request.
            payload: Bytes placed at the destination by the competing writer.
        """
        self._descriptor = descriptor
        self._request = request
        self._payload = payload

    def link(self, source: Path, destination: Path) -> None:
        """Require hidden verified staging, then simulate a no-clobber link collision."""
        assert source.parent == destination.parent
        assert stat.S_IMODE(source.stat().st_mode) == 0o444
        RawFiles.verify(self._descriptor, source, request=self._request.binding)
        with pytest.raises(FileNotFoundError):
            RawStore(destination.parent).open(
                descriptor=self._descriptor, request=self._request.binding
            )
        destination.write_bytes(self._payload)
        raise FileExistsError(destination)


class _SyncFailure:
    """Fail synchronization of the chosen file kind while retaining real fsync."""

    def __init__(self, directory: bool) -> None:
        """Bind the failure boundary.

        Args:
            directory: Whether to fail directory synchronization instead of file sync.
        """
        self._is_directory = directory
        self._fsync = os.fsync

    def fsync(self, descriptor: int) -> None:
        """Raise only at the selected synchronization boundary."""
        if stat.S_ISDIR(os.fstat(descriptor).st_mode) == self._is_directory:
            raise OSError("injected synchronization failure")
        self._fsync(descriptor)


class TestRawStore:
    """Protect byte identity and recovery through the public storage boundary."""

    @pytest.fixture()
    def source_request(self) -> SourceRequest:
        """Resolve the existing synthetic configuration and reference catalog.

        Returns:
            First configured instrument's minute request.
        """
        configuration = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        return SourceRequest.partition(
            configuration.resolve(
                "both-fixture", catalog, implementation_identity=ImplementationIdentity.sha256()
            )
        )[0]

    @staticmethod
    def _describe(source: Path, request: SourceRequest) -> RawObject:
        """Describe fixture bytes with fixed original provenance and clocks."""
        return RawFiles.describe(
            source,
            request=request.binding,
            retrieval_reference="synthetic:mr04",
            ts_received=datetime(2026, 9, 14, tzinfo=UTC),
            ts_ingested=datetime(2026, 9, 14, tzinfo=UTC),
        )

    def test_compressed_objects_reopen_as_original_bytes_and_copy_as_stored(
        self, tmp_path: Path, source_request: SourceRequest
    ) -> None:
        """A compressed object reads back exactly, and a copy keeps its stored encoding."""
        payload = b'{"kind":"frame"}\n' * 200_000
        source = tmp_path / "source"
        source.write_bytes(payload)
        descriptor = self._describe(source, source_request)
        first, second = tmp_path / "first", tmp_path / "second"
        first.mkdir()
        second.mkdir()
        binding = source_request.binding
        published = RawStore(first).publish(
            source, descriptor=descriptor, request=binding, compress=True
        )
        assert published == first / f"{descriptor.sha256}.zst"
        stored = RawStore(first).stored_bytes(descriptor=descriptor, request=binding)
        assert stored < len(payload) // 10
        with RawStore(first).open(descriptor=descriptor, request=binding) as reopened:
            assert reopened.read() == payload
        copied = RawStore(second).copy(RawStore(first), descriptor=descriptor, request=binding)
        assert copied == second / f"{descriptor.sha256}.zst"
        assert copied.read_bytes() == published.read_bytes()
        # An object present in either encoding is reused, not stored twice.
        assert (
            RawStore(first).publish(source, descriptor=descriptor, request=binding, compress=False)
            == published
        )

    def test_compressed_objects_refuse_damage_and_a_second_encoding(
        self, tmp_path: Path, source_request: SourceRequest
    ) -> None:
        """Damage is refused before any byte is read, and two encodings are ambiguous."""
        source = tmp_path / "source"
        source.write_bytes(b"original bytes\n" * 1_000)
        descriptor = self._describe(source, source_request)
        root = tmp_path / "store"
        root.mkdir()
        binding = source_request.binding
        published = RawStore(root).publish(
            source, descriptor=descriptor, request=binding, compress=True
        )
        published.chmod(0o644)
        published.write_bytes(published.read_bytes()[:-4])
        with pytest.raises(ValueError, match="corrupt or truncated"):
            RawStore(root).open(descriptor=descriptor, request=binding)
        (root / descriptor.sha256).write_bytes(source.read_bytes())
        with pytest.raises(ValueError, match="two encodings"):
            RawStore(root).open(descriptor=descriptor, request=binding)
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ValueError, match="absent from origin"):
            RawStore(tmp_path / "other").copy(
                RawStore(empty), descriptor=descriptor, request=binding
            )

    @pytest.mark.parametrize(
        "payload", [b"", b"\x00\xff\r\n" * 262_145], ids=["empty", "multiple-chunks"]
    )
    def test_publish_reopen_and_reuse_without_original_source(
        self, tmp_path: Path, source_request: SourceRequest, payload: bytes
    ) -> None:
        """Publish exact empty/multichunk bytes and reuse the inode and descriptor."""
        source = tmp_path / "source"
        source.write_bytes(payload)
        descriptor = self._describe(source, source_request)
        encoded = _CODEC.encode_json(descriptor)
        root = tmp_path / "store"
        root.mkdir()
        store = RawStore(root)
        published = store.publish(
            source, descriptor=descriptor, request=source_request.binding, compress=False
        )
        original_stat = published.stat()
        assert published == root / descriptor.sha256
        assert stat.S_IMODE(original_stat.st_mode) == 0o444
        assert list(root.iterdir()) == [published]
        source.unlink()
        restored = _CODEC.decode_json(encoded, RawObject)
        assert (
            store.publish(
                source, descriptor=restored, request=source_request.binding, compress=False
            )
            == published
        )
        assert published.stat().st_ino == original_stat.st_ino
        assert published.stat().st_mtime_ns == original_stat.st_mtime_ns
        with RawStore(root).open(descriptor=restored, request=source_request.binding) as stream:
            assert stream.tell() == 0
            assert stream.read() == payload
            assert not stream.writable()
        assert stream.closed
        assert _CODEC.encode_json(restored) == encoded

    def test_reject_invalid_input_and_preserve_existing_conflict(
        self, tmp_path: Path, source_request: SourceRequest
    ) -> None:
        """Reject changed compressed bytes, truncation and conflicts without replacement."""
        source = tmp_path / "source.gz"
        payload = gzip.compress(
            (_ROOT / "tests/fixtures/market_data/tardis/btcusdt.txt").read_bytes(), mtime=0
        )
        source.write_bytes(payload)
        descriptor = self._describe(source, source_request)
        root = tmp_path / "store"
        root.mkdir()
        store = RawStore(root)
        for changed, message in ((payload[:-1], "size mismatch"), (b"X" + payload[1:], "SHA-256")):
            source.write_bytes(changed)
            with pytest.raises(ValueError, match=message):
                store.publish(
                    source, descriptor=descriptor, request=source_request.binding, compress=False
                )
            assert not list(root.iterdir())
        source.write_bytes(payload)
        destination = root / descriptor.sha256
        destination.write_bytes(b"conflict")
        inode = destination.stat().st_ino
        with pytest.raises(ValueError, match="size mismatch"):
            store.publish(
                source, descriptor=descriptor, request=source_request.binding, compress=False
            )
        assert destination.read_bytes() == b"conflict"
        assert destination.stat().st_ino == inode
        with pytest.raises(ValueError, match="size mismatch"):
            store.open(descriptor=descriptor, request=source_request.binding)

    @pytest.mark.parametrize("kind", ["symlink", "dangling", "directory"])
    def test_reject_nonregular_published_names(
        self, tmp_path: Path, source_request: SourceRequest, kind: str
    ) -> None:
        """Do not follow existing symlinks or accept directories at an object address."""
        source = tmp_path / "source"
        source.write_bytes(b"abc")
        descriptor = self._describe(source, source_request)
        root = tmp_path / "store"
        root.mkdir()
        destination = root / descriptor.sha256
        if kind == "directory":
            destination.mkdir()
        else:
            destination.symlink_to(source if kind == "symlink" else tmp_path / "missing")
        store = RawStore(root)
        with pytest.raises(ValueError, match="regular file"):
            store.publish(
                source, descriptor=descriptor, request=source_request.binding, compress=False
            )
        with pytest.raises(ValueError, match="regular file"):
            store.open(descriptor=descriptor, request=source_request.binding)
        assert destination.is_dir() if kind == "directory" else destination.is_symlink()
        assert not list(root.glob(".staging-*"))

    def test_revalidate_unsafe_metadata_and_expected_request_before_io(
        self, tmp_path: Path, source_request: SourceRequest
    ) -> None:
        """Reject unsafe path digests and wrong or modified requests at both boundaries."""
        source = tmp_path / "source"
        source.write_bytes(b"abc")
        descriptor = self._describe(source, source_request)
        store = RawStore(tmp_path / "absent-store")
        wrong = replace(source_request, offset_minutes=1)
        for request in (
            wrong,
            replace(source_request, instrument=source_request.manifest.instruments[1]),
        ):
            with pytest.raises(ValueError, match="request identity"):
                store.publish(
                    source, descriptor=descriptor, request=request.binding, compress=False
                )
            with pytest.raises(ValueError, match="request identity"):
                store.open(descriptor=descriptor, request=request.binding)
        msgspec.structs.force_setattr(source_request, "offset_minutes", True)
        with pytest.raises(ValueError, match="offset"):
            store.publish(
                source, descriptor=descriptor, request=source_request.binding, compress=False
            )
        msgspec.structs.force_setattr(source_request, "offset_minutes", 0)
        msgspec.structs.force_setattr(descriptor, "sha256", "../escape")
        with pytest.raises(ValueError, match="sha256"):
            store.publish(
                source, descriptor=descriptor, request=source_request.binding, compress=False
            )
        with pytest.raises(ValueError, match="sha256"):
            store.open(descriptor=descriptor, request=source_request.binding)
        assert not (tmp_path / "absent-store").exists()

    @pytest.mark.parametrize("competitor", [b"abc", b"bad"])
    def test_racing_publisher_never_overwrites_a_winner(
        self, tmp_path: Path, source_request: SourceRequest, competitor: bytes
    ) -> None:
        """Verify a simultaneous winner after link collision; expose no staged reader."""
        source = tmp_path / "source"
        source.write_bytes(b"abc")
        descriptor = self._describe(source, source_request)
        root = tmp_path / "store"
        root.mkdir()
        publisher = _CompetingPublisher(descriptor, source_request, competitor)
        with patch("market_data.storage.raw.os.link", publisher.link):
            if competitor == b"abc":
                RawStore(root).publish(
                    source, descriptor=descriptor, request=source_request.binding, compress=False
                )
            else:
                with pytest.raises(ValueError, match="SHA-256"):
                    RawStore(root).publish(
                        source,
                        descriptor=descriptor,
                        request=source_request.binding,
                        compress=False,
                    )
        assert (root / descriptor.sha256).read_bytes() == competitor
        assert not list(root.glob(".staging-*"))

    @pytest.mark.parametrize("is_directory", [False, True])
    def test_sync_failure_and_retry(
        self, tmp_path: Path, source_request: SourceRequest, is_directory: bool
    ) -> None:
        """Never acknowledge failed fsync; retry existing bytes after directory failure."""
        source = tmp_path / "source"
        source.write_bytes(b"abc")
        descriptor = self._describe(source, source_request)
        root = tmp_path / "store"
        root.mkdir()
        failure = _SyncFailure(is_directory)
        store = RawStore(root)
        with patch("market_data.storage.raw.os.fsync", failure.fsync):
            with pytest.raises(OSError, match="synchronization failure"):
                store.publish(
                    source, descriptor=descriptor, request=source_request.binding, compress=False
                )
        assert (root / descriptor.sha256).exists() == is_directory
        assert not list(root.glob(".staging-*"))
        if is_directory:
            source.unlink()
            with patch("market_data.storage.raw.os.fsync", failure.fsync):
                with pytest.raises(OSError, match="synchronization failure"):
                    store.publish(
                        source,
                        descriptor=descriptor,
                        request=source_request.binding,
                        compress=False,
                    )
        store.publish(source, descriptor=descriptor, request=source_request.binding, compress=False)
        with store.open(descriptor=descriptor, request=source_request.binding) as stream:
            assert stream.read() == b"abc"

    @pytest.mark.integration
    @pytest.mark.parametrize("point", ["before", "after"])
    def test_process_death_reconciliation(
        self, tmp_path: Path, source_request: SourceRequest, point: str
    ) -> None:
        """Inspect orphan staging and complete publication after abrupt process exit."""
        source = tmp_path / "source"
        source.write_bytes(b"abc")
        descriptor = self._describe(source, source_request)
        descriptor_path = tmp_path / "descriptor.json"
        descriptor_path.write_bytes(_CODEC.encode_json(descriptor))
        request_path = tmp_path / "request.json"
        request_path.write_bytes(_CODEC.encode_json(source_request))
        root = tmp_path / "store"
        root.mkdir()
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                str(_ROOT / "tests/support/subprocesses/interrupt_publish.py"),
                str(root),
                str(source),
                str(descriptor_path),
                str(request_path),
                point,
            ],
            cwd=tmp_path,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert completed.returncode == 75, completed.stderr.decode()
        (staging,) = root.glob(".staging-*")
        RawFiles.verify(descriptor, staging, request=source_request.binding)
        store = RawStore(root)
        if point == "before":
            with pytest.raises(FileNotFoundError):
                store.open(descriptor=descriptor, request=source_request.binding)
        else:
            assert staging.stat().st_ino == (root / descriptor.sha256).stat().st_ino
            with store.open(descriptor=descriptor, request=source_request.binding) as stream:
                assert stream.read() == b"abc"
            source.unlink()
        published = store.publish(
            source, descriptor=descriptor, request=source_request.binding, compress=False
        )
        assert published.read_bytes() == b"abc"
        assert list(root.glob(".staging-*")) == [staging]
        staging.unlink()  # The interrupted child has exited; no writer owns this orphan.
        assert list(root.iterdir()) == [published]
