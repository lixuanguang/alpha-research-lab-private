"""Read, validate and compare the shrink-only record of existing ownership debt."""

from __future__ import annotations

# standard library imports
import json
import subprocess  # nosec B404  # [owner=platform; rationale=Git ledger history boundary; expires=2027-03-01]
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

# third party library imports
from pydantic import Field, TypeAdapter

# project library imports
from alpha_research_governance._models import ImmutableModel


class LedgerEntry(ImmutableModel):
    """Record how many findings of one rule one symbol may still carry."""

    path: str = Field(min_length=1)
    rule: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    count: int = Field(ge=1)


class OwnershipLedger:
    """Hold recorded ownership debt keyed by path, rule and qualified symbol."""

    RULES: ClassVar[frozenset[str]] = frozenset(
        {
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
    )
    _DOCUMENT: ClassVar[TypeAdapter[dict[str, list[LedgerEntry]]]] = TypeAdapter(
        dict[str, list[LedgerEntry]]
    )
    _HEADER: ClassVar[str] = (
        "# Recorded ownership debt from the MR16 migration; see docs/roadmap/python-ownership.md.\n"
        "# Entries may only be removed or lowered. The file is removed when the migration ends.\n"
    )

    def __init__(self, counts: Mapping[tuple[str, str, str], int]) -> None:
        """Bind validated counts by ledger key.

        Args:
            counts: Positive occurrence counts keyed by path, rule and symbol.

        Raises:
            ValueError: If a rule is unknown or a count is not positive.
        """
        for (_, rule, _), count in counts.items():
            if rule not in self.RULES:
                raise ValueError(f"unknown ownership rule {rule}")
            if count < 1:
                raise ValueError("ownership ledger counts must be positive")
        self._counts = dict(sorted(counts.items()))

    @property
    def counts(self) -> Mapping[tuple[str, str, str], int]:
        """Return recorded counts in key order."""
        return self._counts

    @classmethod
    def parse(cls, text: str, *, source: str) -> OwnershipLedger:
        """Parse and validate one ledger document.

        Args:
            text: TOML document with one sorted ``debt`` array of entries.
            source: Name of the document used in error messages.

        Returns:
            The validated ledger.

        Raises:
            ValueError: If the document is malformed, unsorted, duplicated or names an
                unknown rule.
        """
        try:
            document: object = tomllib.loads(text)
            tables = cls._DOCUMENT.validate_python(document)
        except ValueError as error:
            raise ValueError(f"{source} is malformed: {error}") from error
        if set(tables) != {"debt"}:
            raise ValueError(f"{source} must contain exactly one debt array")
        keys = [(entry.path, entry.rule, entry.symbol) for entry in tables["debt"]]
        if keys != sorted(set(keys)):
            raise ValueError(f"{source} entries must be unique and sorted by path, rule, symbol")
        try:
            return cls({key: entry.count for key, entry in zip(keys, tables["debt"], strict=True)})
        except ValueError as error:
            raise ValueError(f"{source}: {error}") from error

    @classmethod
    def read(cls, path: Path) -> OwnershipLedger | None:
        """Read the working ledger, or return ``None`` when no ledger exists.

        Args:
            path: Ledger file in the working tree.

        Returns:
            The validated ledger, or ``None`` when the file is absent.
        """
        if not path.exists():
            return None
        return cls.parse(path.read_text(encoding="utf-8"), source=path.name)

    def render(self) -> str:
        """Render the canonical sorted ledger document.

        Returns:
            TOML text that ``parse`` reads back to the same counts.
        """
        lines = [
            f"    {{ path = {json.dumps(path)}, rule = {json.dumps(rule)}, "
            f"symbol = {json.dumps(symbol)}, count = {count} }},"
            for (path, rule, symbol), count in self._counts.items()
        ]
        body = "\n".join(lines)
        return self._HEADER + (f"debt = [\n{body}\n]\n" if lines else "debt = []\n")

    def growth_since(self, earlier: OwnershipLedger, label: str) -> tuple[str, ...]:
        """Report entries added or raised relative to an earlier ledger version.

        Args:
            earlier: The preceding ledger version.
            label: Description of this version used in diagnostics.

        Returns:
            One diagnostic per grown entry.
        """
        findings: list[str] = []
        for (path, rule, symbol), count in self._counts.items():
            prior = earlier.counts.get((path, rule, symbol), 0)
            if count > prior:
                findings.append(
                    f"ownership ledger: {path} {rule} {symbol} grew from {prior} to {count} "
                    f"in {label}; recorded debt can only shrink"
                )
        return tuple(findings)


class LedgerHistory:
    """Verify that the ledger never grew after it was first committed on this line of work."""

    _BASES: ClassVar[tuple[str, ...]] = ("main", "origin/main")

    def __init__(self, repository_root: Path, relative_path: str) -> None:
        """Bind the checkout and the ledger's repository-relative path.

        Args:
            repository_root: Git checkout containing the ledger.
            relative_path: Ledger path relative to ``repository_root``.
        """
        self._repository_root = repository_root
        self._relative_path = relative_path

    def growth(self, current: OwnershipLedger) -> tuple[str, ...]:
        """Compare the working ledger and each committed version since the merge-base.

        The first existing version seeds the ledger and is unconstrained. Every later
        version, including the working tree, may only remove or lower entries; a
        deleted ledger counts as empty.

        Args:
            current: The validated working-tree ledger.

        Returns:
            Growth diagnostics, or one fail-closed diagnostic when history is unavailable.
        """
        try:
            versions = self._versions()
        except (OSError, UnicodeError, ValueError) as error:
            return (f"ownership ledger: cannot verify that recorded debt only shrinks: {error}",)
        findings: list[str] = []
        previous: OwnershipLedger | None = None
        for label, ledger in (*versions, ("the working tree", current)):
            if ledger is None:
                if previous is not None:
                    previous = OwnershipLedger({})
                continue
            if previous is not None:
                findings.extend(ledger.growth_since(previous, label))
            previous = ledger
        return tuple(findings)

    def _versions(self) -> list[tuple[str, OwnershipLedger | None]]:
        """Read the ledger at the merge-base and at each later commit that changed it."""
        base = next(
            (
                reference
                for reference in self._BASES
                if self._run("rev-parse", "--verify", "--quiet", f"{reference}^{{commit}}")[0] == 0
            ),
            None,
        )
        if base is None:
            raise ValueError("neither main nor origin/main resolves to a commit")
        merge_base = self._git("merge-base", "HEAD", base).strip()
        later = self._git(
            "rev-list", "--reverse", f"{merge_base}..HEAD", "--", self._relative_path
        ).split()
        versions: list[tuple[str, OwnershipLedger | None]] = []
        for commit in (merge_base, *later):
            revision = f"{commit}:./{self._relative_path}"
            if self._run("cat-file", "-e", revision)[0] != 0:
                versions.append((f"commit {commit[:12]}", None))
                continue
            versions.append(
                (
                    f"commit {commit[:12]}",
                    OwnershipLedger.parse(
                        self._git("show", revision), source=f"{self._relative_path}@{commit[:12]}"
                    ),
                )
            )
        return versions

    def _git(self, *arguments: str) -> str:
        """Run one Git query and return its standard output or raise ``ValueError``."""
        status, output, error = self._run(*arguments)
        if status != 0:
            raise ValueError(f"git {arguments[0]} failed: {error.strip()}")
        return output

    def _run(self, *arguments: str) -> tuple[int, str, str]:
        """Run shell-free Git argv in the checkout and return status, stdout and stderr."""
        completed = subprocess.run(  # nosec B603, B607  # [owner=platform; rationale=constant Git query argv; expires=2027-03-01]
            ["git", *arguments],
            cwd=self._repository_root,
            check=False,
            capture_output=True,
        )
        return (
            completed.returncode,
            completed.stdout.decode("utf-8"),
            completed.stderr.decode("utf-8", "replace"),
        )
