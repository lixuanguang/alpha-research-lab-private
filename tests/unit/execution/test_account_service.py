"""Exercise the local account owner socket, retention and process fencing."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import socket
import sqlite3
import stat
import struct
import subprocess
import sys
import threading
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace
from test_paper_activation import TestPaperActivation as _ActivationFixture

# project library imports
from applications.execute import AccountExecutionApplication
from applications.execute.account_service import AccountOwnerService
from configuration import AccountConfiguration
from execution import (
    AccountControl,
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountJournal,
    AccountObservation,
    PaperMarket,
    PaperMarketOutcome,
    PaperOwner,
    SentRequest,
    SocketPaperAccount,
)
from serialization import DomainCodec

# A short existing root keeps AF_UNIX paths in limits on macOS and Linux.
_SOCKET_ROOT = "/private/tmp" if os.path.isdir("/private/tmp") else "/tmp"


class _ServiceHealth(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Decode the exact independent liveness record emitted by the child."""

    pid: int
    owner_id: str
    generation: int
    release_identity: str
    heartbeat_at: str
    heartbeat_ns: int
    request_progress_ns: int
    status: str


class _RecordingAccountApplication:
    """Record service telemetry binding without performing account mutations."""

    def __init__(self) -> None:
        """Retain exact validated requests and diagnostic destination choices."""
        self.requests: list[tuple[AccountExecutionRequest, Path | None]] = []

    def run(
        self,
        *,
        config_path: Path,
        journal_path: Path,
        request_path: Path | None = None,
        request_payload: bytes | None = None,
        telemetry_path: Path | None = None,
        release_identity: str | None = None,
        opened_journal: AccountJournal | None = None,
        phases: dict[str, int] | None = None,
    ) -> AccountExecutionResult:
        """Read the retained typed request and expose the selected telemetry path."""
        assert request_path is None and request_payload is not None
        assert opened_journal is not None
        request = DomainCodec().decode_json(request_payload, AccountExecutionRequest)
        self.requests.append((request, telemetry_path))
        return AccountExecutionResult(accounts=(), orders=())


class _ClientLog(msgspec.Struct, frozen=True):
    """Group one socket client's retained records by attempt."""

    requests: dict[str, SentRequest]
    results: dict[str, bytes]
    errors: dict[str, str]

    @staticmethod
    def read(directory: Path) -> _ClientLog:
        """Read the directory's single client log, keeping each result's exact bytes.

        A repeated result resolves to the earlier result record whose bytes its
        SHA-256 names; one naming no such record leaves its attempt uncertain.
        """
        (log,) = directory.iterdir()
        requests: dict[str, SentRequest] = {}
        results: dict[str, bytes] = {}
        errors: dict[str, str] = {}
        held: dict[str, bytes] = {}
        for line in log.read_bytes().splitlines():
            record = msgspec.json.decode(line, type=dict[str, msgspec.Raw])
            attempt = msgspec.json.decode(record.pop("attempt"), type=str)
            ((kind, value),) = record.items()
            if kind == "error":
                errors[attempt] = msgspec.json.decode(value, type=str)
            elif kind == "request":
                requests[attempt] = DomainCodec().decode_json(value, SentRequest)
            elif kind == "result":
                results[attempt] = bytes(value)
                held[hashlib.sha256(results[attempt]).hexdigest()] = results[attempt]
            else:
                assert kind == "repeated_result"
                digest = msgspec.json.decode(value, type=str)
                if digest in held:
                    results[attempt] = held[digest]
        return _ClientLog(requests=requests, results=results, errors=errors)

    @staticmethod
    def sent(payload: bytes, action: str) -> SentRequest:
        """Name exact payload bytes as the client's pre-dispatch record does."""
        return SentRequest(
            action=action, sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload)
        )


