"""Deterministic tests for architecture-decision and documentation governance."""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha_research.architecture_governance import (
    ArchitectureGovernanceError,
    validate_adr,
    validate_decision_directory,
    validate_local_links,
    validate_repository,
)

REPOSITORY_ROOT = Path(__file__).parents[2]


def _adr_text(
    *,
    identifier: int = 1,
    status: str = "Proposed",
    owner: str = "platform",
    decision_date: str = "2026-08-25",
    review_date: str = "2026-11-25",
    approval_evidence: str = "Pending; test fixture",
    include_reversal: bool = True,
) -> str:
    sections = [
        ("Context", "A bounded decision is required."),
        ("Decision drivers", "- Preserve deterministic behavior."),
        (
            "Considered alternatives",
            "- **Option A:** Use the governed default.\n- **Option B:** Retain the bootstrap.",
        ),
        ("Decision", "Use the governed default."),
        ("Consequences", "The choice is explicit and reviewable."),
        ("Migration and rollout", "Adopt through later implementation packages."),
    ]
    if include_reversal:
        sections.append(
            ("Reversal plan", "Revert consumers through a reviewed compatibility window.")
        )
    sections.append(
        ("Review and evidence", "Review on the recorded date against measured evidence.")
    )
    section_text = "\n\n".join(f"## {heading}\n\n{body}" for heading, body in sections)
    return f"""# ADR {identifier:04d}: Test decision

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A02 |
| Status | {status} |
| Decision owner | {owner} |
| Decision date | {decision_date} |
| Review date | {review_date} |
| Supersedes | None |
| Approval evidence | {approval_evidence} |

{section_text}
"""


def test_repository_architecture_governance_is_valid() -> None:
    decisions = validate_repository(REPOSITORY_ROOT)

    assert [path.name for path in decisions] == [
        "0001-build-and-developer-tooling.md",
        "0002-language-runtime-boundaries.md",
        "0003-schema-and-analytical-interchange.md",
        "0004-data-storage-and-event-transport.md",
        "0005-runtime-lanes.md",
        "0006-deployment-and-activation.md",
        "0007-observability-substrate.md",
        "0008-pydantic-boundary-models.md",
        "0009-remote-execution-service.md",
        "0010-pydantic-instrument-identity-models.md",
        "0011-versioned-venue-calendar-adapter.md",
        "0012-wheel-only-source-admission.md",
    ]


@pytest.mark.parametrize(
    ("status", "owner", "message"),
    [
        ("Draft", "platform", "unsupported ADR status"),
        ("Proposed", "Unassigned", "must name an accountable role"),
        ("Accepted", "platform", "require 'commit="),
    ],
)
def test_adr_lint_rejects_invalid_lifecycle_metadata(
    tmp_path: Path, status: str, owner: str, message: str
) -> None:
    path = tmp_path / "0001-test-decision.md"
    path.write_text(_adr_text(status=status, owner=owner), encoding="utf-8")

    with pytest.raises(ArchitectureGovernanceError, match=message):
        validate_adr(path, expected_identifier=1)


def test_adr_lint_rejects_invalid_review_date_boundaries(tmp_path: Path) -> None:
    path = tmp_path / "0001-test-decision.md"
    invalid_boundaries = (
        ("2026/08/25", "2026-11-25"),
        ("20260825", "2026-11-25"),
        ("2026-W35-1", "2026-11-25"),
        ("2026-08-25", "2026-08-25"),
    )
    for decision_date, review_date in invalid_boundaries:
        path.write_text(
            _adr_text(decision_date=decision_date, review_date=review_date), encoding="utf-8"
        )

        with pytest.raises(ArchitectureGovernanceError, match=r"Decision date|Review date"):
            validate_adr(path, expected_identifier=1)


def test_adr_lint_rejects_missing_reversal_plan(tmp_path: Path) -> None:
    path = tmp_path / "0001-test-decision.md"
    path.write_text(_adr_text(include_reversal=False), encoding="utf-8")

    with pytest.raises(ArchitectureGovernanceError, match="Reversal plan"):
        validate_adr(path, expected_identifier=1)


