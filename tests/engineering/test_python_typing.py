"""Verify exact inferred-debt reconciliation and parsed boundary rejection."""

from __future__ import annotations

# standard library imports
import json
import subprocess
from collections import Counter
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.dependency_admission.models import DependencyAdmissionError
from alpha_research_governance.dependency_admission.policy import _lock_surface_findings
from alpha_research_governance.engineering_standards.python_typing import (
    DiagnosticKey,
    TypingDebtInventory,
    TypingInventoryChecker,
    TypingObligation,
    TypingRetirementTask,
)
from alpha_research_governance.operating_model import OperatingModelError, load_operating_model


class TestTypingInventory:
    """Keep identity stable under line shifts and reject every form of debt drift."""

    def test_reconciliation_requires_exact_identity_and_count(self) -> None:
        """Reject new, moved, multiplied, stale and unattributed obligations."""
        obligation = TypingObligation(
            path="src/sample.py",
            symbol="Reader.load",
            code="misc",
            message='Expression has type "Any"',
            count=2,
            task="parsed-shape",
        )
        inventory = TypingDebtInventory(
            schema_version=1,
            baseline_revision="a" * 40,
            mypy_version="2.3.1",
            tasks={
                "parsed-shape": TypingRetirementTask(
                    owner_role="platform",
                    cause="Parsed JSON values have no validated field shape.",
                    retirement="Validate raw input into the consumer's exact record before access.",
                )
            },
            obligations=(obligation,),
        )
        observed: Counter[DiagnosticKey] = Counter({obligation.key: 2})
        assert inventory.reconcile(observed) == ()
        for count in (0, 1, 3):
            assert inventory.reconcile(Counter({obligation.key: count}))
        for index in range(4):
            components = list(obligation.key)
            components[index] += ".moved"
            moved = components[0], components[1], components[2], components[3]
            assert len(inventory.reconcile(Counter({moved: 2}))) == 2
        duplicate = TypingDebtInventory(
            schema_version=1,
            baseline_revision=inventory.baseline_revision,
            mypy_version="2.3.1",
            tasks=inventory.tasks,
            obligations=(obligation, obligation),
        )
        assert duplicate.reconcile(Counter({obligation.key: 4}))
        unknown_task = TypingDebtInventory(
            schema_version=1,
            baseline_revision=inventory.baseline_revision,
            mypy_version="2.3.1",
            tasks={},
            obligations=(obligation,),
        )
        assert unknown_task.reconcile(observed)

    def test_decorator_and_nested_symbols_survive_line_shifts(self) -> None:
        """Attribute decorated methods and nested functions to lexical ownership."""
        source = (
            "class Reader:\n"
            "    @decorate\n"
            "    def load(self):\n"
            "        if True:\n"
            "            def parse():\n"
            "                return dynamic()\n"
            "        return parse()\n"
        )
        for line, expected in ((1, "Reader"), (2, "Reader.load"), (6, "Reader.load.parse")):
            assert TypingInventoryChecker.symbol_at(source, line) == expected
            assert TypingInventoryChecker.symbol_at("\n\n" + source, line + 2) == expected

    def test_machine_output_is_validated(self, tmp_path: Path) -> None:
        """Reject malformed output and paths outside the owned source roots."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src/sample.py").write_text("value = dynamic()\n", encoding="utf-8")
        checker = TypingInventoryChecker(tmp_path)
        record: dict[str, str | int | None] = {
            "file": "src/sample.py",
            "line": 1,
            "column": 8,
            "end_line": 1,
            "end_column": 17,
            "message": 'Expression has type "Any"',
            "hint": None,
            "code": "misc",
            "severity": "error",
        }
        output = json.dumps(record)
        observed = checker.observed(output + "\n" + output)
        assert observed.total() == 2
        for path in ("/src/sample.py", "src/../sample.py", "outside/sample.py"):
            record["file"] = path
            with pytest.raises(ValueError, match="outside the owned scope"):
                checker.observed(json.dumps(record))
        for malformed in ("not JSON", "[]", '{"file": 4}'):
            with pytest.raises(ValueError):
                checker.observed(malformed)

    @pytest.mark.parametrize(
        ("status", "output", "error"),
        [(2, "", "crashed"), (1, "", ""), (0, "", "warning"), (0, "not JSON", "")],
    )
    def test_probe_fails_closed_on_tool_errors(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        status: int,
        output: str,
        error: str,
    ) -> None:
        """Reject failed processes, contradictory status and invalid machine output."""

        def complete(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
            """Return a controlled checker failure with the requested diagnostic streams.

            Args:
                command: Checker argument vector retained in the fake process result.
                options: Execution options accepted without running a child process.

            Returns:
                Completed process containing the parametrized status and streams.
            """
            return subprocess.CompletedProcess(command, status, output, error)

        monkeypatch.setattr(
            "alpha_research_governance.engineering_standards.python_typing.subprocess.run", complete
        )
        with pytest.raises(ValueError):
            TypingInventoryChecker(tmp_path)._probe()

    def test_inventory_checksum_failure_returns_failure(self, tmp_path: Path) -> None:
        """Reject unreviewed inventory bytes before launching the checker."""
        path = tmp_path / "docs/architecture/python-typing-debt.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}", encoding="utf-8")
        assert TypingInventoryChecker(tmp_path).run() == 1


class TestParsedBoundaries:
    """Reject malformed tables before nested access or policy construction."""

    @pytest.mark.parametrize("payload", ["null", "[]", '"text"', "42"])
    def test_module_lock_root_is_validated(self, tmp_path: Path, payload: str) -> None:
        """Turn non-object Bazel locks into the existing domain error."""
        (tmp_path / "MODULE.bazel.lock").write_text(payload, encoding="utf-8")
        with pytest.raises(DependencyAdmissionError, match=r"MODULE\.bazel\.lock"):
            _lock_surface_findings(tmp_path)

    @pytest.mark.parametrize("payload", ["null", "[]", '"text"', "42"])
    def test_flake_lock_root_is_validated(self, tmp_path: Path, payload: str) -> None:
        """Turn non-object Nix locks into the existing domain error."""
        (tmp_path / "MODULE.bazel.lock").write_text("{}", encoding="utf-8")
        (tmp_path / "flake.lock").write_text(payload, encoding="utf-8")
        with pytest.raises(DependencyAdmissionError, match=r"flake\.lock"):
            _lock_surface_findings(tmp_path)

    @pytest.mark.parametrize(
        "settings",
        ['"not a table"', "{founder_principal = 2026-09-05}", "{founder_principal = 42}"],
    )
    def test_operating_settings_reject_wrong_shapes(self, tmp_path: Path, settings: str) -> None:
        """Keep TOML dates distinct from JSON scalars and reject invalid principals."""
        path = tmp_path / "ownership.toml"
        path.write_text(
            f"schema_version = 2\noperating_model = {settings}\n"
            "domains = []\nrole_assignments = []\n",
            encoding="utf-8",
        )
        with pytest.raises(OperatingModelError):
            load_operating_model(path)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
