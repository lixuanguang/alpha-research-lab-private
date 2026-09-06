"""Validate architecture decisions and repository-local documentation links."""

from __future__ import annotations

# standard library imports
import re
import sys
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

# third party library imports
from pydantic import ValidationError

# project library imports
from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.operating_model import (
    OperatingModel,
    OperatingModelError,
    load_operating_model,
)

_DECISION_FILENAME = re.compile(r"^(?P<identifier>[0-9]{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
_MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\((?P<destination>[^)]+)\)")
_METADATA_ROW = re.compile(r"^\|\s*(?P<key>[^|]+?)\s*\|\s*(?P<value>[^|]+?)\s*\|\s*$")
_DECISION_LOG_ROW = re.compile(
    r"^\|\s*(?P<identifier>[0-9]{4})\s*"
    r"\|\s*\[(?P<title>[^\]]+)\]\((?P<filename>[^)]+)\)\s*"
    r"\|\s*(?P<status>[^|]+?)\s*"
    r"\|\s*(?P<owner>[^|]+?)\s*"
    r"\|\s*(?P<review_date>[^|]+?)\s*\|$"
)
_COMMIT_BOUND_APPROVAL = re.compile(
    r"^commit=(?P<commit>[0-9a-f]{40}|[0-9a-f]{64});\s*approval=(?P<url>\S+)$"
)
_REQUIRED_METADATA = (
    "Roadmap package",
    "Status",
    "Decision owner",
    "Decision date",
    "Review date",
    "Supersedes",
    "Approval evidence",
)
_REQUIRED_SECTIONS = (
    "Context",
    "Decision drivers",
    "Considered alternatives",
    "Decision",
    "Consequences",
    "Migration and rollout",
    "Reversal plan",
    "Review and evidence",
)
_ALLOWED_STATUSES = {
    "Proposed",
    "Founder accepted",
    "Accepted",
    "Rejected",
    "Deprecated",
    "Superseded",
}


class _DecisionLogEntry(ImmutableModel):
    """Store the strict-shaped fields extracted from one decision-log row.

    The inherited immutable model rejects field coercion and unknown fields,
    but this record does not validate ADR identity, status, ownership, dates or
    cross-file consistency. Those semantic checks are performed by the
    directory validator.

    Attributes:
        identifier: Four-digit decision identifier captured from the row.
        title: Markdown link title after surrounding whitespace is stripped.
        filename: Markdown link destination after surrounding whitespace is stripped.
        status: Status text recorded in the row.
        owner: Decision-owner text recorded in the row.
        review_date: Review-date text recorded in the row.
    """

    identifier: str
    title: str
    filename: str
    status: str
    owner: str
    review_date: str


class ArchitectureGovernanceError(ValueError):
    """Report deterministic architecture-governance findings in input order.

    Attributes:
        findings: Immutable tuple preserving the supplied order and duplicate
            messages. The exception message joins these values with newlines.
    """

    def __init__(self, findings: Sequence[str]) -> None:
        """Capture findings without deduplication or reordering.

        Args:
            findings: Ordered diagnostic messages; an empty sequence is allowed.
        """
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


def _parse_metadata(text: str) -> dict[str, str]:
    """Extract matching rows after the first textual metadata marker.

    Args:
        text: Markdown-like source containing an optional textual ``## Control
            metadata`` marker. The marker search is unanchored and does not
            understand Markdown code fences.

    Returns:
        A dictionary of regex-matching ``| key | value |`` rows. Rows whose
        parsed key is exactly ``Field`` or ``---``, malformed lines and later
        level-two sections are ignored; a repeated key overwrites its earlier
        value. Missing markers return an empty dictionary.
    """
    control_start = text.find("## Control metadata")
    if control_start < 0:
        return {}
    next_section = text.find("\n## ", control_start + 1)
    block = text[control_start:] if next_section < 0 else text[control_start:next_section]
    values: dict[str, str] = {}
    for line in block.splitlines():
        match = _METADATA_ROW.fullmatch(line)
        if match is not None and match.group("key") not in {"Field", "---"}:
            values[match.group("key")] = match.group("value")
    return values


