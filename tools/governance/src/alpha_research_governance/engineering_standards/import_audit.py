"""Audit code outside the repository for supported imports of installed platform owners."""

from __future__ import annotations

# standard library imports
import ast
from dataclasses import dataclass
from importlib.machinery import ModuleSpec, PathFinder
from importlib.metadata import packages_distributions
from pathlib import Path
from typing import ClassVar

# project library imports
from alpha_research_governance.engineering_standards.source_layout import SourceLayoutChecker


@dataclass(frozen=True, order=True)
class ImportFinding:
    """Locate one unsupported import or import-path mutation."""

    path: str
    line: int
    rule: str
    symbol: str


class ImportAudit:
    """Apply the platform's supported-import rules to an external source tree.

    Owners are the top-level packages of installed ``alpha-research-*`` distributions.
    Each owner's ``__all__`` is read from its installed ``__init__.py`` source, which is
    located and parsed but never imported, so the audit runs no platform code. Private,
    deep and unexported imports and ``sys.path`` mutation are findings. The repository's
    own style rules (classes over module functions, no lambdas) are not imposed.
    """

    GUIDANCE: ClassVar[dict[str, str]] = {
        "private-import": "import only supported public names",
        "deep-import": "import from the owner package's __init__, not its modules",
        "unexported-import": "the name is not in the owner's __all__",
        "unknown-owner": "the owner package is not installed in this environment",
        "path-mutation": "do not mutate sys.path; install the package instead",
        "unshipped-import": "the operating release does not ship this module; see the QR API map",
    }

    def __init__(
        self, owners: frozenset[str] | None = None, *, shipped: frozenset[str] | None = None
    ) -> None:
        """Bind the installed platform owners and, for a release, the files it ships.

        Args:
            owners: Platform owner packages; ``None`` reads the installed ones.
            shipped: Platform source paths a release ships (``research/reports/__init__.py``);
                ``None`` accepts any installed owner.
        """
        self._owners = self.installed_owners() if owners is None else owners
        self._shipped = shipped
        self._exports: dict[str, frozenset[str] | None] = {}

    @staticmethod
    def installed_owners() -> frozenset[str]:
        """Return top-level packages provided by installed ``alpha-research-*`` distributions."""
        return frozenset(
            package
            for package, names in packages_distributions().items()
            if any(name.startswith("alpha-research-") for name in names)
            and not package.startswith("_")
        )

    def audit(self, root: Path) -> tuple[ImportFinding, ...]:
        """Check every Python file under ``root``, including untracked files.

        Raises:
            OSError: The root is absent or a file cannot be read.
            SyntaxError: A file cannot be parsed.
        """
        if not root.is_dir():
            raise FileNotFoundError(f"import audit root is not a directory: {root}")
        findings: list[ImportFinding] = []
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts or any(part.startswith(".") for part in path.parts):
                continue
            relative = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            findings.extend(self._file(relative, tree))
        return tuple(sorted(findings))

    def report(self, findings: tuple[ImportFinding, ...]) -> tuple[str, ...]:
        """Format findings with their guidance."""
        return tuple(
            f"{item.path}:{item.line}: {item.rule} {item.symbol} ({self.GUIDANCE[item.rule]})"
            for item in findings
        )

    def _file(self, path: str, tree: ast.Module) -> tuple[ImportFinding, ...]:
        """Classify one module's absolute platform imports and path mutations."""
        findings: list[ImportFinding] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    rule = self._rule(alias.name, None)
                    if rule is not None:
                        findings.append(ImportFinding(path, node.lineno, rule, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    rule = self._rule(node.module, alias.name)
                    if rule is not None:
                        symbol = f"{node.module}.{alias.name}"
                        findings.append(ImportFinding(path, node.lineno, rule, symbol))
            elif (line := self._mutation_line(node)) is not None:
                findings.append(ImportFinding(path, line, "path-mutation", "sys.path"))
        return tuple(findings)

    def _rule(self, module: str, name: str | None) -> str | None:
        """Return the violated rule for one imported module or name, if any."""
        if module.split(".")[0] not in self._owners:
            return None
        if any(part.startswith("_") for part in module.split(".")) or (
            name is not None and name.startswith("_")
        ):
            return "private-import"
        if SourceLayoutChecker.owner(module) != module:
            return "deep-import"
        if self._shipped is not None and module.replace(".", "/") + "/__init__.py" not in (
            self._shipped
        ):
            return "unshipped-import"
        exports = self._owner_exports(module)
        if exports is None:
            return "unknown-owner"
        if name is not None and name not in exports:
            return "unexported-import"
        return None

    def _owner_exports(self, module: str) -> frozenset[str] | None:
        """Parse an installed owner's ``__all__`` without importing it."""
        if module not in self._exports:
            spec = self._spec(module)
            origin = None if spec is None else spec.origin
            self._exports[module] = (
                None
                if origin is None or not origin.endswith("__init__.py")
                else SourceLayoutChecker.exports(Path(origin).read_text(encoding="utf-8"))
            )
        return self._exports[module]

    @staticmethod
    def _spec(module: str) -> ModuleSpec | None:
        """Locate a package through the path finder alone, executing no initializer."""
        spec: ModuleSpec | None = None
        parts = module.split(".")
        for length in range(1, len(parts) + 1):
            name = ".".join(parts[:length])
            locations = None if spec is None else spec.submodule_search_locations
            if spec is not None and locations is None:
                return None
            spec = PathFinder.find_spec(name, None if locations is None else list(locations))
            if spec is None:
                return None
        return spec

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
    def _mutation_line(cls, node: ast.AST) -> int | None:
        """Return the line of a node that changes ``sys.path`` in place or rebinds it."""
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"insert", "append", "extend", "remove"}
            and cls._is_sys_path(node.func.value)
        ):
            return node.lineno
        if isinstance(node, ast.Assign) and any(cls._is_sys_path(item) for item in node.targets):
            return node.lineno
        if isinstance(node, ast.AugAssign) and cls._is_sys_path(node.target):
            return node.lineno
        return None
