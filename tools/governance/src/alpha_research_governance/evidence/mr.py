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
    """Remove lines inside the module's supported Markdown fence subset.

    A fence opens on a line whose optional leading whitespace is followed by at
    least three backticks or tildes. While a fence is open, all lines are omitted;
    it closes only on a run using the same marker character and at least the
    opening run's length; trailing text on that line is accepted by the prefix
    match. The helper does not parse language info strings, nested Markdown
    constructs, or malformed fence diagnostics. An unterminated fence consequently
    removes the remainder of the text.

    Retained lines keep their original line endings because the input is split with
    ``keepends=True``. Marker-like text later on a non-fence line is retained, and
    marker lines encountered while a fence is open are considered only as possible
    closures.

    Args:
        text: Markdown or comment-bearing text to filter.

    Returns:
        Text with fenced regions removed and all other lines in their original order.
    """
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
    """Extract exact-level Markdown sections using the repository subset parser.

    HTML comments are removed first, then fenced code is removed, so commented or
    fenced examples cannot create headings. A heading must match the module's
    line-oriented ``#`` pattern. Section boundaries are the next heading at the
    requested level or any shallower level; deeper headings remain in the current
    section body. Returned bodies are stripped only at their outer edges, while
    section order and duplicate headings are preserved. This is intentionally a
    small profile parser rather than a complete Markdown implementation.

    Args:
        text: Merge-request Markdown to inspect.
        level: Heading depth to return; callers use level 2 or 3 for their profile.

    Returns:
        ``(heading, body)`` pairs for headings whose depth equals ``level``.
        Headings and bodies retain source order.
    """
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
    """Validate a merge-request template against the policy's ordered fields.

    Schema version ``2`` selects level-two headings; every other schema version
    selects level-three headings. The parsed heading sequence must exactly match
    ``policy.fields`` in order. Marker validation is a separate raw-text check:
    it requires the exact heading text followed immediately by LF and searches
    from the first matching heading through the next LF-plus-``#`` boundary for
    the exact ``<!-- required:{field.key} -->`` marker. It does not parse fences
    or comments, so marker text there can count; CRLF input can fail the exact-LF
    heading check. Heading discovery itself uses the module's limited Markdown
    parser, so headings in HTML comments or supported fenced code are ignored.
    This function only inspects its arguments and does not perform filesystem I/O
    or mutate the template or policy.

    Args:
        text: Merge-request template Markdown to inspect.
        policy: Loaded evidence policy that supplies the schema version and the
            ordered default field headings and keys.

    Raises:
        EvidenceGovernanceError: If the heading sequence differs from the policy
            or any expected heading or required marker is missing. All findings
            are reported together.
    """
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
    """Parse the optional evidence-context declaration from merge-request text.

    Fenced code is ignored before searching for the repository's HTML-comment
    marker. With no matching declaration, ordinary text returns the default
    ``MrContext``; however, a stray ``evidence-context:`` token is treated as a
    malformed declaration. Exactly one matching declaration is allowed. Its JSON
    is validated by ``MrContext`` using the strict context model, and model
    validation failures are translated to the domain error with their cause.
    Unmatched marker text alongside one valid declaration is not separately
    rejected because the parser counts matching declarations, not arbitrary marker
    occurrences.

    Args:
        text: Merge-request Markdown, possibly containing a context comment.

    Returns:
        Parsed context, or default implementation/no-impact facts when no marker is
        present.

    Raises:
        EvidenceGovernanceError: The marker is malformed, more than one matching
            comment exists, or the declaration is not valid context JSON/model data.
    """
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
    """Validate merge-request fields for the selected evidence profile.

    Institutional mode is selected by ``profile="institutional"`` or by a
    version-1 policy. It parses level-three headings and validates
    ``policy.institutional_fields``, falling back to ``policy.fields`` when the
    institutional collection is empty. Default mode parses level-two headings,
    validates ``policy.fields``, and calls ``classify_mr`` with ``changed_paths``
    and ``change_policy`` to select triggered conditional fields. An untriggered
    conditional heading is optional, but is validated and returned if present.
    ``classify_mr`` considers path names, the optional evidence-context facts, and
    the context operation; this function does not consult a date, filesystem,
    Git, or external control state. In institutional mode, ``changed_paths`` and
    ``change_policy`` are unused.

    Heading extraction uses the module's line-oriented subset: comments and
    supported fenced blocks are removed, headings require one to six ``#``
    characters followed by one space, and section bodies end at the next heading
    at the selected or a shallower level. Deeper headings remain in the body;
    heading order and duplicates are retained; this validator does not require a
    global heading sequence or reject unrelated headings. Required fields are
    checked in policy order, followed by present optional conditional fields. Each
    body is stripped at its outer edges and rejected when empty or when it consists
    only of ``tbd``, ``todo``, ``replace me``, ``pending answer``, ``n/a``, ``na``,
    or ``none``, case-insensitively, with an optional final period or exclamation
    mark.

    Args:
        text: Merge-request Markdown body to inspect.
        policy: Loaded evidence policy supplying baseline, institutional and
            conditional field definitions and the schema version.
        profile: Requested ``"default"`` or ``"institutional"`` profile.
        changed_paths: Repository-relative paths used only by default-mode
            classification to infer documentation, migration, benchmark or
            operational impact. The default is an empty tuple and supplies no
            documentation-only inference.
        change_policy: Optional change-risk policy passed to default-mode
            classification when the body declares change facts. It is otherwise
            unused.

    Returns:
        A mapping from accepted field keys to their outer-stripped body text, in
        validation insertion order. It includes every required field and each
        present optional conditional field.

    Raises:
        EvidenceGovernanceError: If default-mode classification rejects malformed
            context, declared facts without a policy, or invalid change facts; if
            generated metadata is invalid; or if a required or present optional
            field is missing, duplicated, empty, or placeholder-only. Field
            findings are accumulated in validation order and raised together;
            classification errors propagate before field validation begins.
    """
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
    """Read and validate the body and commit identities from a GitHub event JSON file.

    The accepted boundary requires an object root, a ``pull_request`` object, text
    ``body``, and a ``head`` object containing a full lowercase 40- or 64-character
    hexadecimal SHA. The base object is optional: a missing or non-dictionary base,
    and a missing or explicit-null ``base.sha``, all produce ``None``. A non-null
    base SHA must use the same full lowercase format. Extra event keys are ignored;
    duplicate JSON keys and payload size are not guarded here.

    Args:
        path: JSON event file to read as UTF-8 text.

    Returns:
        A tuple of pull-request body text, validated head SHA, and optional validated
        base SHA.

    Raises:
        EvidenceGovernanceError: JSON syntax is invalid, the required root/request/
            body/head structure is absent, or a supplied head/base SHA is not full
            lowercase hexadecimal. JSON syntax errors retain their decoder cause.
        OSError: The event file cannot be read.
        UnicodeDecodeError: The event file is not valid UTF-8.
        ValueError: JSON decoding raises a ``ValueError`` other than ``JSONDecodeError``, such as
            integer conversion rejecting an excessively long number.
        RecursionError: The JSON nesting exceeds the decoder's recursion limit.
    """
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
    """Read unique changed paths from a Git three-dot diff.

    Both commit identities must be full lowercase 40- or 64-character hexadecimal
    SHAs. The function locates ``git`` on ``PATH`` and runs
    ``git diff --name-only -z --no-renames <base>...<head> --`` with
    ``repository_root`` as its working directory. Disabling rename detection
    leaves deleted paths and both pathnames of a rename in the emitted list. Git's
    NUL-delimited output is decoded as UTF-8, deduplicated, and sorted; returned
    names are otherwise kept as Git emitted them. Calling this function performs
    the PATH lookup and launches the Git subprocess; no Python-side file writes or
    path resolution are performed.

    Args:
        repository_root: Working directory in which Git resolves the repository
            and the two commit identities.
        base_sha: Full lowercase base commit SHA in the three-dot revision
            expression.
        head_sha: Full lowercase head commit SHA in the three-dot revision
            expression.

    Returns:
        Unique changed path names emitted by Git, sorted lexicographically. An
        empty tuple indicates that the diff emitted no path names.

    Raises:
        EvidenceGovernanceError: If either SHA is not full lowercase hexadecimal,
            Git is unavailable, or Git exits unsuccessfully.
        OSError: If the Git subprocess cannot be started.
        UnicodeDecodeError: If Git's captured path output is not valid UTF-8.
    """
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
    """Validate a pull-request event and return its head commit SHA.

    The compatibility API reads the event as UTF-8 JSON, validates the required
    pull-request body and head SHA, and validates a supplied non-null base SHA
    using the event parser. It then validates the body against ``policy`` without
    supplying a repository root, so it does not compute a Git diff or classify
    actual changed paths. Body validation still classifies with empty
    ``changed_paths`` and no change policy: context flags or operation can select
    conditional fields, but declared change facts cannot be classified and fail.
    A missing or non-object ``base`` and a null ``base.sha`` are accepted as
    absent, and extra event keys are ignored. The returned value preserves the
    historical head-SHA-only interface; callers needing Git-scope validation
    should use ``lint_github_event`` with ``repository_root``.

    Args:
        path: UTF-8 GitHub pull-request event JSON file to read.
        policy: Evidence policy used to validate the pull-request body.

    Returns:
        The validated ``pull_request.head.sha`` string.

    Raises:
        EvidenceGovernanceError: If the event structure or required SHA format is
            invalid; the body fields, or a malformed, duplicated, or invalid
            evidence-context comment, fail validation; or the body declares change
            facts without a change-risk policy.
        OSError: If the event file cannot be read.
        UnicodeDecodeError: If the event file is not valid UTF-8.
        ValueError: If JSON decoding raises a ValueError other than the JSON
            syntax error translated to ``EvidenceGovernanceError``.
        RecursionError: If JSON nesting exceeds the decoder's recursion limit.
    """
    metadata = lint_github_event(path, policy)
    return str(metadata["head_commit_sha"])
