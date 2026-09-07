"""Prove that undeclared repository and host inputs are absent from Bazel runfiles."""

from __future__ import annotations

# standard library imports
import os
import sys
from collections.abc import Mapping
from pathlib import Path


class SandboxInputCheck:
    """Check selected runfiles and host environment inputs for leakage."""

    _runfiles: Path
    _environment: Mapping[str, str]

    def __init__(self, *, _runfiles: Path, _environment: Mapping[str, str]) -> None:
        """Initialize a check with explicit runfiles and environment context.

        Args:
            _runfiles: Workspace root within the Bazel runfiles tree.
            _environment: Environment mapping used to detect host leakage.
        """
        self._runfiles = _runfiles
        self._environment = _environment

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> SandboxInputCheck:
        """Build a check from the Bazel runfiles environment.

        Args:
            environment: Environment mapping containing the Bazel runfiles variables.

        Returns:
            A check rooted at the workspace's runfiles directory.

        Raises:
            KeyError: If ``TEST_SRCDIR`` or ``TEST_WORKSPACE`` is unset.
        """
        runfiles = Path(environment["TEST_SRCDIR"]) / environment["TEST_WORKSPACE"]
        return cls(_runfiles=runfiles, _environment=environment)

    def run(self) -> int:
        """Check selected undeclared paths and the host secret sentinel.

        Returns:
            ``0`` when all selected inputs are absent; ``1`` after reporting a leak.
        """
        undeclared_inputs = (
            self._runfiles / "docs" / "README.md",
            self._runfiles / "secrets" / "polymarket.secrets",
            self._runfiles / ".git" / "config",
        )
        visible = [str(path) for path in undeclared_inputs if path.exists()]
        if visible:
            print(f"undeclared inputs leaked into the sandbox: {visible}", file=sys.stderr)
            return 1
        if "UNDECLARED_HOST_SECRET" in self._environment:
            print("undeclared host environment leaked into the sandbox", file=sys.stderr)
            return 1
        return 0


def main() -> int:
    """Check that selected undeclared paths and a host secret sentinel are absent.

    Resolve the Bazel runfiles directory from the ``TEST_SRCDIR`` and
    ``TEST_WORKSPACE`` environment variables, then check whether
    ``docs/README.md``, ``secrets/polymarket.secrets``, or ``.git/config`` exists
    and whether the ``UNDECLARED_HOST_SECRET`` sentinel is present in the
    environment. It writes a diagnostic to standard error only when one of those
    checks detects a leak and does not modify files or environment variables.

    Returns:
        ``0`` when all three selected paths are absent and the sentinel is not
        present; ``1`` after reporting a leak to standard error.

    Raises:
        KeyError: If ``TEST_SRCDIR`` or ``TEST_WORKSPACE`` is unset.
    """
    return SandboxInputCheck.from_environment(os.environ).run()


if __name__ == "__main__":
    raise SystemExit(main())
