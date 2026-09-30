"""Validate venue credential files without ever reading developer secrets."""

# standard library imports
import copy
import logging
import os
import pickle
import resource
import uuid
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import cast

# third party library imports
import pytest

# project library imports
from configuration import venue_secrets
from configuration.venue_secrets import (
    VENUE_SECRET_FILES,
    SecretValue,
    VenueSecrets,
    VenueSecretsError,
)


def _frame_strings(error: BaseException) -> list[str]:
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


def _write(directory: Path, venue: str, content: str, mode: int = 0o600) -> Path:
    """Write invented credentials under the venue's configured file name."""
    path = directory / VENUE_SECRET_FILES[venue][0]
    path.write_text(content)
    path.chmod(mode)
    return path


class TestVenueSecrets:
    """Use invented values only; the repository secrets directory is never touched."""

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
        _write(tmp_path, venue.lower(), content)
        secrets = VenueSecrets.read(venue, tmp_path)
        assert secrets.api_key.reveal() == "k-sensitive"
        if has_secret:
            assert secrets.api_secret.reveal() == "s-never-log"
        else:
            with pytest.raises(VenueSecretsError, match="no API_SECRET"):
                _ = secrets.api_secret

    def test_values_never_render(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Keep values out of repr, str, f-strings, logs, pickles and copies."""
        _write(tmp_path, "alpaca", "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\n")
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
        _write(tmp_path, "alpaca", content)
        with pytest.raises(VenueSecretsError) as caught:
            VenueSecrets.read("alpaca", tmp_path)
        assert "sensitive" not in str(caught.value)
        assert "never-log" not in str(caught.value)
        assert not [v for v in _frame_strings(caught.value) if "sensitive" in v or "never-log" in v]

    def test_file_swapped_after_its_check_is_not_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Values come from the file that passed the checks, not from a later swap."""
        path = _write(tmp_path, "alpaca", "API_KEY=k-checked-1\nAPI_SECRET=s-checked-1\n")
        planted = tmp_path / "planted"
        planted.write_text("API_KEY=k-planted-1\nAPI_SECRET=s-planted-1\n")
        planted.chmod(0o644)
        swapped = False

        def swap() -> None:
            """Replace the checked path with a link to the planted file, once."""
            nonlocal swapped
            if not swapped:
                swapped = True
                path.unlink()
                path.symlink_to(planted)

        lstat, open_descriptor = Path.lstat, os.open

        def checked_lstat(self: Path) -> os.stat_result:
            """Stat the path, then race the swap in right after the check."""
            status = lstat(self)
            if self == path:
                swap()
            return status

        def checked_open(file: str | Path, flags: int, mode: int = 0o777) -> int:
            """Open the path, then race the swap in right after the open."""
            descriptor = open_descriptor(file, flags, mode)
            if Path(file) == path:
                swap()
            return descriptor

        # Race the check against the read at whichever point the reader checks.
        monkeypatch.setattr(Path, "lstat", checked_lstat)
        monkeypatch.setattr(os, "open", checked_open)
        secrets = VenueSecrets.read("alpaca", tmp_path)
        assert swapped
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
        _write(tmp_path, "alpaca", "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\n")
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
        _write(tmp_path, "alpaca", "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\n")
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
        _write(tmp_path, "alpaca", "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\n")
        VenueSecrets.read("alpaca", tmp_path)

        class Registering(str):
            """Register another credential while a check iterates the registry."""

            def __contains__(self, item: object) -> bool:
                """Register a new credential mid-check and report no match."""
                SecretValue(f"late-{uuid.uuid4().hex}")
                return False

        assert not venue_secrets._contains_secret(Registering("no credential here"))

    def test_a_later_log_record_factory_keeps_redaction(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Redaction chains the previous factory and survives one installed later."""
        tagged: list[logging.LogRecord] = []

        def tagging(
            name: str,
            level: int,
            pathname: str,
            lineno: int,
            msg: object,
            args: tuple[object, ...] | Mapping[str, object],
            exc_info: venue_secrets._ExcInfo,
            func: str | None = None,
            sinfo: str | None = None,
        ) -> logging.LogRecord:
            """An application factory installed after credentials were loaded."""
            record = logging.LogRecord(
                name, level, pathname, lineno, msg, args, exc_info, func, sinfo
            )
            tagged.append(record)
            return record

        # The logging module's own factory slot; monkeypatch restores it afterwards.
        monkeypatch.setattr(logging, "_logRecordFactory", tagging)
        _write(tmp_path, "alpaca", "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\n")
        key = VenueSecrets.read("alpaca", tmp_path).api_key.reveal()
        with caplog.at_level(logging.DEBUG):
            logging.getLogger("third.party").info("key %s", key)
        assert tagged
        assert "sensitive" not in caplog.text

    def test_short_values_are_refused(self, tmp_path: Path) -> None:
        """A value too short to redact safely is refused, never loaded unredacted."""
        _write(
            tmp_path, "coinbase", "API_KEY=k-sensitive\nAPI_SECRET=c2VjcmV0\nAPI_PASSPHRASE=ab12x\n"
        )
        with pytest.raises(VenueSecretsError, match="invalid API_PASSPHRASE"):
            VenueSecrets.read("coinbase", tmp_path)

    def test_core_dumps_disabled(self, tmp_path: Path) -> None:
        """Keep credential-bearing process memory out of crash dumps."""
        _write(tmp_path, "eia", "API_KEY=k-sensitive\n")
        VenueSecrets.read("eia", tmp_path)
        assert resource.getrlimit(resource.RLIMIT_CORE) == (0, 0)

    @pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o660])
    def test_rejects_shared_permissions(self, tmp_path: Path, mode: int) -> None:
        """Refuse credential files readable or writable by group or others."""
        _write(tmp_path, "eia", "API_KEY=k-sensitive\n", mode)
        with pytest.raises(VenueSecretsError, match="chmod 600"):
            VenueSecrets.read("eia", tmp_path)

    def test_rejects_symlink_missing_and_unknown(self, tmp_path: Path) -> None:
        """Refuse links, absent files and unconfigured venue names."""
        target = _write(tmp_path, "alpaca", "API_KEY=k-sensitive\nAPI_SECRET=s-never-log\n")
        (tmp_path / "coingecko.secrets").symlink_to(target)
        with pytest.raises(VenueSecretsError, match="regular file"):
            VenueSecrets.read("coingecko", tmp_path)
        with pytest.raises(VenueSecretsError, match="missing"):
            VenueSecrets.read("polymarket", tmp_path)
        with pytest.raises(VenueSecretsError, match="unknown"):
            VenueSecrets.read("kraken", tmp_path)
