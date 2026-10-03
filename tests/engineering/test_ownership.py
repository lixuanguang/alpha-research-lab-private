"""Test class-ownership enforcement and the shrink-only ownership ledger."""

from __future__ import annotations

# standard library imports
import os
import subprocess
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.engineering_standards.ownership import (
    OwnershipChecker,
    SourceArea,
)
from alpha_research_governance.engineering_standards.ownership_ledger import OwnershipLedger

REPOSITORY_ROOT = Path(__file__).parents[2]
DOC = '"""Fixture module."""\n\n'


class OwnershipFixture:
    """Build a minimal repository with every governed root and one runtime owner."""

    def __init__(self, root: Path) -> None:
        """Create the governed roots, a runtime owner API and one stubbed native library."""
        self.root = root
        for name in OwnershipChecker.ROOTS:
            (root / name).mkdir(parents=True)
        self.write("src/owner/__init__.py", DOC + '__all__ = ["Exported"]\n')
        self.write("src/owner/inner.py", DOC)
        self.write("tools/typing/stubs/fakelib/__init__.pyi", "def compute() -> int: ...\n")

    def write(self, relative: str, source: str) -> None:
        """Write one fixture file, creating its parent directories."""
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def keys(self) -> list[tuple[str, str, str]]:
        """Return the scanned finding keys in order."""
        return [finding.key for finding in OwnershipChecker.scan(self.root)]

    def ledger(self, entries: dict[tuple[str, str, str], int]) -> None:
        """Write a canonical ledger with the given counts."""
        self.write(OwnershipChecker.LEDGER, OwnershipLedger(entries).render())

    def git(self, *arguments: str) -> None:
        """Run one Git command in the fixture with a fixed identity."""
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        environment |= {
            "GIT_AUTHOR_NAME": "fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
        subprocess.run(
            ["git", *arguments], cwd=self.root, check=True, capture_output=True, env=environment
        )

    def commit(self, message: str) -> None:
        """Stage everything and commit."""
        self.git("add", "-A")
        self.git("commit", "-q", "--no-gpg-sign", "-m", message)


class TestModuleFunctions:
    """Permit module-level functions only for orchestrators and entry points."""

    @pytest.mark.parametrize(
        ("relative", "source"),
        [
            ("src/owner/inner.py", "def helper() -> None:\n    pass\n"),
            ("src/owner/inner.py", "def _helper() -> None:\n    pass\n"),
            ("src/owner/inner.py", "def main() -> None:\n    pass\n"),
            ("src/applications/run/workflow.py", "def _helper() -> None:\n    pass\n"),
            ("src/owner/inner.py", "def __getattr__(name: str) -> object:\n    return name\n"),
            ("tests/unit/test_a.py", "def test_behaviour() -> None:\n    pass\n"),
            (
                "tests/unit/test_a.py",
                "import pytest\n\n@pytest.fixture\ndef value() -> int:\n    return 1\n",
            ),
            ("tests/conftest.py", "def shared() -> int:\n    return 1\n"),
            ("tests/integration/consumers/test_a.py", "def main() -> None:\n    pass\n"),
            ("tools/typing/stubs/fakelib/extra.py", "def compute() -> int:\n    return 1\n"),
            ("src/owner/inner.py", "if True:\n    def hidden() -> None:\n        pass\n"),
            (
                "src/owner/inner.py",
                "try:\n    pass\nexcept ValueError:\n    def hidden() -> None:\n        pass\n",
            ),
        ],
    )
    def test_rejects_non_orchestrator_functions(
        self, tmp_path: Path, relative: str, source: str
    ) -> None:
        """Refuse helpers, tests, fixtures and misplaced entry points at module scope."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write(relative, DOC + source)
        [(path, rule, _)] = fixture.keys()
        assert (path, rule) == (relative, "module-function")

    @pytest.mark.parametrize(
        ("relative", "source"),
        [
            ("src/applications/run/workflow.py", "def run_workflow() -> None:\n    pass\n"),
            ("src/applications/run/workflow.py", "def main() -> None:\n    pass\n"),
            ("tools/governance/src/tool/__init__.py", "def main() -> None:\n    pass\n"),
            ("tests/integration/consumers/flow.py", "def main() -> None:\n    pass\n"),
            ("tests/support/subprocesses/child.py", "def main() -> None:\n    pass\n"),
            ("examples/script.py", "def main() -> None:\n    pass\n"),
            ("tests/conftest.py", "def pytest_configure(config: object) -> None:\n    pass\n"),
            (
                "src/owner/__init__.py",
                "def __getattr__(name: str) -> object:\n    raise AttributeError(name)\n",
            ),
            (
                "src/owner/inner.py",
                "from typing import overload\n\nclass Owner:\n    pass\n\n"
                "@overload\ndef shape(value: int) -> int: ...\n",
            ),
            ("tools/typing/stubs/fakelib/extra.pyi", "def compute() -> int: ...\n"),
        ],
    )
    def test_accepts_orchestrators_and_entry_points(
        self, tmp_path: Path, relative: str, source: str
    ) -> None:
        """Accept application orchestrators, command mains, hooks, lazy exports and stubs."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write(relative, DOC + source)
        assert fixture.keys() == []

    def test_methods_and_classes_are_owned(self, tmp_path: Path) -> None:
        """Accept methods, static methods and test methods on cohesive classes."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write(
            "tests/unit/test_owned.py",
            DOC
            + "class TestOwned:\n    @staticmethod\n    def build() -> int:\n        return 1\n\n"
            "    def test_value(self) -> None:\n        assert self.build() == 1\n",
        )
        assert fixture.keys() == []


class TestNestedBehaviour:
    """Refuse nested functions and lambdas as behaviour owners."""

    def test_nested_function_uses_qualified_symbol(self, tmp_path: Path) -> None:
        """Report a function nested in a method by its qualified name."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write(
            "src/owner/inner.py",
            DOC + "class Owner:\n    def run(self) -> int:\n        def one() -> int:\n"
            "            return 1\n\n        return one()\n",
        )
        assert fixture.keys() == [("src/owner/inner.py", "nested-function", "Owner.run.one")]

    def test_local_class_methods_are_not_nested_functions(self, tmp_path: Path) -> None:
        """Treat methods of a class defined in a method as owned by that class."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write(
            "src/owner/inner.py",
            DOC + "class Owner:\n    def run(self) -> object:\n        class Local:\n"
            "            def value(self) -> int:\n                return 1\n\n"
            "        return Local()\n",
        )
        assert fixture.keys() == []

    def test_every_lambda_is_counted_in_its_scope(self, tmp_path: Path) -> None:
        """Report each lambda under its enclosing scope, including sort keys."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write(
            "src/owner/inner.py",
            DOC + "KEY = lambda value: value\n\nclass Owner:\n    def run(self) -> list[int]:\n"
            "        return sorted([2, 1], key=lambda value: -value)\n",
        )
        assert fixture.keys() == [
            ("src/owner/inner.py", "lambda", "<module>"),
            ("src/owner/inner.py", "lambda", "Owner.run"),
        ]


