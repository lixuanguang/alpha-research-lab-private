"""Validate architecture decision records and repository-local documentation links."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

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
_ALLOWED_STATUSES = {"Proposed", "Accepted", "Rejected", "Deprecated", "Superseded"}


@dataclass(frozen=True)
class _DecisionLogEntry:
    identifier: str
    title: str
    filename: str
    status: str
    owner: str
    review_date: str


class ArchitectureGovernanceError(ValueError):
    """Report one or more deterministic architecture-governance findings."""

    def __init__(self, findings: Sequence[str]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


def _metadata(text: str) -> dict[str, str]:
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
    match = re.search(
        rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## |\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return None if match is None else match.group("body").strip()


def _parse_date(value: str, *, field: str, path: Path, findings: list[str]) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        findings.append(f"{path}: {field} must use YYYY-MM-DD")
        return None


def validate_adr(path: Path, *, expected_identifier: int, template: bool = False) -> None:
    """Validate one ADR's identity, metadata, required sections, and lifecycle fields."""
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

    metadata = _metadata(text)
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
        if status == "Accepted" and metadata["Approval evidence"].casefold().startswith("pending"):
            findings.append(f"{path}: Accepted ADRs require non-pending approval evidence")

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
        metadata = _metadata(text)
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


def validate_decision_directory(directory: Path) -> tuple[Path, ...]:
    """Validate the ADR template, contiguous record identifiers, and decision log."""
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
            validate_adr(path, expected_identifier=identifier)
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
    """Reject missing repository-local Markdown link targets and heading fragments."""
    root = repository_root.resolve()
    findings: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}
    for document in documents:
        text = document.read_text(encoding="utf-8")
        text_without_fences = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        for match in _MARKDOWN_LINK.finditer(text_without_fences):
            destination = match.group("destination").strip().strip("<>")
            parsed = urlsplit(destination)
            if parsed.scheme or destination.startswith("//"):
                continue
            path_text, _, fragment = destination.partition("#")
            target = document if not path_text else document.parent / unquote(path_text)
            target = target.resolve()
            try:
                target.relative_to(root)
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


def validate_repository(repository_root: Path) -> tuple[Path, ...]:
    """Run every repository-local A02 architecture governance check."""
    root = repository_root.resolve()
    decisions = validate_decision_directory(root / "docs" / "architecture" / "decisions")
    validate_local_links(root, sorted((root / "docs").rglob("*.md")))
    return decisions


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the architecture governance checker from the command line."""
    provided = list(sys.argv[1:] if arguments is None else arguments)
    if len(provided) > 1:
        print(
            "usage: python -m alpha_research.architecture_governance [repository-root]",
            file=sys.stderr,
        )
        return 2
    repository_root = Path(provided[0]) if provided else Path.cwd()
    try:
        decisions = validate_repository(repository_root)
    except (ArchitectureGovernanceError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Architecture governance passed for {len(decisions)} ADRs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
