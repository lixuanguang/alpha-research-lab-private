"""Run the repository's compact Python clarity checks."""

from __future__ import annotations

# standard library imports
import re
import tokenize
import tomllib
from datetime import date, timedelta
from functools import partial
from io import StringIO
from pathlib import Path

# third party library imports
from pydantic import TypeAdapter, ValidationError

# project library imports
from alpha_research_governance.engineering_standards.format_compatibility import (
    FormatCompatibilityChecker,
)
from alpha_research_governance.engineering_standards.ownership import OwnershipChecker
from alpha_research_governance.engineering_standards.python_standards import (
    DEFAULT_SOURCE_ROOTS,
    PythonStandardsChecker,
)
from alpha_research_governance.engineering_standards.source_layout import SourceLayoutChecker


class EngineeringStandardsError(ValueError):
    """Report one or more direct engineering-standards findings."""


_SUPPRESSION = re.compile(
    r"#\s*(?:noqa(?::\s*[A-Z0-9, ]+)?|nosec(?:\s+[A-Z0-9, ]+)?|"
    r"type:\s*ignore(?:\[[^]]+\])?|pragma:\s*no cover|fmt:\s*(?:skip|off)|"
    r"ruff:\s*noqa)\b"
)
_SUPPRESSION_METADATA = re.compile(
    r"\[owner=(?P<owner>[a-z][a-z0-9_]*); rationale=(?P<rationale>[^;\[\]]+); "
    r"expires=(?P<expires>\d{4}-\d{2}-\d{2})\]\s*$"
)
_TABLE = TypeAdapter(dict[str, object])


def _table(value: object, context: str) -> dict[str, object]:
    """Return one TOML table or raise a controlled configuration error."""
    try:
        return _TABLE.validate_python(value)
    except (TypeError, ValueError, ValidationError) as error:
        raise ValueError(f"{context} must be a TOML table") from error


def tooling_configuration_findings(repository_root: Path) -> tuple[str, ...]:
    """Check the strict mypy, Ruff, and pytest clarity configuration.

    Args:
        repository_root: Repository containing ``pyproject.toml``.

    Returns:
        Stable findings for missing or weakened global quality settings.
    """
    path = repository_root / "pyproject.toml"
    try:
        document: object = tomllib.loads(path.read_text(encoding="utf-8"))
        root = _table(document, "pyproject.toml")
        tool = _table(root.get("tool"), "pyproject.toml.tool")
        mypy = _table(tool.get("mypy"), "pyproject.toml.tool.mypy")
        pydantic_mypy = _table(tool.get("pydantic-mypy"), "pyproject.toml.tool.pydantic-mypy")
        ruff = _table(tool.get("ruff"), "pyproject.toml.tool.ruff")
        ruff_lint = _table(ruff.get("lint"), "pyproject.toml.tool.ruff.lint")
        pydocstyle = _table(ruff_lint.get("pydocstyle"), "pyproject.toml.tool.ruff.lint.pydocstyle")
        pytest = _table(tool.get("pytest"), "pyproject.toml.tool.pytest")
        pytest_options = _table(pytest.get("ini_options"), "pyproject.toml.tool.pytest.ini_options")
    except (OSError, ValueError) as error:
        return (f"Python tooling configuration: {error}",)

    findings: list[str] = []
    for key in (
        "strict",
        "disallow_any_explicit",
        "disallow_any_unimported",
        "disallow_any_decorated",
        "disallow_any_expr",
    ):
        if mypy.get(key) is not True:
            findings.append(f"mypy must retain {key}=true")
    if mypy.get("plugins") != ["pydantic.mypy"]:
        findings.append("mypy must retain the Pydantic plugin")
    for key in ("init_typed", "init_forbid_extra", "warn_required_dynamic_aliases"):
        if pydantic_mypy.get(key) is not True:
            findings.append(f"Pydantic mypy must retain {key}=true")
    if mypy.get("mypy_path") != ["src", "tools/governance/src", "tools/typing/stubs"]:
        findings.append("mypy must retain the source and native-stub scope")
    for key in (
        "exclude",
        "exclude_gitignore",
        "follow_imports",
        "disable_error_code",
        "ignore_errors",
        "per_module_options",
        "overrides",
    ):
        if key in mypy:
            findings.append(f"mypy must not bypass checks with {key}")

    selected = ruff_lint.get("select")
    if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
        findings.append("Ruff selected rules must be a list of strings")
        selected_rules: tuple[str, ...] = ()
    else:
        selected_rules = tuple(selected)
    for rule, description in (
        ("I", "import sorting"),
        ("D", "Google documentation"),
        ("ANN401", "dynamic typing checks"),
    ):
        if rule not in selected_rules:
            findings.append(f"Ruff must retain {description}")
    if pydocstyle.get("convention") != "google":
        findings.append("Ruff documentation must use the Google convention")
    for configuration_name, configuration in (("ruff", ruff), ("ruff.lint", ruff_lint)):
        for key in ("exclude", "extend-exclude", "extend-ignore", "ignore", "per-file-ignores"):
            if key in configuration:
                findings.append(f"Ruff must not bypass checks with {configuration_name} {key}")
    if pytest_options.get("filterwarnings") != ["error"]:
        findings.append("pytest warnings must remain errors")
    return tuple(findings)


