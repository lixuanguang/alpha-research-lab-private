"""Test class-ownership enforcement over maintained Python."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.engineering_standards.ownership import (
    OwnershipChecker,
    SourceArea,
)

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


class TestOwnershipFindings:
    """Report every finding with its location, and fail closed on unreadable input."""

    def test_findings_name_location_rule_and_guidance(self, tmp_path: Path) -> None:
        """Report each finding with its line, rule, symbol and guidance."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write("src/owner/inner.py", DOC + "FIRST = lambda: 1\nSECOND = lambda: 2\n")
        findings = OwnershipChecker.findings(fixture.root)
        assert findings == (
            f"src/owner/inner.py:3: lambda <module>: {OwnershipChecker.GUIDANCE['lambda']}",
            f"src/owner/inner.py:4: lambda <module>: {OwnershipChecker.GUIDANCE['lambda']}",
        )

    def test_clean_fixture_passes(self, tmp_path: Path) -> None:
        """Report nothing for a repository without findings."""
        assert OwnershipChecker.findings(OwnershipFixture(tmp_path).root) == ()

    def test_missing_root_fails_closed(self, tmp_path: Path) -> None:
        """Refuse a repository without every governed root."""
        (tmp_path / "src").mkdir()
        [finding] = OwnershipChecker.findings(tmp_path)
        assert finding.startswith("ownership scanner: missing ownership source root")

    def test_unparseable_source_fails_closed(self, tmp_path: Path) -> None:
        """Refuse a governed file that is not valid Python."""
        fixture = OwnershipFixture(tmp_path)
        fixture.write("src/owner/inner.py", "def broken(:\n")
        [finding] = OwnershipChecker.findings(fixture.root)
        assert finding.startswith("ownership scanner:")


class TestRepositoryOwnership:
    """Hold the repository to the ownership rules with no recorded exceptions."""

    def test_every_rule_has_guidance(self) -> None:
        """Cover every rule the scanner emits with guidance, over every governed root."""
        assert "examples" in OwnershipChecker.ROOTS
        assert set(OwnershipChecker.GUIDANCE) == {
            "module-function",
            "nested-function",
            "lambda",
            "native-call",
            "native-import",
            "private-import",
            "deep-import",
            "unexported-import",
            "path-mutation",
        }

    def test_repository_has_no_ownership_findings(self) -> None:
        """Pass the repository with no ledger or waiver."""
        assert OwnershipChecker.findings(REPOSITORY_ROOT) == ()

    def test_source_area_roles(self) -> None:
        """Classify command locations without treating consumer tests as commands."""
        assert SourceArea("tests/integration/consumers/flow.py").is_command_location
        assert not SourceArea("tests/integration/consumers/test_flow.py").is_command_location
        assert SourceArea("tools/typing/stubs/fakelib/__init__.pyi").is_stub
        assert not SourceArea("tools/typing/stubs/fakelib/__init__.py").is_stub
