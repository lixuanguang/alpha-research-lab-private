"""Focused tests for repository-local Markdown link validation."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.architecture_governance import (
    ArchitectureGovernanceError,
    validate_local_links,
    validate_repository,
)

REPOSITORY_ROOT = Path(__file__).parents[2]


def test_repository_documentation_links_are_valid() -> None:
    """Validate all current documentation links and heading fragments."""
    documents = validate_repository(REPOSITORY_ROOT)

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
        validate_local_links(root, (source,))


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

    validate_local_links(root, (source,))