class TestNativeLibraries:
    """Keep stubbed native libraries inside owning classes outside applications."""

    def test_call_outside_class_is_refused(self, tmp_path: Path) -> None:
        """Refuse a native reference in module-level code."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write("src/owner/inner.py", DOC + "import fakelib\n\nVALUE = fakelib.compute()\n")
        assert fixture.keys() == [("src/owner/inner.py", "native-call", "<module>")]

    def test_class_use_annotations_and_type_checking_are_accepted(self, tmp_path: Path) -> None:
        """Accept native use in methods, annotations and ``TYPE_CHECKING`` imports."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write(
            "src/owner/inner.py",
            DOC
            + "from typing import TYPE_CHECKING\n\nimport fakelib\nfrom fakelib import compute\n\n"
            "if TYPE_CHECKING:\n    from fakelib import compute as typed\n\n"
            "value: fakelib.Thing\n\nclass Adapter:\n"
            "    def run(self, item: fakelib.Thing) -> int:\n"
            "        return compute() + fakelib.compute()\n",
        )
        assert fixture.keys() == []

    def test_applications_cannot_import_native_libraries(self, tmp_path: Path) -> None:
        """Refuse native imports in the orchestrator layer even inside a class."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write(
            "src/applications/run/workflow.py",
            DOC + "from fakelib import compute\n\nclass Access:\n"
            "    def run(self) -> int:\n        return compute()\n",
        )
        assert fixture.keys() == [("src/applications/run/workflow.py", "native-import", "fakelib")]

    def test_a_new_stub_brings_its_library_under_the_rule(self, tmp_path: Path) -> None:
        """Derive native libraries from the owned stub roots."""
        fixture = OwnershipFixture(tmp_path)
        source = DOC + "import otherlib\n\nVALUE = otherlib.compute()\n"
        fixture.write("src/owner/inner.py", source)
        assert fixture.keys() == []
        fixture.write("tools/typing/stubs/otherlib.pyi", "def compute() -> int: ...\n")
        assert fixture.keys() == [("src/owner/inner.py", "native-call", "<module>")]


class TestExternalImports:
    """Hold tests, tooling and examples to the supported runtime API."""

    @pytest.mark.parametrize(
        ("relative", "source", "expected"),
        [
            ("tests/unit/test_a.py", "from owner._private import Thing\n", "private-import"),
            ("tests/unit/test_a.py", "from owner.inner import _Thing\n", "private-import"),
            ("tests/integration/test_a.py", "from owner.inner import Thing\n", "deep-import"),
            ("tests/engineering/test_a.py", "import owner.inner\n", "deep-import"),
            ("examples/script.py", "from owner.inner import Thing\n", "deep-import"),
            ("tests/unit/test_a.py", "from owner import inner\n", "unexported-import"),
        ],
    )
    def test_rejects_unsupported_imports(
        self, tmp_path: Path, relative: str, source: str, expected: str
    ) -> None:
        """Refuse private names everywhere and deep imports outside unit tests."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write(relative, DOC + source)
        assert [rule for _, rule, _ in fixture.keys()] == [expected]

    @pytest.mark.parametrize(
        ("relative", "source"),
        [
            ("tests/integration/test_a.py", "from owner import Exported\n"),
            ("tests/unit/test_a.py", "from owner.inner import Thing\n"),
            ("tests/unit/test_a.py", "import owner\n"),
            ("src/applications/run/workflow.py", "from owner.inner import Thing\n"),
        ],
    )
    def test_accepts_supported_imports(self, tmp_path: Path, relative: str, source: str) -> None:
        """Accept owner APIs everywhere and public deep names in unit tests."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write(relative, DOC + source)
        assert fixture.keys() == []

    def test_path_mutation_is_refused(self, tmp_path: Path) -> None:
        """Refuse in-place changes to ``sys.path``."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write(
            "tests/integration/consumers/flow.py",
            DOC + "import sys\n\nclass Flow:\n    def load(self) -> None:\n"
            '        sys.path.insert(0, "here")\n',
        )
        assert fixture.keys() == [
            ("tests/integration/consumers/flow.py", "path-mutation", "Flow.load")
        ]


