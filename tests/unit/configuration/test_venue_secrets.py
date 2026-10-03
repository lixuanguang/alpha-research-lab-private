"""Validate venue credential files without ever reading developer secrets."""

# standard library imports
import copy
import inspect
import logging
import os
import pickle
import subprocess
import sys
import uuid
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from types import TracebackType
from typing import cast

# third party library imports
import pytest

# project library imports
import configuration.venue_secrets
from configuration.venue_secrets import (
    VENUE_SECRET_FILES,
    CredentialRedaction,
    SecretValue,
    VenueSecrets,
    VenueSecretsError,
)

_GUARD_PROBE = """
import logging
import resource
import sys

import pytest

from configuration import venue_secrets

state = lambda: (
    logging.getLogRecordFactory(),
    venue_secrets.CredentialRedaction._registered,
    resource.getrlimit(resource.RLIMIT_CORE),
)
before = state()
code = pytest.main(
    [sys.argv[1], "-q", "-p", "no:cacheprovider", "--basetemp", sys.argv[2], "-k", sys.argv[3]]
)
sys.exit(int(code) or (0 if state() == before else 3))
"""


class _CoreDumpsUnchanged:
    """Leave the core-dump limit alone; a lowered hard limit cannot be raised again."""

    def __call__(self) -> None:
        """Do nothing."""


class _SwapRace:
    """Replace a checked credential file with a link to a planted one, once.

    Installed as ``Path.lstat`` it binds to the path being checked, and its
    ``open`` stands in for ``os.open``; either races the swap in right after
    the reader checks or opens the original path.
    """

    def __init__(self, path: Path, planted: Path) -> None:
        """Bind the checked path, the planted file and the original system calls."""
        self.path = path
        self.planted = planted
        self.swapped = False
        self._lstat = Path.lstat
        self._open = os.open

    def __get__(self, instance: Path, owner: type[Path]) -> partial[os.stat_result]:
        """Bind the racing ``lstat`` to the path it is called on."""
        return partial(self.lstat, instance)

    def swap(self) -> None:
        """Replace the checked path with a link to the planted file, once."""
        if not self.swapped:
            self.swapped = True
            self.path.unlink()
            self.path.symlink_to(self.planted)

    def lstat(self, path: Path) -> os.stat_result:
        """Stat the path, then race the swap in right after the check."""
        status = self._lstat(path)
        if path == self.path:
            self.swap()
        return status

    def open(self, file: str | Path, flags: int, mode: int = 0o777) -> int:
        """Open the path, then race the swap in right after the open."""
        descriptor = self._open(file, flags, mode)
        if Path(file) == self.path:
            self.swap()
        return descriptor


class _TaggingFactory:
    """Record every log record, like an application factory installed after loading."""

    def __init__(self) -> None:
        """Start with no records."""
        self.records: list[logging.LogRecord] = []

    def __call__(
        self,
        name: str,
        level: int,
        pathname: str,
        lineno: int,
        msg: object,
        args: tuple[object, ...] | Mapping[str, object],
        exc_info: (
            tuple[type[BaseException], BaseException, TracebackType | None]
            | tuple[None, None, None]
            | None
        ),
        func: str | None = None,
        sinfo: str | None = None,
    ) -> logging.LogRecord:
        """Create and record one log record."""
        record = logging.LogRecord(name, level, pathname, lineno, msg, args, exc_info, func, sinfo)
        self.records.append(record)
        return record


