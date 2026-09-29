"""Reject runtime wording and names that mark retained old-format behaviour."""

from __future__ import annotations

# standard library imports
import re
from pathlib import Path
from typing import ClassVar


class FormatCompatibilityChecker:
    """Scan owned text for old-format wording and revision-suffixed internal names.

    Format changes replace the old format in place. Old data is refused with an
    "unsupported ... schema" error, so runtime source has no reason to describe
    anything as kept for an earlier format, and names carry no ``_vN``/``-vN``
    revision suffix. External API references are listed explicitly.
    """

    _WORDING_ROOTS: ClassVar[tuple[str, ...]] = ("src",)
    _NAME_ROOTS: ClassVar[tuple[str, ...]] = ("src", "tools", "tests", "configs")
    # Assembled from parts so this checker's own source never matches its rules.
    _WORDING: ClassVar[re.Pattern[str]] = re.compile(
        "|".join(("leg" + "acy", "backward" + ".?" + "compat")), re.IGNORECASE
    )
    _SUFFIX: ClassVar[re.Pattern[str]] = re.compile(
        r"[A-Za-z0-9][A-Za-z0-9_-]*[_-]" + "v" + r"\d+\b"
    )
    # External names owned by third parties, such as OKX's versioned API documentation path.
    _EXTERNAL: ClassVar[frozenset[str]] = frozenset({"docs-" + "v5"})

    @classmethod
    def findings(cls, repository_root: Path) -> tuple[str, ...]:
        """Report old-format wording in runtime text and suffixed names in owned files.

        Args:
            repository_root: Repository containing the governed roots.

        Returns:
            Stable ``path:line`` findings; binary files and missing roots yield none.
        """
        findings: list[str] = []
        try:
            for relative, number, line in cls._lines(repository_root, cls._WORDING_ROOTS):
                if cls._WORDING.search(line):
                    findings.append(
                        f"{relative}:{number}: format changes replace in place; "
                        "remove old-format compatibility wording and code"
                    )
            for relative, number, line in cls._lines(repository_root, cls._NAME_ROOTS):
                for match in cls._SUFFIX.finditer(line):
                    if match.group(0) not in cls._EXTERNAL:
                        findings.append(
                            f"{relative}:{number}: internal name {match.group(0)} carries a "
                            "revision suffix; name the format for what it is"
                        )
        except OSError as error:
            findings.append(f"format compatibility: {error}")
        return tuple(findings)

    @staticmethod
    def _lines(repository_root: Path, roots: tuple[str, ...]) -> list[tuple[str, int, str]]:
        """Read every UTF-8 text line under the selected roots in stable order."""
        lines: list[tuple[str, int, str]] = []
        for name in roots:
            root = repository_root / name
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                parts = path.relative_to(repository_root).parts
                # Hidden directories hold local environments and caches, not owned text.
                if (
                    not path.is_file()
                    or "__pycache__" in parts
                    or any(part.startswith(".") for part in parts)
                ):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                relative = "/".join(parts)
                lines.extend(
                    (relative, number, line) for number, line in enumerate(text.splitlines(), 1)
                )
        return lines
