"""Pin lakeFS object versions and materialize verified bytes for existing dataset readers."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import re
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import Literal
from urllib.parse import urlsplit

# third party library imports
import msgspec
from lakefs_sdk import ApiClient, CommitCreation, Configuration, RepositoryCreation
from lakefs_sdk.api.branches_api import BranchesApi
from lakefs_sdk.api.commits_api import CommitsApi
from lakefs_sdk.api.objects_api import ObjectsApi
from lakefs_sdk.api.repositories_api import RepositoriesApi
from lakefs_sdk.api.tags_api import TagsApi

# project library imports
from serialization import DomainCodec, DurableDirectory, WireRecord

# One capture segment is at most 1 GB; objects stream in bounded ranges.
_MAX_OBJECT_BYTES = 2 * 1024**3
_RANGE_BYTES = 64 * 1024 * 1024
# The largest object returned whole by ``LakeFSStorage.read``.
_READ_BYTES = 64 * 1024 * 1024


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
            or not 0 < self.size_bytes <= _MAX_OBJECT_BYTES
        ):
            raise ValueError("invalid versioned object path, size or digest")


class DatasetVersion(WireRecord, frozen=True):
    """Bind a published dataset and derived feature bytes to an immutable storage commit."""

    repository: str
    commit_id: str
    objects: tuple[VersionedObject, ...]
    schema_version: str = "lakefs-dataset-version"

    def __post_init__(self) -> None:
        """Require a bounded unique inventory of raw and snapshot objects, features optional.

        A consumer that needs derived feature bytes, such as the configured backtest,
        requires them itself.
        """
        if (
            self.schema_version != "lakefs-dataset-version"
            or re.fullmatch(r"[a-z0-9][a-z0-9-]{2,62}", self.repository) is None
            or re.fullmatch(r"[0-9a-f]{64}", self.commit_id) is None
            or type(self.objects) is not tuple
            or not 2 <= len(self.objects) <= 4096
        ):
            raise ValueError("invalid lakeFS repository, commit or inventory")
        for item in self.objects:
            if type(item) is not VersionedObject:
                raise TypeError("dataset version requires typed object identities")
            item.__post_init__()
        if len({item.path for item in self.objects}) != len(self.objects):
            raise ValueError("duplicate lakeFS object path")
        components = {PurePosixPath(item.path).parts[0] for item in self.objects}
        if not {"raw", "snapshots"} <= components <= {"raw", "snapshots", "features"}:
            raise ValueError("dataset version requires source and dataset bytes")

    @property
    def components(self) -> frozenset[str]:
        """Return the top-level components this version contains."""
        return frozenset(PurePosixPath(item.path).parts[0] for item in self.objects)

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
        self._owned_client: ApiClient | None = None
        self._branches = BranchesApi(client)
        self._tags = TagsApi(client)
        self._commits = CommitsApi(client)
        self._objects = ObjectsApi(client)
        self._repositories = RepositoriesApi(client)

    @classmethod
    def connect(cls, endpoint: str, credentials: Path) -> LakeFSStorage:
        """Open an explicitly selected private lakeFS connection that this storage owns.

        The credentials are read from the selected file and never copied into research
        records; :meth:`close` releases the connection pool.

        Args:
            endpoint: Non-secret HTTP(S) API endpoint without user information, query or
                fragment.
            credentials: JSON file holding ``access_key_id`` and ``secret_access_key``.

        Returns:
            Storage bound to a client it closes.

        Raises:
            ValueError: The endpoint is not an explicit non-secret HTTP(S) API endpoint.
        """
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("lakeFS requires an explicit non-secret HTTP(S) API endpoint")
        fields = msgspec.json.decode(credentials.read_bytes(), type=dict[str, msgspec.Raw])
        client = ApiClient(
            Configuration(
                host=endpoint,
                username=msgspec.json.decode(fields["access_key_id"], type=str),
                password=msgspec.json.decode(fields["secret_access_key"], type=str),
            )
        )
        storage = cls(client)
        storage._owned_client = client
        return storage

    def close(self) -> None:
        """Close the connection pool of a client opened by :meth:`connect`; others are kept."""
        if self._owned_client is not None:
            self._owned_client.close()

    def create(self, repository: str, *, namespace: str, branch: str = "main") -> None:
        """Create an explicitly named repository with a storage namespace and default branch.

        Args:
            repository: New repository name.
            namespace: Storage namespace, for example ``local://<repository>``.
            branch: Default branch name.
        """
        self._repositories.create_repository(
            RepositoryCreation(name=repository, storage_namespace=namespace, default_branch=branch),
            _request_timeout=30,
        )

    def publish(
        self,
        repository: str,
        branch: str,
        root: Path,
        *,
        components: tuple[str, ...],
        message: str,
        max_bytes: int,
    ) -> DatasetVersion:
        """Upload named component directories, commit them and resolve the new version.

        Every regular file under ``root/<component>`` is uploaded at its path relative
        to ``root``, then the branch is committed and each object is read back and
        verified at the commit.

        Args:
            repository: Existing repository.
            branch: Writable branch.
            root: Local directory holding the components.
            components: Top-level directories to publish, among ``raw``, ``snapshots``
                and ``features``.
            message: Commit message.
            max_bytes: Positive per-object byte bound.

        Returns:
            The verified immutable version of exactly the uploaded objects.

        Raises:
            ValueError: A component, file type or size is unsupported.
        """
        if not components or not set(components) <= {"raw", "snapshots", "features"}:
            raise ValueError("lakeFS publication selects raw, snapshots or features")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("lakeFS publication requires a positive max_bytes")
        objects: list[VersionedObject] = []
        for component in components:
            for path in sorted((root / component).rglob("*")):
                if path.is_symlink():
                    raise ValueError("lakeFS publication refuses symbolic links")
                if not path.is_file():
                    continue
                size = path.stat().st_size
                if size > max_bytes:
                    raise ValueError("lakeFS object exceeds max_bytes")
                if size == 0:
                    raise ValueError("lakeFS publication cannot version an empty file")
                name = path.relative_to(root).as_posix()
                digest = self._file_sha256(path)
                # The SDK opens ``content`` as a local file path and reads it.
                self._objects.upload_object(
                    repository, branch, name, content=str(path), _request_timeout=300
                )
                objects.append(VersionedObject(path=name, sha256=digest, size_bytes=size))
        commit = self._commits.commit(
            repository, branch, CommitCreation(message=message), _request_timeout=60
        )
        return self.resolve(repository, commit.id, kind="commit", objects=tuple(objects))

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
            self.verify(version, item)
        return version

    def read(self, version: DatasetVersion, item: VersionedObject) -> bytes:
        """Retrieve one bounded immutable object whole, verifying its digest.

        Args:
            version: Resolved repository commit and byte inventory.
            item: Exact member of that inventory, at most 64 MiB.

        Returns:
            Verified complete bytes without SDK records or storage timestamps.

        Raises:
            ValueError: Object membership, size or SHA-256 differs, or it is too large.
        """
        if item.size_bytes > _READ_BYTES:
            raise ValueError("lakeFS object is too large to read whole; materialize it")
        return b"".join(self._verified(version, item))

    def verify(self, version: DatasetVersion, item: VersionedObject) -> None:
        """Stream one object at the pinned commit and verify its size and digest."""
        for _ in self._verified(version, item):
            pass

    def _verified(self, version: DatasetVersion, item: VersionedObject) -> Iterator[bytes]:
        """Yield one object's bytes in bounded ranges, then require its size and digest."""
        version.__post_init__()
        if item not in version.objects:
            raise ValueError("object is not part of the pinned dataset version")
        digest = hashlib.sha256()
        received = 0
        for start in range(0, item.size_bytes, _RANGE_BYTES):
            end = min(start + _RANGE_BYTES, item.size_bytes) - 1
            chunk = bytes(
                self._objects.get_object(
                    version.repository,
                    version.commit_id,
                    item.path,
                    range=f"bytes={start}-{end}",
                    presign=False,
                    _request_timeout=60,
                )
            )
            if len(chunk) != end - start + 1:
                raise ValueError("lakeFS object differs from retained bytes")
            digest.update(chunk)
            received += len(chunk)
            yield chunk
        if received != item.size_bytes or digest.hexdigest() != item.sha256:
            raise ValueError("lakeFS object differs from retained bytes")

    def materialize(self, version: DatasetVersion, destination: Path, *, max_bytes: int) -> None:
        """Reopen retained objects for the existing raw/snapshot readers without replacing files.

        Objects stream to staged files in bounded ranges; nothing is linked into place
        until its complete digest is verified.

        Args:
            version: Fully pinned dataset and, optionally, derived features.
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
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if (
                    target.stat().st_size != item.size_bytes
                    or self._file_sha256(target) != item.sha256
                ):
                    raise ValueError("materialized bytes conflict with pinned version")
                continue
            with NamedTemporaryFile(dir=target.parent, prefix=".lakefs-", delete=False) as staged:
                temporary = Path(staged.name)
                try:
                    for chunk in self._verified(version, item):
                        staged.write(chunk)
                    staged.flush()
                    os.fsync(staged.fileno())
                    os.link(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            DurableDirectory.sync(target.parent)

    @staticmethod
    def _file_sha256(path: Path) -> str:
        """Digest one local file in bounded reads."""
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(_RANGE_BYTES):
                digest.update(chunk)
        return digest.hexdigest()