class TestOwnershipLedger:
    """Record existing debt explicitly and let it only shrink."""

    LAMBDAS = DOC + "FIRST = lambda: 1\nSECOND = lambda: 2\n"
    KEY = ("src/owner/inner.py", "lambda", "<module>")

    def test_unrecorded_findings_fail_with_location(self, tmp_path: Path) -> None:
        """Report each new finding with its line and guidance."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write("src/owner/inner.py", self.LAMBDAS)
        findings = OwnershipChecker.findings(fixture.root)
        assert findings[0].startswith("src/owner/inner.py:3: lambda <module>:")
        assert len(findings) == 2

    def test_recorded_debt_passes_and_raised_debt_fails(self, tmp_path: Path) -> None:
        """Accept recorded counts and refuse occurrences beyond them."""
        fixture = OwnershipFixture(tmp_path)
        fixture.git("init", "-q", "-b", "main")
        fixture.write("src/owner/inner.py", self.LAMBDAS)
        fixture.ledger({self.KEY: 2})
        fixture.commit("seed")
        assert OwnershipChecker.findings(fixture.root) == ()
        fixture.write("src/owner/inner.py", self.LAMBDAS + "THIRD = lambda: 3\n")
        [finding] = OwnershipChecker.findings(fixture.root)
        assert "3 findings (lines 3, 4, 5) exceed the 2 recorded" in finding

    def test_stale_entries_fail(self, tmp_path: Path) -> None:
        """Require a fixed finding to remove or lower its ledger entry."""
        fixture = OwnershipFixture(tmp_path)
        fixture.git("init", "-q", "-b", "main")
        fixture.write("src/owner/inner.py", DOC + "FIRST = lambda: 1\n")
        fixture.ledger({self.KEY: 2})
        fixture.commit("seed")
        assert OwnershipChecker.findings(fixture.root) == (
            "ownership ledger: src/owner/inner.py lambda <module> records 2 but 1 remain; "
            "lower or remove the entry",
        )

    def test_ledger_may_shrink_but_not_grow_after_it_is_committed(self, tmp_path: Path) -> None:
        """Compare the working ledger with every committed version since the merge-base."""
        fixture = OwnershipFixture(tmp_path)
        fixture.git("init", "-q", "-b", "main")
        fixture.commit("base without a ledger")
        fixture.git("switch", "-q", "-c", "work")
        fixture.write("src/owner/inner.py", self.LAMBDAS)
        fixture.ledger({self.KEY: 2})
        fixture.commit("seed")
        fixture.write("src/owner/inner.py", DOC + "FIRST = lambda: 1\n")
        fixture.ledger({self.KEY: 1})
        fixture.commit("shrink")
        assert OwnershipChecker.findings(fixture.root) == ()
        fixture.write("src/owner/inner.py", self.LAMBDAS)
        fixture.ledger({self.KEY: 2})
        assert OwnershipChecker.findings(fixture.root) == (
            "ownership ledger: src/owner/inner.py lambda <module> grew from 1 to 2 in the "
            "working tree; recorded debt can only shrink",
        )

    def test_committed_growth_and_readding_fail(self, tmp_path: Path) -> None:
        """Refuse growth hidden in an intermediate commit and a ledger re-added after removal."""
        fixture = OwnershipFixture(tmp_path)
        fixture.git("init", "-q", "-b", "main")
        fixture.write("src/owner/inner.py", self.LAMBDAS)
        fixture.ledger({self.KEY: 1})
        fixture.commit("seed on main")
        fixture.git("switch", "-q", "-c", "work")
        (fixture.root / OwnershipChecker.LEDGER).unlink()
        fixture.commit("remove")
        fixture.ledger({self.KEY: 2})
        fixture.commit("re-add")
        findings = OwnershipChecker.findings(fixture.root)
        assert len(findings) == 1
        assert "grew from 0 to 2 in commit" in findings[0]

    def test_ledger_without_git_history_fails_closed(self, tmp_path: Path) -> None:
        """Refuse a ledger whose growth cannot be verified."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write("src/owner/inner.py", self.LAMBDAS)
        fixture.ledger({self.KEY: 2})
        [finding] = OwnershipChecker.findings(fixture.root)
        assert finding.startswith("ownership ledger: cannot verify that recorded debt only shrinks")

    def test_absent_ledger_needs_no_history(self, tmp_path: Path) -> None:
        """Treat a missing ledger as empty without consulting Git."""
        fixture = OwnershipFixture(tmp_path)
        assert OwnershipChecker.findings(fixture.root) == ()

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("debt = [", "malformed"),
            ("other = []\n", "exactly one debt array"),
            (
                'debt = [{ path = "b", rule = "lambda", symbol = "s", count = 1 },'
                ' { path = "a", rule = "lambda", symbol = "s", count = 1 }]\n',
                "unique and sorted",
            ),
            ('debt = [{ path = "a", rule = "magic", symbol = "s", count = 1 }]\n', "unknown"),
            ('debt = [{ path = "a", rule = "lambda", symbol = "s", count = 0 }]\n', "malformed"),
            ('debt = [{ path = "a", rule = "lambda", symbol = "s", count = "1" }]\n', "malformed"),
        ],
    )
    def test_malformed_ledgers_fail_closed(self, tmp_path: Path, text: str, message: str) -> None:
        """Refuse malformed, unsorted or unknown ledger content."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write(OwnershipChecker.LEDGER, text)
        [finding] = OwnershipChecker.findings(fixture.root)
        assert finding.startswith("ownership ledger:")
        assert message in finding

    def test_render_round_trips(self) -> None:
        """Render a canonical document that parses back to the same counts."""
        ledger = OwnershipLedger({("b.py", "lambda", "x"): 2, ("a.py", "deep-import", "m.n"): 1})
        assert OwnershipLedger.parse(ledger.render(), source="ledger").counts == ledger.counts
        assert OwnershipLedger.parse(OwnershipLedger({}).render(), source="ledger").counts == {}

    def test_missing_root_fails_closed(self, tmp_path: Path) -> None:
        """Refuse a repository without every governed root."""
        (tmp_path / "src").mkdir()
        [finding] = OwnershipChecker.findings(tmp_path)
        assert finding.startswith("ownership scanner: missing ownership source root")


class TestRepositoryOwnership:
    """Hold the repository to its recorded ownership debt."""

    def test_every_rule_has_guidance(self) -> None:
        """Keep the ledger's rule vocabulary aligned with the checker's diagnostics."""
        assert "examples" in OwnershipChecker.ROOTS
        assert set(OwnershipLedger.RULES) == set(OwnershipChecker.GUIDANCE)

    def test_repository_matches_its_ledger(self) -> None:
        """Pass the repository against the committed ledger and its history."""
        assert OwnershipChecker.findings(REPOSITORY_ROOT) == ()

    def test_source_area_roles(self) -> None:
        """Classify command locations without treating consumer tests as commands."""
        assert SourceArea("tests/integration/consumers/flow.py").is_command_location
        assert not SourceArea("tests/integration/consumers/test_flow.py").is_command_location
        assert SourceArea("tools/typing/stubs/fakelib/__init__.pyi").is_stub
        assert not SourceArea("tools/typing/stubs/fakelib/__init__.py").is_stub
