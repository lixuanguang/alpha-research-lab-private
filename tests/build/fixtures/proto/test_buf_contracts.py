"""Contract tests for the Buf compatibility and toolchain checkers."""

from __future__ import annotations

# standard library imports
import subprocess
from collections.abc import Mapping
from pathlib import Path

# third party library imports
import pytest
from buf_compatibility_test import BufCompatibilityCheck
from buf_toolchain_test import BufToolchainCheck


class TestBufCompatibilityCheck:
    """Verify compatibility workflow state, child isolation, and cleanup."""

    def test_repeat_calls_preserve_child_environment_and_cleanup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Run one checker twice with isolated temporary module trees."""
        config = tmp_path / "buf.yaml"
        proto = tmp_path / "toolchain_probe.proto"
        config.write_text("version: v2\n", encoding="utf-8")
        proto.write_text(
            'syntax = "proto3";\nmessage Probe {\n  string target = 1;\n}\n',
            encoding="utf-8",
        )
        executable = tmp_path / "buf"
        calls: list[tuple[list[str], Path, Mapping[str, str]]] = []

        def fake_run(
            command: list[str],
            *,
            env: Mapping[str, str],
            check: bool,
            capture_output: bool,
            text: bool,
        ) -> subprocess.CompletedProcess[str]:
            """Capture Buf's command boundary and model expected statuses.

            Args:
                command: Buf executable and breaking-analysis arguments.
                env: Child environment supplied to the Buf invocation.
                check: Whether subprocess failures should raise automatically.
                capture_output: Whether child output streams are captured.
                text: Whether child output is decoded as text.

            Returns:
                A completed process with the expected additive or breaking status.
            """
            assert check is False
            assert capture_output is True
            assert text is True
            module = Path(command[2])
            calls.append((command, module.parent, env))
            return subprocess.CompletedProcess(
                command,
                1 if module.name == "breaking" else 0,
                stdout="",
                stderr="",
            )

        monkeypatch.setattr(
            "buf_compatibility_test.subprocess.run",
            fake_run,
        )
        checker = BufCompatibilityCheck(
            _buf=executable,
            _config=config,
            _proto=proto,
        )

        assert checker.run() == 0
        assert checker.run() == 0

        assert len(calls) == 4
        for command, temporary, environment in calls:
            assert command[0] == str(executable)
            assert command[1] == "breaking"
            assert command[3] == "--against"
            assert environment == {
                "BUF_CACHE_DIR": str(temporary / "cache"),
                "HOME": str(temporary / "home"),
                "LC_ALL": "C.UTF-8",
                "PATH": "",
                "TZ": "UTC",
            }
            assert not temporary.exists()


class TestBufToolchainCheck:
    """Verify subprocess failure propagation and temporary cleanup."""

    def test_child_failure_preserves_diagnostic_and_cleans_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raise the existing runtime error after a failing lint subprocess."""
        executable = tmp_path / "buf"
        package = tmp_path / "package"
        package.mkdir()
        calls: list[tuple[list[str], Path, Mapping[str, str]]] = []

        def fake_run(
            command: list[str],
            *,
            cwd: Path,
            env: Mapping[str, str],
            check: bool,
            capture_output: bool,
            text: bool,
        ) -> subprocess.CompletedProcess[str]:
            """Capture the first child invocation and return a lint failure.

            Args:
                command: Buf executable and lint arguments.
                cwd: Working directory supplied to the child process.
                env: Child environment supplied to the Buf invocation.
                check: Whether subprocess failures should raise automatically.
                capture_output: Whether child output streams are captured.
                text: Whether child output is decoded as text.

            Returns:
                A completed process representing a failed lint command.
            """
            assert check is False
            assert capture_output is True
            assert text is True
            calls.append((command, cwd, env))
            return subprocess.CompletedProcess(
                command,
                7,
                stdout="lint output",
                stderr="lint diagnostic",
            )

        monkeypatch.setattr("buf_toolchain_test.subprocess.run", fake_run)
        checker = BufToolchainCheck(_buf=executable, _package=package)

        with pytest.raises(RuntimeError, match="lint outputlint diagnostic"):
            checker.run()

        assert len(calls) == 1
        command, cwd, environment = calls[0]
        temporary = Path(environment["HOME"]).parent
        assert command == [str(executable), "lint", "."]
        assert cwd == package
        assert environment == {
            "BUF_CACHE_DIR": str(temporary / "cache"),
            "HOME": str(temporary / "home"),
            "LC_ALL": "C.UTF-8",
            "PATH": "",
            "TZ": "UTC",
        }
        assert not temporary.exists()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
