"""Back up quiesced local workspace components and restore verified bytes atomically."""

from __future__ import annotations

# standard library imports
import fcntl
import hashlib
import os
import re
import sqlite3
import stat
from collections.abc import Callable
from contextlib import ExitStack, closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO, Literal, cast

# project library imports
from serialization import DomainCodec, WireRecord, publish_directory, sync_directory

_COMPONENT = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_LOCK_FILES = frozenset({".workspace.lock", ".workers.lock", ".writer.lock"})
_SQLITE_AUXILIARY_SUFFIXES = (".sqlite3-wal", ".sqlite3-shm", ".sqlite3-journal")
_IMMUTABLE_SQLITE_AUXILIARY_SUFFIXES = (".db-wal", ".db-shm", ".db-journal")
# An account journal's live dispatch lease is marked by an OS-locked sibling file.
_DISPATCH_LEASE_LOCK = re.compile(r".+\.sqlite3\.lease-[0-9a-z]+\Z")


class WorkspaceFile(WireRecord, frozen=True, kw_only=True):
    """Identify one regular retained file by relative name, byte count and digest."""

    name: str
    size_bytes: int
    sha256: str
    mode: int


class WorkspaceManifest(WireRecord, frozen=True, kw_only=True):
    """Describe the exact component tree published in one backup."""

    schema_version: Literal["workspace-backup"]
    components: tuple[str, ...]
    directories: tuple[str, ...]
    files: tuple[WorkspaceFile, ...]

    def __post_init__(self) -> None:
        """Reject duplicate or unsafe archive names before any restore path is built."""
        if self.schema_version != "workspace-backup":
            raise ValueError("unsupported workspace backup schema")
        if not self.components or len(set(self.components)) != len(self.components):
            raise ValueError("workspace backup requires unique components")
        if any(_COMPONENT.fullmatch(name) is None for name in self.components):
            raise ValueError("workspace backup contains an unsafe component")
        if len(set(self.directories)) != len(self.directories):
            raise ValueError("workspace backup has duplicate directories")
        names = tuple(record.name for record in self.files)
        if len(set(names)) != len(names):
            raise ValueError("workspace backup has duplicate files")
        for name in (*self.directories, *names):
            self._relative_name(name)
            if name.split("/", maxsplit=1)[0] not in self.components:
                raise ValueError("workspace backup path is outside selected components")
        if any(
            _DIGEST.fullmatch(record.sha256) is None
            or record.size_bytes < 0
            or record.mode < 0
            or record.mode > 0o777
            for record in self.files
        ):
            raise ValueError("workspace backup file metadata is invalid")

    @staticmethod
    def _relative_name(name: str) -> None:
        """Keep a manifest-supplied name inside the restore destination."""
        path = Path(name)
        if (
            not name
            or path.is_absolute()
            or any(part in (".", "..") for part in path.parts)
            or path.as_posix() != name
        ):
            raise ValueError("workspace backup contains an unsafe relative path")