class TestSocketRetention:
    """Retain socket client requests before sending, and outcomes after."""

    def test_an_unanswered_request_stays_retained_without_an_outcome(self) -> None:
        """A timeout leaves the fsynced request alone: an uncertain outcome to inspect."""
        config = _ActivationFixture._config()
        owner = PaperOwner(
            account_id=config.accounts[0].account_id,
            deployment_sha256="a" * 64,
            authorization_id="retention-grant",
            release_identity="b" * 64,
            owner_id="retention-owner",
            generation=1,
        )
        with TemporaryDirectory(prefix="paper-retention-", dir=_SOCKET_ROOT) as root:
            socket_path = Path(root) / "s.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as silent:
                silent.bind(str(socket_path))
                silent.listen(1)
                account = SocketPaperAccount(
                    config=config,
                    socket_path=socket_path,
                    requests=Path(root) / "requests",
                    paper_owner=owner,
                    timeout_seconds=0.2,
                )
                request = AccountExecutionRequest(
                    action="block",
                    account_id=owner.account_id,
                    reason="uncertain protection",
                    paper_owner=owner,
                )
                with pytest.raises(TimeoutError):
                    account.execute(request)
            log = _ClientLog.read(Path(root) / "requests")
        assert list(log.requests.values()) == [
            _ClientLog.sent(DomainCodec().encode_json(request), "block")
        ]
        assert not log.results and not log.errors

    def test_a_rejection_cut_inside_a_character_keeps_its_error_record(self) -> None:
        """A byte-truncated reason is retained with a replacement character, not lost."""
        config = _ActivationFixture._config()
        owner = PaperOwner(
            account_id=config.accounts[0].account_id,
            deployment_sha256="a" * 64,
            authorization_id="retention-grant",
            release_identity="b" * 64,
            owner_id="retention-owner",
            generation=1,
        )
        with TemporaryDirectory(prefix="paper-retention-", dir=_SOCKET_ROOT) as root:
            socket_path = Path(root) / "s.sock"
            # "refused: " then the first two of the three bytes of one character.
            with _ReplyService(socket_path, b"\x01", b"refused: \xe2\x82") as service:
                account = SocketPaperAccount(
                    config=config,
                    socket_path=socket_path,
                    requests=Path(root) / "requests",
                    paper_owner=owner,
                    timeout_seconds=2,
                )
                with pytest.raises(RuntimeError, match="rejected request: refused: \ufffd"):
                    account.execute(
                        AccountExecutionRequest(
                            action="block",
                            account_id=owner.account_id,
                            reason="rejected protection",
                            paper_owner=owner,
                        )
                    )
            log = _ClientLog.read(Path(root) / "requests")
        assert [_ClientLog.sent(payload, "block") for payload in service.received] == list(
            log.requests.values()
        )
        assert list(log.errors.values()) == ["refused: \ufffd"] and not log.results

    def test_an_exact_repeated_result_is_kept_once_and_named_by_digest(self) -> None:
        """A read answered with bytes the log already holds records only their SHA-256.

        Three reads are answered A, A, B. The log holds A's and B's bytes once each;
        the second attempt names A's digest, and every attempt's result resolves to
        the exact bytes the client received.
        """
        config = _ActivationFixture._config()
        owner = PaperOwner(
            account_id=config.accounts[0].account_id,
            deployment_sha256="a" * 64,
            authorization_id="retention-grant",
            release_identity="b" * 64,
            owner_id="retention-owner",
            generation=1,
        )
        codec = DomainCodec()
        first = codec.encode_json(
            AccountExecutionResult(accounts=(), orders=(), checkpoint=b"first-state")
        )
        second = codec.encode_json(
            AccountExecutionResult(accounts=(), orders=(), checkpoint=b"second-state")
        )
        read = AccountExecutionRequest(
            action="inspect", projection="checkpoint", query_instance="alpha"
        )
        with TemporaryDirectory(prefix="paper-retention-", dir=_SOCKET_ROOT) as root:
            socket_path = Path(root) / "s.sock"
            with _ReplyService(socket_path, b"\x00", (first, first, second)):
                account = SocketPaperAccount(
                    config=config,
                    socket_path=socket_path,
                    requests=Path(root) / "requests",
                    paper_owner=owner,
                    timeout_seconds=2,
                )
                received = [account.execute(read).checkpoint for _ in range(3)]
            (log_path,) = (Path(root) / "requests").iterdir()
            text = log_path.read_bytes()
            log = _ClientLog.read(Path(root) / "requests")
        assert received == [b"first-state", b"first-state", b"second-state"]
        assert text.count(b'"result":') == 2
        assert text.count(b'"repeated_result":"' + hashlib.sha256(first).hexdigest().encode()) == 1
        assert list(log.results.values()) == [first, first, second]
        assert list(log.requests) == list(log.results) and not log.errors

    @staticmethod
    def _checkpoint_answer(state: str) -> bytes:
        """Encode one checkpoint read's answer naming the given state."""
        return DomainCodec().encode_json(
            AccountExecutionResult(accounts=(), orders=(), checkpoint=state.encode())
        )

    def test_the_repeat_window_holds_the_latest_64_distinct_results(self) -> None:
        """A repeat refreshes its result; the 65th distinct result evicts the oldest.

        Answers: A, then B1 to B63 (64 distinct), A again (a repeat, now newest),
        C (evicting B1, not A), A again (a repeat) and B1 again (in full, evicted).
        """
        config = _ActivationFixture._config()
        owner = PaperOwner(
            account_id=config.accounts[0].account_id,
            deployment_sha256="a" * 64,
            authorization_id="retention-grant",
            release_identity="b" * 64,
            owner_id="retention-owner",
            generation=1,
        )
        answer = self._checkpoint_answer
        first, others, last = answer("A"), [answer(f"B{i}") for i in range(1, 64)], answer("C")
        replies = (first, *others, first, last, first, others[0])
        read = AccountExecutionRequest(
            action="inspect", projection="checkpoint", query_instance="alpha"
        )
        with TemporaryDirectory(prefix="paper-retention-", dir=_SOCKET_ROOT) as root:
            socket_path = Path(root) / "s.sock"
            with _ReplyService(socket_path, b"\x00", replies):
                account = SocketPaperAccount(
                    config=config,
                    socket_path=socket_path,
                    requests=Path(root) / "requests",
                    paper_owner=owner,
                    timeout_seconds=2,
                )
                for _ in replies:
                    account.execute(read)
            (log_path,) = (Path(root) / "requests").iterdir()
            kinds = [
                next(
                    key
                    for key in msgspec.json.decode(line, type=dict[str, msgspec.Raw])
                    if key != "attempt"
                )
                for line in log_path.read_bytes().splitlines()
                if b'"request":' not in line
            ]
            log = _ClientLog.read(Path(root) / "requests")
        assert kinds == ["result"] * 64 + ["repeated_result", "result", "repeated_result", "result"]
        assert list(log.results.values()) == list(replies)


