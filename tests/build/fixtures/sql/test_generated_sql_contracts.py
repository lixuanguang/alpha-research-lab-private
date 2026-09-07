"""Contract tests for deterministic generated-SQL verification."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# third party library imports
import pytest
from generated_sql_test import GeneratedSqlCheck


class TestGeneratedSqlCheck:
    """Verify SQL mismatch, unresolved-substitution, and repeat-call behavior."""

    def test_matching_output_can_be_checked_repeatedly(self, tmp_path: Path) -> None:
        """Allow one checker instance to validate stable output more than once."""
        generated = tmp_path / "generated.sql"
        expected = tmp_path / "expected.sql"
        generated.write_text("SELECT 1;\n", encoding="utf-8")
        expected.write_text("SELECT 1;\n", encoding="utf-8")

        checker = GeneratedSqlCheck(_generated=generated, _expected=expected)

        assert checker.run() == 0
        assert checker.run() == 0

    def test_mismatch_reports_golden_diagnostic(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Return failure and preserve the existing mismatch diagnostic."""
        generated = tmp_path / "generated.sql"
        expected = tmp_path / "expected.sql"
        generated.write_text("SELECT 2;\n", encoding="utf-8")
        expected.write_text("SELECT 1;\n", encoding="utf-8")

        assert GeneratedSqlCheck(_generated=generated, _expected=expected).run() == 1
        assert capsys.readouterr().err == "generated SQL differs from the retained golden file\n"

    def test_unresolved_substitution_reports_diagnostic(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Reject an otherwise matching SQL file with an unresolved marker."""
        generated = tmp_path / "generated.sql"
        expected = tmp_path / "expected.sql"
        generated.write_text("SELECT @@TABLE_NAME@@;\n", encoding="utf-8")
        expected.write_text("SELECT @@TABLE_NAME@@;\n", encoding="utf-8")

        assert GeneratedSqlCheck(_generated=generated, _expected=expected).run() == 1
        assert capsys.readouterr().err == "generated SQL contains an unresolved substitution\n"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
