"""Check the source-level Python coding standards migration contract."""

from __future__ import annotations

# standard library imports
import ast
import inspect
import io
import re
import sys
import tokenize
from typing import ClassVar, cast

# third party library imports
from pydantic import BaseModel, ConfigDict, Field

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
        """Return the line-independent identity used by migration baselines.

        Returns:
            The source path, symbol, rule, and stable detail key.
        """
        return (self.path, self.symbol, self.rule, self.detail)


class _Scope(BaseModel):
    """Track typing aliases and lexical bindings for one Python scope.

    ``revalidate_instances="never"`` preserves the identity of ``parent`` so
    lexical lookup observes live bindings as the enclosing scope changes.
    """

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=False,
        revalidate_instances="never",
        strict=True,
        validate_assignment=True,
        validate_default=True,
    )

    symbol: str
    parent: _Scope | None
    aliases: dict[str, str] = Field(default_factory=dict)
    bindings: set[str] = Field(default_factory=set)

    def bind_alias(self, name: str, alias: str) -> None:
        """Bind one name to a recognized typing alias."""
        self.aliases[name] = alias
        self.bindings.add(name)

    def bind_name(self, name: str) -> None:
        """Record a local binding that shadows any outer alias."""
        self.aliases.pop(name, None)
        self.bindings.add(name)

    def resolve(self, name: str) -> str | None:
        """Resolve a name through the lexical scope chain."""
        if name in self.aliases:
            return self.aliases[name]
        if name in self.bindings:
            return None
        if self.parent is None:
            return None
        return self.parent.resolve(name)