class _ReplyService:
    """Accept framed requests on a local socket and answer each with the next reply."""

    def __init__(self, path: Path, status: bytes, replies: bytes | tuple[bytes, ...]) -> None:
        """Bind the socket now; serve one exchange per reply from a thread."""
        self.status = status
        self.replies = (replies,) if isinstance(replies, bytes) else replies
        self.received: list[bytes] = []
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(path))
        self.listener.listen(1)
        self.thread = threading.Thread(target=self._serve)

    def __enter__(self) -> _ReplyService:
        """Start serving the exchanges."""
        self.thread.start()
        return self

    def __exit__(self, *details: object) -> None:
        """Wait for the exchanges and close the socket."""
        self.thread.join(5)
        self.listener.close()

    def _serve(self) -> None:
        """Read one frame per reply and answer it with the fixed status and that reply."""
        for reply in self.replies:
            connection, _ = self.listener.accept()
            with connection:
                length = int.from_bytes(connection.recv(4, socket.MSG_WAITALL), "big")
                self.received.append(connection.recv(length, socket.MSG_WAITALL))
                connection.sendall(self.status + len(reply).to_bytes(4, "big") + reply)


class TestPublicMarketRecovery:
    """Resolve a lost, interrupted or unapplied per-book command by its exact bytes.

    Each case ends with a restarted service life retrying the identical request: the
    account applies a book at most once, and a retry of a committed book returns its
    saved outcome without writing.
    """

    @staticmethod
    def _service(
        tmp_path: Path, config: AccountConfiguration, owner: PaperOwner
    ) -> AccountOwnerService:
        """Open one service life on the journal without serving its socket."""
        service = AccountOwnerService(
            application=AccountExecutionApplication(),
            config=config,
            config_path=tmp_path / "config.json",
            journal_path=tmp_path / "account.sqlite3",
            telemetry_path=None,
            release_identity=owner.release_identity,
            paper_owner=owner,
            socket_path=tmp_path / "account.sock",
            duration_seconds=10,
        )
        service._owner_journal = AccountJournal(
            tmp_path / "account.sqlite3", config, paper_owner=owner
        )
        return service

    @staticmethod
    def _exchange(
        service: AccountOwnerService, frame: bytes, *, answered: bool
    ) -> AccountExecutionResult | None:
        """Send one frame; unless ``answered``, drop the connection before the answer."""
        server, client = socket.socketpair()
        with server, client:
            client.sendall(frame)
            if not answered:
                client.close()
                service._serve_connection(server)
                return None
            service._serve_connection(server)
            header = client.recv(5, socket.MSG_WAITALL)
            body = client.recv(int.from_bytes(header[1:], "big"), socket.MSG_WAITALL)
        assert header[:1] == b"\x00", body
        return DomainCodec().decode_json(body, AccountExecutionResult)

    @staticmethod
    def _head(path: Path) -> bytes:
        """Read the committed head bytes; an unchanged head means no commit wrote."""
        with closing(sqlite3.connect(path)) as connection:
            row = cast(tuple[bytes], connection.execute("SELECT payload FROM firm").fetchone())
        return row[0]

    @staticmethod
    def _retained(tmp_path: Path) -> list[bytes]:
        """Read every service life's retained request lines; each case retains one request."""
        logs = sorted((tmp_path / "service-requests").iterdir())
        return [line for log in logs for line in log.read_bytes().splitlines()]

    @staticmethod
    def _book(
        tmp_path: Path, identity: str
    ) -> tuple[AccountConfiguration, PaperOwner, PaperMarket, bytes]:
        """Claim a current owner and author one fresh book's exact framed request."""

        class _Current(_ActivationFixture):
            """Keep the test grant current while the services run."""

            opening_at = datetime.now(UTC) - timedelta(seconds=13)

        owner = _Current._bootstrap(tmp_path / "account.sqlite3")[-1]
        config = _Current._config()
        codec = DomainCodec()
        (tmp_path / "config.json").write_bytes(codec.encode_json(config))
        book = _Current._market(identity, datetime.now(UTC))
        payload = codec.encode_json(
            AccountExecutionRequest(
                action="public_market",
                account_id=owner.account_id,
                market=book,
                scenario=_Current._scenario(),
                paper_owner=owner,
                projection="operation",
            )
        )
        return config, owner, book, struct.pack("!I", len(payload)) + payload

    def test_a_committed_book_whose_answer_was_lost_is_an_exact_retry(self, tmp_path: Path) -> None:
        """The first life commits but its answer is lost; the next life writes nothing."""
        config, owner, book, frame = self._book(tmp_path, "lost-answer-book")
        assert self._exchange(self._service(tmp_path, config, owner), frame, answered=False) is None
        reader = AccountJournal(tmp_path / "account.sqlite3", config)
        trace = reader.paper_trace(owner.account_id, book.identity)
        assert trace is not None and trace.status == "committed"
        head = self._head(tmp_path / "account.sqlite3")

        result = self._exchange(self._service(tmp_path, config, owner), frame, answered=True)
        assert result is not None and result.public_market == PaperMarketOutcome(
            account_id=owner.account_id,
            market_identity=book.identity,
            trace_sha256=hashlib.sha256(DomainCodec().encode_json(trace)).hexdigest(),
        )
        assert self._head(tmp_path / "account.sqlite3") == head
        assert reader.paper_trace(owner.account_id, book.identity) == trace
        assert self._retained(tmp_path) == [frame[4:], frame[4:]]

    def test_an_interrupted_or_unapplied_book_applies_once_after_restart(
        self, tmp_path: Path
    ) -> None:
        """A frame cut before retention, or retained bytes never applied, changed nothing."""
        config, owner, book, frame = self._book(tmp_path, "interrupted-book")
        head = self._head(tmp_path / "account.sqlite3")
        # The connection ends inside the frame: nothing is retained or applied.
        assert (
            self._exchange(self._service(tmp_path, config, owner), frame[:-8], answered=False)
            is None
        )
        assert not (tmp_path / "service-requests").exists()
        # A life retains the exact bytes, then ends before applying them.
        self._service(tmp_path, config, owner)._retain_request(frame[4:])
        reader = AccountJournal(tmp_path / "account.sqlite3", config)
        assert reader.paper_trace(owner.account_id, book.identity) is None
        assert self._head(tmp_path / "account.sqlite3") == head

        applied = self._exchange(self._service(tmp_path, config, owner), frame, answered=True)
        trace = reader.paper_trace(owner.account_id, book.identity)
        assert trace is not None and applied is not None and applied.public_market is not None
        assert applied.public_market.trace_sha256 == (
            hashlib.sha256(DomainCodec().encode_json(trace)).hexdigest()
        )
        committed = self._head(tmp_path / "account.sqlite3")
        assert committed != head
        retried = self._exchange(self._service(tmp_path, config, owner), frame, answered=True)
        assert retried == applied
        assert self._head(tmp_path / "account.sqlite3") == committed
        assert self._retained(tmp_path) == [frame[4:]] * 3


