"""Validate evidence-governance Markdown templates and merge-request bodies."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

from alpha_research_governance.evidence.models import EvidenceGovernanceError, EvidencePolicy

_HEADING = re.compile(r"^(?P<level>##|###) (?P<title>.+?)\s*$", flags=re.MULTILINE)
_COMMENT = re.compile(r"<!--.*?-->", flags=re.DOTALL)
_PLACEHOLDER = re.compile(r"^(?:tbd|todo|replace me|pending answer)[.!]?\s*$", re.IGNORECASE)


def _parse_sections(text: str) -> tuple[tuple[str, str], ...]:
    matches = tuple(_HEADING.finditer(text))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        if match.group("level") != "###":
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group("title"), text[match.end() : end].strip()))
    return tuple(sections)


def validate_template(text: str, policy: EvidencePolicy) -> None:
    """Reject template drift from the authoritative ordered field policy."""
    sections = _parse_sections(text)
    headings = tuple(heading for heading, _ in sections)
    expected = tuple(field.heading for field in policy.fields)
    findings: list[str] = []
    if headings != expected:
        findings.append("MR template headings and order must exactly match the A05 policy")
    bodies = {heading: body for heading, body in sections}
    for field in policy.fields:
        marker = f"<!-- required:{field.key} -->"
        if marker not in bodies.get(field.heading, ""):
            findings.append(f"MR template field {field.heading!r} must contain {marker}")
    if findings:
        raise EvidenceGovernanceError(findings)


def validate_mr_body(text: str, policy: EvidencePolicy) -> dict[str, str]:
    """Return required field values or reject missing, duplicate, and empty fields."""
    by_heading: dict[str, list[str]] = {}
    for heading, body in _parse_sections(text):
        by_heading.setdefault(heading, []).append(body)

    findings: list[str] = []
    values: dict[str, str] = {}
    for field in policy.fields:
        bodies = by_heading.get(field.heading, [])
        if not bodies:
            findings.append(f"missing required MR field {field.heading!r}")
            continue
        if len(bodies) != 1:
            findings.append(f"duplicate required MR field {field.heading!r}")
            continue
        value = _COMMENT.sub("", bodies[0]).strip()
        if not value or _PLACEHOLDER.fullmatch(value) is not None:
            findings.append(f"required MR field {field.heading!r} is empty or placeholder-only")
            continue
        values[field.key] = value
    if findings:
        raise EvidenceGovernanceError(findings)
    return values


def validate_github_event(path: Path, policy: EvidencePolicy) -> str:
    """Validate a pull-request event body and return its exact head commit SHA."""
    try:
        parsed_event_document: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise EvidenceGovernanceError([f"{path}: invalid JSON: {error}"]) from error
    if not isinstance(parsed_event_document, dict):
        raise EvidenceGovernanceError([f"{path}: event root must be an object"])
    event = cast(dict[str, object], parsed_event_document)
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        raise EvidenceGovernanceError([f"{path}: pull_request object is required"])
    request = cast(dict[str, object], pull_request)
    body = request.get("body")
    head = request.get("head")
    if not isinstance(body, str):
        raise EvidenceGovernanceError([f"{path}: pull_request.body must be text"])
    if not isinstance(head, dict) or not isinstance(head.get("sha"), str):
        raise EvidenceGovernanceError([f"{path}: pull_request.head.sha is required"])
    validate_mr_body(body, policy)
    commit_sha = cast(str, head["sha"])
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit_sha) is None:
        raise EvidenceGovernanceError(
            [f"{path}: pull_request.head.sha must be a full lowercase SHA"]
        )
    return commit_sha
