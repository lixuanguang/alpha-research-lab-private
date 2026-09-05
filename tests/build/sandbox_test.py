"""Prove that undeclared repository and host inputs are absent from Bazel runfiles."""

from __future__ import annotations

# standard library imports
import os
import sys
from pathlib import Path


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
    runfiles = Path(os.environ["TEST_SRCDIR"]) / os.environ["TEST_WORKSPACE"]
    undeclared_inputs = (
        runfiles / "docs" / "README.md",
        runfiles / "secrets" / "polymarket.secrets",
        runfiles / ".git" / "config",
    )
    visible = [str(path) for path in undeclared_inputs if path.exists()]
    if visible:
        print(f"undeclared inputs leaked into the sandbox: {visible}", file=sys.stderr)
        return 1
    if "UNDECLARED_HOST_SECRET" in os.environ:
        print("undeclared host environment leaked into the sandbox", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
