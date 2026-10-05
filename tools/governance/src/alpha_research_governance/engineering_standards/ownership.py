"""Enforce class ownership of Python behaviour, native calls and supported imports."""

from __future__ import annotations

# standard library imports
import ast
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

# project library imports
from alpha_research_governance.engineering_standards.source_layout import SourceLayoutChecker


@dataclass(frozen=True, order=True)
class OwnershipFinding:
    """Identify one ownership finding by path, rule and enclosing symbol."""

    path: str
    rule: str
    symbol: str
    line: int

    @property
    def key(self) -> tuple[str, str, str]:
        """Return the line-independent identity of this finding.

        Returns:
            The repository-relative path, rule and qualified symbol.
        """
        return self.path, self.rule, self.symbol


@dataclass(frozen=True)
class SourceArea:
    """Classify one repository-relative Python path by the ownership role it plays."""

    path: str

    @property
    def is_stub(self) -> bool:
        """Whether the file is an owned stub describing an upstream native interface."""
        return self.path.startswith("tools/typing/stubs/") and self.path.endswith(".pyi")

    @property
    def is_runtime(self) -> bool:
        """Whether the file is shipped runtime source under ``src``."""
        return self.path.startswith("src/")

    @property
    def is_application(self) -> bool:
        """Whether the file belongs to the orchestrator layer under ``src/applications``."""
        return self.path.startswith("src/applications/")

    @property
    def is_unit_test(self) -> bool:
        """Whether the file belongs to the unit-test tree that mirrors runtime owners."""
        return self.path.startswith("tests/unit/")

    @property
    def is_runtime_initializer(self) -> bool:
        """Whether the file is a runtime package initializer."""
        return self.is_runtime and self.path.endswith("/__init__.py")

    @property
    def is_conftest(self) -> bool:
        """Whether the file is a pytest ``conftest.py`` module."""
        return self.path.startswith("tests/") and self.path.endswith("/conftest.py")

    @property
    def is_command_location(self) -> bool:
        """Whether a ``main`` function here is a command or script entry point."""
        name = self.path.rpartition("/")[2]
        return (
            self.is_application
            or self.path.startswith("tools/governance/src/")
            or self.path.startswith("tests/support/")
            or self.path.startswith("examples/")
            or (
                self.path.startswith("tests/integration/consumers/")
                and not name.startswith("test_")
            )
        )


