"""Enforce functional ownership, public imports and installed command boundaries."""

from __future__ import annotations

# standard library imports
import ast
import tomllib
from collections import Counter
from pathlib import Path
from typing import ClassVar

# third party library imports
from pydantic import TypeAdapter


class SourceLayoutChecker:
    """Inspect runtime ASTs and command metadata without importing application code."""

    _GROUPS: ClassVar[frozenset[str]] = frozenset(
        {
            "applications",
            "reference_data",
            "market_data",
            "research",
            "market_data.adapters",
            "market_data.adapters.providers",
            "market_data.adapters.venues",
        }
    )
    _FOUNDATIONS: ClassVar[frozenset[str]] = frozenset(
        {"reference_data", "financial_units", "serialization", "configuration"}
    )
    _TABLE: ClassVar[TypeAdapter[dict[str, object]]] = TypeAdapter(dict[str, object])
    _STRINGS: ClassVar[TypeAdapter[dict[str, str]]] = TypeAdapter(dict[str, str])

    @classmethod
    def owner(cls, module: str) -> str:
        """Resolve the functional owner of an absolute implementation module or API.

        Args:
            module: Absolute import name without an initializer suffix.

        Returns:
            Nearest non-grouping package, including concrete provider and venue owners.
        """
        parts = module.split(".")
        for length in range(1, len(parts) + 1):
            candidate = ".".join(parts[:length])
            if candidate not in cls._GROUPS:
                return candidate
        return module

    @classmethod
    def scan(cls, module: str, source: str, *, is_api: bool = False) -> tuple[str, ...]:
        """Check one module's complete AST, including conditional and relative imports.

        Args:
            module: Absolute runtime module name.
            source: Complete UTF-8 Python source.
            is_api: Whether this is the owner's sole public initializer.

        Returns:
            Stable actionable boundary findings; malformed source fails closed.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            return (f"{module}: invalid Python: {error.msg}",)
        owner = cls.owner(module)
        findings: list[str] = []
        package = module if is_api else module.rpartition(".")[0]
        for node in ast.walk(tree):
            targets: list[tuple[str, tuple[str, ...]]] = []
            if isinstance(node, ast.Import):
                targets = [(item.name, ()) for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                target = node.module or ""
                if node.level:
                    parts = package.split(".")
                    if node.level > len(parts):
                        findings.append(
                            f"{module}:{node.lineno}: relative import escapes ownership"
                        )
                        continue
                    target = ".".join(
                        parts[: len(parts) - node.level + 1] + ([target] if target else [])
                    )
                targets = [(target, tuple(item.name for item in node.names))]
            for target, names in targets:
                problem = cls._import_problem(owner, target, names)
                if problem:
                    findings.append(f"{module}: {problem}")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "main" or node.name.endswith("_main"):
                    if not owner.startswith("applications.") or node.name != "main":
                        findings.append(
                            f"{module}:{node.lineno}: runnable entry functions "
                            "belong to application main"
                        )
            if isinstance(node, ast.If) and any(
                isinstance(child, ast.Name) and child.id == "__name__"
                for child in ast.walk(node.test)
            ):
                findings.append(
                    f"{module}:{node.lineno}: use the sole installed application entrypoint"
                )
        if module.endswith(".__main__"):
            findings.append(f"{module}: independently runnable modules are forbidden")
        if not is_api and any(
            isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(child, ast.Name) and child.id == "__all__" for child in ast.walk(node)
            )
            for node in tree.body
        ):
            findings.append(f"{module}: only the public initializer may declare __all__")
        if is_api and module in cls._GROUPS:
            if any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body):
                findings.append(f"{module}: grouping initializers must not eagerly import children")
        elif is_api:
            exports = [
                node
                for node in tree.body
                if isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in node.targets
                )
            ]
            if (
                len(exports) != 1
                or not isinstance(exports[0].value, (ast.List, ast.Tuple))
                or any(
                    not isinstance(item, ast.Constant)
                    or not isinstance(item.value, str)
                    or item.value.startswith("_")
                    for item in exports[0].value.elts
                )
            ):
                findings.append(f"{module}: public API requires one explicit nonprivate __all__")
        if is_api and module not in cls._GROUPS:
            bound: set[str] = set()
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    bound.update(item.asname or item.name for item in node.names)
                elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    bound.add(node.name)
                elif isinstance(node, ast.Assign):
                    bound.update(
                        target.id for target in node.targets if isinstance(target, ast.Name)
                    )
                elif isinstance(node, (ast.AnnAssign, ast.TypeAlias)):
                    binding = node.target if isinstance(node, ast.AnnAssign) else node.name
                    if isinstance(binding, ast.Name):
                        bound.add(binding.id)
            bound.update(cls._checked_lazy_exports(tree))
            for missing in sorted(cls._exports(source) - bound):
                findings.append(f"{module}: public export {missing} is not bound")
        return tuple(findings)

    @staticmethod
    def _checked_lazy_exports(tree: ast.Module) -> frozenset[str]:
        """Recognize only a typed and exhaustively named lazy public binding."""
        type_imports: set[str] = set()
        for node in tree.body:
            if not (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id == "TYPE_CHECKING"
            ):
                continue
            for child in node.body:
                if isinstance(child, ast.ImportFrom):
                    type_imports.update(alias.asname or alias.name for alias in child.names)
        getters = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "__getattr__"
        ]
        if len(getters) != 1:
            return frozenset()
        body = getters[0].body
        if not (
            body
            and isinstance(body[-1], ast.Raise)
            and isinstance(body[-1].exc, ast.Call)
            and isinstance(body[-1].exc.func, ast.Name)
            and body[-1].exc.func.id == "AttributeError"
        ):
            return frozenset()
        bound: set[str] = set()
        for branch in body:
            if not (
                isinstance(branch, ast.If)
                and isinstance(branch.test, ast.Compare)
                and isinstance(branch.test.left, ast.Name)
                and branch.test.left.id == "name"
                and len(branch.test.ops) == 1
                and isinstance(branch.test.ops[0], ast.In)
                and len(branch.test.comparators) == 1
                and isinstance(branch.test.comparators[0], (ast.Set, ast.Tuple, ast.List))
            ):
                continue
            guard_items = branch.test.comparators[0].elts
            if not all(
                isinstance(item, ast.Constant) and isinstance(item.value, str)
                for item in guard_items
            ):
                continue
            guard = {item.value for item in guard_items if isinstance(item, ast.Constant)}
            module_aliases = {
                alias.asname or alias.name
                for child in branch.body
                if isinstance(child, ast.ImportFrom)
                for alias in child.names
            }
            maps: list[ast.Dict] = []
            for child in branch.body:
                if (
                    isinstance(child, ast.AnnAssign)
                    and isinstance(child.target, ast.Name)
                    and child.target.id == "exports"
                    and isinstance(child.value, ast.Dict)
                ) or (
                    isinstance(child, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == "exports"
                        for target in child.targets
                    )
                    and isinstance(child.value, ast.Dict)
                ):
                    maps.append(child.value)
            if len(maps) != 1 or not any(
                isinstance(child, ast.Return)
                and isinstance(child.value, ast.Subscript)
                and isinstance(child.value.value, ast.Name)
                and child.value.value.id == "exports"
                and isinstance(child.value.slice, ast.Name)
                and child.value.slice.id == "name"
                for child in branch.body
            ):
                continue
            mapping = maps[0]
            if len(mapping.keys) != len(guard):
                continue
            mapped: set[str] = set()
            for key, value in zip(mapping.keys, mapping.values, strict=True):
                if not (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                    and value.value.id in module_aliases
                    and value.attr == key.value
                ):
                    break
                mapped.add(key.value)
            if mapped == guard:
                bound.update(mapped & type_imports)
        return frozenset(bound)

    @classmethod
    def _import_problem(cls, owner: str, target: str, names: tuple[str, ...]) -> str:
        """Identify forbidden dependency direction or cross-owner implementation access."""
        target_owner = cls.owner(target)
        if target == "alpha_research" or target.startswith("alpha_research."):
            return "retired alpha_research namespace import"
        if target == "applications" or target.startswith("applications."):
            if owner != target_owner:
                return "libraries and peer applications cannot import application workflows"
        root = target.split(".")[0]
        if owner == "configuration" and root in {"runtime", "applications", "market_data"}:
            return "configuration cannot import runtime or source factories"
        if owner == "market_data.contracts" and root not in cls._FOUNDATIONS | {"market_data"}:
            if root in {"applications", "runtime", "telemetry", "research"}:
                return "neutral contracts cannot import orchestration or services"
        if owner == "market_data.contracts" and root == "market_data" and target_owner != owner:
            return "neutral contracts cannot import concrete services or adapters"
        if owner in {
            "market_data.storage",
            "market_data.validation",
            "market_data.query",
            "market_data.replay",
            "market_data.books",
            "market_data.datasets",
            "market_data.collection",
        } and target.startswith("market_data.adapters"):
            return "shared market-data services require injected source capabilities"
        if owner == target_owner:
            return ""
        # The error translator is deliberately internal to the reference-data family.
        if (
            owner in {"reference_data.instruments", "reference_data.calendars"}
            and target == "reference_data._validation"
        ):
            return ""
        owned = root in cls._FOUNDATIONS | {
            "market_data",
            "applications",
            "runtime",
            "telemetry",
            "research",
            "accounting",
            "risk",
            "simulation",
            "strategies",
        }
        if owned and (
            any(name.startswith("_") or name == "*" for name in names)
            or any(part.startswith("_") for part in target.split("."))
        ):
            return "cross-owner private import"
        if owned and target != target_owner:
            return f"cross-owner imports must use public API {target_owner}"
        # `from owner import implementation` cannot bypass the API rule.
        if owned and any(name[:1].islower() for name in names) and target in cls._GROUPS:
            return "import a functional public API instead of a grouping namespace"
        return ""

    @staticmethod
    def _exports(source: str) -> frozenset[str]:
        """Read a validated literal API declaration without importing the package."""
        for node in ast.parse(source).body:
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in node.targets
                )
                and isinstance(node.value, (ast.List, ast.Tuple))
            ):
                return frozenset(
                    item.value
                    for item in node.value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
        return frozenset()

    @classmethod
    def findings(cls, repository_root: Path) -> tuple[str, ...]:
        """Check every shipped source module and actual installed entrypoint declaration.

        Args:
            repository_root: Checkout containing src and pyproject.toml.

        Returns:
            Import, API, entrypoint or metadata findings; absent inputs fail closed.
        """
        findings: list[str] = []
        try:
            source_root = repository_root / "src"
            if not source_root.is_dir():
                return ("source layout: missing src root",)
            sources = sorted(source_root.rglob("*.py"))
            apis = {
                ".".join(path.relative_to(source_root).parts[:-1]): cls._exports(
                    path.read_text(encoding="utf-8")
                )
                for path in sources
                if path.name == "__init__.py"
            }
            definitions: Counter[str] = Counter()
            modules: set[str] = set()
            for path in sources:
                parts = path.relative_to(source_root).with_suffix("").parts
                is_api = parts[-1] == "__init__"
                module = ".".join(parts[:-1] if is_api else parts)
                modules.add(module)
                source = path.read_text(encoding="utf-8")
                findings.extend(cls.scan(module, source, is_api=is_api))
                tree = ast.parse(source)
                package = module if is_api else module.rpartition(".")[0]
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ImportFrom):
                        continue
                    target = node.module or ""
                    if node.level:
                        target = ".".join(
                            package.split(".")[: -node.level + 1 or None]
                            + ([target] if target else [])
                        )
                    if target in apis and cls.owner(module) != cls.owner(target):
                        for name in node.names:
                            if name.name not in apis[target]:
                                findings.append(
                                    f"{module}:{node.lineno}: {target}.{name.name} "
                                    "is not in the owner's public API"
                                )
                definitions[cls.owner(module)] += sum(
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "main"
                    for node in ast.walk(tree)
                )
            for owner, count in definitions.items():
                if count > 1:
                    findings.append(f"{owner}: at most one command entry function is permitted")
            parsed: object = tomllib.loads(
                (repository_root / "pyproject.toml").read_text(encoding="utf-8")
            )
            document = cls._TABLE.validate_python(parsed)
            project = cls._TABLE.validate_python(document.get("project"))
            scripts = cls._STRINGS.validate_python(project.get("scripts", {}))
            commands: Counter[str] = Counter()
            for command, entry in scripts.items():
                module, separator, function = entry.partition(":")
                owner = cls.owner(module)
                if (
                    not separator
                    or function != "main"
                    or not owner.startswith("applications.")
                    or module != owner
                ):
                    findings.append(f"{command}: command must bind applications.<owner>:main")
                elif (
                    module not in modules
                    or definitions[owner] != 1
                    or "main" not in apis.get(module, frozenset())
                ):
                    findings.append(f"{command}: command must resolve one actual application main")
                commands[owner] += 1
            for owner, count in commands.items():
                if count > 1:
                    findings.append(f"{owner}: multiple installed command bindings")
        except (OSError, UnicodeError, ValueError, SyntaxError) as error:
            findings.append(f"source layout: {error}")
        return tuple(findings)