class TestAccountOwnerService:
    """Verify one process owns a retained journal and serves typed account commands."""

    @pytest.mark.parametrize("action", ("inspect", "block"))
    def test_only_inspection_suppresses_redundant_operation_telemetry(
        self, tmp_path: Path, action: str
    ) -> None:
        """Reads keep exact request retention; mutations retain their configured telemetry."""
        journal_path = tmp_path / "account.sqlite3"
        owner = _ActivationFixture._bootstrap(journal_path)[-1]
        config = _ActivationFixture._config()
        application = _RecordingAccountApplication()
        telemetry_path = tmp_path / "telemetry.sqlite3"
        service = AccountOwnerService(
            application=application,
            config=config,
            config_path=tmp_path / "config.json",
            journal_path=journal_path,
            telemetry_path=telemetry_path,
            release_identity=owner.release_identity,
            paper_owner=owner,
            socket_path=tmp_path / "account.sock",
            duration_seconds=10,
        )
        service._owner_journal = AccountJournal(journal_path, config, paper_owner=owner)
        request = (
            AccountExecutionRequest(action="inspect", paper_owner=owner)
            if action == "inspect"
            else AccountExecutionRequest(
                action="block",
                account_id=owner.account_id,
                reason="explicit protection",
                paper_owner=owner,
            )
        )
        codec = DomainCodec()
        payload = codec.encode_json(request)
        server, client = socket.socketpair()
        with server, client:
            client.sendall(struct.pack("!I", len(payload)) + payload)
            response = service._serve_connection(server)
            assert response is not None
        assert application.requests == [(request, None if action == "inspect" else telemetry_path)]
        # One service-life log holds the exact request bytes as one fsynced line.
        retained = tuple(service.requests_path.iterdir())
        assert len(retained) == 1 and retained[0].suffix == ".jsonl"
        assert retained[0].read_bytes() == payload + b"\n"

    @staticmethod
    def _service(
        tmp_path: Path, owner: PaperOwner, selected: AccountConfiguration, seconds: int
    ) -> AccountOwnerService:
        """Bind the service without serving."""
        return AccountOwnerService(
            application=_RecordingAccountApplication(),
            config=selected,
            config_path=tmp_path / "config.json",
            journal_path=tmp_path / "account.sqlite3",
            telemetry_path=None,
            release_identity=owner.release_identity,
            paper_owner=owner,
            socket_path=tmp_path / "account.sock",
            duration_seconds=seconds,
        )

    def test_service_life_is_bounded_by_its_signed_configuration(self, tmp_path: Path) -> None:
        """Undeclared configurations keep 120 s; a declared cap admits exactly up to itself."""
        journal_path = tmp_path / "account.sqlite3"
        owner = _ActivationFixture._bootstrap(journal_path)[-1]
        config = _ActivationFixture._config()
        assert config.service_life_limit == 120
        assert b"service_life_seconds" not in DomainCodec().encode_json(config)
        declared = replace(config, service_life_seconds=3000)

        assert self._service(tmp_path, owner, config, 120).duration_seconds == 120
        assert self._service(tmp_path, owner, declared, 3000).duration_seconds == 3000
        for selected, seconds in ((config, 121), (declared, 3001)):
            with pytest.raises(ValueError, match="fixed installed account"):
                self._service(tmp_path, owner, selected, seconds)
        with pytest.raises(ValueError, match="finite declared bound"):
            replace(config, service_life_seconds=90_001)
        request = AccountExecutionRequest(
            action="serve_paper",
            paper_owner=owner,
            service_socket=str(tmp_path / "account.sock"),
            service_seconds=3000,
        )
        assert request.service_seconds == 3000

    @pytest.mark.parametrize(
        ("offset", "seconds", "admitted"),
        ((13, 17, True), (13, 18, False), (31, 100, True)),
    )
    def test_a_current_grant_must_outlast_the_whole_service_life(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        offset: int,
        seconds: int,
        admitted: bool,
    ) -> None:
        """Refuse a life that would outlive its grant; an expired grant may still settle."""
        journal_path = tmp_path / "account.sqlite3"
        owner = _ActivationFixture._bootstrap(journal_path)[-1]
        config = _ActivationFixture._config()
        codec = DomainCodec()
        config_path = tmp_path / "config.json"
        config_path.write_bytes(codec.encode_json(config))
        service = AccountOwnerService(
            application=AccountExecutionApplication(),
            config=config,
            config_path=config_path,
            journal_path=journal_path,
            telemetry_path=None,
            release_identity=owner.release_identity,
            paper_owner=owner,
            socket_path=tmp_path / "account.sock",
            duration_seconds=seconds,
        )
        # The fixture grant is valid from second 11 until second 30 of its session.
        at = _ActivationFixture._at(offset)

        class _Clock(datetime):
            """Read the fixture session's wall clock."""

            @classmethod
            def now(cls, tz: object = None) -> _Clock:
                """Return the selected fixture instant."""
                return cast(_Clock, at)

        monkeypatch.setattr("applications.execute.account_service.datetime", _Clock)
        if admitted:
            service._require_current_owner()
        else:
            with pytest.raises(ValueError, match="paper_service_life_exceeds_authorization"):
                service._require_current_owner()

    @pytest.mark.parametrize("opted_in", (True, False))
    def test_request_timings_are_opt_in_and_ordered(self, tmp_path: Path, opted_in: bool) -> None:
        """An operator-created timings file receives one ordered row per request."""
        journal_path = tmp_path / "account.sqlite3"
        owner = _ActivationFixture._bootstrap(journal_path)[-1]
        config = _ActivationFixture._config()
        codec = DomainCodec()
        config_path = tmp_path / "config.json"
        config_path.write_bytes(codec.encode_json(config))
        service = AccountOwnerService(
            application=AccountExecutionApplication(),
            config=config,
            config_path=config_path,
            journal_path=journal_path,
            telemetry_path=tmp_path / "telemetry.sqlite3",
            release_identity=owner.release_identity,
            paper_owner=owner,
            socket_path=tmp_path / "account.sock",
            duration_seconds=10,
        )
        if opted_in:
            service.timings_path.touch()
        service._enable_timings()
        service._owner_journal = AccountJournal(journal_path, config, paper_owner=owner)
        payload = codec.encode_json(
            AccountExecutionRequest(
                action="block",
                account_id=owner.account_id,
                reason="explicit protection",
                paper_owner=owner,
            )
        )
        server, client = socket.socketpair()
        with server, client:
            client.sendall(struct.pack("!I", len(payload)) + payload)
            assert service._serve_connection(server) is not None
        if not opted_in:
            assert not service.timings_path.exists()
            return
        rows = [
            msgspec.json.decode(line, type=dict[str, object])
            for line in service.timings_path.read_bytes().splitlines()
        ]
        assert len(rows) == 1 and rows[0]["action"] == "block"
        order = (
            "header_ns",
            "retained_ns",
            "owner_checked_ns",
            "journal_ns",
            "alerts_ns",
            "snapshot_ns",
            "monitoring_ns",
            "telemetry_ns",
            "sent_ns",
        )
        clocks = [rows[0][name] for name in order]
        assert all(type(clock) is int for clock in clocks)
        assert clocks == sorted(cast(list[int], clocks))

    @pytest.mark.parametrize("mismatch", ("path", "owner"))
    def test_opened_journal_cannot_override_request_binding(
        self, tmp_path: Path, mismatch: str
    ) -> None:
        """Reusing a store handle cannot substitute another path or owner generation."""
        journal_path = tmp_path / "account.sqlite3"
        _, _, _, _, _, owner = _ActivationFixture._bootstrap(journal_path)
        config = _ActivationFixture._config()
        codec = DomainCodec()
        config_path, request_path = tmp_path / "config.json", tmp_path / "inspect.json"
        config_path.write_bytes(codec.encode_json(config))
        request_path.write_bytes(
            codec.encode_json(AccountExecutionRequest(action="inspect", paper_owner=owner))
        )
        opened = AccountJournal(
            tmp_path / "other.sqlite3" if mismatch == "path" else journal_path,
            config,
            paper_owner=replace(owner, generation=owner.generation + 1)
            if mismatch == "owner"
            else owner,
        )
        with pytest.raises(ValueError, match="opened account journal differs"):
            AccountExecutionApplication().run(
                config_path=config_path,
                journal_path=journal_path,
                request_path=request_path,
                release_identity=owner.release_identity,
                opened_journal=opened,
            )

    @staticmethod
    def _wait_ready(process: subprocess.Popen[bytes], socket_path: Path) -> _ServiceHealth:
        """Wait for the actual child PID and ready socket within a finite test budget."""
        health_path = socket_path.with_suffix(".health.json")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if process.poll() is not None:
                _, stderr = process.communicate()
                raise AssertionError(f"paper account service exited: {stderr.decode()}")
            if socket_path.exists() and health_path.exists():
                health = msgspec.json.decode(health_path.read_bytes(), type=_ServiceHealth)
                if health.pid == process.pid:
                    return health
            time.sleep(0.02)
        raise AssertionError("paper account service did not become ready")

    def test_socket_owner_fence_and_graceful_shutdown(self, tmp_path: Path) -> None:
        """A live owner serves inspection, rejects peers, and stops durably."""

        class _CurrentActivationFixture(_ActivationFixture):
            """Keep the signed test grant current for selective restart."""

            opening_at = datetime.now(UTC) - timedelta(seconds=13)

        journal_path = tmp_path / "account.sqlite3"
        _, _, _, _, _, owner = _CurrentActivationFixture._bootstrap(journal_path)
        config: AccountConfiguration = _CurrentActivationFixture._config()
        codec = DomainCodec()
        config_path = tmp_path / "config.json"
        config_path.write_bytes(codec.encode_json(config))
        socket_directory = TemporaryDirectory(prefix="paper-account-", dir=_SOCKET_ROOT)
        socket_path = Path(socket_directory.name) / "s.sock"
        serve_path = tmp_path / "serve.json"
        serve_path.write_bytes(
            codec.encode_json(
                AccountExecutionRequest(
                    action="serve_paper",
                    service_socket=str(socket_path),
                    service_seconds=10,
                    paper_owner=owner,
                )
            )
        )
        process: subprocess.Popen[bytes] = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from applications.execute import main; main()",
                "account",
                "--config",
                str(config_path),
                "--journal",
                str(journal_path),
                "--request",
                str(serve_path),
                "--release-identity",
                owner.release_identity,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            first_health = self._wait_ready(process, socket_path)
            assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
            assert first_health.generation == owner.generation
            account = SocketPaperAccount(
                config=config,
                socket_path=socket_path,
                requests=tmp_path / "client-requests",
                paper_owner=owner,
            )
            assert account.accounts()[0].ledger.account_id == owner.account_id
            assert account.paper_trace(owner.account_id, "unseen-service-market") is None
            stopped_instance = account.execute(
                AccountExecutionRequest(
                    action="stop_instance",
                    instance_id="alpha",
                    at=datetime.now(UTC),
                    paper_owner=owner,
                )
            )
            assert "alpha" in stopped_instance.stopped_instances
            assert account.reconcile(
                AccountObservation(
                    identity="service-selective-restart-reconcile",
                    at=datetime.now(UTC),
                    snapshot=_CurrentActivationFixture._opening(),
                    open_orders=(),
                )
            )
            restarted_instance = account.execute(
                AccountExecutionRequest(
                    action="restart_instance",
                    instance_id="alpha",
                    at=datetime.now(UTC),
                    paper_owner=owner,
                )
            )
            assert "alpha" not in restarted_instance.stopped_instances
            with pytest.raises(ValueError, match="already owns"):
                AccountExecutionApplication().run(
                    config_path=config_path,
                    journal_path=journal_path,
                    request_path=serve_path,
                    release_identity=owner.release_identity,
                )
            peer = SocketPaperAccount(
                config=config,
                socket_path=socket_path,
                requests=tmp_path / "peer-requests",
                paper_owner=replace(owner, owner_id="replaced-owner"),
            )
            with pytest.raises(RuntimeError, match="paper_owner_stale_or_absent"):
                peer.block(owner.account_id, "peer-must-not-stop-owner")
            stale_book = _CurrentActivationFixture._market("peer-service-market", datetime.now(UTC))
            with pytest.raises(RuntimeError, match="paper_owner_stale_or_absent"):
                peer.apply_public_market(
                    owner.account_id, stale_book, _CurrentActivationFixture._scenario()
                )
            assert account.paper_trace(owner.account_id, stale_book.identity) is None
            assert account.accounts()[0].operator_block is None
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stalled:
                stalled.connect(str(socket_path))
                stalled.sendall(struct.pack("!I", 100) + b"{")
                time.sleep(0.15)
                before_stall = msgspec.json.decode(
                    socket_path.with_suffix(".health.json").read_bytes(), type=_ServiceHealth
                )
                time.sleep(0.25)
                second_health = msgspec.json.decode(
                    socket_path.with_suffix(".health.json").read_bytes(), type=_ServiceHealth
                )
            assert second_health.heartbeat_ns > before_stall.heartbeat_ns
            assert second_health.request_progress_ns == before_stall.request_progress_ns
            stopped = account.shutdown(
                AccountControl(
                    identity="operator-stop-service",
                    account_id=owner.account_id,
                    kind="stop",
                    at=datetime.now(UTC),
                    reason="bounded service complete",
                )
            )
            assert stopped.control is not None and stopped.control.status == "applied"
            stdout, stderr = process.communicate(timeout=8)
            assert process.wait(timeout=0) == 0, stderr.decode()
            assert codec.decode_json(stdout.strip(), AccountExecutionResult).accounts[0].phase == (
                "stopped"
            )
            assert not socket_path.exists()
            assert not socket_path.with_suffix(".health.json").exists()
            retained = tuple((tmp_path / "service-requests").glob("*.jsonl"))
            assert len(retained) == 1
            decoded = tuple(
                codec.decode_json(line, AccountExecutionRequest)
                for line in retained[0].read_bytes().splitlines()
            )
            assert {"stop_instance", "restart_instance"}.issubset(
                {request.action for request in decoded if request.paper_owner == owner}
            )
            assert any(request.action == "shutdown_paper" for request in decoded)
            assert any(request.action == "control" for request in decoded)
            # Each client's one log pairs every sent request with its outcome, and names
            # the exact bytes the service retained before applying them.
            client_log = _ClientLog.read(tmp_path / "client-requests")
            assert client_log.requests and set(client_log.requests) == set(client_log.results)
            assert not client_log.errors
            retained_identities = {
                _ClientLog.sent(line, codec.decode_json(line, AccountExecutionRequest).action)
                for line in retained[0].read_bytes().splitlines()
            }
            assert set(client_log.requests.values()) <= retained_identities
            assert {item.action for item in client_log.requests.values()} >= {
                "stop_instance",
                "restart_instance",
                "shutdown_paper",
            }
            peer_log = _ClientLog.read(tmp_path / "peer-requests")
            assert set(peer_log.requests) == set(peer_log.errors) and len(peer_log.errors) == 2
            assert all("paper_owner_stale_or_absent" in text for text in peer_log.errors.values())
            # The service refused the stale peer before retaining its bytes.
            assert not set(peer_log.requests.values()) & retained_identities
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)
            else:
                process.communicate()
            socket_directory.cleanup()

    def test_service_request_bounds_and_socket_only_shutdown(self, tmp_path: Path) -> None:
        """Startup rejects unbounded lifetimes; CLI cannot execute socket shutdown."""
        owner = _ActivationFixture._bootstrap(tmp_path / "account.sqlite3")[-1]
        # The schema admits only finite lives; the signed configuration's cap is enforced
        # by the service itself (see test_service_life_is_bounded_by_its_signed_configuration).
        with pytest.raises(ValueError, match="bounded lifetime"):
            AccountExecutionRequest(
                action="serve_paper",
                service_socket=str(tmp_path / "s.sock"),
                service_seconds=90_001,
                paper_owner=owner,
            )
        config_path = tmp_path / "config.json"
        codec = DomainCodec()
        config_path.write_bytes(codec.encode_json(_ActivationFixture._config()))
        stop_path = tmp_path / "stop.json"
        stop_path.write_bytes(
            codec.encode_json(
                AccountExecutionRequest(
                    action="shutdown_paper",
                    paper_owner=owner,
                    control=AccountControl(
                        identity="invalid-direct-shutdown",
                        account_id=owner.account_id,
                        kind="stop",
                        at=datetime.now(UTC),
                        reason="socket only",
                    ),
                )
            )
        )
        with pytest.raises(ValueError, match="active socket"):
            AccountExecutionApplication().run(
                config_path=config_path,
                journal_path=tmp_path / "account.sqlite3",
                request_path=stop_path,
                release_identity=owner.release_identity,
            )
        assert (tmp_path / "account.sqlite3").is_file()

    def test_heartbeat_write_failure_stops_durable_account(self, tmp_path: Path) -> None:
        """A lost liveness record ends service after a fenced account stop."""
        journal_path = tmp_path / "account.sqlite3"
        _, _, _, _, _, owner = _ActivationFixture._bootstrap(journal_path)
        config = _ActivationFixture._config()
        before = AccountJournal(journal_path, config)
        original_activation = before.paper_activations()[0]
        original_orders, original_net_orders = before.orders(), before.net_orders()
        config_path = tmp_path / "config.json"
        codec = DomainCodec()
        config_path.write_bytes(codec.encode_json(config))
        socket_directory = TemporaryDirectory(prefix="paper-account-", dir=_SOCKET_ROOT)
        socket_path = Path(socket_directory.name) / "s.sock"
        serve_path = tmp_path / "serve.json"
        serve_path.write_bytes(
            codec.encode_json(
                AccountExecutionRequest(
                    action="serve_paper",
                    service_socket=str(socket_path),
                    service_seconds=10,
                    paper_owner=owner,
                )
            )
        )
        process: subprocess.Popen[bytes] = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from applications.execute import main; main()",
                "account",
                "--config",
                str(config_path),
                "--journal",
                str(journal_path),
                "--request",
                str(serve_path),
                "--release-identity",
                owner.release_identity,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self._wait_ready(process, socket_path)
            health_path = socket_path.with_suffix(".health.json")
            for _ in range(10):
                health_path.unlink(missing_ok=True)
                try:
                    health_path.mkdir()
                except FileExistsError:
                    continue
                break
            assert health_path.is_dir()
            _, stderr = process.communicate(timeout=8)
            assert process.wait(timeout=0) != 0, stderr.decode()
            reopened = AccountJournal(journal_path, config)
            assert reopened.accounts()[0].phase == "stopped"
            assert reopened.paper_activations()[0] == original_activation
            assert reopened.orders() == original_orders
            assert reopened.net_orders() == original_net_orders
            assert any(
                item.request.kind == "stop"
                and item.request.reason == "service_lifetime_complete"
                and item.status == "applied"
                for item in reopened.controls()
            )
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)
            else:
                process.communicate()
            socket_directory.cleanup()
