"""Seal finished socket-client logs and archive them without changing a byte."""

from __future__ import annotations

# standard library imports
import hashlib
import socket
import threading
from compression import zstd
from pathlib import Path
from tempfile import TemporaryDirectory

# third party library imports
import msgspec
import pytest
from test_account_service import _SOCKET_ROOT, _ReplyService
from test_paper_activation import TestPaperActivation as _ActivationFixture

# project library imports
from execution import (
    AccountExecutionRequest,
    AccountExecutionResult,
    ClientLogArchive,
    ClientLogSeal,
    PaperOwner,
    SocketPaperAccount,
)
from serialization import DomainCodec


class _Outcomes(msgspec.Struct, frozen=True):
    """Each attempt's outcome as an operator reads it: result bytes, error or uncertain."""

    results: dict[str, bytes]
    errors: dict[str, str]
    uncertain: tuple[str, ...]

    @staticmethod
    def read(lines: list[bytes]) -> _Outcomes:
        """Interpret records; a missing outcome or unresolved repeat is uncertain."""
        requested: list[str] = []
        results: dict[str, bytes] = {}
        errors: dict[str, str] = {}
        held: dict[str, bytes] = {}
        for line in lines:
            if not line.endswith(b"\n"):
                continue  # An unterminated record was never completely written.
            record = msgspec.json.decode(line, type=dict[str, msgspec.Raw])
            attempt = msgspec.json.decode(record.pop("attempt"), type=str)
            ((kind, value),) = record.items()
            if kind == "request":
                requested.append(attempt)
            elif kind == "result":
                results[attempt] = bytes(value)
                held[hashlib.sha256(bytes(value)).hexdigest()] = bytes(value)
            elif kind == "error":
                errors[attempt] = msgspec.json.decode(value, type=str)
            else:
                digest = msgspec.json.decode(value, type=str)
                if digest in held:
                    results[attempt] = held[digest]
        uncertain = tuple(a for a in requested if a not in results and a not in errors)
        return _Outcomes(results=results, errors=errors, uncertain=uncertain)


class _HeldService:
    """Accept one request and answer it only once released."""

    def __init__(self, path: Path, reply: bytes) -> None:
        """Bind the socket and prepare the held answer."""
        self.reply, self.release = reply, threading.Event()
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(path))
        self.listener.listen(1)
        self.thread = threading.Thread(target=self._serve)
        self.thread.start()

    def _serve(self) -> None:
        """Read one frame, wait for release, then answer."""
        connection, _ = self.listener.accept()
        with connection:
            length = int.from_bytes(connection.recv(4, socket.MSG_WAITALL), "big")
            connection.recv(length, socket.MSG_WAITALL)
            self.release.wait(5)
            connection.sendall(b"\x00" + len(self.reply).to_bytes(4, "big") + self.reply)

    def close(self) -> None:
        """Release the answer and stop."""
        self.release.set()
        self.thread.join(5)
        self.listener.close()


