"""Bound each installed account command's wait without changing its outcome semantics."""

from __future__ import annotations

# standard library imports
import hashlib
import subprocess
from pathlib import Path
from typing import cast, get_args, get_type_hints

# third party library imports
import pytest
from test_account_journal import TestAccountJournal as _AccountFixture

# project library imports
from execution import AccountExecutionRequest, AccountExecutionResult, InstalledPaperAccount
from serialization import DomainCodec


class _Launcher:
    """Stand in for ``subprocess.run``: record each call, then return or raise one outcome."""

    def __init__(self, outcome: subprocess.CompletedProcess[bytes] | Exception) -> None:
        """Bind the single outcome every call produces."""
        self.outcome = outcome
        self.calls: list[tuple[list[str], float]] = []
        self.retained_at_dispatch: list[bool] = []

    def __call__(
        self, arguments: list[str], **options: object
    ) -> subprocess.CompletedProcess[bytes]:
        """Record the argv and wait bound, and whether the request was already retained."""
        timeout = options["timeout"]
        assert isinstance(timeout, int | float)
        self.calls.append((arguments, timeout))
        self.retained_at_dispatch.append(Path(arguments[-1]).is_file())
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class TestInstalledPaperAccount:
    """Wait 300 s for whole-journal backup and restore, 30 s otherwise, never retrying."""

    backup = AccountExecutionRequest(action="backup", backup_root="/absent/backup")
    restore = AccountExecutionRequest(
        action="restore",
        backup_root="/absent/backup",
        restore_root="/absent/restored",
        manifest_sha256="0" * 64,
    )
    inspect = AccountExecutionRequest(action="inspect", projection="statuses")

    @staticmethod
    def _account(tmp_path: Path) -> InstalledPaperAccount:
        """Bind an adapter to absolute paths; the launcher itself is replaced."""
        return InstalledPaperAccount(
            config=_AccountFixture._config(),
            launcher=tmp_path / "launcher",
            target=tmp_path / "target",
            policy=tmp_path / "policy.json",
            requests=tmp_path / "requests",
        )

    @staticmethod
    def _install(monkeypatch: pytest.MonkeyPatch, launcher: _Launcher) -> None:
        """Route the adapter's launcher call to ``launcher``."""
        monkeypatch.setattr("execution.installed_account.subprocess.run", launcher)

    def test_only_backup_and_restore_wait_longer(self) -> None:
        """Every action the request admits is awaited 30 s except backup and restore."""
        hints = cast(dict[str, object], get_type_hints(AccountExecutionRequest))
        actions = cast(tuple[str, ...], get_args(hints["action"]))
        assert {"backup", "restore", "inspect", "control"} <= set(actions)
        assert {
            action: InstalledPaperAccount.command_seconds(action)
            for action in actions
            if InstalledPaperAccount.command_seconds(action) != 30
        } == {"backup": 300, "restore": 300}

    @pytest.mark.parametrize(
        ("request_name", "seconds"), [("backup", 300), ("restore", 300), ("inspect", 30)]
    )
    def test_a_command_is_dispatched_with_its_action_bound(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        request_name: str,
        seconds: int,
    ) -> None:
        """The launcher receives the action's bound; a success keeps its exact receipt."""
        request: AccountExecutionRequest = getattr(self, request_name)
        response = DomainCodec().encode_json(AccountExecutionResult(accounts=(), orders=()))
        launcher = _Launcher(subprocess.CompletedProcess([], 0, response, b""))
        self._install(monkeypatch, launcher)
        account = self._account(tmp_path)

        assert account.execute(request) == AccountExecutionResult(accounts=(), orders=())
        ((arguments, timeout),) = launcher.calls
        assert timeout == seconds
        assert launcher.retained_at_dispatch == [True]
        payload = DomainCodec().encode_json(request)
        retained = account.requests / f"{hashlib.sha256(payload).hexdigest()}.json"
        assert arguments[-2:] == ["--request", str(retained)]
        assert retained.read_bytes() == payload
        (receipt,) = account.requests.glob(f"{retained.stem}.*.result.json")
        assert receipt.read_bytes() == response

    @pytest.mark.parametrize("request_name", ["backup", "restore", "inspect"])
    def test_a_timeout_stays_uncertain_and_is_not_retried(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request_name: str
    ) -> None:
        """An expired wait raises once with the request retained and no receipt or retry."""
        request: AccountExecutionRequest = getattr(self, request_name)
        bound = InstalledPaperAccount.command_seconds(request.action)
        launcher = _Launcher(subprocess.TimeoutExpired(["launcher"], bound))
        self._install(monkeypatch, launcher)
        account = self._account(tmp_path)

        with pytest.raises(subprocess.TimeoutExpired):
            account.execute(request)
        assert [timeout for _, timeout in launcher.calls] == [bound]
        assert [path.suffix for path in account.requests.iterdir()] == [".json"]
        assert not list(account.requests.glob("*.result.json"))

    def test_a_refused_backup_keeps_its_stderr_and_is_not_retried(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-zero exit raises once, retaining the request and the launcher's stderr."""
        launcher = _Launcher(subprocess.CompletedProcess([], 2, b"", b"accounts must be stopped"))
        self._install(monkeypatch, launcher)
        account = self._account(tmp_path)

        with pytest.raises(RuntimeError, match=r"installed paper command failed \(2\)"):
            account.execute(self.backup)
        assert len(launcher.calls) == 1
        (stderr,) = account.requests.glob("*.stderr")
        assert stderr.read_bytes() == b"accounts must be stopped"
        assert not list(account.requests.glob("*.result.json"))
