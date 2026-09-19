"""Read local Coinbase Exchange key/value secrets and sign subscriptions."""

from __future__ import annotations

# standard library imports
import base64
import hashlib
import hmac
from pathlib import Path


class CoinbaseAccessError(ValueError):
    """Explain access requirements without retaining secret-bearing exception text."""


class CoinbaseCredentials:
    """Own Exchange signing material, never a printable or serialized secret record."""

    def __init__(self, key: str, secret: bytes, passphrase: str) -> None:
        """Bind validated Exchange signing inputs with no network activity.

        Args:
            key: Exchange API key; retained privately and never logged.
            secret: Decoded HMAC secret; retained privately and never logged.
            passphrase: Exchange API passphrase; retained privately and never logged.

        Raises:
            CoinbaseAccessError: Exchange credentials are missing, malformed or incompatible.
        """
        if not key or not secret or not passphrase:
            raise CoinbaseAccessError("Exchange key, base64 secret and passphrase are required")
        self._key, self._secret, self._passphrase = key, secret, passphrase

    @classmethod
    def read(cls, path: Path) -> CoinbaseCredentials:
        """Read KEY=VALUE Exchange credentials from an explicitly selected local file.

        Blank lines and comments are allowed. Values are never interpolated,
        printed or included in exceptions. CDP JSON is deliberately unsupported.

        Args:
            path: Explicit local file path; secret values are never reported.

        Returns:
            Validated configuration, credentials or replay state owned by this boundary.

        Raises:
            CoinbaseAccessError: Exchange credentials are missing, malformed or incompatible.
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        try:
            if path.stat().st_size > 16384:
                raise ValueError("oversized credential file")
            fields: dict[str, str] = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                key, separator, value = line.partition("=")
                if not separator or key.strip() in fields:
                    raise ValueError("invalid secret field")
                fields[key.strip()] = value.strip()
            expected = {"COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_PASSPHRASE"}
            if set(fields) != expected:
                raise ValueError("invalid secret fields")
            return cls(
                fields["COINBASE_API_KEY"],
                base64.b64decode(fields["COINBASE_API_SECRET"], validate=True),
                fields["COINBASE_API_PASSPHRASE"],
            )
        except FileNotFoundError:
            raise CoinbaseAccessError(
                "Coinbase secrets file is missing; Exchange L3 access unverified"
            ) from None
        except ValueError, OSError:
            raise CoinbaseAccessError(
                "Fill COINBASE_API_KEY, COINBASE_API_SECRET (base64), and "
                "COINBASE_API_PASSPHRASE in the Exchange secrets file"
            ) from None

    def subscription(self, symbol: str, timestamp: str) -> dict[str, object]:
        """Sign only the read-only WebSocket verification path; caller must not log it.

        Args:
            symbol: Configured native Exchange product ID.
            timestamp: UTC Unix seconds text for this verification challenge.

        Returns:
            Signed read-only level3/heartbeat subscription; must not be persisted.
        """
        signature = hmac.new(
            self._secret, (timestamp + "GET/users/self/verify").encode(), hashlib.sha256
        ).digest()
        return {
            "type": "subscribe",
            "product_ids": [symbol],
            "channels": ["level3", "heartbeat"],
            "key": self._key,
            "passphrase": self._passphrase,
            "timestamp": timestamp,
            "signature": base64.b64encode(signature).decode(),
        }
