"""Keep the remaining inferred Python typing debt exact and reviewable."""

from __future__ import annotations

# standard library imports
import ast
import hashlib
import subprocess  # nosec B404  # [owner=platform; rationale=run the pinned local mypy checker with fixed arguments; expires=2027-03-01]
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

# third party library imports
from pydantic import Field

# project library imports
from alpha_research_governance._models import ImmutableModel

TYPING_DEBT_PATH = "docs/architecture/python-typing-debt.json"
TYPING_DEBT_SHA256 = "f3382fca2f6cdb8235de0f08af9852dbe82ea2730cb40ee1c6faf28f6fa95fd1"
TYPING_PATHS = ("src", "tests", "tools/governance/src", "tools/typing/stubs")
type DiagnosticKey = tuple[str, str, str, str]


class MypyDiagnostic(ImmutableModel):
    """Decode one pinned mypy JSON diagnostic without retaining untyped JSON."""

    file: str
    line: int
    column: int
    end_line: int | None
    end_column: int | None
    message: str
    hint: str | None
    code: str
    severity: Literal["error", "note"]


class TypingRetirementTask(ImmutableModel):
    """Describe the cause, accountable role and concrete work for a debt category."""

    owner_role: Literal["platform", "domain_architecture"]
    cause: str = Field(min_length=20)
    retirement: str = Field(min_length=20)


class TypingObligation(ImmutableModel):
    """Bind a diagnostic multiplicity and retirement task to one qualified symbol."""

    path: str
    symbol: str
    code: str
    message: str
    count: int = Field(gt=0)
    task: str

    @property
    def key(self) -> DiagnosticKey:
        """Return the location-independent identity used for debt reconciliation.

        Returns:
            Source path, qualified symbol, mypy code and complete diagnostic text.
        """
        return self.path, self.symbol, self.code, self.message


class TypingDebtInventory(ImmutableModel):
    """Record unresolved diagnostics separately from source-standard exceptions."""

    schema_version: Literal[1]
    baseline_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    mypy_version: Literal["2.3.1"]
    tasks: dict[str, TypingRetirementTask]
    obligations: tuple[TypingObligation, ...]

    def reconcile(self, observed: Counter[DiagnosticKey]) -> tuple[str, ...]:
        """Reject new, moved, multiplied, resolved or unattributed diagnostics.

        Args:
            observed: Full-scope diagnostics from the stronger mypy probe.

        Returns:
            Stable errors for inventory drift or invalid task assignments.
        """
        expected: Counter[DiagnosticKey] = Counter()
        findings: list[str] = []
        for item in self.obligations:
            if item.key in expected or item.task not in self.tasks:
                findings.append(
                    f"invalid or duplicate typing obligation: {item.path}:{item.symbol}"
                )
            expected[item.key] += item.count
        for key, count in sorted((observed - expected).items()):
            findings.append(f"new typing debt {key!r} ({count})")
        for key, count in sorted((expected - observed).items()):
            findings.append(f"retire resolved typing debt {key!r} ({count})")
        return tuple(findings)