def _section_body(text: str, heading: str) -> str | None:
    """Return the stripped body of the first matching level-two heading.

    Args:
        text: Markdown-like source to search. The regex does not distinguish
            ordinary text from fenced code.
        heading: Heading text matched literally after ``## ``.

    Returns:
        The text up to but excluding the next level-two heading, or to the end
        of input, stripped of surrounding whitespace. Level-three and deeper
        content remains in the body. ``None`` means no case-sensitive matching
        heading followed by a newline; an empty string represents a present but
        blank section.
    """
    match = re.search(
        rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## |\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return None if match is None else match.group("body").strip()


def _parse_date(value: str, *, field: str, path: Path, findings: list[str]) -> date | None:
    """Parse a canonical ISO date and append one finding on failure.

    Args:
        value: Date text accepted by ``date.fromisoformat`` only when its
            canonical ``YYYY-MM-DD`` spelling is identical after parsing.
        field: Metadata field name included in a failure finding.
        path: ADR path included in a failure finding.
        findings: Mutable diagnostic list receiving at most one message when
            parsing or canonicality validation fails.

    Returns:
        The parsed ``date`` for an exact canonical value, otherwise ``None``.
    """
    try:
        parsed_date = date.fromisoformat(value)
    except ValueError:
        findings.append(f"{path}: {field} must use YYYY-MM-DD")
        return None
    if parsed_date.isoformat() != value:
        findings.append(f"{path}: {field} must use YYYY-MM-DD")
        return None
    return parsed_date


def _has_commit_bound_approval(value: str) -> bool:
    """Check the syntactic shape of a commit-bound HTTPS approval value.

    Args:
        value: Expected ``commit=<40-or-64-lowercase-hex>; approval=<URL>``
            text.

    Returns:
        ``True`` only when the anchored format matches and the URL has an
        HTTPS scheme, a hostname and no parsed credentials. This check does not
        contact or authenticate the external evidence URL; query and fragment
        components are otherwise unconstrained.
    """
    match = _COMMIT_BOUND_APPROVAL.fullmatch(value)
    if match is None:
        return False
    try:
        approval = urlsplit(match.group("url"))
    except ValueError:
        return False
    has_credentials = approval.username is not None or approval.password is not None
    return approval.scheme == "https" and bool(approval.hostname) and not has_credentials


def validate_adr(
    path: Path,
    *,
    expected_identifier: int,
    template: bool = False,
    operating_model: OperatingModel | None = None,
) -> None:
    """Validate one ADR's identity, metadata, sections, and lifecycle fields.

    The file is read as UTF-8 and all findings discovered during validation are
    accumulated before one governance error is raised. A non-template ADR must
    use the expected four-digit identifier in its filename and title, and its
    filename must use a lowercase kebab-case slug. Every ADR requires the
    control-metadata fields and ordered level-two sections defined by this
    module; when all required metadata is present, non-template ADRs also
    receive the roadmap, status, ownership, date, and approval checks. The
    ``Accepted`` status requires syntactically valid commit-bound HTTPS evidence.
    The ``Founder accepted`` status requires an operating model that resolves its
    operating domain for ``operation="implementation"`` on the decision date and
    identifies the registered founder.
    ``template=True`` skips the filename, title, lifecycle, and non-empty-section
    checks while retaining required metadata, section-presence, and section-order
    checks.
    This function only reads ``path`` and the optional operating model.

    Args:
        path: ADR or template file to read and validate as UTF-8.
        expected_identifier: Numeric identifier formatted with a minimum width of
            four digits for the expected filename and ADR title when validating a
            non-template file.
        template: Whether to apply template mode, which omits identity,
            lifecycle, and non-empty-section checks.
        operating_model: Optional operating model used only for Founder accepted
            ADRs to validate the operating-domain scope and founder identity.

    Raises:
        ArchitectureGovernanceError: If one or more identity, metadata, section,
            lifecycle, or approval findings are collected.
        OSError: If ``path`` cannot be read.
        UnicodeDecodeError: If ``path`` is not valid UTF-8.
    """
    text = path.read_text(encoding="utf-8")
    findings: list[str] = []
    identifier = f"{expected_identifier:04d}"

    if not template:
        filename_match = _DECISION_FILENAME.fullmatch(path.name)
        if filename_match is None or filename_match.group("identifier") != identifier:
            findings.append(
                f"{path}: filename must start with {identifier}- and use a kebab-case slug"
            )
        if re.search(rf"^# ADR {identifier}: .+$", text, flags=re.MULTILINE) is None:
            findings.append(f"{path}: title must be '# ADR {identifier}: <decision>'")

    metadata = _parse_metadata(text)
    for key in _REQUIRED_METADATA:
        if not metadata.get(key):
            findings.append(f"{path}: missing control metadata field '{key}'")

    if not template and all(metadata.get(key) for key in _REQUIRED_METADATA):
        if metadata["Roadmap package"] != "A02":
            findings.append(f"{path}: Roadmap package must be A02")
        status = metadata["Status"]
        if status not in _ALLOWED_STATUSES:
            findings.append(f"{path}: unsupported ADR status '{status}'")
        if metadata["Decision owner"].casefold() in {"pending", "unassigned", "none"}:
            findings.append(f"{path}: Decision owner must name an accountable role")
        decision_date = _parse_date(
            metadata["Decision date"], field="Decision date", path=path, findings=findings
        )
        review_date = _parse_date(
            metadata["Review date"], field="Review date", path=path, findings=findings
        )
        if decision_date is not None and review_date is not None and review_date <= decision_date:
            findings.append(f"{path}: Review date must be after Decision date")
        if status == "Accepted" and not _has_commit_bound_approval(metadata["Approval evidence"]):
            findings.append(
                f"{path}: Accepted ADRs require 'commit=<40-or-64-hex>; "
                "approval=<HTTPS evidence URL>'"
            )
        if status == "Founder accepted":
            scope = metadata.get("Operating domain", "")
            if operating_model is None or decision_date is None:
                findings.append(f"{path}: founder acceptance requires the operating model and date")
            else:
                try:
                    operating_model.resolve(
                        domain_id=scope, operation="implementation", on_date=decision_date
                    )
                except OperatingModelError as error:
                    findings.append(f"{path}: {error}")
                if metadata["Approval evidence"] != f"founder={operating_model.founder_principal}":
                    findings.append(
                        f"{path}: founder acceptance must identify the registered founder"
                    )

    previous_position = -1
    for section in _REQUIRED_SECTIONS:
        body = _section_body(text, section)
        heading_match = re.search(rf"^## {re.escape(section)}\s*$", text, flags=re.MULTILINE)
        position = -1 if heading_match is None else heading_match.start()
        if body is None:
            findings.append(f"{path}: missing required section '## {section}'")
        elif not template and not body:
            findings.append(f"{path}: section '## {section}' must not be empty")
        if position >= 0 and position <= previous_position:
            findings.append(f"{path}: section '## {section}' is out of order")
        previous_position = max(previous_position, position)

    if findings:
        raise ArchitectureGovernanceError(findings)


def _decision_log_entries(
    log_path: Path, log: str, findings: list[str]
) -> tuple[_DecisionLogEntry, ...]:
    """Parse candidate decision rows from the decision-records section.

    Args:
        log_path: Decision-log path used in missing or malformed-row findings.
        log: Markdown decision log text.
        findings: Mutable diagnostic list. Missing sections and malformed lines
            that begin with a four-digit row marker are appended in encounter
            order; unrelated lines are ignored.

    Returns:
        Valid regex-matching rows as strict-shaped entries in source order.
        Duplicate identifiers are retained here and are reported later by
        ``_validate_decision_log``.
    """
    block = _section_body(log, "Decision records")
    if block is None:
        findings.append(f"{log_path}: missing required section '## Decision records'")
        return ()

    entries: list[_DecisionLogEntry] = []
    for line in block.splitlines():
        if re.match(r"^\|\s*[0-9]{4}\s*\|", line) is None:
            continue
        match = _DECISION_LOG_ROW.fullmatch(line)
        if match is None:
            findings.append(f"{log_path}: malformed decision record row: {line}")
            continue
        entries.append(
            _DecisionLogEntry(
                identifier=match.group("identifier"),
                title=match.group("title").strip(),
                filename=match.group("filename").strip(),
                status=match.group("status").strip(),
                owner=match.group("owner").strip(),
                review_date=match.group("review_date").strip(),
            )
        )
    return tuple(entries)


def _validate_decision_log(
    log_path: Path, log: str, decisions: Sequence[Path], findings: list[str]
) -> None:
    """Validate decision-log rows against the indexed ADR files.

    Parse rows from the supplied log text. The parser appends malformed-row
    findings in log order. Validation then appends duplicate findings in one pass
    and unexpected-row findings in a separate pass, each in log order. It finally
    processes decisions in supplied order, appending missing-row findings and
    cross-file metadata mismatches as encountered. For each expected identifier
    with a first matching row, read its ADR as UTF-8 and compare title, filename,
    status, owner, and review date; duplicate rows are reported but later
    duplicates do not replace the first row used for comparison. This function
    mutates only ``findings`` and does not raise its collected governance error.

    Args:
        log_path: Decision-log path included in diagnostic messages.
        log: Markdown decision-log text to parse in memory.
        decisions: ADR paths whose identifiers and metadata must be represented.
        findings: Mutable diagnostic list receiving validation findings.

    Raises:
        OSError: If an ADR file cannot be read.
        UnicodeDecodeError: If an ADR file is not valid UTF-8.
    """
    entries = _decision_log_entries(log_path, log, findings)
    entries_by_identifier: dict[str, _DecisionLogEntry] = {}
    for entry in entries:
        if entry.identifier in entries_by_identifier:
            findings.append(f"{log_path}: duplicate decision record {entry.identifier}")
        else:
            entries_by_identifier[entry.identifier] = entry

    expected_identifiers = {path.name[:4] for path in decisions}
    for entry in entries:
        if entry.identifier not in expected_identifiers:
            findings.append(f"{log_path}: unexpected decision record {entry.identifier}")

    for path in decisions:
        identifier = path.name[:4]
        indexed_entry = entries_by_identifier.get(identifier)
        if indexed_entry is None:
            findings.append(f"{log_path}: missing decision record {identifier}")
            continue

        text = path.read_text(encoding="utf-8")
        title_match = re.search(
            rf"^# ADR {identifier}: (?P<title>.+?)\s*$", text, flags=re.MULTILINE
        )
        expected_title = "" if title_match is None else title_match.group("title")
        metadata = _parse_metadata(text)
        expected_values = {
            "title": expected_title,
            "filename": path.name,
            "status": metadata.get("Status", ""),
            "owner": metadata.get("Decision owner", ""),
            "review date": metadata.get("Review date", ""),
        }
        actual_values = {
            "title": indexed_entry.title,
            "filename": indexed_entry.filename,
            "status": indexed_entry.status,
            "owner": indexed_entry.owner,
            "review date": indexed_entry.review_date,
        }
        for field, expected in expected_values.items():
            if actual_values[field] != expected:
                findings.append(
                    f"{log_path}: decision {identifier} {field} does not match {path.name}"
                )


def validate_decision_directory(
    directory: Path, *, operating_model: OperatingModel | None = None
) -> tuple[Path, ...]:
    """Validate a decision directory and return its ADR paths when it is valid.

    The directory must contain a valid ``template.md`` and ``README.md`` decision
    log. The scan considers only immediate ``*.md`` entries. Markdown files other
    than those two must use the four-digit, lowercase-kebab-case ADR filename
    convention, and the discovered identifiers must be contiguous starting at
    ``0001``. Each ADR is validated with ``validate_adr``; the supplied operating
    model is forwarded to those
    non-template validations. The decision log must contain exactly one link for
    each ADR. Within the Decision records section, lines starting with a table
    cell containing exactly four digits are checked for duplicate, unexpected,
    or malformed rows; other lines are ignored by the row parser.
    Missing records and title, filename, status, owner, and review-date mismatches
    are reported.
    Findings are accumulated across these checks before one governance error is
    raised. The function reads directory files only and does not write them.

    Args:
        directory: Directory containing ``template.md``, ``README.md``, and ADR
            Markdown files.
        operating_model: Optional operating model passed to each non-template
            ADR validation for Founder accepted decisions.

    Returns:
        The matching ADR paths in lexicographic filename order after all checks
        pass. ``template.md`` and ``README.md`` are excluded.

    Raises:
        ArchitectureGovernanceError: If the template, ADR set, or decision log
            violates any directory or cross-file governance rule.
        OSError: If directory traversal or any required file read fails.
        UnicodeDecodeError: If a required text file is not valid UTF-8.
    """
    findings: list[str] = []
    template_path = directory / "template.md"
    log_path = directory / "README.md"
    if not template_path.is_file():
        findings.append(f"{template_path}: ADR template is missing")
    else:
        try:
            validate_adr(template_path, expected_identifier=0, template=True)
        except ArchitectureGovernanceError as error:
            findings.extend(error.findings)

    markdown_files = tuple(sorted(directory.glob("*.md")))
    unexpected = [
        path
        for path in markdown_files
        if path.name not in {"README.md", "template.md"}
        and _DECISION_FILENAME.fullmatch(path.name) is None
    ]
    for path in unexpected:
        findings.append(f"{path}: ADR filename must be a four-digit identifier and kebab-case slug")
    decisions = tuple(path for path in markdown_files if _DECISION_FILENAME.fullmatch(path.name))
    identifiers = [int(path.name[:4]) for path in decisions]
    if identifiers != list(range(1, len(identifiers) + 1)):
        findings.append(f"{directory}: ADR identifiers must be contiguous and start at 0001")

    for identifier, path in zip(identifiers, decisions, strict=True):
        try:
            validate_adr(path, expected_identifier=identifier, operating_model=operating_model)
        except ArchitectureGovernanceError as error:
            findings.extend(error.findings)

    if not log_path.is_file():
        findings.append(f"{log_path}: decision log is missing")
    else:
        log = log_path.read_text(encoding="utf-8")
        _validate_decision_log(log_path, log, decisions, findings)
        for path in decisions:
            if log.count(f"({path.name})") != 1:
                findings.append(f"{log_path}: must link decision '{path.name}' exactly once")

    if findings:
        raise ArchitectureGovernanceError(findings)
    return decisions


def _heading_anchors(text: str) -> set[str]:
    """Approximate Markdown heading anchors with duplicate suffixes.

    Args:
        text: Markdown source whose level-one through level-six headings should
            be converted into anchors.

    Returns:
        A set of case-folded, punctuation-stripped, whitespace/hyphen-collapsed
        anchors. Repeated bases receive ``-1``, ``-2`` and later suffixes in
        encounter order. The regex also processes headings inside fenced text,
        and the approximation is repository-local rather than an exact
        renderer-specific slug algorithm.
    """
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*$", text, flags=re.MULTILINE):
        without_markup = re.sub(r"[`*_~]", "", heading)
        base = re.sub(r"[^\w\s-]", "", without_markup.casefold())
        base = re.sub(r"[\s-]+", "-", base).strip("-")
        count = counts.get(base, 0)
        anchors.add(base if count == 0 else f"{base}-{count}")
        counts[base] = count + 1
    return anchors


def validate_local_links(repository_root: Path, documents: Iterable[Path]) -> None:
    """Validate repository-local Markdown targets and Markdown heading fragments.

    Each supplied document is read as UTF-8 and scanned for inline, non-image
    Markdown links after text between triple-backtick fences is removed. Links
    with a URL scheme or a network-relative ``//`` destination are treated as
    external and skipped. Other destinations are resolved relative to the source
    document. The path and fragment are percent-decoded separately, and a
    fragment-only destination targets the source document. The checker splits
    only at ``#``, so any query text remains part of the path text. Targets are
    required to resolve to a file inside the resolved repository root. Fragments
    on Markdown targets are checked against this module's approximate,
    case-insensitive heading-anchor algorithm, including duplicate-heading
    suffixes; fragments on other file types are not inspected. Findings are
    reported in document and link encounter order. The function performs local
    filesystem reads and path resolution only; it makes no network requests and
    does not modify any file.

    Args:
        repository_root: Root directory that local links must not escape after
            path resolution.
        documents: Iterable of Markdown-like document paths to scan. The iterable
            is consumed once, in its supplied order.

    Raises:
        ArchitectureGovernanceError: If a local link escapes the repository, its
            target is missing, or a checked Markdown heading does not exist.
        OSError: If a supplied document or checked Markdown target cannot be
            read, or a required path resolution fails.
        UnicodeDecodeError: If a supplied document or checked Markdown target is
            not valid UTF-8.
        ValueError: If URL parsing rejects a link destination.
        RuntimeError: If path resolution encounters a symbolic-link loop.
    """
    resolved_repository_root = repository_root.resolve()
    findings: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}
    for document in documents:
        text = document.read_text(encoding="utf-8")
        text_without_fences = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        for match in _MARKDOWN_LINK.finditer(text_without_fences):
            destination = match.group("destination").strip().strip("<>")
            parsed_url = urlsplit(destination)
            if parsed_url.scheme or destination.startswith("//"):
                continue
            path_text, _, fragment = destination.partition("#")
            target = document if not path_text else document.parent / unquote(path_text)
            target = target.resolve()
            try:
                target.relative_to(resolved_repository_root)
            except ValueError:
                findings.append(f"{document}: local link escapes the repository: {destination}")
                continue
            if not target.is_file():
                findings.append(f"{document}: local link target does not exist: {destination}")
                continue
            if fragment and target.suffix.casefold() == ".md":
                anchors = anchor_cache.setdefault(
                    target, _heading_anchors(target.read_text(encoding="utf-8"))
                )
                if unquote(fragment).casefold() not in anchors:
                    findings.append(f"{document}: Markdown heading does not exist: {destination}")
    if findings:
        raise ArchitectureGovernanceError(findings)


