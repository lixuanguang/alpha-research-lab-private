"""Preserve stopped account workspaces through verified local backup and restore."""

from __future__ import annotations

# standard library imports
import hashlib
from contextlib import closing
from pathlib import Path
from typing import Literal

# project library imports
from configuration import AccountConfiguration
from execution import AccountJournal, AccountView
from execution import AccountRecoveryReceipt as AccountRecoveryReceipt
from runtime.workspace import WorkspaceBackup, WorkspaceManifest
from serialization import DomainCodec


class AccountWorkspace:
    """Back up one explicit account-state directory and refuse automatic activation.

    The journal must be a direct child of a named component directory, normally
    ``state/accounts.sqlite3``. That entire directory, including retained alert
    databases, is captured by the existing workspace backup implementation.
    Keep compatible signed release bytes and trust policy separately; this
    snapshot is account state, never an installation or an authorization.
    """

    def __init__(self, config: AccountConfiguration, *, component: str, journal_name: str) -> None:
        """Bind exact configuration and a safe relative account-journal location."""
        config.__post_init__()
        if (
            not component
            or Path(component).name != component
            or component in (".", "..")
            or Path(journal_name).name != journal_name
            or not journal_name.endswith(".sqlite3")
        ):
            raise ValueError("account recovery requires one component and SQLite filename")
        self.config = config
        self.component = component
        self.journal_name = journal_name

    def backup(self, workspace_root: Path, backup_root: Path) -> AccountRecoveryReceipt:
        """Capture a stopped state under SQLite write locks at an absent destination.

        Every account must have an explicit durable stop or fault. This check
        runs after the backup acquires all selected SQLite write locks, so a
        concurrent restart cannot turn a running snapshot into a recovery point.
        Existing order outcomes and candidate checkpoints remain unchanged.
        """
        guard = _StoppedAccounts(self.config, self._journal(workspace_root))
        WorkspaceBackup.create(
            workspace_root,
            backup_root,
            components=(self.component,),
            validate_quiescence=guard.validate,
        )
        return self.verify(backup_root)

    def verify(self, backup_root: Path) -> AccountRecoveryReceipt:
        """Verify complete file hashes, state schema, config pin and durable stops."""
        manifest = WorkspaceBackup.verify(backup_root)
        self._require_component(manifest)
        accounts = _StoppedAccounts(
            self.config, self._journal(backup_root / "payload"), storage="snapshot"
        ).read()
        return AccountRecoveryReceipt(
            manifest_sha256=hashlib.sha256(
                (backup_root / "manifest.json").read_bytes()
            ).hexdigest(),
            configuration_sha256=hashlib.sha256(DomainCodec().encode_json(self.config)).hexdigest(),
            journal_relative_path=f"{self.component}/{self.journal_name}",
            accounts=accounts,
        )

    def restore(
        self, backup_root: Path, destination_root: Path, *, expected_manifest_sha256: str
    ) -> AccountRecoveryReceipt:
        """Restore pinned bytes into an absent workspace, preserving all stop controls.

        The caller selects the immutable manifest digest. The account owner
        checks staged SQLite state before publication; a mismatched configuration,
        unsupported schema or running account never becomes a usable restore.
        The staged copy is quarantined from managed paper activation. Managed
        resumption uses the latest retained journal, fresh reconciliation and
        an explicit owner claim, never this historical snapshot.
        """
        receipt = self.verify(backup_root)
        if receipt.manifest_sha256 != expected_manifest_sha256:
            raise ValueError("account backup manifest identity differs")
        WorkspaceBackup.restore(
            backup_root, destination_root, validate_restored=self._validate_restored
        )
        return receipt

    def _journal(self, root: Path) -> Path:
        """Resolve only the configured relative journal name."""
        return root / self.component / self.journal_name

    def _validate_restored(self, root: Path) -> None:
        """Admit the staged database through its owner before publication."""
        _StoppedAccounts(self.config, self._journal(root), storage="snapshot").validate()
        # Closing the only connection checkpoints the quarantine into the database,
        # so it is checked as a standalone snapshot, and no SQLite side file is
        # published with it.
        with closing(AccountJournal(self._journal(root), self.config)) as journal:
            journal.quarantine_paper_restore()
        _StoppedAccounts(self.config, self._journal(root), storage="snapshot").validate()

    def _require_component(self, manifest: WorkspaceManifest) -> None:
        """Keep this recovery operation scoped to the selected account component."""
        if manifest.components != (self.component,) or not any(
            item.name == f"{self.component}/{self.journal_name}" for item in manifest.files
        ):
            raise ValueError("account backup component or journal differs")


class _StoppedAccounts:
    """Validate quiescence using a read-only account-owner inspection."""

    def __init__(
        self,
        config: AccountConfiguration,
        journal: Path,
        *,
        storage: Literal["wal", "snapshot"] = "wal",
    ) -> None:
        """Bind the selected state bytes and exact configuration."""
        self.config, self.journal = config, journal
        self.storage = storage

    def read(self) -> tuple[AccountView, ...]:
        """Reject running or unbound account state and return explicitly stopped accounts."""
        accounts = AccountJournal.verify(self.journal, self.config, storage=self.storage)
        if any(
            account.phase not in ("stopped", "faulted")
            or account.active_control_identity is None
            or account.control_cutoff_at is None
            for account in accounts
        ):
            raise ValueError("account backup and restore require explicit stopped accounts")
        return accounts

    def validate(self) -> None:
        """Check quiescence while another owner holds the selected SQLite write locks."""
        self.read()