class TypingInventoryChecker:
    """Own a repository's diagnostic probe and compare its exact remaining debt."""

    def __init__(self, repository_root: Path) -> None:
        """Capture the repository root without reading files or starting processes.

        Args:
            repository_root: Checkout containing the configuration, source and inventory.
        """
        self._root = repository_root

    @staticmethod
    def symbol_at(source: str, line: int) -> str:
        """Locate the innermost definition, including its decorator lines.

        Args:
            source: Python module text corresponding to the diagnostic.
            line: One-based diagnostic line reported by mypy.

        Returns:
            Qualified lexical symbol, or the module identity for top-level statements.

        Raises:
            SyntaxError: Source cannot be parsed by the pinned interpreter.
        """
        nodes = ast.parse(source).body
        scope: list[str] = []
        while nodes:
            enclosing = next(
                (
                    node
                    for node in nodes
                    if min(
                        [node.lineno]
                        + [
                            item.lineno
                            for item in (
                                node.decorator_list
                                if isinstance(
                                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                                )
                                else []
                            )
                        ]
                    )
                    <= line
                    <= (node.end_lineno or node.lineno)
                ),
                None,
            )
            if enclosing is None:
                break
            if isinstance(enclosing, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                scope.append(enclosing.name)
                nodes = enclosing.body
            else:
                children = list(ast.iter_child_nodes(enclosing))
                nodes = []
                while children:
                    child = children.pop(0)
                    if isinstance(child, ast.stmt):
                        nodes.append(child)
                    else:
                        children.extend(ast.iter_child_nodes(child))
        return ".".join(scope) or "<module>"

    def observed(self, output: str) -> Counter[DiagnosticKey]:
        """Validate machine output and assign errors to owned source symbols.

        Args:
            output: Newline-delimited JSON from mypy's pinned JSON formatter.

        Returns:
            Exact diagnostic identities with multiplicities preserved.

        Raises:
            ValueError: Output is malformed or names an unowned source path.
            OSError: A diagnostic source cannot be read.
            SyntaxError: A diagnostic source cannot be parsed.
        """
        result: Counter[DiagnosticKey] = Counter()
        sources: dict[str, str] = {}
        for record in output.splitlines():
            item = MypyDiagnostic.model_validate_json(record)
            if item.severity != "error":
                continue
            path = Path(item.file)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not any(item.file.startswith(f"{root}/") for root in TYPING_PATHS)
            ):
                raise ValueError(f"mypy diagnostic outside the owned scope: {item.file}")
            if item.file not in sources:
                sources[item.file] = (self._root / path).read_text(encoding="utf-8")
            symbol = self.symbol_at(sources[item.file], item.line)
            result[item.file, symbol, item.code, item.message] += 1
        return result

    def _inventory(self) -> TypingDebtInventory:
        """Read and validate the checksum-pinned inventory.

        Returns:
            Validated obligations and their retirement tasks.

        Raises:
            OSError: The inventory cannot be read.
            ValueError: Its checksum or schema differs from the reviewed contract.
        """
        payload = (self._root / TYPING_DEBT_PATH).read_bytes()
        if hashlib.sha256(payload).hexdigest() != TYPING_DEBT_SHA256:
            raise ValueError("typing debt checksum differs from the reviewed inventory")
        return TypingDebtInventory.model_validate_json(payload)

    def _probe(self) -> Counter[DiagnosticKey]:
        """Run the pinned stronger probe and validate its completion status.

        Returns:
            Exact diagnostics for all source, test and stub files.

        Raises:
            OSError: The checker cannot start or a source cannot be read.
            ValueError: The checker fails or returns invalid machine output.
            SyntaxError: Diagnostic source cannot be parsed.
        """
        process = subprocess.run(  # nosec B603  # [owner=platform; rationale=pinned interpreter and fixed mypy diagnostic arguments without shell execution; expires=2027-03-01]
            [
                sys.executable,
                "-m",
                "mypy",
                "--strict",
                "--disallow-any-expr",
                "--disallow-any-decorated",
                "--output=json",
                "--cache-dir=.mypy_cache/typing-inventory",
                *TYPING_PATHS,
            ],
            cwd=self._root,
            check=False,
            capture_output=True,
            text=True,
        )
        if process.returncode not in {0, 1} or process.stderr:
            raise ValueError(f"mypy probe failed: {process.stderr or process.stdout}")
        observed = self.observed(process.stdout)
        if (process.returncode == 1) != bool(observed):
            raise ValueError("mypy exit status disagrees with its diagnostic output")
        return observed

    def run(self) -> int:
        """Run the stronger probe and fail on drift without rewriting the inventory.

        Returns:
            Zero for exact reviewed debt, one for drift or tool/policy failure.
        """
        try:
            inventory = self._inventory()
            observed = self._probe()
            findings = inventory.reconcile(observed)
            for finding in findings:
                print(finding)
            if findings:
                return 1
            print(f"Python typing inventory matches {observed.total()} unresolved diagnostics")
            return 0
        except (OSError, ValueError, SyntaxError) as error:
            print(f"Python typing inventory: {error}")
            return 1


if __name__ == "__main__":
    raise SystemExit(TypingInventoryChecker(Path.cwd()).run())