def _validate_repository(repository_root: Path) -> tuple[Path, ...]:
    """Run every repository-local architecture-governance check."""
    resolved_repository_root = repository_root.resolve()
    decisions = validate_decision_directory(
        resolved_repository_root / "docs" / "architecture" / "decisions",
        operating_model=load_operating_model(
            resolved_repository_root / "docs" / "governance" / "domain-ownership.toml"
        ),
    )
    validate_local_links(
        resolved_repository_root,
        sorted((resolved_repository_root / "docs").rglob("*.md")),
    )
    return decisions


def validate_repository(repository_root: Path) -> tuple[Path, ...]:
    """Validate repository architecture decisions and local documentation links.

    The delegated repository check resolves ``repository_root`` before forming
    paths, loads the operating model from
    ``docs/governance/domain-ownership.toml``, validates the decision directory
    with that model, and then scans sorted Markdown files below ``docs`` for
    repository-local links and heading fragments. The decision-directory check
    must pass before the local-link scan starts, so the wrapper does not combine
    findings from both stages. These operations perform local reads and path
    resolution only; they do not write files or make network requests.

    Args:
        repository_root: Repository path containing the ownership register,
            architecture decisions, and documentation tree. Relative and
            symlinked paths are resolved by the delegated check.

    Returns:
        The validated ADR directory-entry paths, rooted under the resolved
        repository root and ordered by filename; ``template.md`` and
        ``README.md`` are excluded. A symlink entry retains its directory path
        spelling rather than being canonicalized by the return value.

    Raises:
        ArchitectureGovernanceError: If decision-directory or local-link checks
            report findings, or if an ``OperatingModelError`` or escaping
            Pydantic ``ValidationError`` is translated at this public boundary.
            Operating-model failures preserve their message and cause; escaping
            model failures use a repository-scoped generic message and preserve
            their cause.
        OSError: If root resolution or any delegated operating-model, decision,
            or local-link file operation fails.
        UnicodeDecodeError: If delegated UTF-8 text reading fails.
        ValueError: If delegated local-link URL parsing raises an uncaught value
            error; the explicitly handled ``OperatingModelError`` is translated.
        RuntimeError: If delegated path resolution encounters a symbolic-link loop.
    """
    try:
        return _validate_repository(repository_root)
    except OperatingModelError as error:
        raise ArchitectureGovernanceError([str(error)]) from error
    except ValidationError as error:
        raise ArchitectureGovernanceError(
            [f"{repository_root}: architecture model validation failed"]
        ) from error


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the architecture-governance checker and map handled failures to status.

    ``None`` consumes ``sys.argv[1:]``; an explicit sequence is used instead.
    With no arguments the repository root defaults to the process working
    directory. More than one argument prints usage to stderr and returns ``2``.
    Domain and filesystem failures from repository validation are printed to
    stderr and return ``1``; decoding failures, default-working-directory
    resolution errors, output errors and unexpected exceptions propagate.

    Args:
        arguments: Optional command-line arguments; at most one repository-root
            path is accepted.

    Returns:
        ``0`` after printing the number of validated ADRs, ``1`` after a
        handled validation/filesystem failure, or ``2`` for excess arguments.

    Raises:
        OSError: If resolving the default working directory or writing command
            output fails outside the validation handler.
        UnicodeDecodeError: If repository text is not valid UTF-8 and the
            validation path does not translate that decoding failure.
    """
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(cli_arguments) > 1:
        print(
            "usage: python -m alpha_research_governance.architecture_governance [repository-root]",
            file=sys.stderr,
        )
        return 2
    repository_root = Path(cli_arguments[0]) if cli_arguments else Path.cwd()
    try:
        decisions = validate_repository(repository_root)
    except (ArchitectureGovernanceError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Architecture governance passed for {len(decisions)} ADRs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
