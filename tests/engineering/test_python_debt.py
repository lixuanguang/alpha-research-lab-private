"""Exercise exact migration allowances and source-bound design exceptions."""

from __future__ import annotations

# standard library imports
import ast
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.engineering_standards import python_debt
from alpha_research_governance.engineering_standards.python_debt import (
    DEBT_PATH,
    DEBT_SHA256,
    EXCEPTIONS_PATH,
    PythonDebtInventory,
    PythonException,
    PythonExceptions,
    PythonStandardsChecker,
    SourceIdentity,
)
from alpha_research_governance.engineering_standards.python_source import PythonFinding

TODAY = date(2026, 9, 5)
OWNERS = frozenset({"platform"})
ROOT = Path(__file__).parents[2]


class TestPythonDebt:
    """Reject attempts to transfer, multiply, silently change or retain retired debt."""

    @staticmethod
    def _payload(findings: tuple[PythonFinding, ...]) -> bytes:
        """Build a small attributed inventory independently of the production scanner."""
        entries: dict[str, list[tuple[str, str, str]]] = {}
        for item in findings:
            entries.setdefault(item.path, []).append((item.symbol, item.rule, item.detail))
        document = {
            "schema_version": 1,
            "source_revision": "a" * 40,
            "recorded_on": TODAY.isoformat(),
            "work": {
                rule: {
                    "owner_role": "platform",
                    "rationale": "Retire recorded obligations in the owning migration step.",
                    "migration_step": step,
                }
                for rule, step in (
                    ("PYI001", 2),
                    ("PYT001", 3),
                    ("PYD001", 5),
                    ("PYD002", 5),
                    ("PYC001", 6),
                )
            },
            "entries": {path: sorted(rows) for path, rows in entries.items()},
        }
        return json.dumps(document).encode()

    @classmethod
    def _inventory(cls, *findings: PythonFinding) -> PythonDebtInventory:
        """Read a test inventory through the same checked boundary as production."""
        payload = cls._payload(findings)
        return PythonDebtInventory.read(
            payload, expected_sha256=hashlib.sha256(payload).hexdigest(), owner_roles=OWNERS
        )

    @staticmethod
    def _checker() -> PythonStandardsChecker:
        """Use an explicit source scope, owner set and validation date."""
        return PythonStandardsChecker(
            source_roots=("src",), owner_roles=OWNERS, validation_date=TODAY
        )

    def test_reviewed_inventory_is_exact_and_attributed(self) -> None:
        """Bind the checked-in debt bytes to the production pin and real owner."""
        inventory = PythonDebtInventory.read(
            (ROOT / DEBT_PATH).read_bytes(), expected_sha256=DEBT_SHA256, owner_roles=OWNERS
        )
        assert inventory.source_revision == "d3a40ca98d71208426c8501d8d4a1aaaa049768d"
        assert not inventory.obligations
        assert not any("python_source.py" in path for path in inventory.entries)

    def test_changed_inventory_requires_an_explicit_policy_change(self) -> None:
        """Refuse even valid extra entries when only the allowance file changes."""
        first = PythonFinding(
            path="src/a.py", symbol="old", rule="PYD001", detail="docstring", line=2
        )
        added = PythonFinding(
            path="src/a.py", symbol="new", rule="PYD001", detail="docstring", line=9
        )
        original = self._payload((first,))
        with pytest.raises(ValueError, match="checksum changed"):
            PythonDebtInventory.read(
                self._payload((first, added)),
                expected_sha256=hashlib.sha256(original).hexdigest(),
                owner_roles=OWNERS,
            )

    @pytest.mark.parametrize("mutation", ["unknown_owner", "wrong_step", "unknown_rule", "syntax"])
    def test_invalid_attribution_and_unwaivable_rules_are_rejected(self, mutation: str) -> None:
        """Reject unsupported metadata even when the supplied checksum matches."""
        payload = self._payload(
            (PythonFinding(path="src/a.py", symbol="f", rule="PYD001", detail="docstring", line=1),)
        )
        replacements = {
            "unknown_owner": (b'"platform"', b'"unknown"'),
            "wrong_step": (b'"migration_step": 2', b'"migration_step": 6'),
            "unknown_rule": (b'"PYD001"', b'"UNKNOWN"'),
            "syntax": (b'"f", "PYD001"', b'"f", "PYS001"'),
        }
        old, new = replacements[mutation]
        payload = payload.replace(old, new)
        with pytest.raises(ValueError):
            PythonDebtInventory.read(
                payload, expected_sha256=hashlib.sha256(payload).hexdigest(), owner_roles=OWNERS
            )

    def test_line_changes_pass_but_new_symbols_and_moves_do_not(self) -> None:
        """Keep obligations stable under whitespace and scoped to the original definition."""
        old = PythonFinding(path="src/a.py", symbol="f", rule="PYD001", detail="docstring", line=1)
        inventory = self._inventory(old)
        exceptions = PythonExceptions(schema_version=1, exceptions=[])
        moved_line = PythonFinding(
            path="src/a.py", symbol="f", rule="PYD001", detail="docstring", line=100
        )
        assert self._checker().reconcile(inventory, exceptions, (moved_line,), {}) == ()
        moved_symbol = PythonFinding(
            path="src/b.py", symbol="Other.f", rule="PYD001", detail="docstring", line=1
        )
        result = self._checker().reconcile(inventory, exceptions, (moved_symbol,), {})
        assert any("src/b.py:Other.f: new PYD001" in message for message in result)
        assert any("src/a.py:f: retire resolved debt" in message for message in result)

    def test_a_second_any_in_the_same_symbol_is_new_debt(self) -> None:
        """Preserve multiplicity instead of allowing a set-based escape hatch."""
        item = PythonFinding(
            path="src/a.py", symbol="f", rule="PYT001", detail="annotation:Any", line=1
        )
        result = self._checker().reconcile(
            self._inventory(item),
            PythonExceptions(schema_version=1, exceptions=[]),
            (item, item),
            {},
        )
        assert len(result) == 1
        assert "new PYT001" in result[0]
        assert "occurrences: 1" in result[0]

    def test_resolution_requires_retirement_and_cannot_fund_another_rule(self) -> None:
        """Require pruning an old entry and reject a replacement violation independently."""
        old = PythonFinding(path="src/a.py", symbol="f", rule="PYD001", detail="docstring", line=1)
        new = PythonFinding(path="src/a.py", symbol="f", rule="PYD002", detail="Args:x", line=1)
        result = self._checker().reconcile(
            self._inventory(old), PythonExceptions(schema_version=1, exceptions=[]), (new,), {}
        )
        assert any("retire resolved debt PYD001" in message for message in result)
        assert any("new PYD002" in message for message in result)

    def test_source_failure_and_new_untracked_files_fail_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Discover new source without requiring a Git index or repository metadata."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src/new.py").write_text("def malformed(:\n", encoding="utf-8")
        payload = self._payload(())
        inventory_path = tmp_path / DEBT_PATH
        inventory_path.parent.mkdir(parents=True)
        inventory_path.write_bytes(payload)
        (tmp_path / EXCEPTIONS_PATH).write_text("schema_version = 1\nexceptions = []\n")
        monkeypatch.setattr(python_debt, "DEBT_SHA256", hashlib.sha256(payload).hexdigest())
        assert any("PYS001" in message for message in self._checker().findings(tmp_path))
        (tmp_path / "src/new.py").write_text("value = 1\n", encoding="utf-8")
        assert any("PYD001" in message for message in self._checker().findings(tmp_path))

    def test_absent_or_malformed_policy_fails_with_a_diagnostic(self, tmp_path: Path) -> None:
        """Never interpret an unavailable inventory as permission to skip checking."""
        assert "Python standards policy" in self._checker().findings(tmp_path)[0]
        path = tmp_path / DEBT_PATH
        path.parent.mkdir(parents=True)
        path.write_text("{invalid", encoding="utf-8")
        assert "checksum" in self._checker().findings(tmp_path)[0]


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
        """Reject scope and metadata failures before consuming the source obligation."""
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

    def test_valid_exception_discharges_one_obligation_and_rejects_changes(self) -> None:
        """Permit the reviewed decision only while its source and diagnostic remain exact."""
        checker = TestPythonDebt._checker()
        inventory = TestPythonDebt._inventory()
        exception = self._exception()
        policy = PythonExceptions(schema_version=1, exceptions=[exception])
        observed = (
            PythonFinding(
                path="src/a.py", symbol="parse", rule="PYC001", detail="standalone", line=1
            ),
        )
        fingerprint = {("src/a.py", "parse"): "a" * 64}
        assert checker.reconcile(inventory, policy, observed, fingerprint) == ()
        assert any("fingerprint" in x for x in checker.reconcile(inventory, policy, observed, {}))
        assert any("stale" in x for x in checker.reconcile(inventory, policy, (), fingerprint))
        duplicate = PythonExceptions(schema_version=1, exceptions=[exception, exception])
        assert any(
            "duplicate" in x for x in checker.reconcile(inventory, duplicate, observed, fingerprint)
        )

    def test_fingerprint_ignores_lines_but_detects_behavior_and_ambiguous_names(self) -> None:
        """Prevent a reviewed primitive function growing silently into a different workflow."""
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
