"""Reject runtime wording that marks retained old-format behaviour."""

from __future__ import annotations

# standard library imports
import re
from pathlib import Path
from typing import ClassVar


class FormatCompatibilityChecker:
    """Scan runtime source text for words that label kept old-format readers or paths.

    Format changes replace the old format in place. Old data is refused with an
    "unsupported ... schema" error, so runtime source has no reason to describe
    anything as kept for an earlier format.
    """

    _ROOT: ClassVar[str] = "src"
    # Assembled from parts so this checker's own source never matches the rule.
    _WORDING: ClassVar[re.Pattern[str]] = re.compile(
        "|".join(("leg" + "acy", "backward" + ".?" + "compat")), re.IGNORECASE
    )

    @classmethod
    def findings(cls, repository_root: Path) -> tuple[str, ...]:
        """Report every runtime text line that labels old-format compatibility.

        Args:
            repository_root: Repository containing the ``src`` runtime root.

        Returns:
            Stable ``path:line`` findings; binary files and a missing root yield none.
        """
        root = repository_root / cls._ROOT
        if not root.is_dir():
            return ()
        findings: list[str] = []
        try:
            for path in sorted(root.rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                relative = path.relative_to(repository_root).as_posix()
                findings.extend(
                    f"{relative}:{number}: format changes replace in place; "
                    "remove old-format compatibility wording and code"
                    for number, line in enumerate(text.splitlines(), 1)
                    if cls._WORDING.search(line)
                )
        except OSError as error:
            findings.append(f"format compatibility: {error}")
        return tuple(findings)
