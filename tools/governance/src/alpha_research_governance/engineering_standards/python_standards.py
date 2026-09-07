"""Enforce Python source findings directly."""

from __future__ import annotations

# standard library imports
from collections import Counter
from pathlib import Path

# project library imports
from alpha_research_governance.engineering_standards.python_source import (
    PythonFinding,
    PythonSourceChecker,
)


class PythonStandardsChecker:
    """Scan governed Python source files and return direct diagnostics."""

    def __init__(self, *, source_roots: tuple[str, ...]) -> None:
        """Capture the repository-relative roots to scan.

        Args:
            source_roots: Roots scanned recursively for Python source files.
        """
        self._source_roots = source_roots

    def findings(self, repository_root: Path) -> tuple[str, ...]:
        """Scan all governed Python files, including files not tracked by Git.

        Args:
            repository_root: Repository or fixture containing the source roots.

        Returns:
            Deterministic direct diagnostics, or one fail-closed scanner diagnostic.
        """
        try:
            return self._format_findings(self._scan(repository_root))
        except (OSError, UnicodeError, ValueError) as error:
            return (f"Python standards scanner: {error}",)

    def _scan(self, repository_root: Path) -> tuple[PythonFinding, ...]:
        """Scan every Python source file in source-root and path order."""
        observed: list[PythonFinding] = []
        scanner = PythonSourceChecker()
        for source_root in self._source_roots:
            root = repository_root / source_root
            if not root.is_dir():
                raise ValueError(f"missing Python standards source root: {source_root}")
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.suffix not in {".py", ".pyi"}:
                    continue
                relative = path.relative_to(repository_root).as_posix()
                observed.extend(scanner.scan(relative, path.read_text(encoding="utf-8")))
        return tuple(observed)

    @staticmethod
    def _format_findings(observed: tuple[PythonFinding, ...]) -> tuple[str, ...]:
        """Render stable diagnostic identities while retaining repeated occurrences."""
        counts = Counter(finding.key for finding in observed)
        rendered: list[str] = []
        for (path, symbol, rule, detail), count in sorted(counts.items()):
            message = f"{path}:{symbol}: {rule} {detail}"
            if count > 1:
                message += f" (occurrences: {count})"
            rendered.append(message)
        return tuple(rendered)
