"""Validate venue credential files without ever reading developer secrets."""

# standard library imports
import copy
import logging
import pickle
import resource
from pathlib import Path
from types import TracebackType

# third party library imports
import pytest

# project library imports
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
                found += [v for v in frame.f_locals.values() if isinstance(v, str)]
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
