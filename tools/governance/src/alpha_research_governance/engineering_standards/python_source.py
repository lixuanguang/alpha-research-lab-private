"""Check Python source for the repository's retained clarity rules."""

from __future__ import annotations

# standard library imports
import ast
import inspect
import io
import re
import sys
import tokenize
from dataclasses import dataclass, field
from typing import ClassVar

# project library imports
from alpha_research_governance._models import ImmutableModel


class PythonFinding(ImmutableModel):
    """Represent one deterministic Python source standards finding."""

    path: str
    symbol: str
    rule: str
    detail: str
    line: int

    @property
    def key(self) -> tuple[str, str, str, str]:
        """Return the line-independent identity of this finding.

        Returns:
            The source path, symbol, rule, and stable detail key.
        """
        return self.path, self.symbol, self.rule, self.detail

    def sort_key(self) -> tuple[str, str, str, str, int]:
        """Return the deterministic ordering key for this finding.

        Returns:
            The stable identity followed by the source line.
        """
        return (*self.key, self.line)


@dataclass
class _Scope:
    """Track typing aliases and lexical bindings for one Python scope."""

    symbol: str
    parent: _Scope | None
    aliases: dict[str, str] = field(default_factory=dict)
    bindings: set[str] = field(default_factory=set)

    def bind_alias(self, name: str, alias: str) -> None:
        """Bind a name to a recognized typing alias."""
        self.aliases[name] = alias
        self.bindings.add(name)

    def bind_name(self, name: str) -> None:
        """Record a local binding that shadows an outer alias."""
        self.aliases.pop(name, None)
        self.bindings.add(name)

    def resolve(self, name: str) -> str | None:
        """Resolve a name through the lexical scope chain."""
        if name in self.aliases:
            return self.aliases[name]
        if name in self.bindings or self.parent is None:
            return None
        return self.parent.resolve(name)


@dataclass(frozen=True)
class _ImportRecord:
    """Describe one direct import statement in an import block."""

    node: ast.Import | ast.ImportFrom
    category: str
    line: int


