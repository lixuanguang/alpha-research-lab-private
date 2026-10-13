"""Seal finished socket-client logs and archive them losslessly as zstd streams."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import time
from collections.abc import Iterator
from compression import zstd
from pathlib import Path
from typing import BinaryIO, ClassVar, Literal

# project library imports
from serialization import DomainCodec, DurableDirectory, WireRecord


class ClientLogSeal(WireRecord, frozen=True):
    """Name one finished client log's exact final length and SHA-256."""

    log: str
    bytes: int
    sha256: str

    def __post_init__(self) -> None:
        """Require a plain log name, a length and a SHA-256 digest."""
        if (
            not self.log.endswith(".jsonl")
            or "/" in self.log
            or type(self.bytes) is not int
            or self.bytes < 0
            or len(self.sha256) != 64
        ):
            raise ValueError("invalid client log seal")


class ClientLogArchiveResult(WireRecord, frozen=True):
    """Report one log's archival: archived, already archived, or why it was skipped."""

    log: str
    status: Literal["archived", "already_archived", "skipped"]
    reason: str | None = None
    plaintext_bytes: int = 0
    archive_bytes: int = 0
    peak_bytes: int = 0
    seconds: float = 0.0


class ClientLogArchive:
    """Keep a ``SocketPaperAccount`` log's exact bytes, compressed once its writer finished.

    The writer proves it has finished by sealing its log (``seal``): every attempt has
    recorded its outcome or never will, nothing more is appended, and the seal names the
    log's durable length and SHA-256. ``archive`` compresses only a sealed log whose
    bytes still equal its seal. It writes ``<log>.jsonl.zst.tmp``, checks that it
    decompresses to the sealed bytes, renames it to ``<log>.jsonl.zst``, and only then
    removes the plaintext; a log without a seal, or changed since, is kept and reported
    skipped. Until the plaintext is removed it stays authoritative, so an interrupted
    archival leaves either the plaintext alone or both copies. ``lines`` reads either
    form in bounded memory and yields the original bytes, so an attempt without an
    outcome stays uncertain however the log is stored.
    """

    suffix: ClassVar[str] = ".jsonl"
    archived_suffix: ClassVar[str] = ".jsonl.zst"
    sealed_suffix: ClassVar[str] = ".sealed.json"
    temporary_suffix: ClassVar[str] = ".jsonl.zst.tmp"
    # A record carries at most a 1 MiB response, escaped, plus its attempt fields.
    max_line_bytes: ClassVar[int] = 4 * 1_048_576
    chunk_bytes: ClassVar[int] = 1_048_576
    _options: ClassVar[dict[int, int]] = {
        zstd.CompressionParameter.compression_level: 3,
        zstd.CompressionParameter.checksum_flag: 1,
    }

    @classmethod
    def seal(cls, log: Path) -> ClientLogSeal:
        """Make a finished log durable and record its length and digest beside it.

        Call this only when the log's single writer will append nothing more. Sealing
        again returns the same seal while the log is unchanged.

        Raises:
            ValueError: An existing seal names other bytes than the log holds.
        """
        if not log.is_absolute() or not log.name.endswith(cls.suffix):
            raise ValueError("client log path must be an absolute .jsonl file")
        with log.open("rb") as stream:
            os.fsync(stream.fileno())
            length, digest = cls._measure(stream)
        seal = ClientLogSeal(log=log.name, bytes=length, sha256=digest)
        path = cls._seal_path(log)
        if path.exists():
            existing = cls.read_seal(log)
            if existing != seal:
                raise ValueError("client log changed after it was sealed")
            return existing
        temporary = path.with_name(f".{path.name}.tmp")
        with temporary.open("wb") as stream:
            stream.write(DomainCodec().encode_json(seal))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        DurableDirectory.sync(log.parent)
        return seal

    @classmethod
    def read_seal(cls, log: Path) -> ClientLogSeal | None:
        """Return the seal of a log (named by its plaintext path), if it was sealed."""
        path = cls._seal_path(log)
        if not path.is_file():
            return None
        seal = DomainCodec().decode_json(path.read_bytes(), ClientLogSeal)
        if seal.log != log.name:
            raise ValueError("client log seal names another log")
        return seal

    @classmethod
    def archive(cls, directory: Path) -> tuple[ClientLogArchiveResult, ...]:
        """Archive every sealed, unchanged log in one client directory, keeping the rest."""
        if not directory.is_absolute():
            raise ValueError("client log directory must be absolute")
        results: list[ClientLogArchiveResult] = []
        for stale in sorted(directory.glob(f"*{cls.temporary_suffix}")):
            # An interrupted archival: its plaintext is still authoritative.
            stale.unlink()
        names = {path.name.removesuffix(cls.suffix) for path in directory.glob(f"*{cls.suffix}")}
        names |= {
            path.name.removesuffix(cls.archived_suffix)
            for path in directory.glob(f"*{cls.archived_suffix}")
        }
        for name in sorted(names):
            results.append(cls._archive_one(directory / f"{name}{cls.suffix}"))
        DurableDirectory.sync(directory)
        return tuple(results)

    @classmethod
    def lines(cls, log: Path) -> Iterator[bytes]:
        """Yield a log's exact lines, newline included, from its plaintext or archive.

        The concatenated lines are the log's original bytes, an unterminated last line
        included. An archive is checked against its seal once it is fully read, so a
        reader that stops early has not checked it.

        Raises:
            ValueError: A line exceeds ``max_line_bytes``, or an archive is unsealed,
                corrupt or differs from its seal.
        """
        if log.is_file():
            with log.open("rb") as stream:
                yield from cls._bounded_lines(stream)
            return
        archive = cls._archive_path(log)
        seal = cls.read_seal(log)
        if seal is None or not archive.is_file():
            raise ValueError("client log is neither present nor sealed and archived")
        digest, length = hashlib.sha256(), 0
        try:
            with zstd.ZstdFile(archive, "rb") as stream:
                for line in cls._bounded_lines(stream):
                    digest.update(line)
                    length += len(line)
                    yield line
        except zstd.ZstdError as error:
            raise ValueError("client log archive is corrupt") from error
        if (length, digest.hexdigest()) != (seal.bytes, seal.sha256):
            raise ValueError("client log archive differs from its seal")

    @classmethod
    def _archive_one(cls, log: Path) -> ClientLogArchiveResult:
        """Archive one log, or report why its plaintext is kept."""
        archive = cls._archive_path(log)
        seal = cls.read_seal(log)
        if seal is None:
            return ClientLogArchiveResult(
                log=log.name, status="skipped", reason="writer_not_proven_finished"
            )
        started = time.monotonic()
        if archive.is_file():
            # Published before an interruption: the plaintext goes only once the
            # archive is proven to hold the sealed bytes.
            if not cls._matches(archive, seal, compressed=True):
                return ClientLogArchiveResult(
                    log=log.name, status="skipped", reason="published_archive_differs_from_seal"
                )
            peak = cls._occupied(log) + cls._occupied(archive)
            if log.exists():
                log.unlink()
                DurableDirectory.sync(log.parent)
            return ClientLogArchiveResult(
                log=log.name,
                status="already_archived",
                archive_bytes=cls._occupied(archive),
                peak_bytes=peak,
                seconds=time.monotonic() - started,
            )
        if not log.is_file() or not cls._matches(log, seal, compressed=False):
            return ClientLogArchiveResult(
                log=log.name, status="skipped", reason="log_differs_from_seal"
            )
        temporary = archive.with_name(archive.name + ".tmp")
        with (
            log.open("rb") as source,
            zstd.ZstdFile(temporary, "wb", options=cls._options) as target,
        ):
            while chunk := source.read(cls.chunk_bytes):
                target.write(chunk)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        if not cls._matches(temporary, seal, compressed=True):
            temporary.unlink()
            return ClientLogArchiveResult(
                log=log.name, status="skipped", reason="archive_failed_verification"
            )
        temporary.rename(archive)
        DurableDirectory.sync(log.parent)
        plaintext, compressed = cls._occupied(log), cls._occupied(archive)
        log.unlink()
        DurableDirectory.sync(log.parent)
        return ClientLogArchiveResult(
            log=log.name,
            status="archived",
            plaintext_bytes=plaintext,
            archive_bytes=compressed,
            peak_bytes=plaintext + compressed,
            seconds=time.monotonic() - started,
        )

    @classmethod
    def _matches(cls, path: Path, seal: ClientLogSeal, *, compressed: bool) -> bool:
        """Report whether a file holds, or decompresses to, exactly the sealed bytes."""
        try:
            if compressed:
                with zstd.ZstdFile(path, "rb") as stream:
                    length, digest = cls._measure(stream)
            else:
                with path.open("rb") as stream:
                    length, digest = cls._measure(stream)
        except zstd.ZstdError, EOFError:
            return False
        return (length, digest) == (seal.bytes, seal.sha256)

    @classmethod
    def _measure(cls, stream: BinaryIO | zstd.ZstdFile) -> tuple[int, str]:
        """Return a stream's length and SHA-256, reading in bounded chunks."""
        digest, length = hashlib.sha256(), 0
        while chunk := stream.read(cls.chunk_bytes):
            digest.update(chunk)
            length += len(chunk)
        return length, digest.hexdigest()

    @classmethod
    def _bounded_lines(cls, stream: BinaryIO | zstd.ZstdFile) -> Iterator[bytes]:
        """Yield lines of at most ``max_line_bytes``, the last possibly unterminated."""
        while line := stream.readline(cls.max_line_bytes + 1):
            if len(line) > cls.max_line_bytes:
                raise ValueError("client log line exceeds its bound")
            yield line

    @staticmethod
    def _occupied(path: Path) -> int:
        """Return a file's allocated bytes, or zero when it is absent."""
        return path.stat().st_blocks * 512 if path.exists() else 0

    @classmethod
    def _seal_path(cls, log: Path) -> Path:
        """Name a log's seal beside it."""
        return log.with_name(log.name.removesuffix(cls.suffix) + cls.sealed_suffix)

    @classmethod
    def _archive_path(cls, log: Path) -> Path:
        """Name a log's archive beside it."""
        return log.with_name(log.name.removesuffix(cls.suffix) + cls.archived_suffix)