class WorkspaceBackup:
    """Copy explicit local stores after known writers stop, then verify each byte.

    The operation excludes volatile lock and SQLite WAL files. It acquires the
    AttemptStore writer lock and job worker/queue locks when those components are
    selected. Other component producers must be stopped by the caller; a second
    source scan rejects observed mutation during copying.
    """

    @classmethod
    def create(
        cls,
        source_root: Path,
        backup_root: Path,
        *,
        components: tuple[str, ...],
        max_files: int = 100_000,
        max_total_bytes: int = 109_951_162_777,
        validate_quiescence: Callable[[], None] | None = None,
    ) -> str:
        """Publish a checked backup at an absent destination.

        Args:
            source_root: Existing local workspace containing named component directories.
            backup_root: Absent destination; its parent must exist on a local filesystem.
            components: Explicit stores to preserve, including ``jobs`` for queue state.
            max_files: Positive cap on retained regular files.
            max_total_bytes: Positive aggregate copy budget.
            validate_quiescence: Optional owner check under the acquired database write locks.

        Returns:
            SHA-256 of the canonical backup manifest bytes.

        Raises:
            BlockingIOError: A known attempt writer or job worker is active.
            ValueError: A component, file type, byte budget or mutation is unsafe.
        """
        cls._validate_request(source_root, backup_root, components, max_files, max_total_bytes)
        with ExitStack() as stack:
            cls._acquire_locks(stack, source_root, components)
            cls._require_idle_jobs(source_root, components)
            if validate_quiescence is not None:
                validate_quiescence()
            before = cls._inventory(source_root, components, max_files, max_total_bytes)
            with TemporaryDirectory(dir=backup_root.parent, prefix=".workspace-backup-") as temp:
                staging = Path(temp)
                payload = staging / "payload"
                payload.mkdir()
                directories = tuple(name for name, is_dir, _, _ in before if is_dir)
                for name in directories:
                    (payload / name).mkdir(parents=True, exist_ok=True)
                files: list[WorkspaceFile] = []
                for name, is_dir, _, _ in before:
                    if is_dir:
                        continue
                    source = source_root / name
                    destination = payload / name
                    if source.suffix == ".sqlite3":
                        cls._copy_sqlite(source, destination)
                    else:
                        cls._copy_file(source, destination)
                    os.chmod(destination, stat.S_IMODE(source.lstat().st_mode))
                    files.append(cls._describe_file(destination, name))
                after = cls._inventory(source_root, components, max_files, max_total_bytes)
                if before != after:
                    raise ValueError("workspace changed during backup; quiesce all producers")
                manifest = WorkspaceManifest(
                    schema_version="workspace-backup",
                    components=components,
                    directories=directories,
                    files=tuple(files),
                )
                manifest.__post_init__()
                encoded = DomainCodec().encode_json(manifest)
                with (staging / "manifest.json").open("xb") as output:
                    output.write(encoded)
                    output.flush()
                    os.fsync(output.fileno())
                cls._verify(staging, max_files=max_files, max_total_bytes=max_total_bytes)
                cls._sync_tree(staging)
                if not publish_directory(staging, backup_root):
                    raise FileExistsError("backup destination already exists")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def restore(
        cls,
        backup_root: Path,
        destination_root: Path,
        *,
        max_files: int = 100_000,
        max_total_bytes: int = 109_951_162_777,
        validate_restored: Callable[[Path], None] | None = None,
    ) -> WorkspaceManifest:
        """Verify a backup and atomically publish it into an absent workspace path.

        The absent destination prevents replacing an active worker or partial state.
        An optional owner validator checks the staged workspace before publication.
        Callers switch application references only after this method succeeds.
        """
        if destination_root.exists() or destination_root.is_symlink():
            raise FileExistsError("restore destination must be absent")
        if not destination_root.parent.is_dir():
            raise FileNotFoundError("restore destination parent must exist")
        manifest = cls._verify(backup_root, max_files=max_files, max_total_bytes=max_total_bytes)
        with TemporaryDirectory(dir=destination_root.parent, prefix=".workspace-restore-") as temp:
            staging = Path(temp)
            for name in manifest.directories:
                (staging / name).mkdir(parents=True, exist_ok=True)
            for record in manifest.files:
                destination = staging / record.name
                cls._copy_file(backup_root / "payload" / record.name, destination)
                os.chmod(destination, record.mode)
            cls._verify_payload(staging, manifest, max_files, max_total_bytes)
            if validate_restored is not None:
                validate_restored(staging)
            cls._sync_tree(staging)
            if not publish_directory(staging, destination_root):
                raise FileExistsError("restore destination must be absent")
        return manifest

    @classmethod
    def verify(
        cls,
        backup_root: Path,
        *,
        max_files: int = 100_000,
        max_total_bytes: int = 109_951_162_777,
    ) -> WorkspaceManifest:
        """Validate an existing immutable backup without changing the workspace."""
        return cls._verify(backup_root, max_files=max_files, max_total_bytes=max_total_bytes)

    @staticmethod
    def _validate_request(
        source_root: Path,
        backup_root: Path,
        components: tuple[str, ...],
        max_files: int,
        max_total_bytes: int,
    ) -> None:
        """Reject unsafe roots, missing selected stores and unbounded requests."""
        if not source_root.is_dir() or source_root.is_symlink():
            raise ValueError("workspace source must be an existing directory")
        if backup_root.exists() or backup_root.is_symlink():
            raise FileExistsError("workspace backup destination must be absent")
        if not backup_root.parent.is_dir() or backup_root.resolve().is_relative_to(
            source_root.resolve()
        ):
            raise ValueError("workspace backup requires an existing external parent")
        if type(max_files) is not int or max_files <= 0:
            raise ValueError("workspace max_files must be positive")
        if type(max_total_bytes) is not int or max_total_bytes <= 0:
            raise ValueError("workspace max_total_bytes must be positive")
        if not components or len(set(components)) != len(components):
            raise ValueError("workspace backup requires unique components")
        for name in components:
            if type(name) is not str or _COMPONENT.fullmatch(name) is None:
                raise ValueError("workspace component name is unsafe")
            path = source_root / name
            if not path.is_dir() or path.is_symlink():
                raise ValueError(f"workspace component is missing or unsafe: {name}")

    @staticmethod
    def _acquire_locks(stack: ExitStack, source_root: Path, components: tuple[str, ...]) -> None:
        """Fence nested attempt writers, job workers and mutable SQLite stores."""
        paths = [source_root / ".workspace.lock"]
        if "jobs" in components:
            paths.extend(
                (source_root / "jobs" / ".workspace.lock", source_root / "jobs" / ".workers.lock")
            )
        databases: list[Path] = []
        for component in components:
            root = source_root / component
            paths.extend(sorted(root.rglob(".writer.lock")))
            databases.extend(sorted(root.rglob("*.sqlite3")))
        if "attempts" in components and not (source_root / "attempts" / ".writer.lock").exists():
            paths.append(source_root / "attempts" / ".writer.lock")
        for path in paths:
            if path.is_symlink():
                raise ValueError("workspace writer lock path is unsafe")
            lock: BinaryIO = stack.enter_context(path.open("a+b"))
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        for database in databases:
            if not stat.S_ISREG(database.lstat().st_mode):
                raise ValueError("workspace SQLite path is unsafe")
            connection = stack.enter_context(closing(sqlite3.connect(database, timeout=0)))
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                raise BlockingIOError("workspace SQLite writer is active") from error
            stack.callback(connection.rollback)

    @staticmethod
    def _require_idle_jobs(source_root: Path, components: tuple[str, ...]) -> None:
        """Refuse a stale running claim until the pool has recovered it."""
        if "jobs" not in components:
            return
        path = source_root / "jobs" / "jobs.sqlite3"
        if not path.is_file():
            raise ValueError("jobs component has no durable queue database")
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as connection:
            count = WorkspaceBackup._sqlite_scalar(
                connection, "SELECT COUNT(*) FROM jobs WHERE status='running'"
            )
            if type(count) is not int or count != 0:
                raise ValueError("workspace jobs must be idle before backup")

    @classmethod
    def _inventory(
        cls,
        root: Path,
        components: tuple[str, ...],
        max_files: int,
        max_total_bytes: int,
    ) -> tuple[tuple[str, bool, int, str], ...]:
        """Walk selected trees and hash source bytes to detect changes during copying."""
        entries: list[tuple[str, bool, int, str]] = []
        total = 0
        files = 0
        for component in components:
            directory = root / component
            for path in (directory, *sorted(directory.rglob("*"))):
                if (
                    path.name in _LOCK_FILES
                    or path.name.endswith(_SQLITE_AUXILIARY_SUFFIXES)
                    or _DISPATCH_LEASE_LOCK.match(path.name)
                ):
                    continue
                if path.name.endswith(_IMMUTABLE_SQLITE_AUXILIARY_SUFFIXES):
                    raise ValueError("immutable serving SQLite generation is not quiescent")
                mode = path.lstat().st_mode
                name = path.relative_to(root).as_posix()
                if stat.S_ISDIR(mode):
                    entries.append((name, True, 0, ""))
                    continue
                if not stat.S_ISREG(mode):
                    raise ValueError("workspace component contains a symlink or special file")
                files += 1
                size = path.stat().st_size
                total += size
                if files > max_files or total > max_total_bytes:
                    raise ValueError("workspace backup exceeds file or byte budget")
                digest = cls._digest_file(path)
                entries.append((name, False, size, digest))
        return tuple(entries)

    @staticmethod
    def _copy_sqlite(source: Path, destination: Path) -> None:
        """Use SQLite's consistent backup API instead of copying a WAL main file."""
        with closing(sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(destination)) as copy:
                original.backup(copy)
                check = WorkspaceBackup._sqlite_scalar(copy, "PRAGMA integrity_check")
                if check != "ok":
                    raise ValueError("workspace job database backup failed integrity check")
        with destination.open("rb") as saved:
            os.fsync(saved.fileno())

    @staticmethod
    def _copy_file(source: Path, destination: Path) -> None:
        """Copy a regular file without following a changed symlink after inventory."""
        if not stat.S_ISREG(source.lstat().st_mode):
            raise ValueError("workspace source file changed type")
        with source.open("rb") as original, destination.open("xb") as copy:
            for chunk in iter(lambda: original.read(1_048_576), b""):
                copy.write(chunk)
            copy.flush()
            os.fsync(copy.fileno())

    @classmethod
    def _describe_file(cls, path: Path, name: str) -> WorkspaceFile:
        """Record restored byte identity and permission mode."""
        mode = path.stat().st_mode
        return WorkspaceFile(
            name=name,
            size_bytes=path.stat().st_size,
            sha256=cls._digest_file(path),
            mode=stat.S_IMODE(mode),
        )

    @staticmethod
    def _digest_file(path: Path) -> str:
        """Hash a file in bounded chunks."""
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1_048_576), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _sqlite_scalar(connection: sqlite3.Connection, query: str) -> object:
        """Narrow a one-column SQLite diagnostic at the untyped driver boundary."""
        raw = cast(object, connection.execute(query).fetchone())
        if not isinstance(raw, tuple) or len(raw) != 1:
            raise ValueError("workspace SQLite diagnostic returned an invalid row")
        return cast(tuple[object], raw)[0]

    @classmethod
    def _verify(
        cls,
        backup_root: Path,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> WorkspaceManifest:
        """Verify a published backup's schema, inventory and complete byte hashes."""
        if not backup_root.is_dir() or backup_root.is_symlink():
            raise ValueError("workspace backup root is missing or unsafe")
        if not stat.S_ISREG((backup_root / "manifest.json").lstat().st_mode):
            raise ValueError("workspace backup manifest must be a regular file")
        manifest = DomainCodec().decode_json(
            (backup_root / "manifest.json").read_bytes(), WorkspaceManifest
        )
        manifest.__post_init__()
        payload = backup_root / "payload"
        cls._verify_payload(payload, manifest, max_files, max_total_bytes)
        if {path.name for path in backup_root.iterdir()} != {"manifest.json", "payload"}:
            raise ValueError("workspace backup contains unexpected root entries")
        return manifest

    @classmethod
    def _verify_payload(
        cls,
        payload: Path,
        manifest: WorkspaceManifest,
        max_files: int,
        max_total_bytes: int,
    ) -> None:
        """Reject missing, extra, changed or nonregular restored payload entries."""
        if not payload.is_dir() or payload.is_symlink():
            raise ValueError("workspace backup payload is missing or unsafe")
        actual_dirs: set[str] = set()
        actual_files: set[str] = set()
        for path in payload.rglob("*"):
            name = path.relative_to(payload).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                actual_dirs.add(name)
            elif stat.S_ISREG(mode):
                actual_files.add(name)
            else:
                raise ValueError("workspace backup contains a symlink or special file")
        if actual_dirs != set(manifest.directories) or actual_files != {
            record.name for record in manifest.files
        }:
            raise ValueError("workspace backup inventory differs")
        if len(manifest.files) > max_files:
            raise ValueError("workspace backup exceeds file budget")
        total = 0
        for record in manifest.files:
            path = payload / record.name
            size = path.stat().st_size
            total += size
            if total > max_total_bytes or size != record.size_bytes:
                raise ValueError("workspace backup exceeds byte budget or file size differs")
            if stat.S_IMODE(path.stat().st_mode) != record.mode:
                raise ValueError("workspace backup file mode differs")
            if cls._digest_file(path) != record.sha256:
                raise ValueError("workspace backup file digest differs")

    @classmethod
    def _sync_tree(cls, root: Path) -> None:
        """Synchronize staged directories from leaves to publication parent."""
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_dir():
                sync_directory(path)
        sync_directory(root)
