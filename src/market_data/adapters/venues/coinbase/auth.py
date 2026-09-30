"""Read local Coinbase Exchange key/value secrets and sign subscriptions."""

from __future__ import annotations

# standard library imports
import base64
import hashlib
import hmac
from pathlib import Path
from typing import NoReturn

# project library imports
from configuration import VENUE_SECRET_FILES, SecretValue, VenueSecretsError, read_secret_fields

_FIELDS = VENUE_SECRET_FILES["coinbase"][1]


class CoinbaseAccessError(ValueError):
    """Explain access requirements without retaining secret-bearing exception text."""


class CoinbaseCredentials:
    """Own Exchange signing material, never a printable or serialized secret record."""

    __slots__ = ("_key", "_passphrase", "_secret")

    def __init__(self, key: SecretValue, secret: SecretValue, passphrase: SecretValue) -> None:
        """Bind validated Exchange signing inputs with no network activity.

        Args:
            key: Exchange API key; retained privately and never logged.
            secret: Base64 HMAC secret, as the credential file holds it; retained
                privately and never logged.
            passphrase: Exchange API passphrase; retained privately and never logged.

        Raises:
            CoinbaseAccessError: The secret is not nonempty base64.
        """
        if any(type(value) is not SecretValue for value in (key, secret, passphrase)):
            raise TypeError("Exchange credentials must be SecretValue wrappers")
        if not _decoded(secret):
            raise CoinbaseAccessError(
                "Fill API_KEY, API_SECRET (base64), and API_PASSPHRASE in the Exchange secrets file"
            )
        self._key, self._secret, self._passphrase = key, secret, passphrase

    @classmethod
    def read(cls, path: Path) -> CoinbaseCredentials:
        """Read shared-format Exchange credentials from an explicitly selected local file.

        The owner-only file defines ``API_KEY``, ``API_SECRET`` (base64) and
        ``API_PASSPHRASE``. Values are never interpolated, printed or included
        in exceptions. CDP JSON is deliberately unsupported.

        Args:
            path: Explicit local file path; secret values are never reported.

        Returns:
            Validated Exchange signing credentials.

        Raises:
            CoinbaseAccessError: Exchange credentials are missing, malformed or incompatible.
        """
        try:
            fields = read_secret_fields(path, _FIELDS)
        except VenueSecretsError as error:
            raise CoinbaseAccessError(
                f"{error}; Exchange L3 access unverified (API_SECRET must be base64)"
            ) from None
        return cls(fields["API_KEY"], fields["API_SECRET"], fields["API_PASSPHRASE"])

    def __repr__(self) -> str:
        """Render a fixed placeholder instead of signing material."""
        return "CoinbaseCredentials(<redacted>)"

    def __reduce__(self) -> NoReturn:
        """Refuse pickling, deep copies and other serialization of signing material."""
        raise TypeError("CoinbaseCredentials cannot be serialized")

    def subscription(self, symbol: str, timestamp: str) -> dict[str, object]:
        """Sign only the read-only WebSocket verification path; caller must not log it.

        Args:
            symbol: Configured native Exchange product ID.
            timestamp: UTC Unix seconds text for this verification challenge.

        Returns:
            Signed read-only level3/heartbeat subscription; must not be persisted.
        """
        signature = hmac.new(
            base64.b64decode(self._secret.reveal()),
            (timestamp + "GET/users/self/verify").encode(),
            hashlib.sha256,
        ).digest()
        return {
            "type": "subscribe",
            "product_ids": [symbol],
            "channels": ["level3", "heartbeat"],
            "key": self._key.reveal(),
            "passphrase": self._passphrase.reveal(),
            "timestamp": timestamp,
            "signature": base64.b64encode(signature).decode(),
        }


def _decoded(secret: SecretValue) -> bytes | None:
    """Decode a base64 secret, returning None rather than raising.

    Returning keeps the raw value out of any traceback frame's locals.
    """
    try:
        return base64.b64decode(secret.reveal(), validate=True)
    except ValueError:
        return None
