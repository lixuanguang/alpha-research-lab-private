"""Describe the consumed nbformat notebook reading and writing interface."""

# standard library imports
from os import PathLike
from typing import IO

class NotebookNode(dict[str, object]):
    """Attribute-accessible notebook, cell or metadata mapping."""

    cells: list[NotebookNode]
    metadata: dict[str, object]
    cell_type: str
    source: str
    execution_count: int | None
    outputs: list[object]

def read(fp: str | PathLike[str] | IO[str], as_version: int) -> NotebookNode:
    """Read a notebook file as the requested major format version."""

def reads(s: str, as_version: int) -> NotebookNode:
    """Read a notebook from text as the requested major format version."""

def writes(nb: NotebookNode) -> str:
    """Serialize a notebook to text."""

def write(nb: NotebookNode, fp: str | PathLike[str] | IO[str]) -> None:
    """Write a notebook to a path or open text file."""
