"""Read local venue API credentials without exposing their values.

Each venue owns one gitignored ``secrets/<file>.secrets`` file of ``KEY=VALUE``
lines using the shared field names ``API_KEY``, ``API_SECRET`` and, where the
venue requires it, ``API_PASSPHRASE``. Values are held in :class:`SecretValue`,
which never renders, serializes or pickles its content; callers reveal a value
only at the point it is placed into an outbound request.

Loading any credential also installs two process-wide guards: every log record
has registered credential values replaced before any handler sees it, and core
dumps are disabled so process memory holding credentials is never written out.
Errors are raised from frames whose locals hold no raw credential text.
"""

from __future__ import annotations

# standard library imports
import logging
import stat
import threading
import traceback
from pathlib import Path
from typing import Final, NoReturn

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_SECRETS_DIRECTORY: Final = _REPOSITORY_ROOT / "secrets"
_MAXIMUM_FILE_BYTES: Final = 16384
_REDACTED: Final = "<redacted>"
_MINIMUM_REDACTED_LENGTH: Final = 6
_REGISTERED_VALUES: set[str] = set()
_GUARD_LOCK: Final = threading.Lock()

VENUE_SECRET_FILES: Final[dict[str, tuple[str, frozenset[str]]]] = {
    "alpaca": ("alpaca.secrets", frozenset({"API_KEY", "API_SECRET"})),
    "coinbase": ("coinbase.secrets", frozenset({"API_KEY", "API_SECRET", "API_PASSPHRASE"})),
    "coingecko": ("coingecko.secrets", frozenset({"API_KEY"})),
    "eia": ("EIA.secrets", frozenset({"API_KEY"})),
    "polymarket": ("polymarket.secrets", frozenset({"API_KEY", "API_SECRET"})),
}


class VenueSecretsError(ValueError):
    """Explain credential requirements without retaining secret-bearing text."""


class SecretValue:
    """Hold one credential string that cannot be printed, formatted or pickled."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        """Bind a non-empty printable ASCII credential.

        Args:
            value: Credential text; retained privately and never logged.

        Raises:
            VenueSecretsError: The value is empty or contains unsafe characters.
        """
        if not value or not value.isascii() or not value.isprintable():
            del value
            raise VenueSecretsError("credential values must be non-empty printable ASCII")
        self._value = value
        _register(value)

    def reveal(self) -> str:
        """Return the raw credential for an outbound request; caller must not log it."""
        return self._value

    def __repr__(self) -> str:
        """Render a fixed placeholder instead of the credential."""
        return _REDACTED

    __str__ = __repr__

    def __format__(self, format_spec: str) -> str:
        """Format as the fixed placeholder regardless of format specification."""
        return _REDACTED

    def __reduce__(self) -> NoReturn:
        """Refuse pickling, deep copies and other serialization of the credential."""
        raise TypeError("SecretValue cannot be serialized")


class VenueSecrets:
    """Own one venue's validated credentials, never a printable secret record."""

    __slots__ = ("_fields", "venue")

    def __init__(self, venue: str, fields: dict[str, SecretValue]) -> None:
        """Bind validated credential fields for one venue.

        Args:
            venue: Lowercase venue name from ``VENUE_SECRET_FILES``.
            fields: Exactly the field names that venue requires.
        """
        self.venue = venue
        self._fields = dict(fields)

    @property
    def api_key(self) -> SecretValue:
        """Return the venue API key wrapper."""
        return self._fields["API_KEY"]

    @property
    def api_secret(self) -> SecretValue:
        """Return the venue API secret wrapper.

        Raises:
            VenueSecretsError: The venue uses key-only authentication.
        """
        return self._field("API_SECRET")

    @property
    def api_passphrase(self) -> SecretValue:
        """Return the venue API passphrase wrapper.

        Raises:
            VenueSecretsError: The venue does not use a passphrase.
        """
        return self._field("API_PASSPHRASE")

    def _field(self, name: str) -> SecretValue:
        """Return one configured field or fail naming only the field."""
        try:
            return self._fields[name]
        except KeyError:
            raise VenueSecretsError(f"{self.venue} credentials have no {name}") from None

    def __repr__(self) -> str:
        """Name the venue and field names only."""
        return f"VenueSecrets(venue={self.venue!r}, fields={sorted(self._fields)!r})"

    def __reduce__(self) -> NoReturn:
        """Refuse pickling, deep copies and other serialization of credentials."""
        raise TypeError("VenueSecrets cannot be serialized")

    @classmethod
    def read(cls, venue: str, directory: Path | None = None) -> VenueSecrets:
        """Read one venue's ``KEY=VALUE`` credential file from a local directory.

        Blank lines and ``#`` comments are allowed. The file must be a regular,
        owner-only file (mode 600 or stricter on POSIX). Values are never
        interpolated, printed or included in exceptions.

        Args:
            venue: Case-insensitive venue name from ``VENUE_SECRET_FILES``.
            directory: Secrets directory; defaults to the repository ``secrets/``.

        Returns:
            Validated credentials for the venue.

        Raises:
            VenueSecretsError: The venue is unknown, or its file is missing,
                unsafe, malformed or incomplete.
        """
        venue = venue.lower()
        if venue not in VENUE_SECRET_FILES:
            raise VenueSecretsError(f"unknown credential venue: {venue!r}")
        file_name, required = VENUE_SECRET_FILES[venue]
        path = (DEFAULT_SECRETS_DIRECTORY if directory is None else directory) / file_name
        return cls(venue, read_secret_fields(path, required))


