"""Exercise direct Python source standards findings."""

from __future__ import annotations

# standard library imports
from pathlib import Path
from textwrap import dedent

# third party library imports
import pytest

# project library imports
from alpha_research_governance.engineering_standards.python_standards import (
    PythonStandardsChecker,
)


class TestPythonStandards:
    """Verify source discovery, direct findings and fail-closed errors."""

    @staticmethod
    def _checker() -> PythonStandardsChecker:
        """Use an explicit source scope for isolated scanner fixtures."""
        return PythonStandardsChecker(source_roots=("src",))

    def test_source_discovery_includes_untracked_py_and_pyi_files(self, tmp_path: Path) -> None:
        """Scan both supported suffixes without requiring a debt inventory or Git metadata."""
        source = tmp_path / "src"
        source.mkdir()
        (source / "new.py").write_text("value = 1\n", encoding="utf-8")
        (source / "new.pyi").write_text("def malformed(:\n", encoding="utf-8")

        findings = self._checker().findings(tmp_path)

        assert any("src/new.py" in finding and "PYD001" in finding for finding in findings)
        assert any("src/new.pyi" in finding and "PYS001" in finding for finding in findings)

    def test_diagnostic_identity_retains_repeated_occurrences(self, tmp_path: Path) -> None:
        """Group repeated line-level findings by their stable source diagnostic identity."""
        source = tmp_path / "src"
        source.mkdir()
        (source / "any.py").write_text(
            '"""Any fixture."""\n\n'
            "# standard library imports\n"
            "from typing import Any\n\n"
            "items: tuple[Any, Any]\n",
            encoding="utf-8",
        )

        findings = self._checker().findings(tmp_path)

        assert any(
            "src/any.py:<module>: PYT001 variable:items (occurrences: 2)" == finding
            for finding in findings
        )

    def test_syntax_and_filesystem_errors_fail_closed(self, tmp_path: Path) -> None:
        """Return controlled diagnostics for invalid source and unavailable source roots."""
        missing = self._checker().findings(tmp_path)
        assert missing == ("Python standards scanner: missing Python standards source root: src",)

        source = tmp_path / "src"
        source.mkdir()
        (source / "malformed.py").write_text("def malformed(:\n", encoding="utf-8")

        findings = self._checker().findings(tmp_path)

        assert findings == ("src/malformed.py:<module>: PYS001 tokenization",)

    def test_invalid_utf8_fails_closed(self, tmp_path: Path) -> None:
        """Return a scanner diagnostic rather than silently skipping undecodable source."""
        source = tmp_path / "src"
        source.mkdir()
        (source / "invalid.py").write_bytes(b"value = '\xff'\n")

        findings = self._checker().findings(tmp_path)

        assert findings[0].startswith("Python standards scanner:")

    def test_documented_ordinary_function_is_accepted(self, tmp_path: Path) -> None:
        """Allow a documented ordinary function without registration or ownership metadata."""
        source = tmp_path / "src"
        source.mkdir()
        (source / "functions.py").write_text(
            dedent(
                '''
                """Ordinary function fixture."""

                def parse(value: str) -> str:
                    """Return the normalized value.

                    Args:
                        value: Value to normalize.

                    Returns:
                        The normalized value.
                    """
                    return value.strip()
                '''
            ),
            encoding="utf-8",
        )

        assert self._checker().findings(tmp_path) == ()

    def test_retained_source_rules_remain_blocking(self, tmp_path: Path) -> None:
        """Report explicit Any and import-heading violations directly."""
        source = tmp_path / "src"
        source.mkdir()
        (source / "protected.py").write_text(
            '"""Protected rule fixture."""\n\nfrom typing import Any\n\nvalue: Any\n',
            encoding="utf-8",
        )

        findings = self._checker().findings(tmp_path)

        assert any("PYI001" in finding for finding in findings)
        assert any("PYT001" in finding for finding in findings)


if __name__ == "__main__":
    raise SystemExit(
        pytest.main([__file__, str(Path(__file__).with_name("test_python_source_standards.py"))])
    )
