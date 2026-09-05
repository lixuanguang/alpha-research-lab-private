"""Prove that undeclared repository and host inputs are absent from Bazel runfiles."""

from __future__ import annotations

# standard library imports
import os
import sys
from pathlib import Path


def main() -> int:
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