class _ModuleVisit:
    """Collect one module's ownership findings; each scan uses a fresh visit."""

    def __init__(
        self,
        area: SourceArea,
        tree: ast.Module,
        *,
        native_libraries: frozenset[str],
        exports: Mapping[str, frozenset[str]],
        owned_roots: frozenset[str],
    ) -> None:
        """Bind the parsed module and repository context for one scan."""
        self._area = area
        self._tree = tree
        self._native_libraries = native_libraries
        self._exports = exports
        self._owned_roots = owned_roots
        self._native_aliases: dict[str, str] = {}
        self._findings: list[OwnershipFinding] = []

    def findings(self) -> tuple[OwnershipFinding, ...]:
        """Run every ownership rule over the module.

        Returns:
            Findings in source order.
        """
        if self._area.is_stub:
            return ()
        self._collect_native_aliases()
        self._module_functions(self._tree.body)
        self._visit_statements(self._tree.body, ())
        if not self._area.is_runtime:
            self._external_imports()
        return tuple(self._findings)

    def _add(self, rule: str, symbol: str, line: int) -> None:
        """Record one finding for this module."""
        self._findings.append(OwnershipFinding(self._area.path, rule, symbol, line))

    def _module_functions(self, statements: list[ast.stmt]) -> None:
        """Report module-scope functions that are not permitted entry points."""
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not self._is_permitted_module_function(statement):
                    self._add("module-function", statement.name, statement.lineno)
            elif isinstance(statement, (ast.Try, ast.TryStar)):
                self._module_functions(statement.body)
                for handler in statement.handlers:
                    self._module_functions(handler.body)
                self._module_functions(statement.orelse)
                self._module_functions(statement.finalbody)
            elif isinstance(statement, (ast.If, ast.For, ast.AsyncFor, ast.While)):
                self._module_functions(statement.body)
                self._module_functions(statement.orelse)
            elif isinstance(statement, (ast.With, ast.AsyncWith)):
                self._module_functions(statement.body)

    def _is_permitted_module_function(
        self, function: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> bool:
        """Decide whether a module-scope function is an orchestrator or entry point."""
        name = function.name
        if any(
            (isinstance(decorator, ast.Name) and decorator.id == "overload")
            or (isinstance(decorator, ast.Attribute) and decorator.attr == "overload")
            for decorator in function.decorator_list
        ):
            return True
        if name == "__getattr__" and self._area.is_runtime_initializer:
            return True
        if self._area.is_application and not name.startswith("_"):
            return True
        if name == "main" and self._area.is_command_location:
            return True
        return self._area.is_conftest and name.startswith("pytest_")

    def _visit_statements(self, statements: list[ast.stmt], scope: tuple[ast.AST, ...]) -> None:
        """Visit statements within the given lexical scope chain."""
        for statement in statements:
            self._visit(statement, scope)

    def _visit(self, node: ast.AST, scope: tuple[ast.AST, ...]) -> None:
        """Apply nesting, lambda, native-call and path rules to one node."""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if scope and isinstance(scope[-1], (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._add("nested-function", self._qualified((*scope, node)), node.lineno)
            for expression in (
                *node.decorator_list,
                *node.args.defaults,
                *(default for default in node.args.kw_defaults if default is not None),
            ):
                self._visit(expression, scope)
            self._visit_statements(node.body, (*scope, node))
            return
        if isinstance(node, ast.ClassDef):
            for header in (*node.decorator_list, *node.bases, *node.keywords):
                self._visit(header, scope)
            self._visit_statements(node.body, (*scope, node))
            return
        if isinstance(node, ast.Lambda):
            self._add("lambda", self._qualified(scope), node.lineno)
        elif isinstance(node, (ast.Import, ast.ImportFrom, ast.TypeAlias)):
            return
        elif isinstance(node, ast.AnnAssign):
            for part in (node.target, node.value):
                if part is not None:
                    self._visit(part, scope)
            return
        elif isinstance(node, ast.If) and self._is_type_checking(node.test):
            self._visit_statements(node.orelse, scope)
            return
        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in self._native_aliases
            and not any(isinstance(owner, ast.ClassDef) for owner in scope)
        ):
            self._add("native-call", self._qualified(scope), node.lineno)
        elif isinstance(node, (ast.Call, ast.Assign, ast.AugAssign)) and self._mutates_import_path(
            node
        ):
            self._add("path-mutation", self._qualified(scope), node.lineno)
        for child in ast.iter_child_nodes(node):
            self._visit(child, scope)

    @staticmethod
    def _qualified(scope: tuple[ast.AST, ...]) -> str:
        """Return the dotted class and function path of a scope chain."""
        names = [
            owner.name
            for owner in scope
            if isinstance(owner, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        return ".".join(names) or "<module>"

    @staticmethod
    def _is_type_checking(test: ast.expr) -> bool:
        """Whether a condition is the ``TYPE_CHECKING`` guard."""
        return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )

    @staticmethod
    def _is_sys_path(expression: ast.expr) -> bool:
        """Whether an expression is the ``sys.path`` attribute."""
        return (
            isinstance(expression, ast.Attribute)
            and expression.attr == "path"
            and isinstance(expression.value, ast.Name)
            and expression.value.id == "sys"
        )

    @classmethod
    def _mutates_import_path(cls, node: ast.AST) -> bool:
        """Whether a node changes ``sys.path`` in place or rebinds it."""
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            return node.func.attr in {"insert", "append", "extend", "remove"} and cls._is_sys_path(
                node.func.value
            )
        if isinstance(node, ast.Assign):
            return any(cls._is_sys_path(target) for target in node.targets)
        if isinstance(node, ast.AugAssign):
            return cls._is_sys_path(node.target)
        return False

    def _collect_native_aliases(self) -> None:
        """Bind every local name that refers to a stubbed native library."""
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in self._native_libraries:
                        self._native_import(root, node.lineno)
                        self._native_aliases[alias.asname or root] = root
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                root = node.module.split(".")[0]
                if root in self._native_libraries:
                    self._native_import(root, node.lineno)
                    for alias in node.names:
                        self._native_aliases[alias.asname or alias.name] = root

    def _native_import(self, library: str, line: int) -> None:
        """Refuse native-library imports in the orchestrator layer."""
        if self._area.is_application:
            self._add("native-import", library, line)

    def _external_imports(self) -> None:
        """Check imports of runtime owners from tests, tooling and examples."""
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in self._owned_roots:
                        self._external_import(alias.name, None, node.lineno)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                if node.module.split(".")[0] in self._owned_roots:
                    for alias in node.names:
                        self._external_import(node.module, alias.name, node.lineno)

    def _external_import(self, module: str, name: str | None, line: int) -> None:
        """Classify one imported runtime module or name against the supported API."""
        symbol = module if name is None else f"{module}.{name}"
        if any(part.startswith("_") for part in module.split(".")) or (
            name is not None and name.startswith("_")
        ):
            self._add("private-import", symbol, line)
            return
        if SourceLayoutChecker.owner(module) != module:
            if not self._area.is_unit_test:
                self._add("deep-import", symbol, line)
            return
        if name is not None and name not in self._exports.get(module, frozenset()):
            self._add("unexported-import", symbol, line)


class OwnershipChecker:
    """Check class ownership over maintained Python; every finding fails."""

    ROOTS: ClassVar[tuple[str, ...]] = (
        "src",
        "tests",
        "tools/governance/src",
        "tools/typing/stubs",
        "examples",
        "extensions",
    )
    # Research extensions are optional; a repository may have none.
    OPTIONAL_ROOTS: ClassVar[frozenset[str]] = frozenset({"extensions"})
    GUIDANCE: ClassVar[dict[str, str]] = {
        "module-function": (
            "only application orchestrators, command main functions, pytest hooks, lazy "
            "exports and native stubs may be module-level; make it a method of its owner"
        ),
        "nested-function": "give the behaviour a class owner instead of nesting a function",
        "lambda": "give the behaviour a class owner instead of a lambda",
        "native-call": "call stubbed native libraries only inside their owning adapter class",
        "native-import": "applications must reach native libraries through library adapters",
        "private-import": "import only supported public runtime names",
        "deep-import": "reference workflows import only names in an owner's __all__",
        "unexported-import": "the name is not in the owner's __all__",
        "path-mutation": "do not mutate sys.path; import installed packages",
    }

    @classmethod
    def scan(cls, repository_root: Path) -> tuple[OwnershipFinding, ...]:
        """Scan every governed Python file, including untracked files.

        Args:
            repository_root: Repository or fixture containing the governed roots.

        Returns:
            Findings sorted by path, rule, symbol and line.

        Raises:
            OSError: If a governed root is missing or a file cannot be read.
            UnicodeError: If a file is not UTF-8.
            SyntaxError: If a file cannot be parsed.
        """
        for name in cls.ROOTS:
            if name not in cls.OPTIONAL_ROOTS and not (repository_root / name).is_dir():
                raise FileNotFoundError(f"missing ownership source root: {name}")
        source_root = repository_root / "src"
        exports = {
            ".".join(path.relative_to(source_root).parts[:-1]): SourceLayoutChecker.exports(
                path.read_text(encoding="utf-8")
            )
            for path in sorted(source_root.rglob("__init__.py"))
        }
        owned_roots = frozenset(
            path.name for path in source_root.iterdir() if (path / "__init__.py").is_file()
        )
        stubs = repository_root / "tools/typing/stubs"
        native_libraries = frozenset(
            path.name if path.is_dir() else path.stem
            for path in stubs.iterdir()
            if path.is_dir() or path.suffix == ".pyi"
        )
        findings: list[OwnershipFinding] = []
        for name in cls.ROOTS:
            for path in sorted((repository_root / name).rglob("*")):
                if (
                    not path.is_file()
                    or path.suffix not in {".py", ".pyi"}
                    or "__pycache__" in path.parts
                ):
                    continue
                relative = path.relative_to(repository_root).as_posix()
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
                findings.extend(
                    _ModuleVisit(
                        SourceArea(relative),
                        tree,
                        native_libraries=native_libraries,
                        exports=exports,
                        owned_roots=owned_roots,
                    ).findings()
                )
        return tuple(sorted(findings))

    @classmethod
    def findings(cls, repository_root: Path) -> tuple[str, ...]:
        """Report every ownership finding with its location and guidance.

        Args:
            repository_root: Repository or fixture containing the governed roots.

        Returns:
            Stable diagnostics; a missing root or unreadable source fails closed.
        """
        try:
            observed = cls.scan(repository_root)
        except (OSError, UnicodeError, SyntaxError) as error:
            return (f"ownership scanner: {error}",)
        return tuple(
            f"{finding.path}:{finding.line}: {finding.rule} {finding.symbol}: "
            f"{cls.GUIDANCE[finding.rule]}"
            for finding in observed
        )
