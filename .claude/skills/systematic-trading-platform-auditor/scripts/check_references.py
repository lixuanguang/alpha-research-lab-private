"""List repository paths, doc sections and symbols cited by this skill that no longer resolve.

Run it after documentation is reorganized or code is renamed, from the repository
root:

    uv run --frozen --no-editable python \
        .claude/skills/systematic-trading-platform-auditor/scripts/check_references.py

It checks repository paths (`docs/`, `src/`, `tests/`, `configs/`, `tools/`), skill
files (`references/`, `checklists/`, `scripts/`), section names quoted after a doc
path in a sentence that mentions a section, CamelCase class names and dotted module
names in code spans. Exit status 1 means at least one citation is stale.
"""

from __future__ import annotations

# standard library imports
import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


@dataclass(frozen=True)
class StaleCitation:
    """Describe one citation that does not resolve in the repository."""

    source: str
    line: int
    kind: str
    citation: str


@dataclass(frozen=True)
class TextBlock:
    """Hold one paragraph, list item, table row or heading of a markdown file."""

    line: int
    text: str


class MatchText:
    """Read regular-expression groups as plain strings."""

    @staticmethod
    def group(match: re.Match[str], number: int) -> str:
        """Return a group's text, or an empty string when it did not participate."""
        start, end = match.start(number), match.end(number)
        return match.string[start:end] if start >= 0 else ""


