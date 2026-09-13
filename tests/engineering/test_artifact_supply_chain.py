"""Exercise the retained artifact command boundary."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.artifact_supply_chain import main

REPOSITORY_ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("arguments", ((), ("unknown",), ("release-check", "extra")))
def test_unknown_or_malformed_commands_fail(
    arguments: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reject unsupported command shapes without entering a release path."""
    monkeypatch.chdir(REPOSITORY_ROOT)

    assert main(arguments) == 2

    captured = capsys.readouterr()
    assert "usage: alpha-governance-artifacts" in captured.err


def test_release_check_uses_the_current_quantlib_admission_block(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Keep unresolved QuantLib release admission ahead of consumer checks."""
    monkeypatch.chdir(REPOSITORY_ROOT)

    assert main(["release-check"]) == 1

    captured = capsys.readouterr()
    assert "unresolved native dependency admission" in captured.err


def test_release_check_stays_blocked_without_a_trusted_consumer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Keep the future release path closed after dependency admission is resolved."""
    monkeypatch.chdir(REPOSITORY_ROOT)

    def allow(_root: Path) -> None:
        """Model a future successful dependency release admission.

        Args:
            _root: Repository root supplied to the dependency admission gate.
        """

    monkeypatch.setattr(
        "alpha_research_governance.artifact_supply_chain.require_release_admission",
        allow,
    )

    assert main(["release-check"]) == 1

    captured = capsys.readouterr()
    assert "no trusted release consumer" in captured.err


def test_release_check_does_not_write_when_admission_rejects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Stop before any output when the delegated dependency gate rejects release use."""
    monkeypatch.chdir(tmp_path)
    calls: list[Path] = []

    def reject(repository_root: Path) -> None:
        """Record the repository passed to the release gate and reject it.

        Args:
            repository_root: Repository root supplied to the dependency admission gate.

        Raises:
            ValueError: Always, to model a dependency admission failure.
        """
        calls.append(repository_root)
        raise ValueError("dependency admission rejected release")

    monkeypatch.setattr(
        "alpha_research_governance.artifact_supply_chain.require_release_admission", reject
    )

    assert main(["release-check"]) == 1

    captured = capsys.readouterr()
    assert calls == [tmp_path]
    assert "dependency admission rejected release" in captured.err
    assert list(tmp_path.iterdir()) == []


def test_release_check_delegates_admission_before_no_consumer_rejection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Call dependency admission before applying the future no-consumer restriction."""
    monkeypatch.chdir(REPOSITORY_ROOT)
    calls: list[Path] = []

    def allow(repository_root: Path) -> None:
        """Record a successful dependency release admission.

        Args:
            repository_root: Repository root supplied to the dependency admission gate.
        """
        calls.append(repository_root)

    monkeypatch.setattr(
        "alpha_research_governance.artifact_supply_chain.require_release_admission", allow
    )

    assert main(["release-check"]) == 1

    captured = capsys.readouterr()
    assert calls == [REPOSITORY_ROOT]
    assert "no trusted release consumer" in captured.err


def test_release_check_fails_without_repository_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reject missing admission inputs without creating artifacts."""
    monkeypatch.chdir(tmp_path)

    assert main(["release-check"]) == 1

    assert "dependency-admission.toml" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
