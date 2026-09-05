"""Validate concise PR evidence and retain the institutional Markdown profile."""

from __future__ import annotations

# standard library imports
import json
import re
import shutil
import subprocess  # nosec B404  # [owner=platform; rationale=read-only Git diff without a shell; expires=2027-02-28]
from pathlib import Path
from typing import Literal, cast

# third party library imports
from pydantic import ValidationError

# project library imports
from alpha_research_governance.change_risk import ChangeRiskPolicy, RiskClass, classify_change
from alpha_research_governance.evidence.models import (
    EvidenceGovernanceError,
    EvidencePolicy,
    MrContext,
    MrField,
)

_HEADING = re.compile(r"^(?P<level>#{1,6}) (?P<title>.+?)\s*$", flags=re.MULTILINE)
_COMMENT = re.compile(r"<!--.*?-->", flags=re.DOTALL)
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_CONTEXT = re.compile(r"<!--\s*evidence-context:\s*(.*?)-->", flags=re.DOTALL)
_PLACEHOLDER = re.compile(
    r"^(?:tbd|todo|replace me|pending answer|n/?a|none)[.!]?\s*$", re.IGNORECASE
)
_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def _without_fenced_code(text: str) -> str:
    fence = ""
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        match = _FENCE.match(line)
        if match and not fence:
            fence = match[1]
        elif match and fence and match[1][0] == fence[0] and len(match[1]) >= len(fence):
            fence = ""
        elif not fence:
            lines.append(line)
    return "".join(lines)


def _parse_sections(text: str, *, level: int) -> tuple[tuple[str, str], ...]:
    # Neither commented examples nor code snippets can satisfy a required heading.
    text = _without_fenced_code(_COMMENT.sub("", text))
    matches = tuple(match for match in _HEADING.finditer(text) if len(match["level"]) <= level)
    return tuple(
        (
            match["title"],
            text[
                match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(text)
            ].strip(),
        )
        for index, match in enumerate(matches)
        if len(match["level"]) == level
    )


def validate_template(text: str, policy: EvidencePolicy) -> None:
    """Reject template drift from the authoritative ordered default fields."""
    level = 2 if policy.schema_version == 2 else 3
    headings = tuple(heading for heading, _ in _parse_sections(text, level=level))
    findings: list[str] = []
    if headings != tuple(field.heading for field in policy.fields):
        findings.append("MR template headings and order must exactly match the A05 policy")
    for field in policy.fields:
        marker = f"<!-- required:{field.key} -->"
        section = f"{'#' * level} {field.heading}\n"
        if section not in text or marker not in text.split(section, 1)[1].split("\n#", 1)[0]:
            findings.append(f"MR template field {field.heading!r} must contain {marker}")
    if findings:
        raise EvidenceGovernanceError(findings)


def _context(text: str) -> MrContext:
    text = _without_fenced_code(text)
    declarations = _CONTEXT.findall(text)
    if not declarations:
        if "evidence-context:" in text:
            raise EvidenceGovernanceError(["malformed evidence-context comment"])
        return MrContext()
    if len(declarations) != 1:
        raise EvidenceGovernanceError(["only one evidence-context comment is permitted"])
    try:
        return MrContext.model_validate_json(declarations[0])
    except ValidationError as error:
        raise EvidenceGovernanceError(
            ["invalid evidence-context JSON or classification facts"]
        ) from error


def classify_mr(
    text: str,
    *,
    changed_paths: tuple[str, ...] = (),
    change_policy: ChangeRiskPolicy | None = None,
) -> dict[str, object]:
    """Generate scope and applicability; leave unobservable semantic risk unclassified."""
    context = _context(text)
    documentation_only = bool(changed_paths) and all(
        Path(path).suffix.lower() in {".md", ".rst"} for path in changed_paths
    )
    risk_class: RiskClass | None = RiskClass.R0 if documentation_only else None
    classification_source = "documentation_paths" if documentation_only else "requires_change_facts"
    if context.change is not None:
        if change_policy is None:
            raise EvidenceGovernanceError(["classification facts require the change-risk policy"])
        try:
            risk_class = classify_change(context.change, change_policy).risk_class
        except ValueError as error:
            raise EvidenceGovernanceError([str(error)]) from error
        if not documentation_only and risk_class is RiskClass.R0 and changed_paths:
            raise EvidenceGovernanceError(
                ["R0 documentation classification conflicts with changed files"]
            )
        classification_source = "declared_facts"
    source_paths = [
        Path(path) for path in changed_paths if Path(path).suffix.lower() not in {".md", ".rst"}
    ]
    parts = {part.lower() for path in source_paths for part in path.parts}
    triggers = {
        "migration": context.migration
        or bool(parts & {"schema", "schemas", "migration", "migrations"})
        or any(path.suffix in {".proto", ".avsc", ".sql"} for path in source_paths)
        or (context.change is not None and context.change.reversibility == "compatibility_window"),
        "benchmark": context.benchmark
        or bool(parts & {"benchmark", "benchmarks", "performance"})
        or (context.change is not None and context.change.computationally_material),
        "operational": context.operation != "implementation"
        or bool(parts & {"deploy", "deployments", "infra", "infrastructure"})
        or risk_class in {RiskClass.R3, RiskClass.R4},
    }
    return {
        "changed_paths": list(changed_paths),
        "documentation_only": documentation_only,
        "risk_class": risk_class.value if risk_class is not None else None,
        "classification_source": classification_source,
        "operation": context.operation,
        "required_extras": sorted(trigger for trigger, active in triggers.items() if active),
    }


