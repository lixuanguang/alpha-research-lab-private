"""Enforce Python source findings directly."""

from __future__ import annotations

# standard library imports
from collections import Counter
from collections.abc import Callable
from pathlib import Path

# project library imports
from alpha_research_governance.engineering_standards.python_source import (
    PythonFinding,
    PythonSourceChecker,
)

DEFAULT_SOURCE_ROOTS = (
    "src",
    "tests",
    "tools/governance/src",
    "tools/typing/stubs",
    "examples",
    "extensions",
)
# Research extensions are optional; a repository may have none.
OPTIONAL_SOURCE_ROOTS = frozenset({"extensions"})


class PythonStandardsChecker:
    """Scan governed Python source files and return direct diagnostics."""

    def __init__(self, *, source_roots: tuple[str, ...]) -> None:
        """Capture the repository-relative roots to scan.

        Args:
            source_roots: Roots scanned recursively for Python source files.
        """
        self._source_roots = source_roots

    def findings(
        self,
        repository_root: Path,
        *,
        source_observer: Callable[[str, str], tuple[str, ...]] | None = None,
    ) -> tuple[str, ...]:
        """Scan every governed Python file, including untracked files.

        Args:
            repository_root: Repository or fixture containing the source roots.
            source_observer: Optional callback receiving each relative path and source text.

        Returns:
            Deterministic diagnostics, or one fail-closed scanner diagnostic.
        """
        observed: list[PythonFinding] = []
        auxiliary: list[str] = []
        try:
            for source_root in self._source_roots:
                root = repository_root / source_root
                if source_root in OPTIONAL_SOURCE_ROOTS and not root.exists():
                    continue
                if not root.is_dir():
                    return (
                        "Python standards scanner: missing Python standards source root: "
                        f"{source_root}",
                    )
                for path in sorted(root.rglob("*")):
                    if path.is_file() and path.suffix in {".py", ".pyi"}:
                        relative = path.relative_to(repository_root).as_posix()
                        text = path.read_text(encoding="utf-8")
                        observed.extend(PythonSourceChecker().scan(relative, text))
                        if source_observer is not None:
                            auxiliary.extend(source_observer(relative, text))
            counts = Counter(finding.key for finding in observed)
            rendered = tuple(
                f"{path}:{symbol}: {rule} {detail}"
                + (f" (occurrences: {count})" if count > 1 else "")
                for (path, symbol, rule, detail), count in sorted(counts.items())
            )
            return (*rendered, *auxiliary)
        except (OSError, UnicodeError, ValueError) as error:
            return (f"Python standards scanner: {error}",)