class _ImportRecord(ImmutableModel):
    """Describe one direct import statement in an import block."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    node: ast.Import | ast.ImportFrom
    category: str
    line: int


class _ImportGroup(ImmutableModel):
    """Describe one contiguous category segment in an import block."""

    category: str
    records: tuple[_ImportRecord, ...]
    ordinal: int


class _GoogleSection(ImmutableModel):
    """Hold one parsed Google-style docstring section."""

    name: str
    body: tuple[str, ...]


class _FunctionFacts(ImmutableModel):
    """Summarize return, yield, and raise statements in one function body."""

    has_value_return: bool
    has_yield: bool
    has_raise: bool


class _ImportChecker:
    """Check headings, grouping, and order for direct import blocks."""

    _HEADINGS: ClassVar[dict[str, str]] = {
        "standard": "# standard library imports",
        "third-party": "# third party library imports",
        "project": "# project library imports",
    }
    _CATEGORY_RANK: ClassVar[dict[str, int]] = {
        "standard": 0,
        "third-party": 1,
        "project": 2,
    }
    _PROJECT_ROOTS: ClassVar[tuple[str, ...]] = (
        "alpha_research",
        "alpha_research_governance",
    )

    def __init__(
        self, path: str, source_lines: tuple[str, ...], findings: list[PythonFinding]
    ) -> None:
        """Initialize an import checker for one source invocation."""
        self._path = path
        self._lines = source_lines
        self._findings = findings
        self._block_counters: dict[tuple[str, str], int] = {}

    def check(self, module: ast.Module) -> None:
        """Check every import block reachable from the module."""
        self._visit_statement_list(module.body, "<module>", "module")
        self._check_future_layout(module)

    def _visit_statement_list(
        self,
        statements: list[ast.stmt],
        symbol: str,
        context: str,
    ) -> None:
        """Visit one statement list and recurse into nested statement blocks."""
        index = 0
        while index < len(statements):
            statement = statements[index]
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                run: list[ast.Import | ast.ImportFrom] = []
                while index < len(statements) and isinstance(
                    statements[index], (ast.Import, ast.ImportFrom)
                ):
                    run.append(cast(ast.Import | ast.ImportFrom, statements[index]))
                    index += 1
                self._check_block(run, symbol, context)
                continue
            self._visit_nested_statement(statement, symbol, context)
            index += 1

    def _visit_nested_statement(self, statement: ast.stmt, symbol: str, context: str) -> None:
        """Visit statement lists nested under control flow or definitions."""
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            child_symbol = self._qualified_symbol(symbol, statement.name)
            self._visit_statement_list(statement.body, child_symbol, "function")
            return
        if isinstance(statement, ast.ClassDef):
            child_symbol = self._qualified_symbol(symbol, statement.name)
            self._visit_statement_list(statement.body, child_symbol, "class")
            return
        if isinstance(statement, ast.If):
            test = self._expression_fingerprint(statement.test)
            self._visit_statement_list(statement.body, symbol, f"{context}:if:{test}:body")
            self._visit_statement_list(statement.orelse, symbol, f"{context}:if:{test}:else")
            return
        if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
            test_node = (
                statement.iter if isinstance(statement, (ast.For, ast.AsyncFor)) else statement.test
            )
            test = self._expression_fingerprint(test_node)
            self._visit_statement_list(statement.body, symbol, f"{context}:loop:{test}:body")
            self._visit_statement_list(statement.orelse, symbol, f"{context}:loop:{test}:else")
            return
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            test = self._expression_fingerprint(statement.items[0].context_expr)
            self._visit_statement_list(statement.body, symbol, f"{context}:with:{test}")
            return
        if isinstance(statement, (ast.Try, ast.TryStar)):
            self._visit_statement_list(statement.body, symbol, f"{context}:try")
            for handler in statement.handlers:
                handler_name = (
                    self._expression_fingerprint(handler.type) if handler.type else "bare"
                )
                self._visit_statement_list(handler.body, symbol, f"{context}:except:{handler_name}")
            self._visit_statement_list(statement.orelse, symbol, f"{context}:try-else")
            self._visit_statement_list(statement.finalbody, symbol, f"{context}:finally")
            return
        if isinstance(statement, ast.Match):
            subject = self._expression_fingerprint(statement.subject)
            for ordinal, case in enumerate(statement.cases, 1):
                self._visit_statement_list(
                    case.body, symbol, f"{context}:match:{subject}:case:{ordinal}"
                )
            return

    def _check_block(
        self,
        statements: list[ast.Import | ast.ImportFrom],
        symbol: str,
        context: str,
    ) -> None:
        """Check one direct run of import statements."""
        counter_key = (symbol, context)
        block_number = self._block_counters.get(counter_key, 0) + 1
        self._block_counters[counter_key] = block_number
        block = f"{context}:block:{block_number}"
        records = tuple(
            _ImportRecord(
                node=statement,
                category=self._category(statement),
                line=statement.lineno,
            )
            for statement in statements
        )
        for record in records:
            if record.category == "mixed":
                self._add(
                    symbol,
                    "PYI001",
                    f"mixed-category:block={block}",
                    record.line,
                )
        if symbol == "<module>" and any(record.category == "future" for record in records):
            self._check_future_group(records, block)
        non_future = tuple(
            record for record in records if record.category not in {"future", "mixed"}
        )
        if not non_future:
            return
        groups = self._groups(non_future)
        previous: _ImportGroup | None = None
        for group in groups:
            heading = self._HEADINGS[group.category]
            first = group.records[0]
            if not self._has_heading(first.line, heading, first.node.col_offset):
                self._add(
                    symbol,
                    "PYI001",
                    f"heading:{group.category}:block={block}:group={group.ordinal}",
                    first.line,
                )
            if previous is not None:
                previous_last = previous.records[-1].node.end_lineno or previous.records[-1].line
                if self._blank_lines_between(previous_last, first.line) == 0:
                    self._add(
                        symbol,
                        "PYI001",
                        f"separation:{previous.category}-{group.category}:block={block}:group={group.ordinal}",
                        first.line,
                    )
                if self._CATEGORY_RANK[group.category] < self._CATEGORY_RANK[previous.category]:
                    self._add(
                        symbol,
                        "PYI001",
                        f"order:{previous.category}>{group.category}:block={block}:group={group.ordinal}",
                        first.line,
                    )
            previous = group

    def _check_future_group(self, records: tuple[_ImportRecord, ...], block: str) -> None:
        """Check that future imports form the dedicated first import group."""
        future_positions = [
            index for index, record in enumerate(records) if record.category == "future"
        ]
        if not future_positions:
            return
        first_future = future_positions[0]
        contiguous = future_positions == list(range(len(future_positions)))
        if first_future != 0 or not contiguous:
            self._add(
                "<module>", "PYI001", f"future-order:block={block}", records[first_future].line
            )

    def _check_future_layout(self, module: ast.Module) -> None:
        """Require blank separation around module future imports and docstrings."""
        top_level = [
            statement
            for statement in module.body
            if isinstance(statement, (ast.Import, ast.ImportFrom))
        ]
        futures = [
            statement
            for statement in top_level
            if isinstance(statement, ast.ImportFrom) and statement.module == "__future__"
        ]
        if not futures:
            return
        first_future = futures[0]
        docstring = self._module_docstring_node(module)
        first_position = 1 if docstring is not None else 0
        if module.body[first_position : first_position + len(futures)] != futures:
            self._add("<module>", "PYI001", "future-position", first_future.lineno)
        if (
            docstring is not None
            and self._blank_lines_between(
                docstring.end_lineno or docstring.lineno, first_future.lineno
            )
            == 0
        ):
            self._add("<module>", "PYI001", "future-separation:docstring", first_future.lineno)
        later = [
            statement
            for statement in top_level
            if statement.lineno > (futures[-1].end_lineno or futures[-1].lineno)
        ]
        if (
            later
            and self._blank_lines_between(
                futures[-1].end_lineno or futures[-1].lineno, later[0].lineno
            )
            == 0
        ):
            self._add("<module>", "PYI001", "future-separation:imports", later[0].lineno)

    def _module_docstring_node(self, module: ast.Module) -> ast.Constant | None:
        """Return the module docstring expression when present."""
        if not module.body or not isinstance(module.body[0], ast.Expr):
            return None
        value = module.body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value
        return None

    def _groups(self, records: tuple[_ImportRecord, ...]) -> tuple[_ImportGroup, ...]:
        """Split records into contiguous category groups."""
        groups: list[_ImportGroup] = []
        for record in records:
            if record.category == "future":
                continue
            if not groups or groups[-1].category != record.category:
                groups.append(
                    _ImportGroup(
                        category=record.category,
                        records=(record,),
                        ordinal=len(groups) + 1,
                    )
                )
            else:
                previous = groups[-1]
                groups[-1] = _ImportGroup(
                    category=previous.category,
                    records=(*previous.records, record),
                    ordinal=previous.ordinal,
                )
        return tuple(groups)

    def _category(self, statement: ast.Import | ast.ImportFrom) -> str:
        """Classify an import as standard, third-party, project, or future."""
        if isinstance(statement, ast.ImportFrom):
            if statement.module == "__future__":
                return "future"
            if statement.level:
                return "project"
            module = statement.module or ""
        else:
            categories = {
                self._module_category(alias.name.split(".", 1)[0]) for alias in statement.names
            }
            if len(categories) > 1:
                return "mixed"
            return categories.pop()
        return self._module_category(module.split(".", 1)[0])

    def _module_category(self, root: str) -> str:
        """Classify one absolute import root."""
        if root in sys.stdlib_module_names:
            return "standard"
        if root == "" or root in self._PROJECT_ROOTS:
            return "project"
        return "third-party"

    def _qualified_symbol(self, parent: str, name: str) -> str:
        """Build the agreed qualified symbol identity for a definition."""
        return name if parent == "<module>" else f"{parent}.{name}"

    def _has_heading(self, line_number: int, heading: str, indentation: int) -> bool:
        """Return whether the nearest preceding nonblank line is the exact heading."""
        index = line_number - 2
        while index >= 0 and not self._lines[index].strip():
            index -= 1
        if index < 0:
            return False
        line = self._lines[index]
        prefix = line[: len(line) - len(line.lstrip(" \t"))]
        return (
            len(prefix.expandtabs(8)) == indentation
            and line.lstrip().startswith("#")
            and line.strip() == heading
        )

    def _blank_lines_between(self, first_line: int, second_line: int) -> int:
        """Count blank physical lines strictly between two source lines."""
        if second_line <= first_line + 1:
            return 0
        return sum(1 for line in self._lines[first_line : second_line - 1] if not line.strip())

    def _expression_fingerprint(self, node: ast.AST | None) -> str:
        """Return a compact, line-independent AST fingerprint."""
        if node is None:
            return "none"
        return ast.dump(node, annotate_fields=True, include_attributes=False)

    def _add(self, symbol: str, rule: str, detail: str, line: int) -> None:
        """Append one import finding."""
        self._findings.append(
            PythonFinding(
                path=self._path,
                symbol=symbol,
                rule=rule,
                detail=detail,
                line=max(line, 1),
            )
        )


class _AnyChecker:
    """Find explicit typing Any uses while respecting lexical aliases."""

    _ANY = "typing-any"
    _TYPING_MODULE = "typing-module"
    _LITERAL = "typing-literal"
    _ANNOTATED = "typing-annotated"
    _TYPING_MODULES: ClassVar[frozenset[str]] = frozenset({"typing", "typing_extensions"})

    def __init__(self, path: str, findings: list[PythonFinding]) -> None:
        """Initialize an Any checker for one source invocation."""
        self._path = path
        self._findings = findings

    def check(self, module: ast.Module) -> None:
        """Find explicit Any occurrences in the module."""
        scope = _Scope(symbol="<module>", parent=None)
        self._visit_statements(module.body, scope)

    def _visit_statements(self, statements: list[ast.stmt], scope: _Scope) -> None:
        """Visit one lexical statement list without leaking child bindings."""
        for statement in statements:
            self._visit_statement(statement, scope)

    def _visit_statement(self, statement: ast.stmt, scope: _Scope) -> None:
        """Visit one statement and all relevant child scopes."""
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            self._visit_import(statement, scope)
            return
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbol = self._qualified_symbol(scope.symbol, statement.name)
            signature_scope = _Scope(symbol=symbol, parent=scope)
            self._scan_type_parameters(statement.type_params, signature_scope)
            self._scan_function_signature(statement, signature_scope)
            self._scan_type_comment(
                statement.type_comment, signature_scope, "type-comment", statement.lineno
            )
            scope.bind_name(statement.name)
            child_scope = _Scope(symbol=symbol, parent=signature_scope)
            for argument in self._arguments(statement.args):
                child_scope.bind_name(argument.arg)
            self._visit_statements(statement.body, child_scope)
            return
        if isinstance(statement, ast.ClassDef):
            symbol = self._qualified_symbol(scope.symbol, statement.name)
            class_scope = _Scope(symbol=symbol, parent=scope)
            self._scan_type_parameters(statement.type_params, class_scope)
            for decorator in statement.decorator_list:
                self._scan_expression(decorator, class_scope, "expression")
            for base in statement.bases:
                self._scan_expression(base, class_scope, "base")
            for keyword_node in statement.keywords:
                self._scan_expression(keyword_node.value, class_scope, "base")
            scope.bind_name(statement.name)
            self._visit_statements(statement.body, class_scope)
            return
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                self._scan_assignment_target(target, scope)
            detail = self._assignment_detail(statement.targets)
            if self._alias_for_expression(statement.value, scope) == self._ANY:
                self._bind_assignment_alias(statement.targets, statement.value, scope)
            else:
                self._scan_expression(statement.value, scope, detail)
                self._bind_assignment_alias(statement.targets, statement.value, scope)
            self._scan_type_comment(statement.type_comment, scope, detail, statement.lineno)
            return
        if isinstance(statement, ast.AnnAssign):
            target_name = self._target_name(statement.target)
            detail = f"variable:{target_name}" if target_name else "variable"
            self._scan_annotation(statement.annotation, scope, detail)
            if statement.value is not None:
                if self._alias_for_expression(statement.value, scope) == self._ANY:
                    self._bind_assignment_alias((statement.target,), statement.value, scope)
                else:
                    self._scan_expression(
                        statement.value, scope, f"assignment:{target_name or 'expression'}"
                    )
                    self._bind_assignment_alias((statement.target,), statement.value, scope)
            else:
                self._scan_assignment_target(statement.target, scope)
            return
        type_alias_type = getattr(ast, "TypeAlias", None)
        if type_alias_type is not None and isinstance(statement, type_alias_type):
            target = cast(ast.Name, statement.name)
            self._scan_type_parameters(statement.type_params, scope)
            if self._alias_for_expression(statement.value, scope) == self._ANY:
                self._bind_alias_expression(target.id, statement.value, scope)
            else:
                self._scan_annotation(statement.value, scope, f"alias:{target.id}")
                scope.bind_name(target.id)
                self._bind_alias_expression(target.id, statement.value, scope)
            return
        if isinstance(statement, ast.If):
            self._scan_expression(statement.test, scope, "expression")
            self._visit_statements(statement.body, scope)
            self._visit_statements(statement.orelse, scope)
            return
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            self._scan_expression(statement.iter, scope, "expression")
            self._scan_type_comment(statement.type_comment, scope, "type-comment", statement.lineno)
            self._scan_assignment_target(statement.target, scope)
            self._visit_statements(statement.body, scope)
            self._visit_statements(statement.orelse, scope)
            return
        if isinstance(statement, ast.While):
            self._scan_expression(statement.test, scope, "expression")
            self._visit_statements(statement.body, scope)
            self._visit_statements(statement.orelse, scope)
            return
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            for item in statement.items:
                self._scan_expression(item.context_expr, scope, "expression")
                if item.optional_vars is not None:
                    self._scan_assignment_target(item.optional_vars, scope)
            self._visit_statements(statement.body, scope)
            return
        if isinstance(statement, (ast.Try, ast.TryStar)):
            self._visit_statements(statement.body, scope)
            for handler in statement.handlers:
                if handler.type is not None:
                    self._scan_expression(handler.type, scope, "expression")
                if handler.name:
                    scope.bind_name(handler.name)
                self._visit_statements(handler.body, scope)
            self._visit_statements(statement.orelse, scope)
            self._visit_statements(statement.finalbody, scope)
            return
        if isinstance(statement, ast.Match):
            self._scan_expression(statement.subject, scope, "expression")
            for case in statement.cases:
                if case.guard is not None:
                    self._scan_expression(case.guard, scope, "expression")
                self._visit_statements(case.body, scope)
            return
        for child_node in ast.iter_child_nodes(statement):
            if isinstance(child_node, ast.expr):
                self._scan_expression(child_node, scope, "expression")

    def _visit_import(self, statement: ast.Import | ast.ImportFrom, scope: _Scope) -> None:
        """Record typing imports and their aliases."""
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                bound_name = alias.asname or alias.name.split(".", 1)[0]
                scope.bind_name(bound_name)
                if alias.name in self._TYPING_MODULES:
                    scope.bind_alias(bound_name, self._TYPING_MODULE)
            return
        module = statement.module or ""
        for alias in statement.names:
            bound_name = alias.asname or alias.name
            if module in self._TYPING_MODULES and alias.name == "Any":
                self._add(scope.symbol, "PYT001", f"import:Any:{bound_name}", statement.lineno)
                scope.bind_alias(bound_name, self._ANY)
            elif module in self._TYPING_MODULES and alias.name in {"Literal", "Annotated"}:
                scope.bind_alias(
                    bound_name, self._LITERAL if alias.name == "Literal" else self._ANNOTATED
                )
            else:
                scope.bind_name(bound_name)

    def _scan_function_signature(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        scope: _Scope,
    ) -> None:
        """Scan decorators, defaults, parameter annotations, and return annotation."""
        for decorator in function.decorator_list:
            self._scan_expression(decorator, scope, "expression")
        positional = list(function.args.posonlyargs) + list(function.args.args)
        for argument, default in zip(
            positional[-len(function.args.defaults) :], function.args.defaults
        ):
            self._scan_expression(default, scope, f"default:{argument.arg}")
        for argument, kw_default in zip(function.args.kwonlyargs, function.args.kw_defaults):
            if kw_default is not None:
                self._scan_expression(kw_default, scope, f"default:{argument.arg}")
        for argument in self._arguments(function.args):
            if argument.annotation is not None:
                self._scan_annotation(
                    argument.annotation, scope, f"parameter:{argument.arg}", argument.lineno
                )
            if argument.type_comment:
                self._scan_quoted_annotation(
                    argument.type_comment, scope, f"parameter:{argument.arg}", argument.lineno
                )
        if function.returns is not None:
            self._scan_annotation(function.returns, scope, "Returns", function.lineno)

    def _qualified_symbol(self, parent: str, name: str) -> str:
        """Build the agreed qualified symbol identity for a definition."""
        return name if parent == "<module>" else f"{parent}.{name}"

    def _scan_type_parameters(self, parameters: list[ast.type_param], scope: _Scope) -> None:
        """Inspect Python 3.12 generic bounds for explicit dynamic types."""
        for parameter in parameters:
            if isinstance(parameter, ast.TypeVar) and parameter.bound is not None:
                self._scan_annotation(parameter.bound, scope, f"type-bound:{parameter.name}")

    def _arguments(self, arguments: ast.arguments) -> tuple[ast.arg, ...]:
        """Return all declared arguments in source-signature order."""
        values: list[ast.arg] = [*arguments.posonlyargs, *arguments.args]
        if arguments.vararg is not None:
            values.append(arguments.vararg)
        values.extend(arguments.kwonlyargs)
        if arguments.kwarg is not None:
            values.append(arguments.kwarg)
        return tuple(values)

    def _scan_assignment_target(self, target: ast.expr, scope: _Scope) -> None:
        """Record names bound by an assignment target."""
        if isinstance(target, ast.Name):
            scope.bind_name(target.id)
            return
        for child in ast.iter_child_nodes(target):
            if isinstance(child, ast.expr):
                self._scan_assignment_target(child, scope)

    def _bind_assignment_alias(
        self,
        targets: tuple[ast.expr, ...] | list[ast.expr],
        value: ast.expr,
        scope: _Scope,
    ) -> None:
        """Preserve a typing.Any assignment alias within the current scope."""
        alias = self._alias_for_expression(value, scope)
        for target in targets:
            if isinstance(target, ast.Name):
                if alias is None:
                    scope.bind_name(target.id)
                else:
                    self._bind_alias_expression(target.id, value, scope)

    def _bind_alias_expression(self, name: str, value: ast.expr, scope: _Scope) -> None:
        """Bind a target to a recognized alias and emit its assignment finding."""
        alias = self._alias_for_expression(value, scope)
        if alias == self._ANY:
            self._add(scope.symbol, "PYT001", f"alias:{name}", getattr(value, "lineno", 1))
            scope.bind_alias(name, self._ANY)
        elif alias == self._TYPING_MODULE:
            scope.bind_alias(name, self._TYPING_MODULE)
        else:
            scope.bind_name(name)

    def _alias_for_expression(self, node: ast.expr, scope: _Scope) -> str | None:
        """Resolve a simple alias expression."""
        if isinstance(node, ast.Name):
            return scope.resolve(node.id)
        if isinstance(node, ast.Attribute) and node.attr == "Any":
            return self._attribute_alias(node, scope)
        return None

    def _scan_annotation(
        self, node: ast.expr, scope: _Scope, detail: str, line: int | None = None
    ) -> None:
        """Scan an annotation, including quoted forward references."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            self._scan_quoted_annotation(node.value, scope, detail, line)
            return
        self._scan_annotation_tree(node, scope, detail, literal_context=False, line=line)

    def _scan_annotation_tree(
        self,
        node: ast.AST,
        scope: _Scope,
        detail: str,
        literal_context: bool,
        line: int | None = None,
    ) -> None:
        """Scan annotation syntax while excluding Literal string values."""
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str) and not literal_context:
                self._scan_quoted_annotation(node.value, scope, detail, line)
            return
        if isinstance(node, ast.Attribute) and node.attr == "Any":
            if self._attribute_alias(node, scope) == self._ANY:
                self._add(scope.symbol, "PYT001", detail, line or node.lineno)
            self._scan_annotation_tree(node.value, scope, detail, literal_context, line)
            return
        if isinstance(node, ast.Name):
            if scope.resolve(node.id) == self._ANY:
                self._add(scope.symbol, "PYT001", detail, line or node.lineno)
            return
        is_literal = isinstance(node, ast.Subscript) and self._is_literal_expression(
            node.value, scope
        )
        if isinstance(node, ast.Subscript) and self._is_annotated_expression(node.value, scope):
            # Annotated's first element is a type; remaining elements are ordinary metadata.
            elements = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            if elements:
                self._scan_annotation_tree(elements[0], scope, detail, literal_context, line)
            for metadata in elements[1:]:
                self._scan_expression(metadata, scope, detail)
            return
        for child in ast.iter_child_nodes(node):
            self._scan_annotation_tree(child, scope, detail, literal_context or is_literal, line)

    def _scan_quoted_annotation(
        self, value: str, scope: _Scope, detail: str, line: int | None = None
    ) -> None:
        """Parse and scan one quoted forward annotation."""
        try:
            expression = ast.parse(value, mode="eval").body
        except (SyntaxError, ValueError):
            return
        self._scan_annotation_tree(expression, scope, detail, literal_context=False, line=line)

    def _scan_type_comment(self, value: str | None, scope: _Scope, detail: str, line: int) -> None:
        """Scan a recognized type comment while ignoring ordinary comments."""
        if not value:
            return
        expressions = [value]
        if "->" in value:
            arguments, _, result = value.partition("->")
            expressions = [arguments.strip(" ()"), result.strip()]
        for expression_text in expressions:
            if not expression_text:
                continue
            try:
                expression = ast.parse(expression_text, mode="eval").body
            except (SyntaxError, ValueError):
                continue
            if isinstance(expression, ast.expr):
                self._scan_annotation_tree(
                    expression, scope, detail, literal_context=False, line=line
                )

    def _scan_expression(self, node: ast.AST, scope: _Scope, detail: str) -> None:
        """Scan an ordinary expression while ignoring string constants."""
        if isinstance(node, ast.Constant):
            return
        if isinstance(node, ast.Attribute) and node.attr == "Any":
            if self._attribute_alias(node, scope) == self._ANY:
                self._add(
                    scope.symbol, "PYT001", self._expression_detail(detail, node), node.lineno
                )
            self._scan_expression(node.value, scope, detail)
            return
        if isinstance(node, ast.Name):
            if scope.resolve(node.id) == self._ANY:
                self._add(
                    scope.symbol, "PYT001", self._expression_detail(detail, node), node.lineno
                )
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.AST):
                self._scan_expression(child, scope, detail)

    def _attribute_alias(self, node: ast.Attribute, scope: _Scope) -> str | None:
        """Resolve a qualified typing.Any attribute."""
        if isinstance(node.value, ast.Name):
            module_alias = scope.resolve(node.value.id)
            return self._ANY if module_alias == self._TYPING_MODULE else None
        return None

    def _is_literal_expression(self, node: ast.expr, scope: _Scope) -> bool:
        """Return whether a subscript expression is typing.Literal."""
        if isinstance(node, ast.Name):
            return scope.resolve(node.id) == self._LITERAL
        if isinstance(node, ast.Attribute):
            return (
                node.attr == "Literal"
                and self._attribute_module(node, scope) in self._TYPING_MODULES
            )
        return False

    def _is_annotated_expression(self, node: ast.expr, scope: _Scope) -> bool:
        """Recognize the typing metadata wrapper through imports and qualified aliases."""
        if isinstance(node, ast.Name):
            return scope.resolve(node.id) == self._ANNOTATED
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "Annotated"
            and self._attribute_module(node, scope) in self._TYPING_MODULES
        )

    def _attribute_module(self, node: ast.Attribute, scope: _Scope) -> str | None:
        """Resolve the module name behind a qualified typing attribute."""
        if isinstance(node.value, ast.Name) and scope.resolve(node.value.id) == self._TYPING_MODULE:
            return "typing"
        return None

    def _assignment_detail(self, targets: list[ast.expr]) -> str:
        """Return a stable assignment detail key."""
        names = tuple(self._target_name(target) or "expression" for target in targets)
        return f"assignment:{','.join(names)}"

    def _target_name(self, target: ast.expr) -> str | None:
        """Return a simple target name when available."""
        return target.id if isinstance(target, ast.Name) else None

    def _expression_detail(self, detail: str, node: ast.AST) -> str:
        """Add a stable expression fingerprint to an ordinary expression detail."""
        if detail in {"expression", "base"}:
            return f"{detail}:{ast.dump(node, annotate_fields=True, include_attributes=False)}"
        return detail

    def _add(self, symbol: str, rule: str, detail: str, line: int) -> None:
        """Append one Any finding."""
        self._findings.append(
            PythonFinding(
                path=self._path,
                symbol=symbol,
                rule=rule,
                detail=detail,
                line=max(line, 1),
            )
        )