class RepositoryIndex:
    """Index the repository's documents, headings, symbols and modules."""

    DEFINITION: ClassVar[re.Pattern[str]] = re.compile(
        r"^\s*(?:class|def|async def|type)\s+(\w+)|^(\w+)\s*(?::[^=\n]+)?=", re.MULTILINE
    )
    HEADING: ClassVar[re.Pattern[str]] = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)

    def __init__(self, repository: Path) -> None:
        """Index symbols and modules under the repository's `src` tree."""
        self.repository = repository
        self.symbols: set[str] = set()
        self.modules: set[str] = set()
        self._headings: dict[Path, set[str]] = {}
        source_root = repository / "src"
        for path in source_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for match in self.DEFINITION.finditer(text):
                self.symbols.add(MatchText.group(match, 1) or MatchText.group(match, 2))
            parts = list(path.relative_to(source_root).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            for length in range(1, len(parts) + 1):
                self.modules.add(".".join(parts[:length]))
        self.packages = {module.split(".")[0] for module in self.modules}

    def exists(self, relative: str) -> bool:
        """Report whether a repository-relative path exists."""
        return (self.repository / relative).exists()

    def has_heading(self, document: str, heading: str) -> bool:
        """Report whether a markdown document has a heading with this text."""
        path = self.repository / document
        if path not in self._headings:
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            self._headings[path] = {
                self.normalize(MatchText.group(match, 1)) for match in self.HEADING.finditer(text)
            }
        return self.normalize(heading) in self._headings[path]

    NUMBERING: ClassVar[re.Pattern[str]] = re.compile(r"^\d+(?:\.\d+)*\.?\s+")

    @classmethod
    def normalize(cls, text: str) -> str:
        """Normalize heading text for comparison, ignoring numbering such as `8.` or `3.3`."""
        words = " ".join(text.replace("`", "").lower().split())
        return cls.NUMBERING.sub("", words)


class CitationChecker:
    """Find stale citations in the skill's markdown files."""

    REPOSITORY_PATH: ClassVar[re.Pattern[str]] = re.compile(
        r"(?<![\w./-])((?:docs|src|tests|configs|tools)/[\w./-]*[\w/])"
    )
    SKILL_PATH: ClassVar[re.Pattern[str]] = re.compile(
        r"(?<![\w./-])((?:references|checklists|scripts)/[\w.-]+\.(?:md|py))"
    )
    CODE_SPAN: ClassVar[re.Pattern[str]] = re.compile(r"`([^`\n]+)`")
    QUOTED: ClassVar[re.Pattern[str]] = re.compile(r'"([^"]+)"')
    DOCUMENT: ClassVar[re.Pattern[str]] = re.compile(r"docs/[\w./-]+\.md")
    SECTION_LIST: ClassVar[re.Pattern[str]] = re.compile(r'`?\s*\(((?:"[^"]+"(?:,\s*)?)+)\)')
    CLASS_NAME: ClassVar[re.Pattern[str]] = re.compile(r"[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+")
    QUALIFIED: ClassVar[re.Pattern[str]] = re.compile(r"([A-Z]\w+)\.([a-z_]\w*)")
    MODULE: ClassVar[re.Pattern[str]] = re.compile(r"[a-z_]+(?:\.[a-z_]+)+")
    FILE_SUFFIXES: ClassVar[tuple[str, ...]] = (".json", ".md", ".py", ".sqlite3", ".toml")
    NON_REPOSITORY_SPANS: ClassVar[frozenset[str]] = frozenset(
        {"BaseException", "Class.method", "NodeVisitor", "ValueError"}
    )
    BLOCK_START: ClassVar[re.Pattern[str]] = re.compile(r"^\s*(?:[-*]\s|\d+\.\s|\||#)")

    def __init__(self, skill: Path, index: RepositoryIndex) -> None:
        """Bind the skill directory and the repository index."""
        self.skill = skill
        self.index = index

    def documents(self) -> list[tuple[str, Path]]:
        """Return the skill's markdown files and the agents that preload the skill."""
        found = [
            (path.relative_to(self.skill).as_posix(), path)
            for path in sorted(self.skill.rglob("*.md"))
        ]
        agents = self.index.repository / ".claude" / "agents"
        if agents.is_dir():
            for path in sorted(agents.glob("*.md")):
                if self.skill.name in path.read_text(encoding="utf-8"):
                    found.append((path.relative_to(self.index.repository).as_posix(), path))
        return found

    def check(self) -> tuple[list[StaleCitation], int]:
        """Return every stale citation and the number of citations checked."""
        stale: list[StaleCitation] = []
        checked = 0
        for source, path in self.documents():
            lines = path.read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines, start=1):
                found, count = self._check_line(source, number, line)
                stale.extend(found)
                checked += count
            for block in self._blocks(lines):
                found, count = self._check_sections(source, block)
                stale.extend(found)
                checked += count
        return stale, checked

    def _check_line(self, source: str, number: int, line: str) -> tuple[list[StaleCitation], int]:
        """Check the paths, symbols and modules cited on one line."""
        stale: list[StaleCitation] = []
        checked = 0
        for match in self.REPOSITORY_PATH.finditer(line):
            citation = MatchText.group(match, 1).split("#", 1)[0].rstrip(".")
            checked += 1
            if not self.index.exists(citation):
                stale.append(StaleCitation(source, number, "path", citation))
        for match in self.SKILL_PATH.finditer(line):
            citation = MatchText.group(match, 1)
            checked += 1
            if not (self.skill / citation).exists():
                stale.append(StaleCitation(source, number, "skill file", citation))
        for match in self.CODE_SPAN.finditer(line):
            result = self._check_span(MatchText.group(match, 1).strip())
            if result is not None:
                checked += 1
                if not result:
                    stale.append(StaleCitation(source, number, "symbol or module", match[0]))
        return stale, checked

    def _check_span(self, text: str) -> bool | None:
        """Return whether a code span resolves, or None when it is not a citation."""
        if text in self.NON_REPOSITORY_SPANS or text.endswith(self.FILE_SUFFIXES):
            return None
        if self.CLASS_NAME.fullmatch(text):
            return text in self.index.symbols
        qualified = self.QUALIFIED.fullmatch(text)
        if qualified:
            return all(
                MatchText.group(qualified, number) in self.index.symbols for number in (1, 2)
            )
        if self.MODULE.fullmatch(text) and text.split(".")[0] in self.index.packages:
            return text in self.index.modules
        return None

    def _check_sections(self, source: str, block: TextBlock) -> tuple[list[StaleCitation], int]:
        """Check section names quoted after a doc path.

        Two forms count: a parenthesized quoted list directly after the path, as in a
        routing table, and quoted names after the path in a block that mentions a section.
        """
        documents = [(match.end(), match[0]) for match in self.DOCUMENT.finditer(block.text)]
        cited: list[tuple[str, str]] = []
        for end, document in documents:
            listed = self.SECTION_LIST.match(block.text, end)
            if listed is not None:
                names = self.QUOTED.finditer(MatchText.group(listed, 1))
                cited.extend((document, MatchText.group(name, 1)) for name in names)
        if "section" in block.text.lower():
            for match in self.QUOTED.finditer(block.text):
                preceding = [document for end, document in documents if end <= match.start()]
                if preceding:
                    cited.append((preceding[-1], MatchText.group(match, 1)))
        stale: list[StaleCitation] = []
        checked = 0
        unique: list[tuple[str, str]] = []
        for pair in cited:
            if pair not in unique:
                unique.append(pair)
        for document, heading in unique:
            if not self.index.exists(document):
                continue
            checked += 1
            if not self.index.has_heading(document, heading):
                stale.append(
                    StaleCitation(source, block.line, "section", f'{document} "{heading}"')
                )
        return stale, checked

    def _blocks(self, lines: list[str]) -> list[TextBlock]:
        """Split markdown lines into paragraphs, list items, table rows and headings."""
        blocks: list[TextBlock] = []
        current: list[str] = []
        start = 0
        in_fence = False
        for number, line in enumerate(lines, start=1):
            if line.strip().startswith("```"):
                in_fence = not in_fence
            if in_fence or not line.strip() or self.BLOCK_START.match(line):
                if current:
                    blocks.append(TextBlock(start, " ".join(current)))
                current = []
                if in_fence or not line.strip():
                    continue
            if not current:
                start = number
            current.append(line.strip())
        if current:
            blocks.append(TextBlock(start, " ".join(current)))
        return blocks


class CheckOptions(argparse.Namespace):
    """Hold the parsed command-line options with precise types."""

    repository: str | None


def main(argv: list[str] | None = None) -> int:
    """Report stale citations in the skill and return 1 when any exist."""
    parser = argparse.ArgumentParser(description="List stale citations in this skill.")
    parser.add_argument(
        "--repository", help="repository root (default: three levels above the skill)"
    )
    options = parser.parse_args(argv, namespace=CheckOptions())
    skill = Path(__file__).resolve().parent.parent
    repository = Path(options.repository).resolve() if options.repository else skill.parents[2]
    if not (repository / "src").is_dir():
        print(f"check_references: no src directory under {repository}", file=sys.stderr)
        return 2
    stale, checked = CitationChecker(skill, RepositoryIndex(repository)).check()
    for item in stale:
        print(f"{item.source}:{item.line}  {item.kind:<16} {item.citation}")
    print(f"check_references: {checked} citations checked, {len(stale)} stale")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
