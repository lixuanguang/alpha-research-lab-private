"""Validate repository-local Markdown links and heading fragments."""

from __future__ import annotations

# standard library imports
import re
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from urllib.parse import unquote, urlsplit

_MARKDOWN_LINK: re.Pattern[str] = re.compile(r"(?<!!)\[[^\]]+\]\((?P<destination>[^)]+)\)")
_HEADING_PATTERN: re.Pattern[str] = re.compile(
    r"^#{1,6}\s+(?P<heading>.+?)\s*#*$", flags=re.MULTILINE
)


class ArchitectureGovernanceError(ValueError):
    """Report local-link findings in input order."""


class ArchitectureGovernanceService:
    """Validate local links for one repository context."""

    def __init__(self, repository_root: Path) -> None:
        """Bind a repository path without reading files.

        Args:
            repository_root: Root bounding local link targets.
        """
        self._repository_root = repository_root

    @staticmethod
    def _heading_anchors(text: str) -> set[str]:
        """Derive approximate anchors from Markdown heading text.

        Case-fold and strip markup/punctuation. Preserve GitHub's one hyphen per
        space and existing hyphens; repeated headings receive ``-1``, ``-2`` suffixes.
        """
        anchors: set[str] = set()
        counts: dict[str, int] = {}
        for match in _HEADING_PATTERN.finditer(text):
            heading = match.group("heading")
            without_markup = re.sub(r"[`*_~]", "", heading)
            base = re.sub(r"[^\w -]", "", without_markup.casefold())
            base = base.replace(" ", "-")
            count = counts.get(base, 0)
            anchors.add(base if count == 0 else f"{base}-{count}")
            counts[base] = count + 1
        return anchors

    def validate_local_links(self, documents: Iterable[Path]) -> None:
        """Validate Markdown links in ``documents``.

        External URLs are skipped. Local targets stay inside the repository and use valid
        heading anchors for Markdown fragments.

        Args:
            documents: Markdown documents to scan, in supplied order.

        Raises:
            ArchitectureGovernanceError: If a local target or fragment is invalid.
            OSError, UnicodeDecodeError: If a supplied document or target cannot be read.
        """
        resolved_root = self._repository_root.resolve()
        findings: list[str] = []
        anchor_cache: dict[Path, set[str]] = {}
        for document in documents:
            text = document.read_text(encoding="utf-8")
            text_without_fences = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
            for match in _MARKDOWN_LINK.finditer(text_without_fences):
                destination: str = match.group("destination")
                destination = destination.strip().strip("<>")
                parsed_url = urlsplit(destination)
                if parsed_url.scheme or destination.startswith("//"):
                    continue

                path_text, _, fragment = destination.partition("#")
                target = (
                    document if not path_text else document.parent / unquote(path_text)
                ).resolve()
                try:
                    target.relative_to(resolved_root)
                except ValueError:
                    findings.append(f"{document}: local link escapes the repository: {destination}")
                    continue
                if not target.is_file():
                    findings.append(f"{document}: local link target does not exist: {destination}")
                    continue
                if fragment and target.suffix.casefold() == ".md":
                    if target not in anchor_cache:
                        anchor_cache[target] = self._heading_anchors(
                            target.read_text(encoding="utf-8")
                        )
                    anchors = anchor_cache[target]
                    if unquote(fragment).casefold() not in anchors:
                        findings.append(
                            f"{document}: Markdown heading does not exist: {destination}"
                        )
        if findings:
            raise ArchitectureGovernanceError("\n".join(findings))


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the local-link checker and map failures to status.

    Args:
        arguments: Optional command-line arguments; at most one repository-root path is accepted.

    Returns:
        ``0`` after validation, ``1`` after a handled failure, or ``2`` for excess arguments.
    """
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(cli_arguments) > 1:
        print("usage: alpha-governance-architecture [repository-root]", file=sys.stderr)
        return 2
    repository_root = Path(cli_arguments[0]) if cli_arguments else Path.cwd()
    try:
        root = repository_root.resolve()
        documents = tuple(sorted((root / "docs").rglob("*.md")))
        ArchitectureGovernanceService(root).validate_local_links(documents)
    except (ArchitectureGovernanceError, OSError, UnicodeError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Architecture link check passed for {len(documents)} documents.")
    return 0
