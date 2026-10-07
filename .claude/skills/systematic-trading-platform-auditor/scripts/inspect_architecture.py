"""Map owner-level imports to audit dependency direction and blast radius.

The repository's governance checker is authoritative for import rules. This map
orients an audit instead: which functional owners depend on which, where import
cycles join owners, which imports break the documented direction, which
third-party packages each owner touches, and which modules depend on a module
under review (including through names re-exported by an owner's public API).

Typical use from the repository root:

    uv run --frozen --no-editable python \
        .claude/skills/systematic-trading-platform-auditor/scripts/inspect_architecture.py \
        --dependents execution.accounts
"""

from __future__ import annotations

# standard library imports
import argparse
import ast
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


@dataclass(frozen=True)
class ImportRecord:
    """Record one imported module as seen from an importing module."""

    importer: str
    imported: str
    path: str
    line: int
    names: tuple[str, ...]
    type_only: bool

    def as_record(self) -> dict[str, str | int | bool | list[str]]:
        """Return the import as a JSON-ready record."""
        return {
            "importer": self.importer,
            "imported": self.imported,
            "path": self.path,
            "line": self.line,
            "names": list(self.names),
            "type_only": self.type_only,
        }

    def location(self) -> str:
        """Return the source location of the import."""
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class DirectionIssue:
    """Record one import that breaks the documented dependency direction."""

    rule: str
    record: ImportRecord
    detail: str


