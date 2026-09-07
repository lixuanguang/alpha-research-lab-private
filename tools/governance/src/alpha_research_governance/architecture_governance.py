"""Validate repository-local Markdown links.

Architecture decisions remain useful as human-readable records, but their
metadata and approval lifecycle are not a runtime contract. This checker keeps
the small, mechanical part of the old architecture tool: local links must
resolve inside the checkout and Markdown fragments must name a heading.
"""

from __future__ import annotations

# standard library imports
import re
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from urllib.parse import unquote, urlsplit

_MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\((?P<destination>[^)]+)\)")
_HEADING_PATTERN: re.Pattern[str] = re.compile(
    r"^#{1,6}\s+(?P<heading>.+?)\s*#*$", flags=re.MULTILINE
)


class ArchitectureGovernanceError(ValueError):
    """Report deterministic local-link findings in input order.

    Attributes:
        findings: Immutable tuple preserving the supplied diagnostic order.
    """

    def __init__(self, findings: Sequence[str]) -> None:
        """Capture findings without deduplication or reordering.

        Args:
            findings: Ordered diagnostic messages. An empty sequence is allowed.
        """
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


def _required_group(match: re.Match[str], name: str) -> str:
    """Read a named regex group through a checked string boundary."""
    value = match.groupdict().get(name)
    if not isinstance(value, str):
        raise ArchitectureGovernanceError([f"regex group {name!r} did not capture text"])
    return value


def _heading_anchors(text: str) -> set[str]:
    """Return the repository's approximate Markdown heading anchors.

    Args:
        text: Markdown source whose headings should be converted to anchors.

    Returns:
        Case-folded, punctuation-stripped anchors. Duplicate headings receive
        the ``-1``, ``-2`` suffixes used by common Markdown renderers.
    """
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for match in _HEADING_PATTERN.finditer(text):
        heading = _required_group(match, "heading")
        without_markup = re.sub(r"[`*_~]", "", heading)
        base = re.sub(r"[^\w\s-]", "", without_markup.casefold())
        base = re.sub(r"[\s-]+", "-", base).strip("-")
        count = counts.get(base, 0)
        anchors.add(base if count == 0 else f"{base}-{count}")
        counts[base] = count + 1
    return anchors


class ArchitectureGovernanceService:
    """Validate local links for one repository context."""

    def __init__(self, repository_root: Path) -> None:
        """Bind a repository path without reading files.

        Args:
            repository_root: Root that local link targets must remain inside.
        """
        self._repository_root = repository_root

    def validate_local_links(self, documents: Iterable[Path]) -> None:
        """Validate Markdown links in ``documents``.

        Links with a URL scheme or network-relative destination are external
        and are skipped. Other destinations resolve relative to their source,
        must remain inside the repository, and must point to an existing file.
        Markdown fragments are checked against the target's heading anchors.

        Args:
            documents: Markdown documents to scan in supplied order.

        Raises:
            ArchitectureGovernanceError: If a local target or fragment is invalid.
            OSError: If a supplied document or target cannot be read.
            UnicodeDecodeError: If a supplied document or target is not UTF-8.
        """
        resolved_root = self._repository_root.resolve()
        findings: list[str] = []
        anchor_cache: dict[Path, set[str]] = {}
        for document in documents:
            text = document.read_text(encoding="utf-8")
            text_without_fences = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
            for match in _MARKDOWN_LINK.finditer(text_without_fences):
                destination = _required_group(match, "destination").strip().strip("<>")
                parsed_url = urlsplit(destination)
                if parsed_url.scheme or destination.startswith("//"):
                    continue

                path_text, _, fragment = destination.partition("#")
                target = document if not path_text else document.parent / unquote(path_text)
                target = target.resolve()
                try:
                    target.relative_to(resolved_root)
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
                        findings.append(
                            f"{document}: Markdown heading does not exist: {destination}"
                        )
        if findings:
            raise ArchitectureGovernanceError(findings)

    def validate_repository(self) -> tuple[Path, ...]:
        """Validate all Markdown files below the repository's ``docs`` path.

        Returns:
            The sorted Markdown paths that were checked.

        Raises:
            ArchitectureGovernanceError: If a local link is invalid.
            OSError: If the repository or a document cannot be read.
        """
        root = self._repository_root.resolve()
        documents = tuple(sorted((root / "docs").rglob("*.md")))
        self.validate_local_links(documents)
        return documents


def validate_local_links(repository_root: Path, documents: Iterable[Path]) -> None:
    """Validate repository-local Markdown links and heading fragments.

    Args:
        repository_root: Root that resolved targets must remain inside.
        documents: Markdown documents to scan in supplied order.

    Raises:
        ArchitectureGovernanceError: If a target is missing, escapes, or has a
            missing heading.
    """
    ArchitectureGovernanceService(repository_root).validate_local_links(documents)


def validate_repository(repository_root: Path) -> tuple[Path, ...]:
    """Validate all documentation links in ``repository_root``.

    Args:
        repository_root: Repository whose Markdown documentation is scanned.

    Returns:
        Sorted Markdown paths that were checked.
    """
    return ArchitectureGovernanceService(repository_root).validate_repository()


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the local-link checker and map validation failures to status.

    Args:
        arguments: Optional command-line arguments. At most one repository-root
            path is accepted; ``None`` consumes ``sys.argv[1:]``.

    Returns:
        ``0`` after successful validation, ``1`` after a handled failure, or
        ``2`` for excess arguments.
    """
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(cli_arguments) > 1:
        print("usage: alpha-governance-architecture [repository-root]", file=sys.stderr)
        return 2
    repository_root = Path(cli_arguments[0]) if cli_arguments else Path.cwd()
    try:
        documents = validate_repository(repository_root)
    except (ArchitectureGovernanceError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Architecture link check passed for {len(documents)} documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