class PythonSourceChecker:
    """Check one Python source string against the retained clarity contract."""

    _path: str
    _lines: tuple[str, ...]
    _findings: list[PythonFinding]
    _overload_aliases: set[str]
    _overload_modules: set[str]

    _HEADINGS: ClassVar[dict[str, str]] = {
        "standard": "# standard library imports",
        "third-party": "# third party library imports",
        "project": "# project library imports",
    }
    _CATEGORY_RANK: ClassVar[dict[str, int]] = {"standard": 0, "third-party": 1, "project": 2}
    _PROJECT_ROOTS: ClassVar[tuple[str, ...]] = (
        "applications",
        "configuration",
        "financial_units",
        "market_data",
        "reference_data",
        "research",
        "accounting",
        "execution",
        "portfolio",
        "risk",
        "simulation",
        "strategies",
        "runtime",
        "serialization",
        "telemetry",
        "alpha_research_governance",
    )
    _TYPING_MODULES: ClassVar[frozenset[str]] = frozenset({"typing", "typing_extensions"})
    _SECTION_NAMES: ClassVar[tuple[str, ...]] = ("Args", "Returns", "Yields", "Raises")
    _ARGUMENT_ENTRY: ClassVar[re.Pattern[str]] = re.compile(
        r"^\s{2,}(?P<name>\*{0,2}[A-Za-z_]\w*)(?:\s*\([^)]*\))?\s*:\s*"
        r"(?P<description>.*)$"
    )

    def scan(self, path: str, source: str) -> tuple[PythonFinding, ...]:
        """Parse source and return stable import, typing, and documentation findings.

        Args:
            path: Repository-relative or display path for the source unit.
            source: UTF-8 decoded Python source text.

        Returns:
            Findings sorted by stable identity and then source line.
        """
        self._path = path
        self._lines = tuple(source.splitlines())
        self._findings = []
        self._overload_aliases = {"overload"}
        self._overload_modules = set()
        self._import_counters.clear()
        try:
            list(tokenize.generate_tokens(io.StringIO(source).readline))
            module = ast.parse(source, filename=path, type_comments=True)
        except (IndentationError, SyntaxError, tokenize.TokenError) as error:
            line = 1
            if isinstance(error, tokenize.TokenError):
                raw_args: tuple[object, ...] = error.args
                if (
                    len(raw_args) > 1
                    and isinstance(raw_args[1], tuple)
                    and isinstance(raw_args[1][0], int)
                ):
                    line = max(raw_args[1][0], 1)
            if isinstance(error, SyntaxError) and error.lineno is not None:
                line = max(error.lineno, 1)
            detail = "tokenization" if isinstance(error, tokenize.TokenError) else "syntax"
            self._add("<module>", "PYS001", detail, line)
            result = tuple(sorted(self._findings, key=PythonFinding.sort_key))
            self._clear()
            return result
        try:
            self._check_imports(module)
            self._check_any(module)
            self._collect_overload_bindings(module)
            self._check_docs(module)
            return tuple(sorted(self._findings, key=PythonFinding.sort_key))
        finally:
            self._clear()

    def _clear(self) -> None:
        """Release invocation state after a successful or failed scan."""
        self._path = ""
        self._lines = ()
        self._findings = []
        self._overload_aliases = set()
        self._overload_modules = set()
        self._import_counters.clear()

    def _add(self, symbol: str, rule: str, detail: str, line: int) -> None:
        """Append one finding using the current scan context."""
        line = max(line, 1)
        self._findings.append(
            PythonFinding(path=self._path, symbol=symbol, rule=rule, detail=detail, line=line)
        )

    def _check_imports(self, module: ast.Module) -> None:
        """Check every import block, including nested and guarded blocks."""
        self._import_statements(module.body, "<module>", "module")
        top_level = [item for item in module.body if isinstance(item, (ast.Import, ast.ImportFrom))]
        futures = [
            item
            for item in top_level
            if isinstance(item, ast.ImportFrom) and item.module == "__future__"
        ]
        if not futures:
            return
        first = futures[0]
        docstring: ast.Constant | None = None
        if module.body and isinstance(module.body[0], ast.Expr):
            value = module.body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                docstring = value
        position = 1 if docstring is not None else 0
        if module.body[position : position + len(futures)] != futures:
            self._add("<module>", "PYI001", "future-position", first.lineno)
        if (
            docstring is not None
            and self._blank_lines(docstring.end_lineno or docstring.lineno, first.lineno) == 0
        ):
            self._add("<module>", "PYI001", "future-separation:docstring", first.lineno)
        last_line = futures[-1].end_lineno or futures[-1].lineno
        later = [item for item in top_level if item.lineno > last_line]
        if later and self._blank_lines(last_line, later[0].lineno) == 0:
            self._add("<module>", "PYI001", "future-separation:imports", later[0].lineno)

    def _import_statements(self, statements: list[ast.stmt], symbol: str, context: str) -> None:
        """Visit direct import runs and recurse through nested statement blocks."""
        index = 0
        while index < len(statements):
            statement = statements[index]
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                run: list[ast.Import | ast.ImportFrom] = []
                while index < len(statements):
                    candidate = statements[index]
                    if not isinstance(candidate, (ast.Import, ast.ImportFrom)):
                        break
                    run.append(candidate)
                    index += 1
                key = (symbol, context)
                number = self._import_counters.get(key, 0) + 1
                self._import_counters[key] = number
                self._import_block(run, symbol, f"{context}:block:{number}")
                continue
            self._import_nested(statement, symbol, context)
            index += 1

    def _import_nested(self, statement: ast.stmt, symbol: str, context: str) -> None:
        """Recurse into definitions and control-flow blocks containing imports."""
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            child = statement.name if symbol == "<module>" else f"{symbol}.{statement.name}"
            kind = "class" if isinstance(statement, ast.ClassDef) else "function"
            self._import_statements(statement.body, child, kind)
        elif isinstance(statement, ast.If):
            test = self._expression_fingerprint(statement.test)
            self._import_statements(statement.body, symbol, f"{context}:if:{test}:body")
            self._import_statements(statement.orelse, symbol, f"{context}:if:{test}:else")
        elif isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
            test_node = (
                statement.iter if isinstance(statement, (ast.For, ast.AsyncFor)) else statement.test
            )
            test = self._expression_fingerprint(test_node)
            self._import_statements(statement.body, symbol, f"{context}:loop:{test}:body")
            self._import_statements(statement.orelse, symbol, f"{context}:loop:{test}:else")
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            test = self._expression_fingerprint(statement.items[0].context_expr)
            self._import_statements(statement.body, symbol, f"{context}:with:{test}")
        elif isinstance(statement, (ast.Try, ast.TryStar)):
            self._import_statements(statement.body, symbol, f"{context}:try")
            for handler in statement.handlers:
                kind = self._expression_fingerprint(handler.type) if handler.type else "bare"
                self._import_statements(handler.body, symbol, f"{context}:except:{kind}")
            self._import_statements(statement.orelse, symbol, f"{context}:try-else")
            self._import_statements(statement.finalbody, symbol, f"{context}:finally")
        elif isinstance(statement, ast.Match):
            subject = self._expression_fingerprint(statement.subject)
            for ordinal, case in enumerate(statement.cases, 1):
                self._import_statements(
                    case.body, symbol, f"{context}:match:{subject}:case:{ordinal}"
                )

    def _import_block(
        self, statements: list[ast.Import | ast.ImportFrom], symbol: str, block: str
    ) -> None:
        """Check headings, separation, ordering, and future-import placement."""
        records = tuple(
            _ImportRecord(node=item, category=self._category(item), line=item.lineno)
            for item in statements
        )
        for record in records:
            if record.category == "mixed":
                self._add(symbol, "PYI001", f"mixed-category:block={block}", record.line)
        if symbol == "<module>" and any(item.category == "future" for item in records):
            positions = [index for index, item in enumerate(records) if item.category == "future"]
            if positions != list(range(len(positions))):
                self._add(
                    "<module>", "PYI001", f"future-order:block={block}", records[positions[0]].line
                )
        ordinary = tuple(item for item in records if item.category not in {"future", "mixed"})
        groups: list[tuple[str, list[_ImportRecord]]] = []
        for record in ordinary:
            if not groups or groups[-1][0] != record.category:
                groups.append((record.category, [record]))
            else:
                groups[-1][1].append(record)
        previous: tuple[str, list[_ImportRecord]] | None = None
        for ordinal, group in enumerate(groups, 1):
            category, grouped = group
            first = grouped[0]
            if not self._has_heading(first.line, self._HEADINGS[category], first.node.col_offset):
                self._add(
                    symbol,
                    "PYI001",
                    f"heading:{category}:block={block}:group={ordinal}",
                    first.line,
                )
            if previous is not None:
                prior_category, prior_records = previous
                prior_line = prior_records[-1].node.end_lineno or prior_records[-1].line
                if self._blank_lines(prior_line, first.line) == 0:
                    self._add(
                        symbol,
                        "PYI001",
                        f"separation:{prior_category}-{category}:block={block}:group={ordinal}",
                        first.line,
                    )
                if self._CATEGORY_RANK[category] < self._CATEGORY_RANK[prior_category]:
                    self._add(
                        symbol,
                        "PYI001",
                        f"order:{prior_category}>{category}:block={block}:group={ordinal}",
                        first.line,
                    )
            previous = group

    def _category(self, statement: ast.Import | ast.ImportFrom) -> str:
        """Classify one import by package root, including relative imports."""
        if isinstance(statement, ast.ImportFrom):
            if statement.module == "__future__":
                return "future"
            if statement.level:
                return "project"
            root = (statement.module or "").split(".", 1)[0]
        else:
            roots = {alias.name.split(".", 1)[0] for alias in statement.names}
            categories = {self._module_category(root) for root in roots}
            return "mixed" if len(categories) > 1 else categories.pop()
        return self._module_category(root)

    def _module_category(self, root: str) -> str:
        """Classify one absolute import root."""
        if root in sys.stdlib_module_names:
            return "standard"
        return "project" if not root or root in self._PROJECT_ROOTS else "third-party"

    def _has_heading(self, line: int, heading: str, indentation: int) -> bool:
        """Return whether the nearest preceding nonblank line is the exact heading."""
        index = line - 2
        while index >= 0 and not self._lines[index].strip():
            index -= 1
        if index < 0:
            return False
        source_line = self._lines[index]
        prefix = source_line[: len(source_line) - len(source_line.lstrip(" \t"))]
        return len(prefix.expandtabs(8)) == indentation and source_line.strip() == heading

    def _blank_lines(self, first: int, second: int) -> int:
        """Count blank physical lines strictly between two source lines."""
        return sum(1 for line in self._lines[first : second - 1] if not line.strip())

    @staticmethod
    def _expression_fingerprint(node: ast.AST | None) -> str:
        """Return a compact line-independent AST fingerprint."""
        return (
            "none"
            if node is None
            else ast.dump(node, annotate_fields=True, include_attributes=False)
        )

    def _check_any(self, module: ast.Module) -> None:
        """Find explicit typing.Any uses while respecting lexical aliases."""
        self._any_statements(module.body, _Scope(symbol="<module>", parent=None))

    def _any_statements(self, statements: list[ast.stmt], scope: _Scope) -> None:
        """Visit statements while keeping child bindings in child scopes."""
        for statement in statements:
            self._any_statement(statement, scope)

    def _any_statement(self, statement: ast.stmt, scope: _Scope) -> None:
        """Scan one statement and its relevant expressions or child scopes."""
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            self._any_import(statement, scope)
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbol = (
                statement.name if scope.symbol == "<module>" else f"{scope.symbol}.{statement.name}"
            )
            signature = _Scope(symbol=symbol, parent=scope)
            self._any_type_parameters(statement.type_params, signature)
            self._any_function_signature(statement, signature)
            self._any_type_comment(
                statement.type_comment, signature, "type-comment", statement.lineno
            )
            scope.bind_name(statement.name)
            child = _Scope(symbol=symbol, parent=signature)
            for argument in self._arguments(statement.args):
                child.bind_name(argument.arg)
            self._any_statements(statement.body, child)
        elif isinstance(statement, ast.ClassDef):
            symbol = (
                statement.name if scope.symbol == "<module>" else f"{scope.symbol}.{statement.name}"
            )
            child = _Scope(symbol=symbol, parent=scope)
            self._any_type_parameters(statement.type_params, child)
            for decorator in statement.decorator_list:
                self._any_expression(decorator, child, "expression")
            for base in statement.bases:
                self._any_expression(base, child, "base")
            for keyword in statement.keywords:
                self._any_expression(keyword.value, child, "base")
            scope.bind_name(statement.name)
            self._any_statements(statement.body, child)
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                self._any_target(target, scope)
            detail = "assignment:" + ",".join(
                target.id if isinstance(target, ast.Name) else "expression"
                for target in statement.targets
            )
            if self._alias_expression(statement.value, scope) != "typing-any":
                self._any_expression(statement.value, scope, detail)
            self._bind_aliases(statement.targets, statement.value, scope)
            self._any_type_comment(statement.type_comment, scope, detail, statement.lineno)
        elif isinstance(statement, ast.AnnAssign):
            name = statement.target.id if isinstance(statement.target, ast.Name) else None
            detail = f"variable:{name}" if name else "variable"
            self._any_expression(statement.annotation, scope, detail, annotation=True)
            if statement.value is not None:
                if self._alias_expression(statement.value, scope) != "typing-any":
                    self._any_expression(
                        statement.value, scope, f"assignment:{name or 'expression'}"
                    )
                self._bind_aliases((statement.target,), statement.value, scope)
            else:
                self._any_target(statement.target, scope)
        elif isinstance(statement, ast.TypeAlias):
            target_node = statement.name
            if not isinstance(target_node, ast.Name):
                return
            alias_name = target_node.id
            self._any_type_parameters(statement.type_params, scope)
            if self._alias_expression(statement.value, scope) == "typing-any":
                self._bind_alias_expression(alias_name, statement.value, scope)
            else:
                self._any_expression(statement.value, scope, f"alias:{alias_name}", annotation=True)
                scope.bind_name(alias_name)
                self._bind_alias_expression(alias_name, statement.value, scope)
        elif isinstance(statement, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            if isinstance(statement, (ast.For, ast.AsyncFor)):
                self._any_expression(statement.iter, scope, "expression")
                self._any_type_comment(
                    statement.type_comment, scope, "type-comment", statement.lineno
                )
                self._any_target(statement.target, scope)
            else:
                self._any_expression(statement.test, scope, "expression")
            self._any_statements(statement.body, scope)
            self._any_statements(statement.orelse, scope)
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            for item in statement.items:
                self._any_expression(item.context_expr, scope, "expression")
                if item.optional_vars is not None:
                    self._any_target(item.optional_vars, scope)
            self._any_statements(statement.body, scope)
        elif isinstance(statement, (ast.Try, ast.TryStar)):
            self._any_statements(statement.body, scope)
            for handler in statement.handlers:
                if handler.type is not None:
                    self._any_expression(handler.type, scope, "expression")
                if handler.name:
                    scope.bind_name(handler.name)
                self._any_statements(handler.body, scope)
            self._any_statements(statement.orelse, scope)
            self._any_statements(statement.finalbody, scope)
        elif isinstance(statement, ast.Match):
            self._any_expression(statement.subject, scope, "expression")
            for case in statement.cases:
                if case.guard is not None:
                    self._any_expression(case.guard, scope, "expression")
                self._any_statements(case.body, scope)
        else:
            for child_node in ast.iter_child_nodes(statement):
                if isinstance(child_node, ast.expr):
                    self._any_expression(child_node, scope, "expression")

    def _any_import(self, statement: ast.Import | ast.ImportFrom, scope: _Scope) -> None:
        """Record typing aliases and report direct Any imports."""
        if isinstance(statement, ast.Import):
            for item in statement.names:
                name = item.asname or item.name.split(".", 1)[0]
                scope.bind_name(name)
                if item.name in self._TYPING_MODULES:
                    scope.bind_alias(name, "typing-module")
            return
        module = statement.module or ""
        for item in statement.names:
            name = item.asname or item.name
            if module in self._TYPING_MODULES and item.name == "Any":
                self._add(scope.symbol, "PYT001", f"import:Any:{name}", statement.lineno)
                scope.bind_alias(name, "typing-any")
            elif module in self._TYPING_MODULES and item.name in {"Literal", "Annotated"}:
                scope.bind_alias(
                    name, "typing-literal" if item.name == "Literal" else "typing-annotated"
                )
            else:
                scope.bind_name(name)

    def _any_function_signature(
        self, function: ast.FunctionDef | ast.AsyncFunctionDef, scope: _Scope
    ) -> None:
        """Scan decorators, defaults, parameter annotations, and return annotations."""
        for decorator in function.decorator_list:
            self._any_expression(decorator, scope, "expression")
        positional = [*function.args.posonlyargs, *function.args.args]
        for argument, default in zip(
            positional[-len(function.args.defaults) :], function.args.defaults
        ):
            self._any_expression(default, scope, f"default:{argument.arg}")
        for argument, kw_default in zip(function.args.kwonlyargs, function.args.kw_defaults):
            if kw_default is not None:
                self._any_expression(kw_default, scope, f"default:{argument.arg}")
        for argument in self._arguments(function.args):
            if argument.annotation is not None:
                self._any_expression(
                    argument.annotation,
                    scope,
                    f"parameter:{argument.arg}",
                    annotation=True,
                    line=argument.lineno,
                )
            if argument.type_comment:
                self._any_quoted(
                    argument.type_comment, scope, f"parameter:{argument.arg}", argument.lineno
                )
        if function.returns is not None:
            self._any_expression(
                function.returns, scope, "Returns", annotation=True, line=function.lineno
            )

    def _any_type_parameters(self, parameters: list[ast.type_param], scope: _Scope) -> None:
        """Inspect generic bounds for explicit dynamic types."""
        for parameter in parameters:
            if isinstance(parameter, ast.TypeVar) and parameter.bound is not None:
                self._any_expression(
                    parameter.bound, scope, f"type-bound:{parameter.name}", annotation=True
                )

    @staticmethod
    def _arguments(arguments: ast.arguments) -> tuple[ast.arg, ...]:
        """Return all declared arguments in source-signature order."""
        values = [*arguments.posonlyargs, *arguments.args]
        if arguments.vararg is not None:
            values.append(arguments.vararg)
        values.extend(arguments.kwonlyargs)
        if arguments.kwarg is not None:
            values.append(arguments.kwarg)
        return tuple(values)

    def _any_target(self, target: ast.expr, scope: _Scope) -> None:
        """Record names bound by an assignment target."""
        if isinstance(target, ast.Name):
            scope.bind_name(target.id)
        else:
            for child in ast.iter_child_nodes(target):
                if isinstance(child, ast.expr):
                    self._any_target(child, scope)

    def _bind_aliases(
        self, targets: tuple[ast.expr, ...] | list[ast.expr], value: ast.expr, scope: _Scope
    ) -> None:
        """Preserve recognized aliases for each simple assignment target."""
        alias = self._alias_expression(value, scope)
        for target in targets:
            if isinstance(target, ast.Name):
                if alias == "typing-any":
                    self._bind_alias_expression(target.id, value, scope)
                elif alias == "typing-module":
                    scope.bind_alias(target.id, alias)
                else:
                    scope.bind_name(target.id)

    def _bind_alias_expression(self, name: str, value: ast.expr, scope: _Scope) -> None:
        """Bind a target to a recognized alias and report dynamic aliases."""
        alias = self._alias_expression(value, scope)
        if alias == "typing-any":
            self._add(scope.symbol, "PYT001", f"alias:{name}", value.lineno)
            scope.bind_alias(name, alias)
        elif alias == "typing-module":
            scope.bind_alias(name, alias)
        else:
            scope.bind_name(name)

    def _alias_expression(self, node: ast.expr, scope: _Scope) -> str | None:
        """Resolve a simple typing alias expression."""
        if isinstance(node, ast.Name):
            return scope.resolve(node.id)
        if isinstance(node, ast.Attribute) and node.attr == "Any":
            return "typing-any" if self._attribute_alias(node, scope) == "typing-any" else None
        return None

    def _any_quoted(self, value: str, scope: _Scope, detail: str, line: int | None = None) -> None:
        """Parse and scan one quoted forward annotation or type comment."""
        try:
            expression = ast.parse(value, mode="eval").body
        except SyntaxError, ValueError:
            return
        self._any_expression(expression, scope, detail, annotation=True, line=line)

    def _any_type_comment(self, value: str | None, scope: _Scope, detail: str, line: int) -> None:
        """Scan a recognized type comment while ignoring ordinary comments."""
        if not value:
            return
        expressions = [value]
        if "->" in value:
            arguments, _, result = value.partition("->")
            expressions = [arguments.strip(" ()"), result.strip()]
        for expression in expressions:
            if expression:
                self._any_quoted(expression, scope, detail, line)

    def _any_expression(
        self,
        node: ast.AST,
        scope: _Scope,
        detail: str,
        *,
        annotation: bool = False,
        literal: bool = False,
        line: int | None = None,
    ) -> None:
        """Scan expressions and annotations for qualified or aliased Any references."""
        if isinstance(node, ast.Constant):
            if annotation and isinstance(node.value, str) and not literal:
                self._any_quoted(node.value, scope, detail, line)
            return
        if isinstance(node, ast.Attribute) and node.attr == "Any":
            if self._attribute_alias(node, scope) == "typing-any":
                if not annotation:
                    detail = self._expression_detail(detail, node)
                self._add(scope.symbol, "PYT001", detail, line or node.lineno)
            self._any_expression(
                node.value, scope, detail, annotation=annotation, literal=literal, line=line
            )
            return
        if isinstance(node, ast.Name):
            if scope.resolve(node.id) == "typing-any":
                detail = detail if annotation else self._expression_detail(detail, node)
                self._add(scope.symbol, "PYT001", detail, line or node.lineno)
            return
        is_literal = (
            annotation
            and isinstance(node, ast.Subscript)
            and self._is_typing(node.value, scope, "Literal")
        )
        if (
            annotation
            and isinstance(node, ast.Subscript)
            and self._is_typing(node.value, scope, "Annotated")
        ):
            elements = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            if elements:
                self._any_expression(
                    elements[0], scope, detail, annotation=True, literal=literal, line=line
                )
            for metadata in elements[1:]:
                self._any_expression(metadata, scope, detail)
            return
        for child in ast.iter_child_nodes(node):
            self._any_expression(
                child,
                scope,
                detail,
                annotation=annotation,
                literal=literal or is_literal,
                line=line,
            )

    def _attribute_alias(self, node: ast.Attribute, scope: _Scope) -> str | None:
        """Resolve a qualified typing attribute alias."""
        if isinstance(node.value, ast.Name) and scope.resolve(node.value.id) == "typing-module":
            return "typing-any" if node.attr == "Any" else None
        return None

    def _is_typing(self, node: ast.expr, scope: _Scope, name: str) -> bool:
        """Return whether an expression names a recognized typing wrapper."""
        aliases = {"Literal": "typing-literal", "Annotated": "typing-annotated"}
        if isinstance(node, ast.Name):
            return scope.resolve(node.id) == aliases[name]
        return (
            isinstance(node, ast.Attribute)
            and node.attr == name
            and isinstance(node.value, ast.Name)
            and scope.resolve(node.value.id) == "typing-module"
        )

    @staticmethod
    def _expression_detail(detail: str, node: ast.AST) -> str:
        """Add an AST fingerprint to generic expression findings."""
        if detail in {"expression", "base"}:
            return f"{detail}:{ast.dump(node, annotate_fields=True, include_attributes=False)}"
        return detail

    def _collect_overload_bindings(self, module: ast.Module) -> None:
        """Collect typing overload aliases used by decorators in the source tree."""
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom) and node.module in {
                "typing",
                "typing_extensions",
            }:
                for item in node.names:
                    if item.name == "overload":
                        self._overload_aliases.add(item.asname or item.name)
            elif isinstance(node, ast.Import):
                for item in node.names:
                    if item.name in {"typing", "typing_extensions"}:
                        self._overload_modules.add(item.asname or item.name)

    def _is_overload(self, function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Return whether a function is a typing overload signature."""
        for decorator in function.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id in self._overload_aliases:
                return True
            if (
                isinstance(decorator, ast.Attribute)
                and decorator.attr == "overload"
                and isinstance(decorator.value, ast.Name)
                and decorator.value.id in self._overload_modules
            ):
                return True
        return False

    def _check_docs(self, module: ast.Module) -> None:
        """Check module, class, and named-function documentation contracts."""
        self._definition_doc(module, "<module>")
        self._doc_statements(module.body, "<module>")

    def _doc_statements(self, statements: list[ast.stmt], parent: str) -> None:
        """Visit definitions nested in statements and control-flow blocks."""
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol = statement.name if parent == "<module>" else f"{parent}.{statement.name}"
                self._function_doc(statement, symbol)
                self._doc_statements(statement.body, symbol)
            elif isinstance(statement, ast.ClassDef):
                symbol = statement.name if parent == "<module>" else f"{parent}.{statement.name}"
                self._definition_doc(statement, symbol)
                self._doc_statements(statement.body, symbol)
            elif isinstance(
                statement, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)
            ):
                self._doc_statements(statement.body, parent)
                if isinstance(statement, (ast.If, ast.For, ast.AsyncFor, ast.While)):
                    self._doc_statements(statement.orelse, parent)
            elif isinstance(statement, (ast.Try, ast.TryStar)):
                self._doc_statements(statement.body, parent)
                for handler in statement.handlers:
                    self._doc_statements(handler.body, parent)
                self._doc_statements(statement.orelse, parent)
                self._doc_statements(statement.finalbody, parent)
            elif isinstance(statement, ast.Match):
                for case in statement.cases:
                    self._doc_statements(case.body, parent)

    def _definition_doc(
        self, node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, symbol: str
    ) -> str | None:
        """Check and return one definition's summary docstring."""
        value = self._docstring(node)
        if value is None or not value.strip():
            self._add(
                symbol, "PYD001", "summary", node.lineno if not isinstance(node, ast.Module) else 1
            )
            return None
        return value

    def _function_doc(self, function: ast.FunctionDef | ast.AsyncFunctionDef, symbol: str) -> None:
        """Check summary and any present Google-style sections for one function."""
        if self._is_overload(function):
            return
        value = self._definition_doc(function, symbol)
        if self._path.startswith("tests/") and function.name.startswith("test_"):
            return
        if function.name.startswith("_") and function.name != "__init__":
            return
        if any(owner.startswith("_") for owner in symbol.split(".")[:-1]):
            return
        sections = self._sections(value or "")
        arguments = tuple(
            item.arg for item in self._arguments(function.args) if item.arg not in {"self", "cls"}
        )
        for name, body in sections.items():
            if any(line.strip() for line in body):
                continue
            self._add(symbol, "PYD002", name, function.lineno)
            if name == "Args":
                for argument in arguments:
                    self._add(symbol, "PYD002", f"parameter:{argument}", function.lineno)

        args_section = sections.get("Args")
        if args_section is not None and any(line.strip() for line in args_section):
            described = self._described_arguments(args_section)
            for name in arguments:
                if name not in described:
                    self._add(symbol, "PYD002", f"parameter:{name}", function.lineno)
            for name in described:
                if name not in arguments:
                    self._add(symbol, "PYD002", f"parameter:{name}", function.lineno)

    def _sections(self, docstring: str) -> dict[str, tuple[str, ...]]:
        """Parse top-level Google section headers and their indented bodies."""
        sections: dict[str, tuple[str, ...]] = {}
        current: str | None = None
        body: list[str] = []
        for line in inspect.cleandoc(docstring).splitlines():
            stripped = line.strip()
            header = (
                stripped[:-1]
                if stripped.endswith(":") and stripped[:-1] in self._SECTION_NAMES
                else None
            )
            if header is not None and not line.startswith((" ", "\t")):
                if current is not None:
                    sections[current] = tuple(body)
                current, body = header, []
            elif current is not None:
                if stripped and not line.startswith((" ", "\t")):
                    sections[current] = tuple(body)
                    current, body = None, []
                else:
                    body.append(line)
        if current is not None:
            sections[current] = tuple(body)
        return sections

    def _described_arguments(self, lines: tuple[str, ...]) -> set[str]:
        """Return parameter names with nonempty Google descriptions."""
        described: set[str] = set()
        current: str | None = None
        has_text = False
        for line in lines:
            match = self._ARGUMENT_ENTRY.match(line)
            if match is not None:
                if current is not None and has_text:
                    described.add(current)
                groups: dict[str, str | None] = match.groupdict()
                current = (groups.get("name") or "").lstrip("*")
                has_text = bool((groups.get("description") or "").strip())
            elif current is not None and line.strip():
                has_text = True
        if current is not None and has_text:
            described.add(current)
        return described

    @staticmethod
    def _docstring(
        node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> str | None:
        """Return the raw first string expression used as a docstring."""
        if node.body and isinstance(node.body[0], ast.Expr):
            value = node.body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
        return None

    def __init__(self) -> None:
        """Initialize reusable per-scan state."""
        self._import_counters: dict[tuple[str, str], int] = {}
        self._path = ""
        self._lines = ()
        self._findings = []