class TestVenueSecrets:
    """Use invented values only; the repository secrets directory is never touched."""

    def test_module_leaves_process_guards_as_it_found_them(self, tmp_path: Path) -> None:
        """Running this module leaves logging, the registry and core limits unchanged."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                _GUARD_PROBE,
                __file__,
                str(tmp_path / "run"),
                "not process_guards",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        # Exit 3: every test passed, but the process-wide guards they installed remained.
        assert result.returncode == 0, result.stdout[-2000:]

    @pytest.mark.parametrize(
        ("venue", "content", "has_secret"),
        [
            ("alpaca", "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\n", True),
            ("polymarket", "# comment\n\nAPI_KEY = k-sensitive\nAPI_SECRET=s-never-log", True),
            ("coingecko", "API_KEY=k-sensitive\n", False),
            ("EIA", "API_KEY=k-sensitive\n", False),
        ],
    )
    def test_read(self, tmp_path: Path, venue: str, content: str, has_secret: bool) -> None:
        """Read each venue's shared-format fields and reveal them only on request."""
        TestVenueSecrets.write_credentials(tmp_path, venue.lower(), content)
        secrets = VenueSecrets.read(venue, tmp_path)
        assert secrets.api_key.reveal() == "k-sensitive"
        if has_secret:
            assert secrets.api_secret.reveal() == "s-never-log"
        else:
            with pytest.raises(VenueSecretsError, match="no API_SECRET"):
                _ = secrets.api_secret

    def test_values_never_render(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Keep values out of repr, str, f-strings, logs, pickles and copies."""
        TestVenueSecrets.write_credentials(
            tmp_path, "alpaca", "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\n"
        )
        secrets = VenueSecrets.read("alpaca", tmp_path)
        with caplog.at_level(logging.DEBUG):
            logging.getLogger("test").info("loaded %s %r", secrets.api_key, secrets)
            logging.getLogger("test").info(f"{secrets.api_secret} {secrets.api_secret!r:>30}")
        rendered = " ".join(
            [repr(secrets), str(secrets.api_key), repr(secrets.api_secret), caplog.text]
        )
        assert "sensitive" not in rendered
        assert "never-log" not in rendered
        for value in (secrets, secrets.api_key):
            with pytest.raises(TypeError):
                pickle.dumps(value)
            with pytest.raises(TypeError):
                copy.deepcopy(value)
        assert secrets.api_key != SecretValue("k-sensitive")

    @pytest.mark.parametrize(
        "content",
        [
            "",
            "API_KEY=\nAPI_SECRET=\n",
            "API_KEY=k-sensitive\n",
            "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\nEXTRA=never-log\n",
            "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\nAPI_KEY=k-sensitive\n",
            "k-sensitive\nAPI_SECRET=s-never-log\n",
            "ALPACA_API_KEY=k-sensitive\nALPACA_API_SECRET=s-never-log\n",
            "API_KEY=k-sen\tsitive\nAPI_SECRET=s-never-log\n",
        ],
    )
    def test_invalid_content(self, tmp_path: Path, content: str) -> None:
        """Reject placeholders, extras and malformed lines without echoing values."""
        TestVenueSecrets.write_credentials(tmp_path, "alpaca", content)
        with pytest.raises(VenueSecretsError) as caught:
            VenueSecrets.read("alpaca", tmp_path)
        assert "sensitive" not in str(caught.value)
        assert "never-log" not in str(caught.value)
        assert not [
            v
            for v in TestVenueSecrets.frame_strings(caught.value)
            if "sensitive" in v or "never-log" in v
        ]

    def test_credential_directory_is_always_explicit(self) -> None:
        """No default directory: one derived from the module file lands inside .venv."""
        directory = inspect.signature(VenueSecrets.read).parameters["directory"]
        # A parameter with a default renders as "name: annotation = default".
        assert "=" not in str(directory)
        assert not hasattr(configuration.venue_secrets, "DEFAULT_SECRETS_DIRECTORY")

    def test_file_swapped_after_its_check_is_not_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Values come from the file that passed the checks, not from a later swap."""
        path = TestVenueSecrets.write_credentials(
            tmp_path, "alpaca", "API_KEY=k-checked-1\nAPI_SECRET=s-checked-1\n"
        )
        planted = tmp_path / "planted"
        planted.write_text("API_KEY=k-planted-1\nAPI_SECRET=s-planted-1\n")
        planted.chmod(0o644)
        race = _SwapRace(path, planted)
        # Race the check against the read at whichever point the reader checks.
        monkeypatch.setattr(Path, "lstat", race)
        monkeypatch.setattr(os, "open", race.open)
        secrets = VenueSecrets.read("alpaca", tmp_path)
        assert race.swapped
        assert secrets.api_key.reveal() == "k-checked-1"

    def test_undecodable_file_leaves_no_bytes_in_the_exception_chain(self, tmp_path: Path) -> None:
        """A file that is not UTF-8 is refused without its bytes reachable from the error."""
        path = tmp_path / VENUE_SECRET_FILES["alpaca"][0]
        path.write_bytes(b"API_KEY=k-sensitive\nAPI_SECRET=s-never-log\xff\n")
        path.chmod(0o600)
        with pytest.raises(VenueSecretsError, match="cannot be read as UTF-8") as caught:
            VenueSecrets.read("alpaca", tmp_path)
        chain: list[BaseException] = []
        current: BaseException | None = caught.value
        while current is not None:
            chain.append(current)
            current = current.__cause__ or current.__context__
        # A UnicodeDecodeError's .object is the whole file, credentials included.
        assert not [
            item
            for item in chain
            if isinstance(item, UnicodeDecodeError) and b"never-log" in item.object
        ]
        assert caught.value.__context__ is None

    def test_logs_redact_revealed_values(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Redact raw values that reach any logger, including exception and stack text."""
        TestVenueSecrets.write_credentials(
            tmp_path, "alpaca", "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\n"
        )
        secrets = VenueSecrets.read("alpaca", tmp_path)
        key, secret = secrets.api_key.reveal(), secrets.api_secret.reveal()
        with caplog.at_level(logging.DEBUG):
            logging.getLogger("httpx").debug("headers %s", {"APCA-API-KEY-ID": key})
            logging.getLogger("websockets.client").debug(f"> TEXT {secret}", stack_info=True)
            try:
                raise RuntimeError(f"rejected header {secret}")
            except RuntimeError:
                logging.getLogger("third.party").exception("request failed for %s", key)
        assert caplog.records
        assert "sensitive" not in caplog.text
        assert "never-log" not in caplog.text
        assert "<redacted>" in caplog.text
        assert "rejected header" in caplog.text

    def test_failing_handler_never_prints_raw_arguments(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Handler errors and raw record fields carry no credential, only the placeholder."""
        TestVenueSecrets.write_credentials(
            tmp_path, "alpaca", "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\n"
        )
        key = VenueSecrets.read("alpaca", tmp_path).api_key.reveal()

        class Broken(logging.Handler):
            """Fail like a closed stream or a full disk."""

            def emit(self, record: logging.LogRecord) -> None:
                """Fail, and report it the way standard handlers do."""
                try:
                    raise OSError("disk full")
                except OSError:
                    self.handleError(record)

        logger = logging.getLogger("third.party.broken")
        handler = Broken()
        logger.addHandler(handler)
        logger.propagate = False
        try:
            logger.error("sent %s", key)
            logger.error("arity %s %s", key)
            logger.error("prefix %.3s", key)
            record = logger.makeRecord(
                logger.name, logging.ERROR, __file__, 1, "header %s", (key,), None
            )
        finally:
            logger.removeHandler(handler)
            logger.propagate = True
        # HTTPHandler sends the raw record fields.
        assert "sensitive" not in f"{record.getMessage()} {record.args!r}"
        assert "sensitive" not in capsys.readouterr().err

    def test_registration_during_a_redaction_check_is_safe(self, tmp_path: Path) -> None:
        """A credential registered on another thread cannot break an in-progress check."""
        TestVenueSecrets.write_credentials(
            tmp_path, "alpaca", "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\n"
        )
        VenueSecrets.read("alpaca", tmp_path)

        class Registering(str):
            """Register another credential while a check iterates the registry."""

            def __contains__(self, item: object) -> bool:
                """Register a new credential mid-check and report no match."""
                SecretValue(f"late-{uuid.uuid4().hex}")
                return False

        assert not CredentialRedaction._contains_secret(Registering("no credential here"))

    def test_a_later_log_record_factory_keeps_redaction(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Redaction chains the previous factory and survives one installed later."""
        tagging = _TaggingFactory()
        # The logging module's own factory slot; monkeypatch restores it afterwards.
        monkeypatch.setattr(logging, "_logRecordFactory", tagging)
        TestVenueSecrets.write_credentials(
            tmp_path, "alpaca", "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\n"
        )
        key = VenueSecrets.read("alpaca", tmp_path).api_key.reveal()
        with caplog.at_level(logging.DEBUG):
            logging.getLogger("third.party").info("key %s", key)
        assert tagging.records
        assert "sensitive" not in caplog.text

    def test_short_values_are_refused(self, tmp_path: Path) -> None:
        """A value too short to redact safely is refused, never loaded unredacted."""
        TestVenueSecrets.write_credentials(
            tmp_path, "coinbase", "API_KEY=k-sensitive\nAPI_SECRET=c2VjcmV0\nAPI_PASSPHRASE=ab12x\n"
        )
        with pytest.raises(VenueSecretsError, match="invalid API_PASSPHRASE"):
            VenueSecrets.read("coinbase", tmp_path)

    def test_core_dumps_disabled(self, tmp_path: Path) -> None:
        """Keep credential-bearing process memory out of crash dumps."""
        TestVenueSecrets.write_credentials(tmp_path, "eia", "API_KEY=k-sensitive\n")
        # A fresh process: the lowered limit cannot be restored for later tests.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import resource, sys\n"
                "from pathlib import Path\n"
                "from configuration.venue_secrets import VenueSecrets\n"
                "VenueSecrets.read('eia', Path(sys.argv[1]))\n"
                "print(resource.getrlimit(resource.RLIMIT_CORE))",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "(0, 0)"

    @pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o660])
    def test_rejects_shared_permissions(self, tmp_path: Path, mode: int) -> None:
        """Refuse credential files readable or writable by group or others."""
        TestVenueSecrets.write_credentials(tmp_path, "eia", "API_KEY=k-sensitive\n", mode)
        with pytest.raises(VenueSecretsError, match="chmod 600"):
            VenueSecrets.read("eia", tmp_path)

    def test_rejects_symlink_missing_and_unknown(self, tmp_path: Path) -> None:
        """Refuse links, absent files and unconfigured venue names."""
        target = TestVenueSecrets.write_credentials(
            tmp_path, "alpaca", "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\n"
        )
        (tmp_path / "coingecko.secrets").symlink_to(target)
        with pytest.raises(VenueSecretsError, match="regular file"):
            VenueSecrets.read("coingecko", tmp_path)
        with pytest.raises(VenueSecretsError, match="missing"):
            VenueSecrets.read("polymarket", tmp_path)
        with pytest.raises(VenueSecretsError, match="unknown"):
            VenueSecrets.read("kraken", tmp_path)

    @staticmethod
    def frame_strings(error: BaseException) -> list[str]:
        """Collect string locals from non-test frames across the exception chain."""
        found: list[str] = []
        pending: list[BaseException | None] = [error]
        while pending:
            current = pending.pop()
            if current is None:
                continue
            pending += [current.__cause__, current.__context__]
            traceback: TracebackType | None = current.__traceback__
            while traceback is not None:
                frame = traceback.tb_frame
                if frame.f_code.co_filename != __file__:
                    values = cast(dict[str, object], frame.f_locals).values()
                    found += [v for v in values if isinstance(v, str)]
                traceback = traceback.tb_next
        return found

    @staticmethod
    def write_credentials(directory: Path, venue: str, content: str, mode: int = 0o600) -> Path:
        """Write invented credentials under the venue's configured file name."""
        path = directory / VENUE_SECRET_FILES[venue][0]
        path.write_text(content)
        path.chmod(mode)
        return path

    @pytest.fixture(autouse=True)
    def _restore_process_guards(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Undo the process-wide guards that loading a credential installs.

        Each test starts with an empty registry, and its redacting log-record factory
        is removed afterwards. A lowered hard core-dump limit can never be raised
        again by an unprivileged process, so core dumps are left alone here and
        checked in a separate process.
        """
        monkeypatch.setattr(CredentialRedaction, "_registered", frozenset())
        factory: object = logging.getLogRecordFactory()
        monkeypatch.setattr(logging, "_logRecordFactory", factory)
        monkeypatch.setattr(CredentialRedaction, "_disable_core_dumps", _CoreDumpsUnchanged())
