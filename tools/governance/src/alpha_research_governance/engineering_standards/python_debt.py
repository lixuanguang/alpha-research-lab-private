"""Enforce Python source findings and reviewed design exceptions."""

from __future__ import annotations

# standard library imports
import ast
import hashlib
import tomllib
from collections import Counter
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from typing import Literal

# third party library imports
from pydantic import Field, ValidationError

# project library imports
from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.engineering_standards.python_source import (
    PythonFinding,
    PythonSourceChecker,
)

EXCEPTIONS_PATH = "docs/architecture/python-standards-exceptions.toml"
type FindingKey = tuple[str, str, str, str]


class PythonException(ImmutableModel):
    """Bind a reviewed design exception to one obligation and exact definition body."""

    path: str
    symbol: str
    rule: Literal["PYC001", "PYD001", "PYD002"]
    detail: str = Field(min_length=1)
    kind: Literal["low_level", "framework", "compatibility", "inherited_contract"]
    owner_role: str
    rationale: str = Field(min_length=12)
    expires: date
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @property
    def key(self) -> FindingKey:
        """Identify the one diagnostic the exception may discharge.

        Returns:
            File, qualified symbol, rule and semantic detail.
        """
        return self.path, self.symbol, self.rule, self.detail

    def validate_context(
        self, *, owner_roles: frozenset[str], validation_date: date, fingerprint: str | None
    ) -> None:
        """Reject unowned, expired, unsupported or changed exceptions.

        Args:
            owner_roles: Roles admitted by the ownership policy.
            validation_date: Explicit date used for deterministic lifetime checks.
            fingerprint: Observed definition digest, or absence for an unknown symbol.

        Raises:
            ValueError: Any metadata, lifetime or source identity requirement fails.
        """
        if self.owner_role not in owner_roles or not SourceIdentity.valid_path(self.path):
            raise ValueError("Python exception has an unknown owner or invalid source path")
        if not self.rationale.strip() or len(self.rationale.strip()) < 12:
            raise ValueError(
                "Python exception requires a concrete rationale of at least 12 characters"
            )
        if not validation_date <= self.expires <= validation_date + timedelta(days=180):
            raise ValueError("Python exception expired or exceeds the 180-day maximum lifetime")
        if self.rule == "PYC001" and self.kind == "inherited_contract":
            raise ValueError("Python exception category cannot waive this rule")
        if self.rule != "PYC001" and self.kind != "inherited_contract":
            raise ValueError("Python exception category cannot waive this rule")
        if fingerprint != self.source_sha256:
            raise ValueError("Python exception source fingerprint changed or symbol is missing")


class PythonExceptions(ImmutableModel):
    """Decode explicit TOML exceptions without allowing arbitrary suppression rules."""

    schema_version: Literal[1]
    exceptions: list[PythonException]


