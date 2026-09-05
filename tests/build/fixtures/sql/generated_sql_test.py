"""Verify deterministic SQL template output against a retained golden file."""

from __future__ import annotations

# standard library imports
import os
import sys
from pathlib import Path


def main() -> int:
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