class TestClientLogArchive:
    """A sealed log archives to its exact bytes; anything unproven stays plaintext."""

    owner = PaperOwner(
        account_id="shared",
        deployment_sha256="a" * 64,
        authorization_id="archive-grant",
        release_identity="b" * 64,
        owner_id="archive-owner",
        generation=1,
    )
    read = AccountExecutionRequest(
        action="inspect", projection="checkpoint", query_instance="alpha"
    )

    _matches = ClientLogArchive._matches

    @staticmethod
    def _refuse_archives(path: Path, seal: ClientLogSeal, *, compressed: bool) -> bool:
        """Fail every compressed copy's verification; check plaintext as usual."""
        return False if compressed else TestClientLogArchive._matches(path, seal, compressed=False)

    @staticmethod
    def _answer(state: str) -> bytes:
        """Encode one checkpoint read's answer."""
        return DomainCodec().encode_json(
            AccountExecutionResult(accounts=(), orders=(), checkpoint=state.encode())
        )

    def _client(self, root: Path) -> SocketPaperAccount:
        """Bind a client whose log lives in ``root/requests``."""
        return SocketPaperAccount(
            config=_ActivationFixture._config(),
            socket_path=root / "s.sock",
            requests=root / "requests",
            paper_owner=self.owner,
            timeout_seconds=2,
        )

    def _written(self, root: Path) -> Path:
        """Answer three reads A, A, B, then leave what a crash or lost response would.

        That is an unanswered attempt, a repeat naming no held result and a torn last record.
        """
        with _ReplyService(root / "s.sock", b"\x00", tuple(map(self._answer, "aab"))):
            client = self._client(root)
            for _ in range(3):
                client.execute(self.read)
        (log,) = (root / "requests").glob("*.jsonl")
        with log.open("ab") as stream:
            stream.write(b'{"attempt":"lost","request":{"action":"inspect","sha256":"')
            stream.write(b"0" * 64 + b'","bytes":10}}\n')
            stream.write(b'{"attempt":"dangling","request":{"action":"inspect","sha256":"')
            stream.write(b"1" * 64 + b'","bytes":10}}\n')
            stream.write(b'{"attempt":"dangling","repeated_result":"' + b"2" * 64 + b'"}\n')
            stream.write(b'{"attempt":"torn","res')
        return log

    def test_an_archived_log_reads_back_byte_for_byte_with_the_same_outcomes(self) -> None:
        """The archive keeps every byte, so repeats resolve and uncertain attempts stay so."""
        with TemporaryDirectory(prefix="client-log-", dir=_SOCKET_ROOT) as name:
            root = Path(name)
            log = self._written(root)
            original = log.read_bytes()
            before = _Outcomes.read(list(ClientLogArchive.lines(log)))
            seal = ClientLogArchive.seal(log)
            assert (seal.bytes, seal.sha256) == (
                len(original),
                hashlib.sha256(original).hexdigest(),
            )
            (result,) = ClientLogArchive.archive(root / "requests")
            assert result.status == "archived" and not log.exists()
            archive = log.with_name(log.name + ".zst")
            assert zstd.decompress(archive.read_bytes()) == original
            lines = list(ClientLogArchive.lines(log))
            assert b"".join(lines) == original
            after = _Outcomes.read(lines)
            assert after == before
            assert list(after.results.values()) == list(map(self._answer, "aab"))
            assert after.uncertain == ("lost", "dangling")
            assert result.peak_bytes == result.plaintext_bytes + result.archive_bytes
            # Allocation is whole blocks, so a tiny log may occupy no less once archived.
            assert result.archive_bytes <= result.plaintext_bytes
            assert archive.stat().st_size < len(original)

    def test_close_refuses_later_commands_and_seals_the_finished_log(self) -> None:
        """Closing seals exactly the durable log; a later command is refused, not logged."""
        with TemporaryDirectory(prefix="client-log-", dir=_SOCKET_ROOT) as name:
            root = Path(name)
            with _ReplyService(root / "s.sock", b"\x00", self._answer("a")):
                client = self._client(root)
                client.execute(self.read)
            seal = client.close(timeout_seconds=1)
            (log,) = (root / "requests").glob("*.jsonl")
            assert seal is not None and seal.bytes == len(log.read_bytes())
            with pytest.raises(ValueError, match="log is closed"):
                client.execute(self.read)
            assert seal.bytes == len(log.read_bytes())
            assert client.close(timeout_seconds=1) == seal

    def test_a_writer_with_a_command_in_flight_is_not_sealed_or_archived(self) -> None:
        """Close times out unsealed; the late outcome is still recorded; archival keeps it."""
        with TemporaryDirectory(prefix="client-log-", dir=_SOCKET_ROOT) as name:
            root = Path(name)
            service = _HeldService(root / "s.sock", self._answer("late"))
            client = self._client(root)
            sender = threading.Thread(target=client.execute, args=(self.read,))
            sender.start()
            try:
                while not list((root / "requests").glob("*.jsonl")):
                    sender.join(0.01)
                assert client.close(timeout_seconds=0.2) is None
            finally:
                service.close()
                sender.join(5)
            (log,) = (root / "requests").glob("*.jsonl")
            assert b'"result":' in log.read_bytes()
            assert not list((root / "requests").glob("*.sealed.json"))
            original = log.read_bytes()
            (result,) = ClientLogArchive.archive(root / "requests")
            assert (result.status, result.reason) == ("skipped", "writer_not_proven_finished")
            assert log.read_bytes() == original

    def test_a_log_changed_after_its_seal_is_kept(self) -> None:
        """A record appended after sealing means the writer had not finished."""
        with TemporaryDirectory(prefix="client-log-", dir=_SOCKET_ROOT) as name:
            root = Path(name)
            log = self._written(root)
            ClientLogArchive.seal(log)
            with log.open("ab") as stream:
                stream.write(b"sult\n")
            original = log.read_bytes()
            (result,) = ClientLogArchive.archive(root / "requests")
            assert (result.status, result.reason) == ("skipped", "log_differs_from_seal")
            assert log.read_bytes() == original
            with pytest.raises(ValueError, match="changed after it was sealed"):
                ClientLogArchive.seal(log)

    def test_a_failed_verification_leaves_the_plaintext_and_no_partial_archive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An archive that does not decompress to the sealed bytes is never published."""
        with TemporaryDirectory(prefix="client-log-", dir=_SOCKET_ROOT) as name:
            root = Path(name)
            log = self._written(root)
            ClientLogArchive.seal(log)
            original = log.read_bytes()
            monkeypatch.setattr(ClientLogArchive, "_matches", self._refuse_archives)
            (result,) = ClientLogArchive.archive(root / "requests")
            assert (result.status, result.reason) == ("skipped", "archive_failed_verification")
            assert log.read_bytes() == original
            assert sorted(p.name.split(".", 1)[1] for p in (root / "requests").iterdir()) == [
                "jsonl",
                "sealed.json",
            ]

    def test_interrupted_archival_resumes_from_the_authoritative_copy(self) -> None:
        """A partial temporary file is discarded; a published archive retires the plaintext."""
        with TemporaryDirectory(prefix="client-log-", dir=_SOCKET_ROOT) as name:
            root = Path(name)
            log = self._written(root)
            ClientLogArchive.seal(log)
            original = log.read_bytes()
            partial = log.with_name(log.name + ".zst.tmp")
            partial.write_bytes(zstd.compress(original)[:20])
            (first,) = ClientLogArchive.archive(root / "requests")
            assert first.status == "archived" and not partial.exists()
            # A crash after publishing but before removing the plaintext keeps both.
            log.write_bytes(original)
            (second,) = ClientLogArchive.archive(root / "requests")
            assert second.status == "already_archived" and not log.exists()
            assert b"".join(ClientLogArchive.lines(log)) == original

    def test_a_published_archive_that_differs_from_its_seal_is_refused(self) -> None:
        """Neither a wrong archive beside the plaintext nor a damaged one is trusted."""
        with TemporaryDirectory(prefix="client-log-", dir=_SOCKET_ROOT) as name:
            root = Path(name)
            log = self._written(root)
            ClientLogArchive.seal(log)
            original = log.read_bytes()
            archive = log.with_name(log.name + ".zst")
            archive.write_bytes(zstd.compress(original.replace(b"aab", b"aac") + b"x"))
            (result,) = ClientLogArchive.archive(root / "requests")
            assert (result.status, result.reason) == (
                "skipped",
                "published_archive_differs_from_seal",
            )
            assert log.read_bytes() == original
            archive.unlink()
            (archived,) = ClientLogArchive.archive(root / "requests")
            assert archived.status == "archived"
            damaged = bytearray(archive.read_bytes())
            damaged[len(damaged) // 2] ^= 0xFF
            archive.write_bytes(bytes(damaged))
            with pytest.raises(ValueError, match="archive"):
                list(ClientLogArchive.lines(log))