class ModuleIndex:
    """Map Python files under a source root to dotted module names and re-exports."""

    def __init__(self, source_root: Path, display_root: Path) -> None:
        """Index every module under the source root."""
        self.source_root = source_root
        self.display_root = display_root
        self.paths: dict[str, Path] = {}
        for path in sorted(source_root.rglob("*.py")):
            relative = path.relative_to(source_root)
            if "__pycache__" in relative.parts:
                continue
            parts = list(relative.with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            if parts:
                self.paths[".".join(parts)] = path
        self.packages = {module.split(".")[0] for module in self.paths}
        self.reexports: dict[str, dict[str, str]] = {}

    def is_internal(self, module: str) -> bool:
        """Report whether a dotted name belongs to the indexed source tree."""
        return module.split(".")[0] in self.packages

    def is_package(self, module: str) -> bool:
        """Report whether a module is a package initializer."""
        path = self.paths.get(module)
        return path is not None and path.name == "__init__.py"

    def resolve(self, module: str) -> str:
        """Return the longest indexed prefix of a dotted name."""
        parts = module.split(".")
        while parts:
            candidate = ".".join(parts)
            if candidate in self.paths:
                return candidate
            parts.pop()
        return module

    def display(self, path: Path) -> str:
        """Return a path relative to the display root when possible."""
        try:
            return path.relative_to(self.display_root).as_posix()
        except ValueError:
            return path.as_posix()

    def defining_modules(self, record: ImportRecord) -> set[str]:
        """Return the modules that actually define what an import record uses."""
        resolved = self.resolve(record.imported)
        exports = self.reexports.get(resolved, {})
        if not record.names:
            return {resolved}
        return {exports.get(name, resolved) for name in record.names}


class ImportCollector(ast.NodeVisitor):
    """Collect the imports of one module, marking type-checking-only blocks."""

    def __init__(self, module: str, index: ModuleIndex) -> None:
        """Bind the module being read and the index used to resolve its imports."""
        self.module = module
        self.index = index
        self.path = index.display(index.paths[module])
        self.package = module if index.is_package(module) else module.rpartition(".")[0]
        self.records: list[ImportRecord] = []
        self._type_only_depth = 0

    def visit_If(self, node: ast.If) -> None:
        """Visit a TYPE_CHECKING block with its imports marked type-only."""
        if not self._is_type_checking(node.test):
            self.generic_visit(node)
            return
        self._type_only_depth += 1
        for statement in node.body:
            self.visit(statement)
        self._type_only_depth -= 1
        for statement in node.orelse:
            self.visit(statement)

    def visit_Import(self, node: ast.Import) -> None:
        """Record plain imports."""
        for alias in node.names:
            self._record(alias.name, node.lineno, ())

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Record from-imports, resolving relative bases and imported submodules."""
        base = self._absolute(node.module, node.level)
        if base is None:
            return
        grouped: dict[str, list[str]] = {}
        for alias in node.names:
            submodule = f"{base}.{alias.name}"
            if submodule in self.index.paths:
                grouped.setdefault(submodule, [])
            else:
                grouped.setdefault(base, []).append(alias.name)
        for imported, names in grouped.items():
            self._record(imported, node.lineno, tuple(names))

    def _absolute(self, module: str | None, level: int) -> str | None:
        """Return the absolute dotted base of an import statement."""
        if level == 0:
            return module
        parts = self.package.split(".") if self.package else []
        if level - 1 > len(parts):
            return None
        base = parts[: len(parts) - (level - 1)]
        if module:
            base.append(module)
        return ".".join(base) or None

    def _record(self, imported: str, line: int, names: tuple[str, ...]) -> None:
        """Append one import record."""
        self.records.append(
            ImportRecord(
                importer=self.module,
                imported=imported,
                path=self.path,
                line=line,
                names=names,
                type_only=self._type_only_depth > 0,
            )
        )

    @staticmethod
    def _is_type_checking(test: ast.expr) -> bool:
        """Report whether an if-test is the TYPE_CHECKING guard."""
        if isinstance(test, ast.Name):
            return test.id == "TYPE_CHECKING"
        return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


class OwnerResolver:
    """Resolve modules to functional owners and owners to layers."""

    DEFAULT_GROUPING: ClassVar[tuple[str, ...]] = (
        "applications",
        "market_data",
        "market_data.adapters",
        "market_data.adapters.providers",
        "market_data.adapters.venues",
        "reference_data",
        "research",
    )

    def __init__(self, grouping: tuple[str, ...]) -> None:
        """Bind the grouping namespaces whose subpackages are owners."""
        self.grouping = frozenset(grouping)

    def owner(self, module: str) -> str:
        """Return the functional owner of a module."""
        parts = module.split(".")
        owner = parts[0]
        for part in parts[1:]:
            if owner not in self.grouping:
                break
            owner = f"{owner}.{part}"
        return owner

    @staticmethod
    def layer(owner: str) -> str:
        """Return the layer of an owner."""
        return "application" if owner.split(".")[0] == "applications" else "library"


class ArchitectureGraph:
    """Derive owner dependencies, cycles, direction issues and dependents."""

    def __init__(self, records: list[ImportRecord], index: ModuleIndex, owners: OwnerResolver):
        """Bind every import record of the source tree."""
        self.index = index
        self.owners = owners
        self.internal = [record for record in records if index.is_internal(record.imported)]
        self.external = [record for record in records if not index.is_internal(record.imported)]

    def owner_of_import(self, record: ImportRecord) -> str:
        """Return the owner of an imported module."""
        return self.owners.owner(self.index.resolve(record.imported))

    def owner_edges(self, runtime_only: bool = False) -> dict[tuple[str, str], list[ImportRecord]]:
        """Return cross-owner imports keyed by (importing owner, imported owner)."""
        edges: dict[tuple[str, str], list[ImportRecord]] = {}
        for record in self.internal:
            if runtime_only and record.type_only:
                continue
            source = self.owners.owner(record.importer)
            target = self.owner_of_import(record)
            if source != target:
                edges.setdefault((source, target), []).append(record)
        return edges

    def owner_names(self) -> list[str]:
        """Return every owner with at least one module."""
        return sorted({self.owners.owner(module) for module in self.index.paths})

    def mutual_imports(self) -> list[tuple[str, str, ImportRecord, ImportRecord]]:
        """Return owner pairs that import each other at runtime, with one sample each way."""
        edges = self.owner_edges(runtime_only=True)
        return [
            (source, target, records[0], edges[(target, source)][0])
            for (source, target), records in sorted(edges.items())
            if source < target and (target, source) in edges
        ]

    def cycles(self) -> list[list[str]]:
        """Return groups of owners whose runtime imports reach one another."""
        adjacency: dict[str, set[str]] = {}
        for source, target in self.owner_edges(runtime_only=True):
            adjacency.setdefault(source, set()).add(target)
        nodes = sorted(
            set(adjacency) | {node for targets in adjacency.values() for node in targets}
        )
        reach = {node: self._reachable(node, adjacency) for node in nodes}
        groups: list[list[str]] = []
        assigned: set[str] = set()
        for node in nodes:
            if node in assigned or node not in reach[node]:
                continue
            group = sorted(
                other for other in nodes if other in reach[node] and node in reach[other]
            )
            groups.append(group)
            assigned.update(group)
        return groups

    def direction_issues(self) -> list[DirectionIssue]:
        """Return imports that break the documented dependency direction."""
        issues: list[DirectionIssue] = []
        for record in self.internal:
            source = self.owners.owner(record.importer)
            target = self.owner_of_import(record)
            if source == target:
                continue
            resolved = self.index.resolve(record.imported)
            source_layer = OwnerResolver.layer(source)
            if source_layer == "library" and OwnerResolver.layer(target) == "application":
                issues.append(
                    DirectionIssue("library-imports-application", record, f"{source} -> {target}")
                )
            if source_layer == "application" and OwnerResolver.layer(target) == "application":
                issues.append(
                    DirectionIssue("sibling-application", record, f"{source} -> {target}")
                )
            if resolved != target and not target.startswith(f"{resolved}."):
                issues.append(
                    DirectionIssue("below-owner-api", record, f"{resolved} is inside {target}")
                )
            breach = self._private_breach(record, resolved)
            if breach is not None:
                issues.append(DirectionIssue("private-name", record, breach))
        return issues

    def _private_breach(self, record: ImportRecord, resolved: str) -> str | None:
        """Return what an import reaches outside a private name's package scope, if anything."""
        parts = resolved.split(".")
        private_names = [name for name in record.names if name.startswith("_")]
        scope: str | None = None
        for position, part in enumerate(parts):
            if part.startswith("_"):
                scope = ".".join(parts[:position])
                break
        if scope is None and private_names:
            scope = resolved if self.index.is_package(resolved) else resolved.rpartition(".")[0]
        if scope is None or self._within(record.importer, scope):
            return None
        return ", ".join(private_names) if private_names else resolved

    def dependents(self, module: str, transitive: bool) -> list[ImportRecord]:
        """Return imports that reach a module or its submodules."""
        found: list[ImportRecord] = []
        seen_records: set[ImportRecord] = set()
        visited: set[str] = {module}
        frontier = [module]
        while frontier:
            current = frontier.pop()
            for record in self.internal:
                defining = self.index.defining_modules(record)
                if not any(self._within(name, current) for name in defining):
                    continue
                if record not in seen_records:
                    seen_records.add(record)
                    found.append(record)
                if transitive and record.importer not in visited:
                    visited.add(record.importer)
                    frontier.append(record.importer)
        return sorted(found, key=self._record_key)

    def third_party(self) -> dict[str, list[str]]:
        """Return the non-standard-library top-level packages each owner imports."""
        packages: dict[str, set[str]] = {}
        for record in self.external:
            top = record.imported.split(".")[0]
            if top in sys.stdlib_module_names or top == "__future__":
                continue
            packages.setdefault(self.owners.owner(record.importer), set()).add(top)
        return {owner: sorted(names) for owner, names in packages.items()}

    @staticmethod
    def _within(name: str, module: str) -> bool:
        """Report whether a dotted name is a module or lies inside it."""
        return name == module or name.startswith(f"{module}.")

    @staticmethod
    def _reachable(start: str, adjacency: dict[str, set[str]]) -> set[str]:
        """Return every owner reachable from a starting owner."""
        seen: set[str] = set()
        frontier = list(adjacency.get(start, set()))
        while frontier:
            node = frontier.pop()
            if node in seen:
                continue
            seen.add(node)
            frontier.extend(adjacency.get(node, set()))
        return seen

    @staticmethod
    def _record_key(record: ImportRecord) -> tuple[str, int]:
        """Order import records by location."""
        return (record.path, record.line)


class ArchitectureScan:
    """Build the module index, re-export map and import records of a source tree."""

    def __init__(self, source_root: Path, display_root: Path) -> None:
        """Bind the source tree to scan."""
        self.index = ModuleIndex(source_root, display_root)

    def records(self) -> tuple[list[ImportRecord], list[str]]:
        """Return every import record and any files that could not be parsed."""
        records: list[ImportRecord] = []
        unparsed: list[str] = []
        for module, path in self.index.paths.items():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as error:
                unparsed.append(f"{self.index.display(path)}: {type(error).__name__}: {error}")
                continue
            collector = ImportCollector(module, self.index)
            collector.visit(tree)
            records.extend(collector.records)
            if self.index.is_package(module):
                self.index.reexports[module] = self._exports(collector.records, module)
        return records, unparsed

    def _exports(self, records: list[ImportRecord], package: str) -> dict[str, str]:
        """Map each name a package imports from inside itself to its defining module."""
        exports: dict[str, str] = {}
        for record in records:
            resolved = self.index.resolve(record.imported)
            if resolved != package and resolved.startswith(f"{package}."):
                for name in record.names:
                    exports[name] = resolved
        return exports


class ArchitectureReport:
    """Render the owner map, cycles, direction issues and dependents."""

    def __init__(self, graph: ArchitectureGraph, unparsed: list[str], source: str) -> None:
        """Bind the analysed graph."""
        self.graph = graph
        self.unparsed = unparsed
        self.source = source

    def overview_text(self) -> str:
        """Render the default overview."""
        edges = self.graph.owner_edges()
        owners = self.graph.owner_names()
        lines = [
            f"Architecture map of {self.source}: {len(self.graph.index.paths)} modules in "
            f"{len(owners)} owners; {len(edges)} owner-to-owner dependencies.",
            "Authoritative import rules: uv run --frozen --no-editable "
            "alpha-governance-engineering-standards",
            "",
        ]
        lines.extend(self._issue_lines())
        lines.extend(self._cycle_lines())
        lines.extend(self._owner_table(edges, owners))
        lines.extend(self._unparsed_lines())
        return "\n".join(lines)

    def owner_text(self, owner: str) -> str:
        """Render one owner's outgoing and incoming dependencies."""
        edges = self.graph.owner_edges()
        outgoing = sorted((key, value) for key, value in edges.items() if key[0] == owner)
        incoming = sorted((key, value) for key, value in edges.items() if key[1] == owner)
        lines = [f"Owner {owner} ({OwnerResolver.layer(owner)})", "", "Depends on:"]
        lines.extend(self._edge_lines(outgoing, 1))
        lines.extend(["", "Used by:"])
        lines.extend(self._edge_lines(incoming, 0))
        packages = self.graph.third_party().get(owner, [])
        lines.extend(["", f"Third-party imports: {', '.join(packages) if packages else 'none'}"])
        return "\n".join(lines)

    def dependents_text(self, module: str, transitive: bool) -> str:
        """Render the imports that reach a module."""
        records = self.graph.dependents(module, transitive)
        importers = sorted({record.importer for record in records})
        owners = sorted({self.graph.owners.owner(name) for name in importers})
        scope = "transitively" if transitive else "directly"
        lines = [
            f"{len(importers)} modules in {len(owners)} owners import {module} {scope} "
            "(names re-exported by package APIs are resolved to their defining module).",
            "",
        ]
        for owner in owners:
            lines.append(owner)
            lines.extend(
                f"  {record.location()}  {record.importer} imports {record.imported}"
                + (f" ({', '.join(record.names)})" if record.names else "")
                + (" [type-only]" if record.type_only else "")
                for record in records
                if self.graph.owners.owner(record.importer) == owner
            )
        return "\n".join(lines)

    def json_text(self, module: str | None, transitive: bool) -> str:
        """Render the complete analysis as JSON."""
        edges = self.graph.owner_edges()
        document: dict[str, object] = {
            "source": self.source,
            "modules": len(self.graph.index.paths),
            "owners": self.graph.owner_names(),
            "owner_edges": [
                {
                    "from": source,
                    "to": target,
                    "imports": [record.as_record() for record in records],
                }
                for (source, target), records in sorted(edges.items())
            ],
            "cycles": self.graph.cycles(),
            "mutual_imports": [
                {"owners": [first, second], "samples": [forward.as_record(), back.as_record()]}
                for first, second, forward, back in self.graph.mutual_imports()
            ],
            "direction_issues": [
                {"rule": issue.rule, "detail": issue.detail, "import": issue.record.as_record()}
                for issue in self.graph.direction_issues()
            ],
            "third_party": self.graph.third_party(),
            "unparsed": self.unparsed,
        }
        if module is not None:
            document["dependents"] = [
                record.as_record() for record in self.graph.dependents(module, transitive)
            ]
        return json.dumps(document, indent=2, sort_keys=True)

    def _issue_lines(self) -> list[str]:
        """Return the direction-issue section."""
        issues = self.graph.direction_issues()
        lines = [f"Direction issues: {len(issues)}"]
        lines.extend(
            f"  [{issue.rule}] {issue.record.location()}  {issue.record.importer} imports "
            f"{issue.record.imported} ({issue.detail})"
            + (" [type-only]" if issue.record.type_only else "")
            for issue in issues
        )
        lines.append("")
        return lines

    def _cycle_lines(self) -> list[str]:
        """Return mutual owner imports and larger runtime cycles (TYPE_CHECKING excluded)."""
        mutual = self.graph.mutual_imports()
        lines = [f"Owners importing each other at runtime: {len(mutual)}"]
        for first, second, forward, backward in mutual:
            lines.append(f"  {first} <-> {second}")
            lines.append(f"    {forward.location()}  {forward.importer} imports {forward.imported}")
            lines.append(
                f"    {backward.location()}  {backward.importer} imports {backward.imported}"
            )
        cycles = self.graph.cycles()
        lines.extend(["", f"Runtime import cycles between owners: {len(cycles)}"])
        lines.extend(
            f"  {len(group)} owners: {', '.join(group)}  (inspect with --owner <name>)"
            for group in cycles
        )
        lines.append("")
        return lines

    def _owner_table(
        self, edges: dict[tuple[str, str], list[ImportRecord]], owners: list[str]
    ) -> list[str]:
        """Return the per-owner fan-out, fan-in and third-party table."""
        fan_out = Counter(source for source, _ in edges)
        fan_in = Counter(target for _, target in edges)
        third_party = self.graph.third_party()
        lines = [f"{'owner':<36} {'layer':<12} {'depends on':>10} {'used by':>8}  third-party"]
        lines.extend(
            f"{owner:<36} {OwnerResolver.layer(owner):<12} {fan_out[owner]:>10} "
            f"{fan_in[owner]:>8}  {', '.join(third_party.get(owner, []))}"
            for owner in owners
        )
        return lines

    def _unparsed_lines(self) -> list[str]:
        """Return the unparsed-file section, if any."""
        if not self.unparsed:
            return []
        return ["", "Could not parse:", *(f"  {entry}" for entry in self.unparsed)]

    @staticmethod
    def _edge_lines(
        edges: list[tuple[tuple[str, str], list[ImportRecord]]], other_index: int
    ) -> list[str]:
        """Return detail lines for a list of owner edges."""
        if not edges:
            return ["  none"]
        lines: list[str] = []
        for key, records in edges:
            lines.append(f"  {key[other_index]} ({len(records)} imports)")
            lines.extend(
                f"    {record.location()}  {record.importer} imports {record.imported}"
                + (" [type-only]" if record.type_only else "")
                for record in records[:5]
            )
            if len(records) > 5:
                lines.append(f"    ... {len(records) - 5} more")
        return lines


class InspectOptions(argparse.Namespace):
    """Hold the parsed command-line options with precise types."""

    source_root: str
    owner: str | None
    dependents: str | None
    transitive: bool
    grouping: str | None
    output: str


class InspectCommand:
    """Own the command-line interface of the architecture inspector."""

    @staticmethod
    def parser() -> argparse.ArgumentParser:
        """Build the argument parser."""
        parser = argparse.ArgumentParser(
            description="Map owner-level imports for an architecture audit."
        )
        parser.add_argument(
            "--source-root", default="src", help="package root to scan (default: src)"
        )
        parser.add_argument("--owner", help="show one owner's dependencies, e.g. execution")
        parser.add_argument(
            "--dependents", help="list imports reaching a module, e.g. execution.accounts"
        )
        parser.add_argument(
            "--transitive", action="store_true", help="follow --dependents transitively"
        )
        parser.add_argument(
            "--grouping",
            help="comma-separated grouping namespaces whose subpackages are owners "
            f"(default: {','.join(OwnerResolver.DEFAULT_GROUPING)})",
        )
        parser.add_argument(
            "--format", dest="output", choices=("text", "json"), default="text", help="output"
        )
        return parser


def main(argv: list[str] | None = None) -> int:
    """Scan the source tree and print the requested architecture view."""
    options = InspectCommand.parser().parse_args(argv, namespace=InspectOptions())
    source_root = Path(options.source_root).resolve()
    if not source_root.is_dir():
        print(f"inspect_architecture: no such directory: {source_root}", file=sys.stderr)
        return 2
    grouping = (
        tuple(name.strip() for name in options.grouping.split(",") if name.strip())
        if options.grouping
        else OwnerResolver.DEFAULT_GROUPING
    )
    scan = ArchitectureScan(source_root, Path.cwd())
    records, unparsed = scan.records()
    graph = ArchitectureGraph(records, scan.index, OwnerResolver(grouping))
    report = ArchitectureReport(graph, unparsed, options.source_root)
    if options.output == "json":
        print(report.json_text(options.dependents, options.transitive))
    elif options.dependents:
        print(report.dependents_text(options.dependents, options.transitive))
    elif options.owner:
        print(report.owner_text(options.owner))
    else:
        print(report.overview_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
