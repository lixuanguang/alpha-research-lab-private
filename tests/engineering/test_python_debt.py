"""Exercise source findings and source-bound design exceptions."""

from __future__ import annotations

# standard library imports
import ast
from datetime import date, timedelta
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.engineering_standards.python_debt import (
    EXCEPTIONS_PATH,
    PythonException,
    PythonExceptions,
    PythonStandardsChecker,
    SourceIdentity,
)
from alpha_research_governance.engineering_standards.python_source import PythonFinding

TODAY = date(2026, 9, 5)
OWNERS = frozenset({"platform"})


class TestPythonDebt:
    """Reject unwaived source findings without a migration baseline."""

    @staticmethod
    def _checker() -> PythonStandardsChecker:
        """Use an explicit source scope, owner set and validation date."""
        return PythonStandardsChecker(
            source_roots=("src",), owner_roles=OWNERS, validation_date=TODAY
        )

    def test_source_checker_does_not_require_retired_debt_inventory(self, tmp_path: Path) -> None:
        """Scan source and report current findings when the empty inventory is absent."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src/new.py").write_text("value = 1\n", encoding="utf-8")
        (tmp_path / EXCEPTIONS_PATH).parent.mkdir(parents=True)
        (tmp_path / EXCEPTIONS_PATH).write_text(
            "schema_version = 1\nexceptions = []\n", encoding="utf-8"
        )

        findings = self._checker().findings(tmp_path)

        assert any("PYD001" in message for message in findings)

    def test_source_failure_and_new_files_fail_closed(self, tmp_path: Path) -> None:
        """Discover new source and preserve syntax diagnostics without Git metadata."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src/new.py").write_text("def malformed(:\n", encoding="utf-8")
        (tmp_path / EXCEPTIONS_PATH).parent.mkdir(parents=True)
        (tmp_path / EXCEPTIONS_PATH).write_text(
            "schema_version = 1\nexceptions = []\n", encoding="utf-8"
        )

        assert any("PYS001" in message for message in self._checker().findings(tmp_path))

    def test_absent_or_malformed_exception_policy_fails_with_a_diagnostic(
        self, tmp_path: Path
    ) -> None:
        """Never interpret an unavailable exception register as permission to skip checks."""
        missing = self._checker().findings(tmp_path)
        assert "Python standards policy" in missing[0]

        path = tmp_path / EXCEPTIONS_PATH
        path.parent.mkdir(parents=True)
        path.write_text("{invalid", encoding="utf-8")
        malformed = self._checker().findings(tmp_path)
        assert "Python standards policy" in malformed[0]

    def test_line_changes_do_not_change_exception_identity(self) -> None:
        """Keep exceptions tied to source definitions instead of line numbers."""
        old = PythonFinding(
            path="src/a.py", symbol="parse", rule="PYC001", detail="standalone", line=1
        )
        exception = TestPythonExceptions._exception()
        shifted = PythonFinding(
            path=old.path,
            symbol=old.symbol,
            rule=old.rule,
            detail=old.detail,
            line=100,
        )
        fingerprint = {("src/a.py", "parse"): "a" * 64}
        policy = PythonExceptions(schema_version=1, exceptions=[exception])

        assert self._checker().reconcile(policy, (shifted,), fingerprint) == ()

    def test_unwaived_and_duplicate_findings_remain_blocking(self) -> None:
        """Preserve multiplicity and report findings not discharged by one exception."""
        item = PythonFinding(
            path="src/a.py", symbol="f", rule="PYT001", detail="annotation:Any", line=1
        )
        result = self._checker().reconcile(
            PythonExceptions(schema_version=1, exceptions=[]), (item, item), {}
        )

        assert len(result) == 1
        assert "PYT001" in result[0]
        assert "occurrences: 2" in result[0]


class TestPythonExceptions:
    """Require exact scope, valid ownership, bounded lifetime and unchanged source."""

    @staticmethod
    def _exception(**updates: object) -> PythonException:
        """Construct a valid low-level exception with explicit optional mutations."""
        values: dict[str, object] = {
            "path": "src/a.py",
            "symbol": "parse",
            "rule": "PYC001",
            "detail": "standalone",
            "kind": "low_level",
            "owner_role": "platform",
            "rationale": "Parse one primitive value without state or external dependencies.",
            "expires": TODAY + timedelta(days=30),
            "source_sha256": "a" * 64,
        }
        values.update(updates)
        return PythonException.model_validate(values)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("owner_role", "unknown"),
            ("rationale", " " * 15),
            ("expires", TODAY - timedelta(days=1)),
            ("expires", TODAY + timedelta(days=181)),
            ("path", "../a.py"),
            ("kind", "inherited_contract"),
        ],
    )
    def test_unjustified_metadata_is_rejected(self, field: str, value: object) -> None:
        """Reject scope and metadata failures before consuming source findings."""
        exception = self._exception(**{field: value})
        with pytest.raises(ValueError):
            exception.validate_context(
                owner_roles=OWNERS, validation_date=TODAY, fingerprint="a" * 64
            )

    @pytest.mark.parametrize("rule", ["PYI001", "PYT001", "PYS001", "UNKNOWN"])
    def test_exception_cannot_waive_import_any_or_syntax_rules(self, rule: str) -> None:
        """Limit design exceptions to object-design and inherited-documentation decisions."""
        with pytest.raises(ValueError):
            self._exception(rule=rule)

    def test_valid_exception_discharges_one_finding_and_rejects_changes(self) -> None:
        """Permit a reviewed decision only while source and diagnostic remain exact."""
        checker = TestPythonDebt._checker()
        exception = self._exception()
        policy = PythonExceptions(schema_version=1, exceptions=[exception])
        observed = (
            PythonFinding(
                path="src/a.py", symbol="parse", rule="PYC001", detail="standalone", line=1
            ),
        )
        fingerprint = {("src/a.py", "parse"): "a" * 64}
        assert checker.reconcile(policy, observed, fingerprint) == ()
        assert any("fingerprint" in x for x in checker.reconcile(policy, observed, {}))
        assert any("stale" in x for x in checker.reconcile(policy, (), fingerprint))
        duplicate = PythonExceptions(schema_version=1, exceptions=[exception, exception])
        assert any("duplicate" in x for x in checker.reconcile(duplicate, observed, fingerprint))

    def test_fingerprint_ignores_lines_but_detects_behavior_and_ambiguous_names(self) -> None:
        """Prevent a reviewed primitive growing silently into a different workflow."""
        source = "def parse(value: str) -> str:\n    return value.strip()\n"
        first, shifted, changed, ambiguous = (SourceIdentity() for _ in range(4))
        first.visit(ast.parse(source))
        shifted.visit(ast.parse("\n\n" + source))
        changed.visit(ast.parse(source.replace("value.strip()", "value.upper()")))
        ambiguous.visit(ast.parse(source + source))
        assert first.symbols == shifted.symbols
        assert first.symbols != changed.symbols
        assert ambiguous.symbols["parse"] == "ambiguous"


if __name__ == "__main__":
    raise SystemExit(
        pytest.main([__file__, str(Path(__file__).with_name("test_python_source_standards.py"))])
    )
