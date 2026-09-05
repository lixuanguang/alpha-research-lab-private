"""Verify deterministic SQL template output against a retained golden file."""

from __future__ import annotations

# standard library imports
import os
import sys
from pathlib import Path


def main() -> int:
    """Compare generated SQL with its retained golden output.

    Resolve the Bazel runfiles directory from the ``TEST_SRCDIR`` and
    ``TEST_WORKSPACE`` environment variables, then read the generated and expected
    SQL files as UTF-8 text. It writes a diagnostic to standard error only when
    the texts differ or an unresolved ``@@`` substitution remains.

    Returns:
        ``0`` when the generated SQL matches the expected text and contains no
        unresolved substitution; ``1`` after reporting a mismatch or unresolved
        substitution to standard error.

    Raises:
        KeyError: If ``TEST_SRCDIR`` or ``TEST_WORKSPACE`` is unset.
        OSError: If either SQL file cannot be read.
        UnicodeDecodeError: If either SQL file is not valid UTF-8.
    """
    root = Path(os.environ["TEST_SRCDIR"]) / os.environ["TEST_WORKSPACE"]
    package = root / "tests" / "build" / "fixtures" / "sql"
    generated = (package / "build_evidence.sql").read_text(encoding="utf-8")
    expected = (package / "build_evidence.expected.sql").read_text(encoding="utf-8")
    if generated != expected:
        print("generated SQL differs from the retained golden file", file=sys.stderr)
        return 1
    if "@@" in generated:
        print("generated SQL contains an unresolved substitution", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
