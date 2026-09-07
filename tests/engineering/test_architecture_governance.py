"""Focused tests for repository-local Markdown link validation."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.architecture_governance import (
    ArchitectureGovernanceError,
    ArchitectureGovernanceService,
    main,
)

REPOSITORY_ROOT = Path(__file__).parents[2]


def test_repository_documentation_links_are_valid() -> None:
    """Validate all current documentation links and heading fragments."""
    documents = tuple(sorted((REPOSITORY_ROOT / "docs").rglob("*.md")))
    ArchitectureGovernanceService(REPOSITORY_ROOT).validate_local_links(documents)

    assert documents
    assert all(path.suffix == ".md" for path in documents)


@pytest.mark.parametrize(
    ("destination", "message"),
    [
        ("missing.md", "target does not exist"),
        ("../../outside.md", "escapes the repository"),
        ("target.md#missing-heading", "heading does not exist"),
    ],
)
def test_local_links_reject_invalid_targets(tmp_path: Path, destination: str, message: str) -> None:
    """Reject missing, escaping, and unknown-fragment local links."""
    root = tmp_path / "repo"
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "target.md").write_text("# Existing heading\n", encoding="utf-8")
    source = docs / "source.md"
    source.write_text(f"[target]({destination})\n", encoding="utf-8")

    with pytest.raises(ArchitectureGovernanceError, match=message):
        ArchitectureGovernanceService(root).validate_local_links((source,))


def test_local_links_ignore_external_urls_and_fenced_examples(tmp_path: Path) -> None:
    """Ignore network links and Markdown examples inside fenced code."""
    root = tmp_path / "repo"
    docs = root / "docs"
    docs.mkdir(parents=True)
    source = docs / "source.md"
    source.write_text(
        "[external](https://example.com/missing)\n\n```md\n[example](missing.md)\n```\n",
        encoding="utf-8",
    )

    ArchitectureGovernanceService(root).validate_local_links((source,))


def test_cli_reports_invalid_document_encoding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Return a controlled failure for unreadable Markdown source encoding."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "invalid.md").write_bytes(b"\xff")

    assert main([str(tmp_path)]) == 1
    assert "decode" in capsys.readouterr().err


def test_link_service_does_not_retain_findings_between_calls(tmp_path: Path) -> None:
    """Allow correction after failure using the same repository-bound service."""
    source = tmp_path / "source.md"
    source.write_text("[missing](missing.md)\n", encoding="utf-8")
    service = ArchitectureGovernanceService(tmp_path)
    with pytest.raises(ArchitectureGovernanceError, match="target does not exist"):
        service.validate_local_links((source,))
    source.write_text("# Heading\n# Heading\n[self](#heading-1)\n", encoding="utf-8")

    service.validate_local_links((source,))
