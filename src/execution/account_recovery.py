"""Identify stopped account recovery snapshots without granting resumption authority."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# project library imports
from execution.account_records import AccountView
from serialization import WireRecord


class AccountRecoveryReceipt(WireRecord, frozen=True):
    """Identify a verified snapshot without granting permission to resume it."""

    manifest_sha256: str
    configuration_sha256: str
    journal_relative_path: str
    accounts: tuple[AccountView, ...]

    def __post_init__(self) -> None:
        """Require content identities and explicit stopped account observations."""
        for digest in (self.manifest_sha256, self.configuration_sha256):
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise ValueError("account recovery receipt requires SHA-256 identities")
        path = Path(self.journal_relative_path)
        if path.is_absolute() or len(path.parts) != 2 or ".." in path.parts or not self.accounts:
            raise ValueError("invalid account recovery receipt")
        for account in self.accounts:
            account.__post_init__()
            if account.phase == "running":
                raise ValueError("account recovery receipt cannot authorize running accounts")
