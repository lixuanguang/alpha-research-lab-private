"""Validate local secret parsing and the Exchange-only read challenge."""

# standard library imports
import base64
import hashlib
import hmac
from pathlib import Path
from typing import cast

# third party library imports
import pytest

# project library imports
from configuration import SecretValue
from market_data.adapters.venues.coinbase import CoinbaseAccessError, CoinbaseCredentials


class TestCoinbaseCredentials:
    """Use invented signing material; never read developer secrets."""

    def test_signature(self, tmp_path: Path) -> None:
        """Sign the documented GET verification path and compact channel subscription."""
        path = tmp_path / "coinbase.secrets"
        path.write_text("API_KEY=example\nAPI_SECRET=c2VjcmV0\nAPI_PASSPHRASE=phrase\n")
        path.chmod(0o600)
        credentials = CoinbaseCredentials.read(path)
        request = credentials.subscription("BTC-USD", "1")
        expected = base64.b64encode(
            hmac.new(b"secret", b"1GET/users/self/verify", hashlib.sha256).digest()
        ).decode()
        assert request["signature"] == expected
        assert request["channels"] == ["level3", "heartbeat"]
        assert "secret" not in repr(credentials)
        assert not hasattr(credentials, "__dict__")
        assert all(
            isinstance(cast(object, getattr(credentials, slot)), SecretValue)
            for slot in CoinbaseCredentials.__slots__
        )

    def test_rejects_shared_readable_file(self, tmp_path: Path) -> None:
        """Refuse group- or world-readable credential files."""
        path = tmp_path / "coinbase.secrets"
        path.write_text("API_KEY=example\nAPI_SECRET=c2VjcmV0\nAPI_PASSPHRASE=phrase\n")
        path.chmod(0o644)
        with pytest.raises(CoinbaseAccessError, match="chmod 600"):
            CoinbaseCredentials.read(path)

    @pytest.mark.parametrize(
        "content",
        [
            None,
            "",
            "API_KEY=\nAPI_SECRET=\nAPI_PASSPHRASE=\n",
            '{"name":"sensitive","privateKey":"never-log"}',
            "API_KEY=sensitive\nAPI_SECRET=bad!\nAPI_PASSPHRASE=never-log\n",
            "API_KEY=sensitive\nAPI_SECRET=c2VjcmV0\nAPI_PASSPHRASE=never-log\nEXTRA=never-log\n",
        ],
    )
    def test_missing_or_incompatible(self, tmp_path: Path, content: str | None) -> None:
        """Reject missing, placeholder and CDP secrets without reflecting their contents."""
        path = tmp_path / "coinbase.secrets"
        if content is not None:
            path.write_text(content)
            path.chmod(0o600)
        with pytest.raises(CoinbaseAccessError) as caught:
            CoinbaseCredentials.read(path)
        assert "sensitive" not in str(caught.value)
        assert "never-log" not in str(caught.value)