class SourceIdentity(ast.NodeVisitor):
    """Compute definition identities without absolute paths or source line numbers."""

    def __init__(self) -> None:
        """Initialize a single-source identity collector."""
        self.symbols: dict[str, str] = {}
        self._scope: list[str] = []

    @staticmethod
    def valid_path(path: str) -> bool:
        """Require a canonical repository-relative Python source path.

        Args:
            path: Untrusted source or exception path.

        Returns:
            Whether the path is canonical, relative and identifies Python source.
        """
        parsed = PurePosixPath(path)
        return (
            bool(path)
            and not parsed.is_absolute()
            and parsed.as_posix() == path
            and ".." not in parsed.parts
            and "\\" not in path
            and parsed.suffix in {".py", ".pyi"}
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Collect a class and its nested definitions.

        Args:
            node: Parsed class definition.
        """
        self._definition(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Collect a synchronous function and its nested definitions.

        Args:
            node: Parsed function definition.
        """
        self._definition(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Collect an asynchronous function and its nested definitions.

        Args:
            node: Parsed asynchronous function definition.
        """
        self._definition(node)

    def _definition(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Hash semantic AST content and reject ambiguous repeated qualified names."""
        self._scope.append(node.name)
        symbol = ".".join(self._scope)
        fingerprint = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        self.symbols[symbol] = "ambiguous" if symbol in self.symbols else fingerprint
        self.generic_visit(node)
        self._scope.pop()


class PythonStandardsChecker:
    """Compare current source findings to scoped, reviewed design exceptions."""

    def __init__(
        self, *, source_roots: tuple[str, ...], owner_roles: frozenset[str], validation_date: date
    ) -> None:
        """Capture governed source scope and deterministic review context.

        Args:
            source_roots: Repository-relative roots scanned recursively for Python.
            owner_roles: Roles admitted by the ownership policy.
            validation_date: Explicit date used to check exception lifetime.
        """
        self._source_roots = source_roots
        self._owner_roles = owner_roles
        self._validation_date = validation_date

    def findings(self, repository_root: Path) -> tuple[str, ...]:
        """Run the source contract without Git, network access or file mutation.

        Args:
            repository_root: Repository or Bazel fixture containing source and policy.

        Returns:
            Deterministic diagnostics; an empty tuple means the contract passed.
        """
        try:
            parsed_exceptions: object = tomllib.loads(
                (repository_root / EXCEPTIONS_PATH).read_text(encoding="utf-8")
            )
            exceptions = PythonExceptions.model_validate(parsed_exceptions)
            observed, fingerprints = self._scan(repository_root)
            return self.reconcile(exceptions, observed, fingerprints)
        except ValidationError as error:
            details: object = error.errors(include_input=False)
            return (f"Python standards policy: {details}",)
        except (OSError, ValueError) as error:
            message = str(error)
            return (f"Python standards policy: {message}",)

    def reconcile(
        self,
        exceptions: PythonExceptions,
        observed: tuple[PythonFinding, ...],
        fingerprints: dict[tuple[str, str], str],
    ) -> tuple[str, ...]:
        """Return unwaived source findings and invalid exception diagnostics.

        Args:
            exceptions: Explicit design exceptions from the current policy.
            observed: Complete source-scanner diagnostics for the admitted roots.
            fingerprints: AST digests indexed by file and qualified definition.

        Returns:
            Stable diagnostics naming source findings or bad exceptions.
        """
        findings: list[str] = []
        actual = Counter(item.key for item in observed)
        exception_keys: set[FindingKey] = set()
        for exception in exceptions.exceptions:
            key = exception.key
            try:
                exception.validate_context(
                    owner_roles=self._owner_roles,
                    validation_date=self._validation_date,
                    fingerprint=fingerprints.get((exception.path, exception.symbol)),
                )
            except ValueError as error:
                findings.append(f"Python exception {exception.path}:{exception.symbol}: {error}")
                continue
            reason = None
            if key in exception_keys:
                reason = "duplicate exception"
            elif actual[key] != 1:
                reason = "stale or ambiguous exception; exactly one source finding is required"
            if reason is not None:
                findings.append(f"Python exception {exception.path}:{exception.symbol}: {reason}")
                continue
            exception_keys.add(key)
        for key, count in sorted((actual - Counter(exception_keys)).items()):
            path, symbol, rule, detail = key
            findings.append(f"{path}:{symbol}: {rule} {detail} (occurrences: {count})")
        return tuple(findings)

    def _scan(
        self, repository_root: Path
    ) -> tuple[tuple[PythonFinding, ...], dict[tuple[str, str], str]]:
        """Scan every source file, including new files not yet added to Git."""
        observed: list[PythonFinding] = []
        fingerprints: dict[tuple[str, str], str] = {}
        scanner = PythonSourceChecker()
        for source_root in self._source_roots:
            root = repository_root / source_root
            if not root.is_dir():
                raise ValueError(f"missing Python standards source root: {source_root}")
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.suffix not in {".py", ".pyi"}:
                    continue
                relative = path.relative_to(repository_root).as_posix()
                source = path.read_text(encoding="utf-8")
                observed.extend(scanner.scan(relative, source))
                try:
                    tree = ast.parse(source)
                except SyntaxError:
                    continue
                identities = SourceIdentity()
                identities.visit(tree)
                fingerprints.update(
                    ((relative, symbol), digest) for symbol, digest in identities.symbols.items()
                )
        return tuple(observed), fingerprints