def validate_mr_body(
    text: str,
    policy: EvidencePolicy,
    *,
    profile: Literal["default", "institutional"] = "default",
    changed_paths: tuple[str, ...] = (),
    change_policy: ChangeRiskPolicy | None = None,
) -> dict[str, str]:
    """Reject missing, duplicate, empty or placeholder fields for the applicable profile."""
    institutional = profile == "institutional" or policy.schema_version == 1
    fields: tuple[MrField, ...] = (
        (policy.institutional_fields or policy.fields) if institutional else policy.fields
    )
    optional_fields: tuple[MrField, ...] = ()
    if not institutional:
        metadata = classify_mr(text, changed_paths=changed_paths, change_policy=change_policy)
        triggers = metadata["required_extras"]
        if not isinstance(triggers, list):
            raise EvidenceGovernanceError(["generated PR metadata is invalid"])
        fields = (
            *fields,
            *(field for field in policy.conditional_fields if field.trigger in triggers),
        )
        optional_fields = tuple(
            field for field in policy.conditional_fields if field.trigger not in triggers
        )
    by_heading: dict[str, list[str]] = {}
    for heading, body in _parse_sections(text, level=3 if institutional else 2):
        by_heading.setdefault(heading, []).append(body)

    findings: list[str] = []
    values: dict[str, str] = {}
    for field in (*fields, *(field for field in optional_fields if field.heading in by_heading)):
        bodies = by_heading.get(field.heading, [])
        if not bodies:
            findings.append(f"missing required MR field {field.heading!r}")
            continue
        if len(bodies) != 1:
            findings.append(f"duplicate required MR field {field.heading!r}")
            continue
        value = bodies[0].strip()
        if not value or _PLACEHOLDER.fullmatch(value) is not None:
            findings.append(f"required MR field {field.heading!r} is empty or placeholder-only")
            continue
        values[field.key] = value
    if findings:
        raise EvidenceGovernanceError(findings)
    return values


def _read_github_event(path: Path) -> tuple[str, str, str | None]:
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise EvidenceGovernanceError([f"{path}: invalid JSON"]) from error
    if not isinstance(parsed, dict):
        raise EvidenceGovernanceError([f"{path}: event root must be an object"])
    request = parsed.get("pull_request")
    if not isinstance(request, dict):
        raise EvidenceGovernanceError([f"{path}: pull_request object is required"])
    body = request.get("body")
    head = request.get("head")
    if not isinstance(body, str):
        raise EvidenceGovernanceError([f"{path}: pull_request.body must be text"])
    if not isinstance(head, dict) or not isinstance(head.get("sha"), str):
        raise EvidenceGovernanceError([f"{path}: pull_request.head.sha is required"])
    commit_sha = cast(str, head["sha"])
    if _SHA.fullmatch(commit_sha) is None:
        raise EvidenceGovernanceError(
            [f"{path}: pull_request.head.sha must be a full lowercase SHA"]
        )
    base = request.get("base")
    base_sha = base.get("sha") if isinstance(base, dict) else None
    if base_sha is not None and (not isinstance(base_sha, str) or _SHA.fullmatch(base_sha) is None):
        raise EvidenceGovernanceError(
            [f"{path}: pull_request.base.sha must be a full lowercase SHA"]
        )
    return body, commit_sha, base_sha


def github_changed_paths(repository_root: Path, base_sha: str, head_sha: str) -> tuple[str, ...]:
    """Read the PR's merge-base diff, including deleted and both sides of renamed paths."""
    if any(_SHA.fullmatch(sha) is None for sha in (base_sha, head_sha)):
        raise EvidenceGovernanceError(["PR diff requires full lowercase base and head SHAs"])
    git = shutil.which("git")
    if git is None:
        raise EvidenceGovernanceError(["Git is required to classify the PR diff"])
    result = subprocess.run(  # nosec B603  # [owner=platform; rationale=read-only Git with full SHA arguments and no shell; expires=2027-02-28]
        [git, "diff", "--name-only", "-z", "--no-renames", f"{base_sha}...{head_sha}", "--"],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise EvidenceGovernanceError(
            ["cannot read the PR diff; fetch the event base and head commits"]
        )
    return tuple(sorted(set(result.stdout.decode("utf-8").rstrip("\0").split("\0")) - {""}))


def lint_github_event(
    path: Path,
    policy: EvidencePolicy,
    *,
    repository_root: Path | None = None,
    change_policy: ChangeRiskPolicy | None = None,
) -> dict[str, object]:
    """Lint the event with actual Git scope and produce commit-bound metadata."""
    body, head_sha, base_sha = _read_github_event(path)
    changed_paths: tuple[str, ...] = ()
    if repository_root is not None:
        if base_sha is None:
            raise EvidenceGovernanceError(
                ["pull_request.base.sha is required for hosted classification"]
            )
        changed_paths = github_changed_paths(repository_root, base_sha, head_sha)
    validate_mr_body(body, policy, changed_paths=changed_paths, change_policy=change_policy)
    return {
        "head_commit_sha": head_sha,
        "base_commit_sha": base_sha,
        **classify_mr(body, changed_paths=changed_paths, change_policy=change_policy),
    }


def validate_github_event(path: Path, policy: EvidencePolicy) -> str:
    """Preserve the body-only compatibility API; the CLI additionally validates Git scope."""
    metadata = lint_github_event(path, policy)
    return str(metadata["head_commit_sha"])
