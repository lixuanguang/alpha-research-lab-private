"""Pin lakeFS object versions and materialize verified bytes for existing dataset readers."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import re
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import Literal

# third party library imports
from lakefs_sdk import ApiClient
from lakefs_sdk.api.branches_api import BranchesApi
from lakefs_sdk.api.commits_api import CommitsApi
from lakefs_sdk.api.objects_api import ObjectsApi
from lakefs_sdk.api.tags_api import TagsApi

# project library imports
from serialization import DomainCodec, WireRecord, sync_directory


class VersionedObject(WireRecord, frozen=True):
    """Retain one relative object path and the exact reader-visible bytes."""

    path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        """Refuse path traversal, unbounded bytes and malformed content digests."""
        path = PurePosixPath(self.path)
        if (
            path.is_absolute()
            or str(path) != self.path
            or ".." in path.parts
            or not path.parts
            or path.parts[0] not in ("raw", "snapshots", "features")
            or len(path.parts) < 2
            or "\\" in self.path
            or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None
            or type(self.size_bytes) is not int
            or not 0 < self.size_bytes <= 64 * 1024 * 1024
        ):
            raise ValueError("invalid versioned object path, size or digest")


class DatasetVersion(WireRecord, frozen=True):
    """Bind a published dataset and derived feature bytes to an immutable storage commit."""

    repository: str
    commit_id: str
    objects: tuple[VersionedObject, ...]
    schema_version: str = "lakefs-dataset-version"

    def __post_init__(self) -> None:
        """Require a bounded unique inventory containing raw, snapshot and feature objects."""
        if (
            self.schema_version != "lakefs-dataset-version"
            or re.fullmatch(r"[a-z0-9][a-z0-9-]{2,62}", self.repository) is None
            or re.fullmatch(r"[0-9a-f]{64}", self.commit_id) is None
            or type(self.objects) is not tuple
            or not 3 <= len(self.objects) <= 4096
        ):
            raise ValueError("invalid lakeFS repository, commit or inventory")
        for item in self.objects:
            if type(item) is not VersionedObject:
                raise TypeError("dataset version requires typed object identities")
            item.__post_init__()
        if len({item.path for item in self.objects}) != len(self.objects):
            raise ValueError("duplicate lakeFS object path")
        if {PurePosixPath(item.path).parts[0] for item in self.objects} != {
            "raw",
            "snapshots",
            "features",
        }:
            raise ValueError("dataset version requires source, dataset and derived feature bytes")

    @property
    def identity(self) -> str:
        """Hash the resolved immutable version manifest.

        Returns:
            SHA-256 retained by configuration and ClearML, separate from knowledge time.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class LakeFSStorage:
    """Keep version resolution and integrity outside unchanged domain reader semantics."""

    def __init__(self, client: ApiClient) -> None:
        """Bind an explicitly authenticated SDK client without global credential discovery.

        Args:
            client: Caller-owned lakeFS client; caller closes its connection pool.
        """
        self._branches = BranchesApi(client)
        self._tags = TagsApi(client)
        self._commits = CommitsApi(client)
        self._objects = ObjectsApi(client)

    def resolve(
        self,
        repository: str,
        reference: str,
        *,
        kind: Literal["branch", "tag", "commit"],
        objects: tuple[VersionedObject, ...],
    ) -> DatasetVersion:
        """Resolve mutable references once, then verify every object at that commit.

        Args:
            repository: Explicit retained repository name.
            reference: Branch, tag or full commit selected by the caller.
            kind: Declared reference kind; no ambiguous fallback between namespaces.
            objects: Expected existing dataset manifests, raw objects and feature snapshot.

        Returns:
            Immutable commit and complete byte identities, suitable for retained configuration.

        Raises:
            ValueError: Reference kind or downloaded byte identity is incompatible.
        """
        if kind == "branch":
            commit = self._branches.get_branch(repository, reference, _request_timeout=15).commit_id
        elif kind == "tag":
            commit = self._tags.get_tag(repository, reference, _request_timeout=15).commit_id
        elif kind == "commit":
            commit = self._commits.get_commit(repository, reference, _request_timeout=15).id
        else:
            raise ValueError("unsupported lakeFS reference kind")
        version = DatasetVersion(repository=repository, commit_id=commit, objects=objects)
        for item in version.objects:
            self.read(version, item)
        return version

    def read(self, version: DatasetVersion, item: VersionedObject) -> bytes:
        """Retrieve only immutable commit bytes, retaining their original domain clocks.

        Args:
            version: Resolved repository commit and byte inventory.
            item: Exact member of that inventory.

        Returns:
            Verified complete bytes without SDK records or storage timestamps.

        Raises:
            ValueError: Object membership, size or SHA-256 differs.
        """
        version.__post_init__()
        if item not in version.objects:
            raise ValueError("object is not part of the pinned dataset version")
        payload = bytes(
            self._objects.get_object(
                version.repository,
                version.commit_id,
                item.path,
                range=f"bytes=0-{item.size_bytes}",
                presign=False,
                _request_timeout=15,
            )
        )
        if len(payload) != item.size_bytes or hashlib.sha256(payload).hexdigest() != item.sha256:
            raise ValueError("lakeFS object differs from retained bytes")
        return payload

    def materialize(self, version: DatasetVersion, destination: Path, *, max_bytes: int) -> None:
        """Reopen retained objects for the existing raw/snapshot readers without replacing files.

        Args:
            version: Fully pinned dataset and derived features.
            destination: New or existing explicit local cache root; no symlink ancestors.
            max_bytes: Bound on the complete version inventory, including raw bytes.

        Raises:
            ValueError: Inventory exceeds budget or existing bytes/path ownership conflict.
        """
        version.__post_init__()
        if (
            type(max_bytes) is not int
            or sum(item.size_bytes for item in version.objects) > max_bytes
        ):
            raise ValueError("versioned dataset exceeds materialization byte budget")
        if destination.is_symlink() or destination.absolute() != destination.resolve():
            raise ValueError("materialization requires a resolved non-symlink root")
        destination.mkdir(parents=True, exist_ok=True)
        for item in version.objects:
            target = destination / item.path
            if any(parent.is_symlink() for parent in (target, *target.parents)):
                raise ValueError("versioned object path crosses a symlink")
            payload = self.read(version, item)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.read_bytes() != payload:
                    raise ValueError("materialized bytes conflict with pinned version")
                continue
            with NamedTemporaryFile(dir=target.parent, prefix=".lakefs-", delete=False) as staged:
                temporary = Path(staged.name)
                try:
                    staged.write(payload)
                    staged.flush()
                    os.fsync(staged.fileno())
                    os.link(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            sync_directory(target.parent)