def test_accepted_adr_requires_commit_bound_https_approval(tmp_path: Path) -> None:
    path = tmp_path / "0001-test-decision.md"
    path.write_text(
        _adr_text(
            status="Accepted",
            approval_evidence=(
                f"commit={'a' * 40}; approval=https://forge.example/reviews/approved"
            ),
        ),
        encoding="utf-8",
    )

    validate_adr(path, expected_identifier=1)

    path.write_text(
        _adr_text(
            status="Accepted",
            approval_evidence=f"commit={'a' * 40}; approval=http://forge.example/insecure",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ArchitectureGovernanceError, match="HTTPS evidence URL"):
        validate_adr(path, expected_identifier=1)

    path.write_text(
        _adr_text(
            status="Accepted",
            approval_evidence=f"commit={'a' * 40}; approval=https://[malformed/review",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ArchitectureGovernanceError, match="HTTPS evidence URL"):
        validate_adr(path, expected_identifier=1)


def test_decision_log_rejects_unlogged_and_noncontiguous_records(tmp_path: Path) -> None:
    directory = tmp_path / "decisions"
    directory.mkdir()
    (directory / "template.md").write_text(_adr_text(identifier=0), encoding="utf-8")
    (directory / "README.md").write_text("# Decision log\n", encoding="utf-8")
    (directory / "0002-second-decision.md").write_text(_adr_text(identifier=2), encoding="utf-8")

    with pytest.raises(ArchitectureGovernanceError) as captured:
        validate_decision_directory(directory)

    assert "contiguous" in str(captured.value)
    assert "must link decision" in str(captured.value)


def test_decision_log_rejects_adr_metadata_drift(tmp_path: Path) -> None:
    mutations = (
        ("[Test decision]", "[Wrong title]", "title does not match"),
        ("(0001-test-decision.md)", "(0001-wrong.md)", "filename does not match"),
        ("| Proposed |", "| Accepted |", "status does not match"),
        ("| platform |", "| wrong_owner |", "owner does not match"),
        ("| 2026-11-25 |", "| 2026-12-01 |", "review date does not match"),
    )
    directory = tmp_path / "decisions"
    directory.mkdir()
    (directory / "template.md").write_text(_adr_text(identifier=0), encoding="utf-8")
    (directory / "0001-test-decision.md").write_text(_adr_text(), encoding="utf-8")
    row = "| 0001 | [Test decision](0001-test-decision.md) | Proposed | platform | 2026-11-25 |"
    for old, new, message in mutations:
        log = f"""# Decision log

## Decision records

| ID | Decision | Status | Owner | Review date |
| --- | --- | --- | --- | --- |
{row.replace(old, new)}
"""
        (directory / "README.md").write_text(log, encoding="utf-8")

        with pytest.raises(ArchitectureGovernanceError, match=message):
            validate_decision_directory(directory)


def test_decision_log_rejects_invalid_record_structure(tmp_path: Path) -> None:
    invalid_records = (
        ("", "missing decision record 0001"),
        (
            "| 0001 | [Test decision](0001-test-decision.md) | "
            "Proposed | platform | 2026-11-25 |\n"
            "| 0001 | [Test decision](0001-test-decision.md) | "
            "Proposed | platform | 2026-11-25 |",
            "duplicate decision record 0001",
        ),
        (
            "| 0001 | [Test decision](0001-test-decision.md) | "
            "Proposed | platform | 2026-11-25 |\n"
            "| 0002 | [Unexpected](0002-unexpected.md) | "
            "Proposed | platform | 2026-11-25 |",
            "unexpected decision record 0002",
        ),
        ("| 0001 | malformed |", "malformed decision record row"),
    )
    directory = tmp_path / "decisions"
    directory.mkdir()
    (directory / "template.md").write_text(_adr_text(identifier=0), encoding="utf-8")
    (directory / "0001-test-decision.md").write_text(_adr_text(), encoding="utf-8")
    for rows, message in invalid_records:
        log = f"""# Decision log

## Decision records

| ID | Decision | Status | Owner | Review date |
| --- | --- | --- | --- | --- |
{rows}
"""
        (directory / "README.md").write_text(log, encoding="utf-8")

        with pytest.raises(ArchitectureGovernanceError, match=message):
            validate_decision_directory(directory)


def test_decision_directory_rejects_uncontrolled_markdown_filename(tmp_path: Path) -> None:
    directory = tmp_path / "decisions"
    directory.mkdir()
    (directory / "template.md").write_text(_adr_text(identifier=0), encoding="utf-8")
    (directory / "README.md").write_text("# Decision log\n", encoding="utf-8")
    (directory / "draft_choice.md").write_text(_adr_text(), encoding="utf-8")

    with pytest.raises(ArchitectureGovernanceError, match="ADR filename"):
        validate_decision_directory(directory)


def test_local_link_check_accepts_anchor_and_rejects_missing_target(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "source.md"
    target = docs / "target.md"
    target.write_text("# Target\n\n## Existing heading\n", encoding="utf-8")
    source.write_text("[valid](target.md#existing-heading)\n", encoding="utf-8")

    validate_local_links(tmp_path, [source, target])

    source.write_text("[invalid](missing.md)\n", encoding="utf-8")
    with pytest.raises(ArchitectureGovernanceError, match="does not exist"):
        validate_local_links(tmp_path, [source, target])

    source.write_text("[invalid](target.md#missing-heading)\n", encoding="utf-8")
    with pytest.raises(ArchitectureGovernanceError, match="heading does not exist"):
        validate_local_links(tmp_path, [source, target])
