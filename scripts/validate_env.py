#!/usr/bin/env python3
"""Validate that the development environment has all required dependencies."""

from __future__ import annotations

import sys

REQUIRED_PYTHON = (3, 11)

REQUIRED_PACKAGES: list[str] = [
    "pmxt",
    "pydantic",
    "pydantic_settings",
    "pyarrow",
    "duckdb",
    "yaml",  # pyyaml
    "click",
    "structlog",
    "dotenv",  # python-dotenv
    "ruff",
    "mypy",
    "pytest",
]


def check_python_version() -> bool:
    """Return True if the running Python version meets the minimum."""
    current = sys.version_info[:2]
    if current < REQUIRED_PYTHON:
        print(
            f"FAIL: Python {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}+ required, "
            f"got {current[0]}.{current[1]}"
        )
        return False
    print(f"  OK: Python {current[0]}.{current[1]}")
    return True


def check_package(name: str) -> bool:
    """Return True if *name* is importable."""
    try:
        __import__(name)
        print(f"  OK: {name}")
    except ImportError:
        print(f"FAIL: {name} not importable")
        return False
    return True


def main() -> None:
    print("=== Environment Validation ===\n")

    ok = check_python_version()
    print()

    for pkg in REQUIRED_PACKAGES:
        ok = check_package(pkg) and ok

    # Check alpha_core itself
    print()
    try:
        import alpha_core

        print(f"  OK: alpha_core {alpha_core.__version__}")
    except ImportError:
        print("FAIL: alpha_core not importable (run `pip install -e '.[dev]'`)")
        ok = False

    print()
    if ok:
        print("All checks passed.")
    else:
        print("Some checks FAILED — see above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
