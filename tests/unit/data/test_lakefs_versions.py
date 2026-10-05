"""Prove lakeFS version inventories, streamed verification and publication with a fake API."""

from __future__ import annotations

# standard library imports
import hashlib
from pathlib import Path

# third party library imports
import pytest
from lakefs_sdk import ApiClient, CommitCreation, Configuration

# project library imports
import market_data.storage.versions as versions_module
from market_data.storage import DatasetVersion, LakeFSStorage, VersionedObject

_COMMIT = "c" * 64


class _Commit:
    """Carry a commit identity, as the SDK's commit record does."""

    def __init__(self, identity: str) -> None:
        """Bind the identity."""
        self.id = identity


class _FakeLakeFS:
    """Hold uploaded objects per path and serve inclusive byte ranges at one commit."""

    def __init__(self) -> None:
        """Start empty."""
        self.objects: dict[str, bytes] = {}
        self.ranges: list[str] = []
        self.messages: list[str] = []
        self.corrupt: str | None = None

    def upload_object(
        self, repository: str, branch: str, path: str, *, content: str, _request_timeout: int
    ) -> object:
        """Stage one object from a local file path, as the SDK opens ``content``."""
        self.objects[path] = Path(content).read_bytes()
        return None

    def get_object(
        self,
        repository: str,
        ref: str,
        path: str,
        *,
        range: str,
        presign: bool,
        _request_timeout: int,
    ) -> bytearray:
        """Serve one inclusive range, optionally corrupting one path."""
        self.ranges.append(range)
        start, end = (int(part) for part in range.removeprefix("bytes=").split("-"))
        payload = self.objects[path]
        if path == self.corrupt:
            payload = payload[:-1] + b"!"
        return bytearray(payload[start : end + 1])

    def commit(
        self,
        repository: str,
        branch: str,
        commit_creation: CommitCreation,
        *,
        _request_timeout: int,
    ) -> _Commit:
        """Record the commit message and return a fixed commit."""
        self.messages.append("committed")
        return _Commit(_COMMIT)

    def get_commit(self, repository: str, commit_id: str, *, _request_timeout: int) -> _Commit:
        """Resolve the fixed commit."""
        return _Commit(commit_id)


class TestLakeFSVersions:
    """Check inventories, ranged reads and publication."""

    @staticmethod
    def storage(monkeypatch: pytest.MonkeyPatch) -> tuple[LakeFSStorage, _FakeLakeFS]:
        """Bind a storage whose SDK APIs are the fake, with 8-byte ranges."""
        fake = _FakeLakeFS()
        storage = LakeFSStorage(ApiClient(Configuration(host="http://127.0.0.1:1/api/v1")))
        monkeypatch.setattr(storage, "_objects", fake)
        monkeypatch.setattr(storage, "_commits", fake)
        monkeypatch.setattr(versions_module, "_RANGE_BYTES", 8)
        return storage, fake

    @staticmethod
    def item(path: str, payload: bytes) -> VersionedObject:
        """Describe one object's bytes."""
        return VersionedObject(
            path=path, sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload)
        )

    def test_features_are_optional_but_raw_and_snapshots_are_not(self) -> None:
        """A version needs raw and snapshot bytes; derived features may be added."""
        raw, snapshot, feature = (
            self.item("raw/a", b"a"),
            self.item("snapshots/b", b"b"),
            self.item("features/c", b"c"),
        )
        plain = DatasetVersion(repository="mr17-data", commit_id=_COMMIT, objects=(raw, snapshot))
        assert plain.components == frozenset({"raw", "snapshots"})
        with_features = DatasetVersion(
            repository="mr17-data", commit_id=_COMMIT, objects=(raw, snapshot, feature)
        )
        assert "features" in with_features.components
        with pytest.raises(ValueError, match="source and dataset bytes"):
            DatasetVersion(repository="mr17-data", commit_id=_COMMIT, objects=(raw, feature))

    def test_publish_uploads_commits_and_verifies_in_ranges(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every file is uploaded, committed and read back in bounded ranges."""
        storage, fake = self.storage(monkeypatch)
        (tmp_path / "raw/x").mkdir(parents=True)
        (tmp_path / "snapshots").mkdir()
        (tmp_path / "raw/x/journal").write_bytes(b"0123456789abcdefghij")
        (tmp_path / "snapshots/manifest.json").write_bytes(b"{}")
        version = storage.publish(
            "mr17-data",
            "main",
            tmp_path,
            components=("raw", "snapshots"),
            message="J2",
            max_bytes=1000,
        )
        assert version.commit_id == _COMMIT and fake.messages == ["committed"]
        assert [item.path for item in version.objects] == [
            "raw/x/journal",
            "snapshots/manifest.json",
        ]
        assert fake.ranges[:3] == ["bytes=0-7", "bytes=8-15", "bytes=16-19"]
        restored = tmp_path / "restored"
        storage.materialize(version, restored, max_bytes=1000)
        assert (restored / "raw/x/journal").read_bytes() == b"0123456789abcdefghij"
        storage.materialize(version, restored, max_bytes=1000)
        fake.corrupt = "raw/x/journal"
        with pytest.raises(ValueError, match="differs from retained bytes"):
            storage.verify(version, version.objects[0])
        with pytest.raises(ValueError, match="differs from retained bytes"):
            storage.materialize(version, tmp_path / "again", max_bytes=1000)
        assert not (tmp_path / "again/raw/x/journal").exists()

    def test_whole_reads_and_publication_are_bounded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Large objects are materialized, not read whole; oversized files are refused."""
        storage, _ = self.storage(monkeypatch)
        monkeypatch.setattr(versions_module, "_READ_BYTES", 4)
        big = self.item("raw/big", b"0123456789")
        version = DatasetVersion(
            repository="mr17-data", commit_id=_COMMIT, objects=(big, self.item("snapshots/s", b"s"))
        )
        with pytest.raises(ValueError, match="too large to read whole"):
            storage.read(version, big)
        (tmp_path / "raw").mkdir()
        (tmp_path / "raw/big").write_bytes(b"0123456789")
        with pytest.raises(ValueError, match="exceeds max_bytes"):
            storage.publish(
                "mr17-data", "main", tmp_path, components=("raw",), message="x", max_bytes=4
            )
        (tmp_path / "raw/empty").write_bytes(b"")
        with pytest.raises(ValueError, match="empty file"):
            storage.publish(
                "mr17-data", "main", tmp_path, components=("raw",), message="x", max_bytes=100
            )
        with pytest.raises(ValueError, match="selects raw, snapshots or features"):
            storage.publish(
                "mr17-data", "main", tmp_path, components=("other",), message="x", max_bytes=4
            )
