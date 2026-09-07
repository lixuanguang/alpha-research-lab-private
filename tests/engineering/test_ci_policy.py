"""Focused tests for fail-closed secret scanning and CLI failure propagation."""

from __future__ import annotations

# standard library imports
import subprocess
from pathlib import Path
from types import SimpleNamespace

# third party library imports
import pytest

# project library imports
from alpha_research_governance import ci_policy
from alpha_research_governance.ci_policy import secrets


def test_secret_patterns_report_identifiers_without_secret_contents() -> None:
    """Detect supported high-confidence tokens while keeping payloads out of findings."""
    payload = b"api_key=" + b"A" * 24

    assert secrets.scan_secret_bytes(payload) == ("assigned_credential",)
    assert secrets.scan_secret_bytes(b"-----BEGIN " + b"PRIVATE KEY-----") == ("private_key",)
    assert secrets.scan_secret_bytes(b"API_KEY_ENV=") == ()
    assert "A" * 24 not in str(secrets.scan_secret_bytes(payload))


def test_secret_scan_rejects_unsafe_and_oversized_paths(tmp_path: Path) -> None:
    """Reject paths that escape the root, resolve through links, or exceed the bound."""
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"api_key=" + b"A" * 24)
    with pytest.raises(secrets.CIPolicyError, match="secret pattern"):
        secrets.scan_secret_paths(tmp_path, ("secret.txt",), maximum_file_bytes=100)

    oversized = tmp_path / "oversized.txt"
    oversized.write_bytes(b"x" * 101)
    with pytest.raises(secrets.CIPolicyError, match="exceeds 100 bytes"):
        secrets.scan_secret_paths(tmp_path, ("oversized.txt",), maximum_file_bytes=100)

    link = tmp_path / "linked.txt"
    link.symlink_to(secret)
    with pytest.raises(secrets.CIPolicyError, match="non-regular path"):
        secrets.scan_secret_paths(tmp_path, ("linked.txt",), maximum_file_bytes=100)
    broken_link = tmp_path / "broken.txt"
    broken_link.symlink_to(tmp_path / "missing.txt")
    with pytest.raises(secrets.CIPolicyError, match="non-regular path"):
        secrets.scan_secret_paths(tmp_path, ("broken.txt",), maximum_file_bytes=100)
    with pytest.raises(secrets.CIPolicyError, match="repository-relative"):
        secrets.scan_secret_paths(tmp_path, ("../outside.txt",), maximum_file_bytes=100)


def test_external_scanner_failure_is_propagated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Treat a nonzero detect-private-key result as a blocking CI failure."""

    def failed_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        """Return a synthetic failed scanner process.

        Args:
            _args: Positional scanner arguments, unused by the fixture.
            _kwargs: Keyword scanner arguments, unused by the fixture.

        Returns:
            A process-like result with a failing exit code.

        Raises:
            RuntimeError: Never raised; this documents the fixture contract.
        """
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(subprocess, "run", failed_run)
    with pytest.raises(secrets.CIPolicyError, match="failed with exit 2"):
        secrets.run_external_secret_scanner(tmp_path, ("tracked.txt",))


def test_external_scanner_start_failure_is_propagated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Treat an unavailable detect-private-key executable as a blocking CI failure."""

    def unavailable_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        """Raise the operating-system startup error expected from subprocess.

        Args:
            _args: Positional scanner arguments, unused by the fixture.
            _kwargs: Keyword scanner arguments, unused by the fixture.

        Returns:
            This fixture never returns.

        Raises:
            FileNotFoundError: The scanner executable is unavailable.
        """
        raise FileNotFoundError("detect-private-key")

    monkeypatch.setattr(subprocess, "run", unavailable_run)
    with pytest.raises(secrets.CIPolicyError, match="could not start"):
        secrets.run_external_secret_scanner(tmp_path, ("tracked.txt",))


def test_cli_rejects_empty_scan_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """Return a nonzero status when the minimal compatibility CLI has no scope."""
    assert ci_policy.main(["scan-secrets"]) == 1
    assert "scan-secrets accepts" in capsys.readouterr().err


def test_cli_accepts_the_make_all_scan_invocation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Accept the exact ``alpha-governance-ci scan-secrets --all`` command used by Make."""
    observed: list[tuple[str, ...]] = []

    def tracked_paths(_root: Path) -> tuple[str, ...]:
        """Supply one tracked path without invoking Git in this CLI contract test.

        Args:
            _root: Temporary repository root, unused by the fixture.

        Returns:
            One synthetic tracked path.
        """
        return ("tracked.txt",)

    def successful_scan(_root: Path, paths: tuple[str, ...]) -> None:
        """Record the selected full-tracked scope and return success.

        Args:
            _root: Temporary repository root, unused by the fixture.
            paths: Paths selected for scanning.
        """
        observed.append(paths)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ci_policy, "_git_tracked_paths", tracked_paths)
    monkeypatch.setattr(ci_policy, "scan_repository_paths", successful_scan)

    assert ci_policy.main(["scan-secrets", "--all"]) == 0
    assert observed == [("tracked.txt",)]
    assert "passed for 1 governed paths" in capsys.readouterr().out


def test_cli_propagates_external_scanner_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Return a nonzero CLI status when the external scanner fails."""

    def failed_scan(_root: Path, _paths: tuple[str, ...]) -> None:
        """Raise the same blocking error the scanner boundary reports.

        Args:
            _root: Temporary repository root, unused by the fixture.
            _paths: Selected paths, unused by the fixture.

        Raises:
            secrets.CIPolicyError: The synthetic scanner failed.
        """
        raise secrets.CIPolicyError(["private-key scanner failed with exit 2"])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ci_policy, "scan_repository_paths", failed_scan)
    assert ci_policy.main(["scan-secrets", "tracked.txt"]) == 1
    assert "failed with exit 2" in capsys.readouterr().err


def test_external_scanner_uses_shell_free_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pass validated paths to detect-private-key as separate argv tokens."""
    calls: list[tuple[object, ...]] = []

    def successful_run(*args: object, **kwargs: object) -> SimpleNamespace:
        """Record the scanner invocation and return success.

        Args:
            args: Positional scanner arguments.
            kwargs: Keyword scanner arguments.

        Returns:
            A process-like result with a successful exit code.
        """
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", successful_run)
    secrets.run_external_secret_scanner(tmp_path, ("a.txt", "b.txt"))

    assert calls == [
        (
            (["detect-private-key", "--", "a.txt", "b.txt"],),
            {"cwd": tmp_path, "check": False},
        )
    ]


def test_cli_smoke_module_has_no_scheduler_or_event_log_api() -> None:
    """Keep the compatibility namespace limited to the retained secret boundary."""
    assert not hasattr(ci_policy, "run_affected_ci_lane")
    assert not hasattr(ci_policy, "run_authoritative_full_ci_lane")
    assert not hasattr(ci_policy, "CIEvent")
