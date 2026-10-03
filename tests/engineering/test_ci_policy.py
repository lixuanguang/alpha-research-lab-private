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
from alpha_research_governance.ci_policy import SecretScanCommand
from alpha_research_governance.ci_policy.secrets import CIPolicyError, SecretScanner


class ProcessDouble:
    """Stand in for ``subprocess.run`` and record each invocation."""

    def __init__(self, *, returncode: int = 0, error: OSError | None = None) -> None:
        """Bind the synthetic exit status or startup failure."""
        self.returncode = returncode
        self.error = error
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> SimpleNamespace:
        """Record the call, then fail to start or return the synthetic status."""
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(returncode=self.returncode)


class ScanRecorder:
    """Stand in for a repository scan and record the selected scope."""

    def __init__(self, error: CIPolicyError | None = None) -> None:
        """Bind an optional blocking error to raise after recording."""
        self.error = error
        self.calls: list[tuple[Path, tuple[str, ...]]] = []

    def __call__(self, root: Path, paths: tuple[str, ...]) -> None:
        """Record one scan and raise the configured error, if any."""
        self.calls.append((root, paths))
        if self.error is not None:
            raise self.error


class TestSecretPatterns:
    """Detect high-confidence secret patterns without disclosing their contents."""

    def test_secret_patterns_report_identifiers_without_secret_contents(self) -> None:
        """Detect supported high-confidence tokens while keeping payloads out of findings."""
        payload = b"api_key=" + b"A" * 24

        assert SecretScanner.scan_bytes(payload) == ("assigned_credential",)
        assert SecretScanner.scan_bytes(b"-----BEGIN " + b"PRIVATE KEY-----") == ("private_key",)
        assert SecretScanner.scan_bytes(b"API_KEY_ENV=") == ()
        assert "A" * 24 not in str(SecretScanner.scan_bytes(payload))

    def test_python_credential_references_do_not_hide_literal_secrets(self) -> None:
        """Exclude valid attribute expressions only, retaining literal/config detection."""
        key = b'"apiKey": '
        attribute = b"self.credentials.api_key"
        dynamic = b"request = {" + key + attribute + b"}\n"
        assert SecretScanner.scan_bytes(dynamic, python_source=True) == ()
        assert SecretScanner.scan_bytes(dynamic) == ("assigned_credential",)
        for literal in (attribute, b"A" * 24):
            quoted = b"request = {" + key + b'"' + literal + b'"}\n'
            assert SecretScanner.scan_bytes(quoted, python_source=True) == ("assigned_credential",)
        invalid = dynamic + b"\nthis is not valid python!"
        assert SecretScanner.scan_bytes(invalid, python_source=True) == ("assigned_credential",)
        mixed = dynamic + b"password = '" + b"B" * 24 + b"'\n"
        assert SecretScanner.scan_bytes(mixed, python_source=True) == ("assigned_credential",)
        unicode_prefix = "label = '价格'; ".encode() + dynamic
        assert SecretScanner.scan_bytes(unicode_prefix, python_source=True) == ()