def validate_suppression_line(
    line: str,
    *,
    validation_date: date,
    maximum_lifetime_days: int = 180,
    minimum_rationale_characters: int = 12,
) -> tuple[str, ...]:
    """Validate metadata attached to one source suppression.

    The owner is a local annotation rather than a role looked up in a registry.
    This keeps suppression accountability visible in the source while allowing
    the repository to operate without an institutional ownership model.

    Args:
        line: Source comment to inspect.
        validation_date: Date against which the expiry is checked.
        maximum_lifetime_days: Inclusive maximum lifetime for a suppression.
        minimum_rationale_characters: Minimum trimmed rationale length.

    Returns:
        Ordered findings, or an empty tuple when the line is not a suppression.
    """
    if _SUPPRESSION.search(line) is None:
        return ()
    metadata = _SUPPRESSION_METADATA.search(line)
    if metadata is None:
        return ("suppression requires [owner=...; rationale=...; expires=YYYY-MM-DD]",)
    findings: list[str] = []
    groups: dict[str, str | None] = metadata.groupdict()
    owner = groups.get("owner") or ""
    rationale = groups.get("rationale") or ""
    expiry_text = groups.get("expires") or ""
    if not owner:
        findings.append("suppression owner must be a non-empty lowercase identifier")
    if len(rationale.strip()) < minimum_rationale_characters:
        findings.append("suppression rationale is too short")
    try:
        expiry = date.fromisoformat(expiry_text)
    except ValueError:
        findings.append("suppression expiry must be a valid calendar date")
    else:
        if expiry < validation_date:
            findings.append("suppression is expired")
        if expiry > validation_date + timedelta(days=maximum_lifetime_days):
            findings.append("suppression exceeds the maximum lifetime")
    return tuple(findings)


def _suppression_for_source(relative: str, text: str, *, validation_date: date) -> tuple[str, ...]:
    """Collect suppression metadata findings from one already-read source file."""
    try:
        comments = tuple(
            token
            for token in tokenize.generate_tokens(StringIO(text).readline)
            if token.type == tokenize.COMMENT
        )
    except (IndentationError, tokenize.TokenError) as error:
        return (f"{relative}: cannot inspect suppression comments: {error}",)
    return tuple(
        f"{relative}:{comment.start[0]}: {issue}"
        for comment in comments
        for issue in validate_suppression_line(comment.string, validation_date=validation_date)
    )


def source_tree_findings(
    repository_root: Path,
    *,
    source_roots: tuple[str, ...] = DEFAULT_SOURCE_ROOTS,
    validation_date: date | None = None,
) -> tuple[str, ...]:
    """Return direct clarity findings for every owned Python source file.

    Args:
        repository_root: Repository containing the source roots to scan.
        source_roots: Repository-relative roots containing owned ``.py`` and
            ``.pyi`` files.
        validation_date: Date used to evaluate suppression expiry metadata.

    Returns:
        Stable source diagnostics. A missing root or unreadable source is a
        finding so the command fails closed.
    """
    observer = partial(
        _suppression_for_source,
        validation_date=date.today() if validation_date is None else validation_date,
    )
    return PythonStandardsChecker(source_roots=source_roots).findings(
        repository_root, source_observer=observer
    )


def validate_repository(
    repository_root: Path,
    *,
    source_roots: tuple[str, ...] = DEFAULT_SOURCE_ROOTS,
    validation_date: date | None = None,
) -> tuple[str, ...]:
    """Validate the retained Python clarity contract for a repository.

    Args:
        repository_root: Repository containing the source roots to scan.
        source_roots: Repository-relative roots containing owned Python source.
        validation_date: Date used to evaluate suppression expiry metadata.

    Returns:
        An empty tuple when all source files pass.

    Raises:
        EngineeringStandardsError: If any source finding is present.
    """
    findings = (
        *tooling_configuration_findings(repository_root),
        *SourceLayoutChecker.findings(repository_root),
        *FormatCompatibilityChecker.findings(repository_root),
        *OwnershipChecker.findings(repository_root),
        *source_tree_findings(
            repository_root,
            source_roots=source_roots,
            validation_date=validation_date,
        ),
    )
    if findings:
        raise EngineeringStandardsError("\n".join(findings))
    return findings