class _FunctionFactsVisitor:
    """Collect function-body facts without entering nested definitions."""

    def __init__(self) -> None:
        """Initialize empty function facts."""
        self.has_value_return = False
        self.has_yield = False
        self.has_raise = False

    def collect(self, statements: list[ast.stmt]) -> _FunctionFacts:
        """Collect return, yield, and raise facts from one function body."""
        for statement in statements:
            self._visit(statement)
        return _FunctionFacts(
            has_value_return=self.has_value_return,
            has_yield=self.has_yield,
            has_raise=self.has_raise,
        )

    def _visit(self, node: ast.AST) -> None:
        """Visit one node while stopping at nested definitions."""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        if isinstance(node, ast.Return) and node.value is not None:
            self.has_value_return = True
        elif isinstance(node, (ast.Yield, ast.YieldFrom)):
            self.has_yield = True
        elif isinstance(node, ast.Raise):
            self.has_raise = True
        for child in ast.iter_child_nodes(node):
            self._visit(child)


class _DocumentationChecker:
    """Check docstrings and structured Google-style API contracts."""

    _SECTION_NAMES: ClassVar[tuple[str, ...]] = ("Args", "Returns", "Yields", "Raises")
    _ARGUMENT_ENTRY = re.compile(r"^\s{2,}(\*{0,2}[A-Za-z_]\w*)(?:\s*\([^)]*\))?\s*:\s*(.*)$")

    def __init__(self, path: str, findings: list[PythonFinding]) -> None:
        """Initialize a documentation checker for one source invocation."""
        self._path = path
        self._findings = findings

    def check(self, module: ast.Module) -> None:
        """Check module, class, and named-function documentation."""
        self._check_definition_doc(module, "<module>")
        self._visit_statements(module.body, "<module>", "module")

    def _visit_statements(self, statements: list[ast.stmt], parent: str, kind: str) -> None:
        """Visit definitions in one statement list."""
        for statement in statements:
            self._visit_statement(statement, parent, kind)

    def _visit_statement(self, statement: ast.stmt, parent: str, kind: str) -> None:
        """Visit one definition and nested control-flow definitions."""
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbol = statement.name if parent == "<module>" else f"{parent}.{statement.name}"
            self._check_function(statement, symbol, kind == "module")
            self._visit_statements(statement.body, symbol, "function")
            return
        if isinstance(statement, ast.ClassDef):
            symbol = statement.name if parent == "<module>" else f"{parent}.{statement.name}"
            self._check_definition_doc(statement, symbol)
            self._visit_statements(statement.body, symbol, "class")
            return
        if isinstance(statement, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            self._visit_statements(statement.body, parent, kind)
            self._visit_statements(statement.orelse, parent, kind)
            return
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            self._visit_statements(statement.body, parent, kind)
            return
        if isinstance(statement, (ast.Try, ast.TryStar)):
            self._visit_statements(statement.body, parent, kind)
            for handler in statement.handlers:
                self._visit_statements(handler.body, parent, kind)
            self._visit_statements(statement.orelse, parent, kind)
            self._visit_statements(statement.finalbody, parent, kind)
            return
        if isinstance(statement, ast.Match):
            for case in statement.cases:
                self._visit_statements(case.body, parent, kind)

    def _check_definition_doc(
        self, node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, symbol: str
    ) -> str | None:
        """Check one module, class, or function summary docstring."""
        value = self._docstring(node)
        if value is None or not value.strip():
            line = node.lineno if not isinstance(node, ast.Module) else 1
            self._add(symbol, "PYD001", "summary", line)
            return None
        return value

    def _check_function(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        symbol: str,
        module_level: bool,
    ) -> None:
        """Check one function summary and its required structured sections."""
        value = self._check_definition_doc(function, symbol)
        if module_level:
            self._add(symbol, "PYC001", "module-level-function", function.lineno)
        if not self._is_public_api(function.name, symbol):
            return
        sections = self._sections(value or "")
        expected_arguments = self._expected_arguments(function.args)
        if expected_arguments:
            args_section = sections.get("Args")
            if args_section is None or not self._has_nonblank(args_section.body):
                self._add(symbol, "PYD002", "Args", function.lineno)
                for name in expected_arguments:
                    self._add(symbol, "PYD002", f"parameter:{name}", function.lineno)
            else:
                described = self._described_arguments(args_section.body)
                for name in expected_arguments:
                    if name not in described:
                        self._add(symbol, "PYD002", f"parameter:{name}", function.lineno)
        facts = _FunctionFactsVisitor().collect(function.body)
        required_section = (
            "Yields"
            if facts.has_yield
            else "Returns"
            if self._needs_returns(function, facts)
            else None
        )
        if required_section is not None:
            section = sections.get(required_section)
            if section is None or not self._has_nonblank(section.body):
                self._add(symbol, "PYD002", required_section, function.lineno)
        if facts.has_raise:
            section = sections.get("Raises")
            if section is None or not self._has_nonblank(section.body):
                self._add(symbol, "PYD002", "Raises", function.lineno)

    def _is_public_api(self, name: str, symbol: str) -> bool:
        """Return whether a function requires structured public API docs."""
        if self._path.startswith("tests/") and name.startswith("test_"):
            return False
        if name.startswith("_") and name != "__init__":
            return False
        owners = symbol.split(".")[:-1]
        return not any(owner.startswith("_") for owner in owners)

    def _needs_returns(
        self, function: ast.FunctionDef | ast.AsyncFunctionDef, facts: _FunctionFacts
    ) -> bool:
        """Return whether a function has a documented return contract."""
        if facts.has_value_return:
            return True
        if function.returns is None:
            return False
        if isinstance(function.returns, ast.Constant):
            return function.returns.value not in {None, "None"}
        return True

    def _expected_arguments(self, arguments: ast.arguments) -> tuple[str, ...]:
        """Return documented parameter names excluding implicit receivers."""
        values = [argument.arg for argument in [*arguments.posonlyargs, *arguments.args]]
        if arguments.vararg is not None:
            values.append(arguments.vararg.arg)
        values.extend(argument.arg for argument in arguments.kwonlyargs)
        if arguments.kwarg is not None:
            values.append(arguments.kwarg.arg)
        return tuple(name for name in values if name not in {"self", "cls"})

    def _sections(self, docstring: str) -> dict[str, _GoogleSection]:
        """Parse top-level Google section headers and their indented bodies."""
        lines = inspect.cleandoc(docstring).splitlines()
        sections: dict[str, _GoogleSection] = {}
        current: str | None = None
        body: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped in {f"{name}:" for name in self._SECTION_NAMES} and not line.startswith(
                (" ", "\t")
            ):
                if current is not None:
                    sections[current] = _GoogleSection(name=current, body=tuple(body))
                current = stripped[:-1]
                body = []
            elif current is not None:
                if stripped and not line.startswith((" ", "\t")):
                    sections[current] = _GoogleSection(name=current, body=tuple(body))
                    current = None
                    body = []
                else:
                    body.append(line)
        if current is not None:
            sections[current] = _GoogleSection(name=current, body=tuple(body))
        return sections

    def _described_arguments(self, lines: tuple[str, ...]) -> set[str]:
        """Return parameter names with a nonempty Google description."""
        described: set[str] = set()
        current: str | None = None
        has_text = False
        for line in lines:
            match = self._ARGUMENT_ENTRY.match(line)
            if match is not None:
                if current is not None and has_text:
                    described.add(current)
                current = match.group(1).lstrip("*")
                has_text = bool(match.group(2).strip())
            elif current is not None and line.strip():
                has_text = True
        if current is not None and has_text:
            described.add(current)
        return described

    def _has_nonblank(self, lines: tuple[str, ...]) -> bool:
        """Return whether a section contains prose or a structured entry."""
        return any(line.strip() for line in lines)

    def _docstring(
        self,
        node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> str | None:
        """Return the raw first string expression used as a docstring."""
        body = node.body
        if not body or not isinstance(body[0], ast.Expr):
            return None
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        return None

    def _add(self, symbol: str, rule: str, detail: str, line: int) -> None:
        """Append one documentation finding."""
        self._findings.append(
            PythonFinding(
                path=self._path,
                symbol=symbol,
                rule=rule,
                detail=detail,
                line=max(line, 1),
            )
        )


class PythonSourceChecker:
    """Check one Python source string against the migration standards."""

    def scan(self, path: str, source: str) -> tuple[PythonFinding, ...]:
        """Scan source and return deterministic line-aware findings.

        Args:
            path: Repository-relative or display path for the source unit.
            source: UTF-8 decoded Python source text.

        Returns:
            Findings sorted by stable identity and then source line.
        """
        findings: list[PythonFinding] = []
        source_lines = tuple(source.splitlines())
        try:
            self._tokenize(source)
        except (IndentationError, SyntaxError, tokenize.TokenError) as error:
            line = self._error_line()
            if isinstance(error, SyntaxError) and error.lineno is not None:
                line = max(error.lineno, 1)
            findings.append(
                PythonFinding(
                    path=path,
                    symbol="<module>",
                    rule="PYS001",
                    detail="tokenization",
                    line=line,
                )
            )
            return tuple(sorted(findings, key=lambda finding: (*finding.key, finding.line)))
        try:
            module = ast.parse(source, filename=path, type_comments=True)
        except (IndentationError, SyntaxError) as error:
            line = self._error_line()
            if isinstance(error, SyntaxError) and error.lineno is not None:
                line = max(error.lineno, 1)
            findings.append(
                PythonFinding(
                    path=path,
                    symbol="<module>",
                    rule="PYS001",
                    detail="syntax",
                    line=line,
                )
            )
            return tuple(sorted(findings, key=lambda finding: (*finding.key, finding.line)))
        _ImportChecker(path, source_lines, findings).check(module)
        _AnyChecker(path, findings).check(module)
        _DocumentationChecker(path, findings).check(module)
        return tuple(sorted(findings, key=lambda finding: (*finding.key, finding.line)))

    def __init__(self) -> None:
        """Initialize a stateless reusable source checker."""
        self._last_error_line = 1

    def _tokenize(self, source: str) -> None:
        """Tokenize source and retain an error line for fail-closed findings."""
        self._last_error_line = 1
        try:
            list(tokenize.generate_tokens(io.StringIO(source).readline))
        except tokenize.TokenError as error:
            location = error.args[1]
            if isinstance(location, tuple) and location and isinstance(location[0], int):
                self._last_error_line = max(location[0], 1)
            raise

    def _error_line(self) -> int:
        """Return the latest parser/tokenizer error line."""
        return max(self._last_error_line, 1)
