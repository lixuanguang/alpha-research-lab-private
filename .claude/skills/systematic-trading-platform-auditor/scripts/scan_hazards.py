"""Scan Python source for trading-platform hazard leads.

A lead is a line worth reading during an audit, not a finding. Each rule states
what to verify; the auditor confirms or dismisses every lead against the code and
the repository's contracts. Leads in library owners are listed before tooling and
application orchestrators, where sampling clocks and the environment is expected.

Typical use from the repository root:

    uv run --frozen --no-editable python \
        .claude/skills/systematic-trading-platform-auditor/scripts/scan_hazards.py src
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
class HazardRule:
    """Describe one lead pattern and what an auditor verifies about it."""

    identifier: str
    name: str
    category: str
    verify: str

    def as_record(self) -> dict[str, str]:
        """Return the rule as a JSON-ready record."""
        return {
            "identifier": self.identifier,
            "name": self.name,
            "category": self.category,
            "verify": self.verify,
        }


@dataclass(frozen=True)
class Lead:
    """Record one source line that matched a hazard rule."""

    rule: str
    path: str
    line: int
    owner: str
    layer: str
    source: str

    def as_record(self) -> dict[str, str | int]:
        """Return the lead as a JSON-ready record."""
        return {
            "rule": self.rule,
            "path": self.path,
            "line": self.line,
            "owner": self.owner,
            "layer": self.layer,
            "source": self.source,
        }


class RuleCatalog:
    """Own the hazard rules in their display order."""

    RULES: ClassVar[tuple[HazardRule, ...]] = (
        HazardRule(
            "T1",
            "wall-clock-read",
            "temporal",
            "Libraries receive clocks explicitly; orchestrators may sample them. Durations "
            "need a monotonic clock. Check the owning contract for deliberate sampling points.",
        ),
        HazardRule(
            "T2",
            "naive-or-host-time",
            "temporal",
            "Every instant must be timezone-aware UTC and local time needs an explicit IANA "
            "zone; naive values and the host timezone shift instants silently.",
        ),
        HazardRule(
            "T3",
            "missing-value-fill",
            "temporal",
            "Missing values stay explicit; a fill carries a stale, zero or future value into "
            "a feature or decision.",
        ),
        HazardRule(
            "T4",
            "negative-shift",
            "temporal",
            "A negative shift reads later rows: acceptable for a label, leakage in a feature.",
        ),
        HazardRule(
            "T5",
            "as-of-join",
            "temporal",
            "Join on availability time with the contract's inclusivity; check direction, "
            "exact matches and tolerance.",
        ),
        HazardRule(
            "T6",
            "window-edges",
            "temporal",
            "Windows are half-open and completed; check closed and label edges and centring.",
        ),
        HazardRule(
            "N1",
            "float-conversion",
            "numeric",
            "Floats never feed decisions, postings, reservations, risk checks or "
            "reconciliation; they belong only in declared analytical projections.",
        ),
        HazardRule(
            "N2",
            "decimal-from-float",
            "numeric",
            "Build Decimal from str or int; a float argument carries binary error into money.",
        ),
        HazardRule(
            "N3",
            "ambient-decimal-context",
            "numeric",
            "Results must not depend on the ambient Decimal context or its precision.",
        ),
        HazardRule(
            "N4",
            "builtin-round",
            "numeric",
            "Money rounding needs an explicit quantum and mode, applied once.",
        ),
        HazardRule(
            "N5",
            "tolerance-compare",
            "numeric",
            "Exact reconciliation uses no tolerance; an approximate comparison needs a "
            "derived error bound.",
        ),
        HazardRule(
            "D1",
            "builtin-hash",
            "determinism",
            "hash() of str and bytes is salted per process; never use it for identity, "
            "ordering or partitioning.",
        ),
        HazardRule(
            "D2",
            "unseeded-random",
            "determinism",
            "Randomness takes an explicit seed or generator so that runs reproduce.",
        ),
        HazardRule(
            "D3",
            "non-canonical-json",
            "determinism",
            "json.dumps without sort_keys is not canonical; identities and digests need a "
            "canonical codec.",
        ),
        HazardRule(
            "D4",
            "set-iteration-order",
            "determinism",
            "A set of strings iterates in a per-process order; sort it before it reaches "
            "output, hashes or decisions.",
        ),
        HazardRule(
            "F1",
            "broad-except",
            "failure",
            "Broad handlers belong only at a process or task boundary that records the "
            "failure and produces a defined outcome.",
        ),
        HazardRule(
            "F2",
            "swallowed-exception",
            "failure",
            "A handler that only logs, passes, continues or returns a constant can turn a "
            "failure into approval, silent data loss or a skipped posting.",
        ),
        HazardRule(
            "F3",
            "environment-read",
            "failure",
            "Libraries receive configuration explicitly; environment reads belong to "
            "orchestrators.",
        ),
        HazardRule(
            "F4",
            "blocking-sleep",
            "failure",
            "Sleeps block event loops and often hide unbounded retries; check bounds and backoff.",
        ),
        HazardRule(
            "P1",
            "sequence-growth-in-loop",
            "performance",
            "Rebuilding a tuple or list from itself per iteration is quadratic in history length.",
        ),
        HazardRule(
            "P2",
            "copy-in-loop",
            "performance",
            "Per-iteration model_copy or deepcopy re-validates or copies whole objects.",
        ),
        HazardRule(
            "P3",
            "codec-in-loop",
            "performance",
            "Construct codecs, encoders and decoders once per owner, not per iteration.",
        ),
        HazardRule(
            "P4",
            "row-iteration",
            "performance",
            "Row-wise dataframe iteration; prefer vectorised or lazy expressions.",
        ),
    )

    @classmethod
    def identifiers(cls) -> tuple[str, ...]:
        """Return the rule identifiers in display order."""
        return tuple(rule.identifier for rule in cls.RULES)

    @classmethod
    def categories(cls) -> tuple[str, ...]:
        """Return the rule categories in display order."""
        ordered: list[str] = []
        for rule in cls.RULES:
            if rule.category not in ordered:
                ordered.append(rule.category)
        return tuple(ordered)

    @classmethod
    def rule(cls, identifier: str) -> HazardRule:
        """Return the rule with an identifier."""
        return cls.RULES[cls.identifiers().index(identifier)]

    @classmethod
    def position(cls, identifier: str) -> int:
        """Return the display position of a rule."""
        return cls.identifiers().index(identifier)


class SourceLocator:
    """Find Python files and classify each one by owner and layer."""

    SKIPPED_DIRECTORIES: ClassVar[frozenset[str]] = frozenset(
        {
            ".dependency-cache",
            ".git",
            ".hypothesis",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".uv-cache",
            ".venv",
            "__pycache__",
            "build",
            "data",
            "dist",
            "logs",
            "node_modules",
            "venv",
        }
    )
    GROUPING_NAMESPACES: ClassVar[frozenset[str]] = frozenset(
        {"applications", "market_data", "reference_data", "research"}
    )
    LAYERS: ClassVar[tuple[str, ...]] = ("library", "tooling", "application", "test")

    def __init__(self, root: Path, include_tests: bool) -> None:
        """Bind the repository root and whether directory walks include tests."""
        self.root = root
        self.include_tests = include_tests

    def files(self, targets: list[Path]) -> list[Path]:
        """Return the Python files under the targets in a stable order."""
        found: set[Path] = set()
        for target in targets:
            resolved = target.resolve()
            if resolved.is_file():
                if resolved.suffix == ".py":
                    found.add(resolved)
                continue
            include_tests = self.include_tests or self._is_test(self.display(resolved))
            for candidate in resolved.rglob("*.py"):
                directories = candidate.relative_to(resolved).parts[:-1]
                if any(part in self.SKIPPED_DIRECTORIES for part in directories):
                    continue
                if include_tests or not self._is_test(self.display(candidate)):
                    found.add(candidate)
        return sorted(found)

    def display(self, path: Path) -> str:
        """Return a path relative to the root when it lies inside the root."""
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def classify(self, path: Path) -> tuple[str, str]:
        """Return the owner and layer of a source file."""
        shown = self.display(path)
        if self._is_test(shown):
            return "tests", "test"
        parts = Path(shown).parts
        if len(parts) >= 3 and parts[0] == "src":
            owner = parts[1]
            if owner in self.GROUPING_NAMESPACES and len(parts) >= 4:
                owner = f"{owner}.{parts[2]}"
            return owner, ("application" if parts[1] == "applications" else "library")
        return (parts[0] if len(parts) > 1 else "."), "tooling"

    @staticmethod
    def _is_test(shown: str) -> bool:
        """Report whether a displayed path is test code."""
        path = Path(shown)
        return "tests" in path.parts or path.name.startswith("test_") or path.name == "conftest.py"


class HazardVisitor(ast.NodeVisitor):
    """Collect hazard leads from one parsed module."""

    WALL_CLOCK_SUFFIXES: ClassVar[tuple[str, ...]] = (
        "datetime.now",
        "datetime.today",
        "datetime.utcnow",
        "date.today",
        "Timestamp.now",
        "Timestamp.today",
        "Timestamp.utcnow",
    )
    WALL_CLOCK_CALLS: ClassVar[frozenset[str]] = frozenset({"time.time", "time.time_ns"})
    FILL_METHODS: ClassVar[frozenset[str]] = frozenset(
        {"backfill", "bfill", "ffill", "fill_nan", "fill_null", "fillna", "interpolate"}
    )
    WINDOW_METHODS: ClassVar[frozenset[str]] = frozenset(
        {"group_by_dynamic", "resample", "upsample"}
    )
    TOLERANCE_CALLS: ClassVar[frozenset[str]] = frozenset(
        {"allclose", "approx", "assert_allclose", "assert_almost_equal", "isclose"}
    )
    CONTEXT_CALLS: ClassVar[frozenset[str]] = frozenset(
        {"getcontext", "localcontext", "setcontext"}
    )
    RANDOM_CALLS: ClassVar[frozenset[str]] = frozenset(
        {
            "betavariate",
            "choice",
            "choices",
            "expovariate",
            "gauss",
            "getrandbits",
            "normal",
            "normalvariate",
            "permutation",
            "rand",
            "randint",
            "randn",
            "random",
            "randrange",
            "sample",
            "seed",
            "shuffle",
            "triangular",
            "uniform",
        }
    )
    UNSEEDED_CONSTRUCTORS: ClassVar[frozenset[str]] = frozenset(
        {"Random", "RandomState", "default_rng"}
    )
    LOG_CALLS: ClassVar[frozenset[str]] = frozenset(
        {"critical", "debug", "error", "exception", "info", "log", "print", "warn", "warning"}
    )
    ROW_METHODS: ClassVar[frozenset[str]] = frozenset(
        {"iter_rows", "iterrows", "itertuples", "map_rows"}
    )
    SET_CONSUMERS: ClassVar[frozenset[str]] = frozenset({"enumerate", "iter", "list", "tuple"})
    FLOAT_TYPES: ClassVar[frozenset[str]] = frozenset({"float16", "float32", "float64"})

    def __init__(self, path: str, lines: list[str], owner: str, layer: str) -> None:
        """Bind the file being scanned and its classification."""
        self.path = path
        self.lines = lines
        self.owner = owner
        self.layer = layer
        self.leads: list[Lead] = []
        self._seen: set[tuple[str, int]] = set()
        self._loop_depth = 0

    def visit_Call(self, node: ast.Call) -> None:
        """Check one call against every call-shaped rule."""
        name = self._dotted(node.func)
        last = name.rsplit(".", 1)[-1]
        self._check_clocks(node, name, last)
        self._check_fills_and_windows(node, last)
        self._check_numbers(node, name, last)
        self._check_determinism(node, name, last)
        self._check_operations(node, name, last)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Flag reads of the process environment."""
        if node.attr == "environ" and isinstance(node.value, ast.Name) and node.value.id == "os":
            self._add("F3", node)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        """Flag broad handlers and handlers that swallow the failure."""
        if self._is_broad(node.type):
            self._add("F1", node)
        if self._swallows(node):
            self._add("F2", node)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        """Flag iteration over sets and track loop depth."""
        if self._is_set_expression(node.iter):
            self._add("D4", node)
        self._visit_loop(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        """Flag iteration over sets and track loop depth."""
        if self._is_set_expression(node.iter):
            self._add("D4", node)
        self._visit_loop(node)

    def visit_While(self, node: ast.While) -> None:
        """Track loop depth."""
        self._visit_loop(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        """Track loop depth inside a list comprehension."""
        self._visit_loop(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        """Track loop depth inside a set comprehension."""
        self._visit_loop(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        """Track loop depth inside a dict comprehension."""
        self._visit_loop(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        """Track loop depth inside a generator expression."""
        self._visit_loop(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """Flag tuple growth by augmented assignment inside loops."""
        if self._loop_depth and isinstance(node.op, ast.Add) and isinstance(node.value, ast.Tuple):
            self._add("P1", node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Flag rebuilding a tuple or list from itself inside loops."""
        if (
            self._loop_depth
            and len(node.targets) == 1
            and self._rebuilds_sequence(node.targets[0], node.value)
        ):
            self._add("P1", node)
        self.generic_visit(node)

    def _visit_loop(self, node: ast.AST) -> None:
        """Visit a loop or comprehension with the loop depth raised."""
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def _check_clocks(self, node: ast.Call, name: str, last: str) -> None:
        """Flag wall-clock reads and naive or host-timezone datetimes."""
        if name in self.WALL_CLOCK_CALLS or name.endswith(self.WALL_CLOCK_SUFFIXES):
            self._add("T1", node)
        if self._creates_naive_time(node, name, last):
            self._add("T2", node)

    def _creates_naive_time(self, node: ast.Call, name: str, last: str) -> bool:
        """Report whether a call builds a naive datetime or uses the host timezone."""
        keywords = {keyword.arg for keyword in node.keywords}
        if name.split(".")[-1] == "datetime" and 3 <= len(node.args) < 8:
            return "tzinfo" not in keywords
        if last in {"utcfromtimestamp", "utcnow"}:
            return True
        if last == "fromtimestamp":
            return len(node.args) < 2 and "tz" not in keywords
        if name.endswith("datetime.today"):
            return True
        if name.endswith("datetime.now"):
            return not node.args and "tz" not in keywords
        if last == "strptime":
            return not self._format_has_offset(node)
        if last == "astimezone":
            return not node.args and not node.keywords
        if last == "replace":
            return self._keyword_is_none(node, "tzinfo")
        if last in {"tz_convert", "tz_localize"}:
            return bool(node.args) and self._is_none(node.args[0])
        return False

    def _check_fills_and_windows(self, node: ast.Call, last: str) -> None:
        """Flag missing-value fills, negative shifts, as-of joins and window edges."""
        if last in self.FILL_METHODS:
            self._add("T3", node)
        if last == "shift" and self._has_negative_shift(node):
            self._add("T4", node)
        if last in {"join_asof", "merge_asof"}:
            self._add("T5", node)
        if last in self.WINDOW_METHODS or (
            last == "rolling" and self._keyword_is_true(node, "center")
        ):
            self._add("T6", node)

    def _check_numbers(self, node: ast.Call, name: str, last: str) -> None:
        """Flag float conversion, float-built decimals, ambient context, round and tolerance."""
        if name == "float" or last in self.FLOAT_TYPES or self._is_float_astype(node, last):
            self._add("N1", node)
        if last == "from_float" or (last == "Decimal" and self._first_argument_is_float(node)):
            self._add("N2", node)
        if last in self.CONTEXT_CALLS:
            self._add("N3", node)
        if name == "round":
            self._add("N4", node)
        if last in self.TOLERANCE_CALLS:
            self._add("N5", node)

    def _check_determinism(self, node: ast.Call, name: str, last: str) -> None:
        """Flag salted hashing, unseeded randomness, non-canonical JSON and set order."""
        if name == "hash":
            self._add("D1", node)
        if self._is_unseeded_random(node, name, last):
            self._add("D2", node)
        if name in {"dumps", "json.dumps"} and not self._keyword_is_true(node, "sort_keys"):
            self._add("D3", node)
        if (
            (name in self.SET_CONSUMERS or last == "join")
            and node.args
            and self._is_set_expression(node.args[0])
        ):
            self._add("D4", node)

    def _check_operations(self, node: ast.Call, name: str, last: str) -> None:
        """Flag environment reads, sleeps, row iteration and per-iteration copies or codecs."""
        if name in {"getenv", "os.getenv", "os.putenv"}:
            self._add("F3", node)
        if name in {"sleep", "time.sleep"}:
            self._add("F4", node)
        if last in self.ROW_METHODS or (last == "apply" and self._is_row_axis(node)):
            self._add("P4", node)
        if not self._loop_depth:
            return
        if last in {"deepcopy", "model_copy"}:
            self._add("P2", node)
        if last.endswith(("Codec", "Decoder", "Encoder")) and last[:1].isupper():
            self._add("P3", node)

    def _is_unseeded_random(self, node: ast.Call, name: str, last: str) -> bool:
        """Report whether a call draws from global or unseeded random state."""
        parts = name.split(".")
        if len(parts) == 2 and parts[0] == "random" and parts[1] in self.RANDOM_CALLS:
            return True
        if (
            len(parts) >= 3
            and parts[-3] in {"np", "numpy"}
            and parts[-2] == "random"
            and parts[-1] in self.RANDOM_CALLS
        ):
            return True
        if last in self.UNSEEDED_CONSTRUCTORS:
            return not node.args and not node.keywords
        return False

    def _swallows(self, handler: ast.ExceptHandler) -> bool:
        """Report whether a handler only logs, passes, continues or returns a constant."""
        for statement in handler.body:
            if any(isinstance(child, ast.Raise) for child in ast.walk(statement)):
                return False
            if not self._is_swallowing_statement(statement):
                return False
        return True

    def _is_swallowing_statement(self, statement: ast.stmt) -> bool:
        """Report whether a handler statement discards the failure."""
        if isinstance(statement, (ast.Break, ast.Continue, ast.Pass)):
            return True
        if isinstance(statement, ast.Return):
            return statement.value is None or isinstance(statement.value, ast.Constant)
        if isinstance(statement, ast.Expr):
            if isinstance(statement.value, ast.Constant):
                return True
            if isinstance(statement.value, ast.Call):
                return self._dotted(statement.value.func).rsplit(".", 1)[-1] in self.LOG_CALLS
        return False

    def _rebuilds_sequence(self, target: ast.expr, value: ast.expr) -> bool:
        """Report whether an assignment rebuilds a sequence from the same target."""
        target_name = self._dotted(target)
        if "?" in target_name:
            return False
        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
            return (
                isinstance(value.right, (ast.List, ast.Tuple))
                and self._dotted(value.left) == target_name
            )
        if isinstance(value, (ast.List, ast.Tuple)) and value.elts:
            first = value.elts[0]
            return isinstance(first, ast.Starred) and self._dotted(first.value) == target_name
        return False

    def _has_negative_shift(self, node: ast.Call) -> bool:
        """Report whether a shift call moves values backwards in time."""
        candidates = list(node.args[:1])
        candidates.extend(
            keyword.value for keyword in node.keywords if keyword.arg in {"n", "periods"}
        )
        return any(self._is_negative_integer(candidate) for candidate in candidates)

    def _is_float_astype(self, node: ast.Call, last: str) -> bool:
        """Report whether an astype call converts to a float dtype."""
        if last != "astype" or not node.args:
            return False
        dtype = node.args[0]
        if isinstance(dtype, ast.Name):
            return dtype.id == "float"
        if isinstance(dtype, ast.Constant):
            return isinstance(dtype.value, str) and "float" in dtype.value
        if isinstance(dtype, ast.Attribute):
            return dtype.attr in self.FLOAT_TYPES
        return False

    def _first_argument_is_float(self, node: ast.Call) -> bool:
        """Report whether a Decimal constructor receives a float."""
        if not node.args:
            return False
        argument = node.args[0]
        if isinstance(argument, ast.Constant):
            return isinstance(argument.value, float)
        return isinstance(argument, ast.Call) and self._dotted(argument.func) == "float"

    def _is_set_expression(self, expression: ast.expr) -> bool:
        """Report whether an expression evaluates to a set."""
        if isinstance(expression, (ast.Set, ast.SetComp)):
            return True
        return isinstance(expression, ast.Call) and self._dotted(expression.func) in {
            "frozenset",
            "set",
        }

    def _is_broad(self, handled: ast.expr | None) -> bool:
        """Report whether an except clause catches every ordinary exception."""
        if handled is None:
            return True
        if isinstance(handled, ast.Name):
            return handled.id in {"BaseException", "Exception"}
        if isinstance(handled, ast.Tuple):
            return any(self._is_broad(element) for element in handled.elts)
        return False

    def _add(self, rule: str, node: ast.stmt | ast.expr | ast.excepthandler) -> None:
        """Record a lead once per rule and line."""
        key = (rule, node.lineno)
        if key in self._seen:
            return
        self._seen.add(key)
        line = node.lineno
        source = self.lines[line - 1].strip() if 0 < line <= len(self.lines) else ""
        self.leads.append(
            Lead(
                rule=rule,
                path=self.path,
                line=line,
                owner=self.owner,
                layer=self.layer,
                source=source[:140],
            )
        )

    @classmethod
    def _dotted(cls, node: ast.expr) -> str:
        """Return the dotted source name of an expression, with '?' for dynamic parts."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{cls._dotted(node.value)}.{node.attr}"
        if isinstance(node, ast.Call):
            return f"{cls._dotted(node.func)}()"
        return "?"

    @staticmethod
    def _format_has_offset(node: ast.Call) -> bool:
        """Report whether a strptime format parses a UTC offset, assuming so if unknown."""
        if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant):
            return True
        pattern = node.args[1].value
        return not isinstance(pattern, str) or "%z" in pattern

    @staticmethod
    def _is_none(expression: ast.expr) -> bool:
        """Report whether an expression is the literal None."""
        return isinstance(expression, ast.Constant) and expression.value is None

    @classmethod
    def _keyword_is_none(cls, node: ast.Call, name: str) -> bool:
        """Report whether a call passes None for a keyword."""
        return any(keyword.arg == name and cls._is_none(keyword.value) for keyword in node.keywords)

    @staticmethod
    def _keyword_is_true(node: ast.Call, name: str) -> bool:
        """Report whether a call passes True for a keyword."""
        return any(
            keyword.arg == name
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        )

    @staticmethod
    def _is_row_axis(node: ast.Call) -> bool:
        """Report whether an apply call runs once per dataframe row."""
        return any(
            keyword.arg == "axis"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value in (1, "columns")
            for keyword in node.keywords
        )

    @staticmethod
    def _is_negative_integer(expression: ast.expr) -> bool:
        """Report whether an expression is a negative integer literal."""
        if (
            isinstance(expression, ast.UnaryOp)
            and isinstance(expression.op, ast.USub)
            and isinstance(expression.operand, ast.Constant)
        ):
            value = expression.operand.value
            return isinstance(value, int) and not isinstance(value, bool) and value > 0
        return False


class HazardScanner:
    """Parse source files and collect their hazard leads."""

    def __init__(self, locator: SourceLocator) -> None:
        """Bind the locator that names and classifies files."""
        self.locator = locator

    def scan(self, files: list[Path]) -> tuple[list[Lead], list[str]]:
        """Return the leads found in the files and the files that could not be parsed."""
        leads: list[Lead] = []
        unparsed: list[str] = []
        for path in files:
            shown = self.locator.display(path)
            try:
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text, filename=shown)
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as error:
                unparsed.append(f"{shown}: {type(error).__name__}: {error}")
                continue
            owner, layer = self.locator.classify(path)
            visitor = HazardVisitor(shown, text.splitlines(), owner, layer)
            visitor.visit(tree)
            leads.extend(visitor.leads)
        return leads, unparsed


class LeadReport:
    """Filter, order and render hazard leads for an auditor."""

    def __init__(
        self, leads: list[Lead], scanned: int, unparsed: list[str], paths: list[str]
    ) -> None:
        """Bind the leads of one scan and its scope."""
        self.leads = sorted(leads, key=self._sort_key)
        self.scanned = scanned
        self.unparsed = unparsed
        self.paths = paths

    def select(
        self,
        rules: list[str] | None,
        categories: list[str] | None,
        layers: list[str] | None,
    ) -> LeadReport:
        """Return a report restricted to the given rules, categories and layers."""
        kept = [
            lead
            for lead in self.leads
            if (rules is None or lead.rule in rules)
            and (categories is None or RuleCatalog.rule(lead.rule).category in categories)
            and (layers is None or lead.layer in layers)
        ]
        return LeadReport(kept, self.scanned, self.unparsed, self.paths)

    def render_text(self, limit: int) -> str:
        """Render a summary table and up to `limit` leads per rule (0 for all)."""
        files = len({lead.path for lead in self.leads})
        lines = [
            f"Hazard leads: {len(self.leads)} in {files} of {self.scanned} Python files "
            f"({', '.join(self.paths)})",
            "Leads are lines to read, not findings. Confirm or dismiss each one against "
            "the code and its contract.",
            "",
        ]
        lines.extend(self._summary_lines())
        for identifier in RuleCatalog.identifiers():
            lines.extend(self._rule_lines(identifier, limit))
        if self.unparsed:
            lines.append("")
            lines.append("Could not parse:")
            lines.extend(f"  {entry}" for entry in self.unparsed)
        return "\n".join(lines)

    def render_json(self) -> str:
        """Render the complete report as JSON."""
        present = sorted({lead.rule for lead in self.leads}, key=RuleCatalog.position)
        document: dict[str, object] = {
            "paths": self.paths,
            "scanned_files": self.scanned,
            "unparsed": self.unparsed,
            "rules": [RuleCatalog.rule(identifier).as_record() for identifier in present],
            "leads": [lead.as_record() for lead in self.leads],
        }
        return json.dumps(document, indent=2, sort_keys=True)

    def _summary_lines(self) -> list[str]:
        """Return the per-rule, per-layer count table."""
        counts = Counter((lead.rule, lead.layer) for lead in self.leads)
        header = f"{'rule':<5} {'name':<24} {'category':<12}" + "".join(
            f" {layer:>11}" for layer in SourceLocator.LAYERS
        )
        lines = [header]
        for rule in RuleCatalog.RULES:
            row = [counts[(rule.identifier, layer)] for layer in SourceLocator.LAYERS]
            if sum(row):
                lines.append(
                    f"{rule.identifier:<5} {rule.name:<24} {rule.category:<12}"
                    + "".join(f" {count:>11}" for count in row)
                )
        if len(lines) == 1:
            lines.append("(no leads)")
        return lines

    def _rule_lines(self, identifier: str, limit: int) -> list[str]:
        """Return the detailed lines for one rule."""
        leads = [lead for lead in self.leads if lead.rule == identifier]
        if not leads:
            return []
        rule = RuleCatalog.rule(identifier)
        shown = leads if limit <= 0 else leads[:limit]
        lines = [
            "",
            f"{rule.identifier} {rule.name} ({rule.category}): {len(leads)}",
            f"  verify: {rule.verify}",
        ]
        lines.extend(
            f"  {lead.layer:<11} {lead.path}:{lead.line}  [{lead.owner}]  {lead.source}"
            for lead in shown
        )
        hidden = len(leads) - len(shown)
        if hidden:
            lines.append(f"  ... {hidden} more; use --rule {identifier} with --layer, or --limit 0")
        return lines

    @staticmethod
    def _sort_key(lead: Lead) -> tuple[int, int, str, int]:
        """Order leads by rule, then layer priority, then location."""
        return (
            RuleCatalog.position(lead.rule),
            SourceLocator.LAYERS.index(lead.layer),
            lead.path,
            lead.line,
        )


class ScanOptions(argparse.Namespace):
    """Hold the parsed command-line options with precise types."""

    paths: list[str]
    root: str
    rules: list[str] | None
    categories: list[str] | None
    layers: list[str] | None
    limit: int
    include_tests: bool
    output: str


class ScanCommand:
    """Own the command-line interface of the hazard scanner."""

    @classmethod
    def parser(cls) -> argparse.ArgumentParser:
        """Build the argument parser, listing every rule in the help text."""
        parser = argparse.ArgumentParser(
            description="List trading-platform hazard leads for an audit to read.",
            epilog=cls._epilog(),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument("paths", nargs="*", help="files or directories (default: src)")
        parser.add_argument(
            "--root", default=".", help="repository root used for relative paths (default: .)"
        )
        parser.add_argument(
            "--rule",
            dest="rules",
            action="append",
            choices=RuleCatalog.identifiers(),
            help="only this rule; repeatable",
        )
        parser.add_argument(
            "--category",
            dest="categories",
            action="append",
            choices=RuleCatalog.categories(),
            help="only this category; repeatable",
        )
        parser.add_argument(
            "--layer",
            dest="layers",
            action="append",
            choices=SourceLocator.LAYERS,
            help="only this layer; repeatable",
        )
        parser.add_argument(
            "--limit", type=int, default=12, help="leads shown per rule; 0 shows all (default 12)"
        )
        parser.add_argument(
            "--include-tests", action="store_true", help="include tests in directory walks"
        )
        parser.add_argument(
            "--format", dest="output", choices=("text", "json"), default="text", help="output"
        )
        return parser

    @staticmethod
    def _epilog() -> str:
        """Describe every rule for the help text."""
        lines = ["rules:"]
        lines.extend(
            f"  {rule.identifier} {rule.name} ({rule.category}): {rule.verify}"
            for rule in RuleCatalog.RULES
        )
        return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Scan the selected paths and print hazard leads for an auditor."""
    options = ScanCommand.parser().parse_args(argv, namespace=ScanOptions())
    paths = options.paths or ["src"]
    root = Path(options.root).resolve()
    targets = [root / path for path in paths]
    missing = [str(target) for target in targets if not target.exists()]
    if missing:
        print(f"scan_hazards: no such path: {', '.join(missing)}", file=sys.stderr)
        return 2
    locator = SourceLocator(root, include_tests=options.include_tests)
    files = locator.files(targets)
    if not files:
        print("scan_hazards: no Python files under the given paths", file=sys.stderr)
        return 2
    leads, unparsed = HazardScanner(locator).scan(files)
    report = LeadReport(leads, len(files), unparsed, paths).select(
        options.rules, options.categories, options.layers
    )
    print(report.render_json() if options.output == "json" else report.render_text(options.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