def read_secret_fields(path: Path, required: frozenset[str]) -> dict[str, SecretValue]:
    """Read exactly the required ``KEY=VALUE`` fields from one owner-only file.

    Blank lines and ``#`` comments are allowed. The file must be a regular,
    owner-only file (no group or other permission bits). Values are never
    interpolated, printed or included in exceptions; only the file name and
    expected field names are reported.

    Args:
        path: Explicit local credential file.
        required: Exact field names the file must define.

    Returns:
        Each required field wrapped as a :class:`SecretValue`.

    Raises:
        VenueSecretsError: The file is missing, unsafe, malformed or incomplete.
    """
    file_name = path.name
    try:
        status = path.lstat()
    except FileNotFoundError:
        raise VenueSecretsError(f"{file_name} is missing from the secrets directory") from None
    except OSError:
        raise VenueSecretsError(f"{file_name} cannot be inspected") from None
    if not stat.S_ISREG(status.st_mode):
        raise VenueSecretsError(f"{file_name} must be a regular file, not a link")
    if status.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise VenueSecretsError(f"{file_name} is accessible by others; run chmod 600 on it")
    if status.st_size > _MAXIMUM_FILE_BYTES:
        raise VenueSecretsError(f"{file_name} exceeds {_MAXIMUM_FILE_BYTES} bytes")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        raise VenueSecretsError(f"{file_name} cannot be read as UTF-8") from None
    outcome = _parse_fields(text, required)
    del text
    if isinstance(outcome, str):
        raise VenueSecretsError(f"{file_name} {outcome}")
    return outcome


def _parse_fields(text: str, required: frozenset[str]) -> dict[str, SecretValue] | str:
    """Parse credential lines, returning an error description instead of raising.

    Returning rather than raising means no traceback ever retains this frame's
    locals, which hold raw credential text.
    """
    expected = f"must contain exactly {', '.join(sorted(required))}"
    fields: dict[str, SecretValue] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or name in fields or name not in required:
            return expected
        try:
            fields[name] = SecretValue(value.strip())
        except VenueSecretsError:
            return f"has an empty or invalid {name}"
    if set(fields) != required:
        return expected
    return fields


def _register(value: str) -> None:
    """Record a credential for log redaction and install process guards once."""
    with _GUARD_LOCK:
        if not _REGISTERED_VALUES:
            _disable_core_dumps()
            _install_log_redaction()
        if len(value) >= _MINIMUM_REDACTED_LENGTH:
            _REGISTERED_VALUES.add(value)


def redact(text: str) -> str:
    """Replace every registered credential value in ``text`` with a placeholder.

    Args:
        text: Arbitrary diagnostic text.

    Returns:
        The text with registered credential values removed.
    """
    for value in sorted(_REGISTERED_VALUES, key=len, reverse=True):
        text = text.replace(value, _REDACTED)
    return text


def _contains_secret(text: str) -> bool:
    """Report whether any registered credential value occurs in ``text``."""
    return any(value in text for value in _REGISTERED_VALUES)


class _RedactingLogRecord(logging.LogRecord):
    """Log record whose rendered message, traceback and stack omit credentials."""

    def getMessage(self) -> str:  # overrides the logging API name
        """Render the message and pre-render any credential-bearing diagnostics.

        ``logging.Formatter`` calls this before it renders ``exc_info`` and
        ``stack_info``, so both are redacted here before any handler emits them.
        """
        message = super().getMessage()
        if self.exc_info and self.exc_info[1] is not None and not self.exc_text:
            rendered = "".join(traceback.format_exception(*self.exc_info)).rstrip("\n")
            if _contains_secret(rendered):
                self.exc_text = redact(rendered)
        if self.stack_info and _contains_secret(self.stack_info):
            self.stack_info = redact(self.stack_info)
        return redact(message) if _contains_secret(message) else message


def _install_log_redaction() -> None:
    """Make every logger create records that redact registered credentials.

    This covers third-party HTTP and WebSocket libraries regardless of which
    handlers are configured later.
    """
    logging.setLogRecordFactory(_RedactingLogRecord)


def _disable_core_dumps() -> None:
    """Prevent crash dumps from writing credential-bearing memory to disk."""
    try:
        # standard library imports
        import resource  # POSIX-only module

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except ImportError, ValueError, OSError:
        return