class TestRepositoryScan:
    """Validate bounded repository paths before running the external scanner."""

    @pytest.mark.parametrize(
        ("filename", "prefix", "suffix"),
        [
            ("config.json", b'{"api_key": "', b'"}'),
            ("config.py", b"{'password': '", b"'}"),
            ("config.yaml", b'"client-secret": ', b"\n"),
            ("config.toml", b"'token' = '", b"'\n"),
        ],
    )
    def test_repository_scan_rejects_quoted_credentials(
        self, tmp_path: Path, filename: str, prefix: bytes, suffix: bytes
    ) -> None:
        """Reject quoted credential assignments without disclosing their values."""
        credential = b"A" * 24
        payload = prefix + credential + suffix
        assert SecretScanner.scan_bytes(payload) == ("assigned_credential",)
        (tmp_path / filename).write_bytes(payload)

        with pytest.raises(CIPolicyError, match="assigned_credential") as caught:
            SecretScanner.scan_paths(tmp_path, (filename,))

        assert filename in str(caught.value)
        assert credential.decode() not in str(caught.value)

    def test_secret_scan_rejects_unsafe_and_oversized_paths(self, tmp_path: Path) -> None:
        """Reject paths that escape the root, resolve through links, or exceed the bound."""
        secret = tmp_path / "secret.txt"
        secret.write_bytes(b"api_key=" + b"A" * 24)
        with pytest.raises(CIPolicyError, match="secret pattern"):
            SecretScanner.scan_paths(tmp_path, ("secret.txt",), maximum_file_bytes=100)

        oversized = tmp_path / "oversized.txt"
        oversized.write_bytes(b"x" * 101)
        with pytest.raises(CIPolicyError, match="exceeds 100 bytes"):
            SecretScanner.scan_paths(tmp_path, ("oversized.txt",), maximum_file_bytes=100)

        link = tmp_path / "linked.txt"
        link.symlink_to(secret)
        with pytest.raises(CIPolicyError, match="non-regular path"):
            SecretScanner.scan_paths(tmp_path, ("linked.txt",), maximum_file_bytes=100)
        broken_link = tmp_path / "broken.txt"
        broken_link.symlink_to(tmp_path / "missing.txt")
        with pytest.raises(CIPolicyError, match="non-regular path"):
            SecretScanner.scan_paths(tmp_path, ("broken.txt",), maximum_file_bytes=100)
        with pytest.raises(CIPolicyError, match="repository-relative"):
            SecretScanner.scan_paths(tmp_path, ("../outside.txt",), maximum_file_bytes=100)

    def test_repository_scan_passes_only_existing_normalized_files_to_external_scanner(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Scan each surviving file once and skip deletions before invoking the tool."""
        (tmp_path / "tracked.txt").write_text("safe content\n", encoding="utf-8")
        recorder = ScanRecorder()

        monkeypatch.setattr(SecretScanner, "run_external", recorder)
        SecretScanner.scan_paths(tmp_path, ("tracked.txt", "deleted.txt", "tracked.txt"))

        assert recorder.calls == [(tmp_path.resolve(), ("tracked.txt",))]


class TestExternalScanner:
    """Propagate every external scanner failure and use shell-free argv."""

    def test_external_scanner_failure_is_propagated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Treat a nonzero detect-private-key result as a blocking CI failure."""
        monkeypatch.setattr(subprocess, "run", ProcessDouble(returncode=2))
        with pytest.raises(CIPolicyError, match="failed with exit 2"):
            SecretScanner.run_external(tmp_path, ("tracked.txt",))

    def test_external_scanner_start_failure_is_propagated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Treat an unavailable detect-private-key executable as a blocking CI failure."""
        monkeypatch.setattr(
            subprocess, "run", ProcessDouble(error=FileNotFoundError("detect-private-key"))
        )
        with pytest.raises(CIPolicyError, match="could not start"):
            SecretScanner.run_external(tmp_path, ("tracked.txt",))

    def test_external_scanner_uses_shell_free_argv(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Pass validated paths to detect-private-key as separate argv tokens."""
        process = ProcessDouble()
        monkeypatch.setattr(subprocess, "run", process)
        SecretScanner.run_external(tmp_path, ("a.txt", "b.txt"))

        assert process.calls == [
            (
                (["detect-private-key", "--", "a.txt", "b.txt"],),
                {"cwd": tmp_path, "check": False},
            )
        ]


class TestSecretScanCommand:
    """Map command scopes and failures to exit statuses."""

    @staticmethod
    def tracked_paths(_root: Path) -> tuple[str, ...]:
        """Supply one tracked path without invoking Git in this CLI contract test."""
        return ("tracked.txt",)

    def test_cli_rejects_empty_scan_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Return a nonzero status when the secret-scan CLI has no scope."""
        assert ci_policy.main(["scan-secrets"]) == 1
        assert "scan-secrets accepts" in capsys.readouterr().err

    def test_cli_accepts_the_make_all_scan_invocation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Accept the exact ``alpha-governance-ci scan-secrets --all`` command used by Make."""
        recorder = ScanRecorder()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(SecretScanCommand, "tracked_paths", self.tracked_paths)
        monkeypatch.setattr(SecretScanner, "scan_paths", recorder)

        assert ci_policy.main(["scan-secrets", "--all"]) == 0
        assert [paths for _, paths in recorder.calls] == [("tracked.txt",)]
        assert "passed for 1 governed paths" in capsys.readouterr().out

    def test_cli_propagates_external_scanner_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Return a nonzero CLI status when the external scanner fails."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            SecretScanner,
            "scan_paths",
            ScanRecorder(CIPolicyError(["private-key scanner failed with exit 2"])),
        )
        assert ci_policy.main(["scan-secrets", "tracked.txt"]) == 1
        assert "failed with exit 2" in capsys.readouterr().err

    def test_cli_reports_git_failure_from_one_error_boundary(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Fail closed when tracked paths cannot be obtained from Git."""
        monkeypatch.chdir(tmp_path)

        assert ci_policy.main(["scan-secrets", "--all"]) == 1
        assert "CI secret scan failed" in capsys.readouterr().err
