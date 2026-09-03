"""Shared adapters for typed governance command-line applications."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Protocol, TextIO, runtime_checkable

import typer


@runtime_checkable
class _RenderableCLIError(Protocol):
    """Structural boundary for Typer's user-facing parser errors."""

    exit_code: int

    def show(self, file: TextIO | None = None) -> None:
        """Render the error without exposing a traceback."""


def run_typer(
    app: typer.Typer,
    *,
    arguments: Sequence[str] | None,
    handled_errors: tuple[type[Exception], ...],
    program_name: str,
) -> int:
    """Run a Typer app while preserving the repository's integer-returning API."""
    try:
        result = typer.main.get_command(app).main(
            args=list(sys.argv[1:] if arguments is None else arguments),
            prog_name=program_name,
            standalone_mode=False,
        )
    except handled_errors as error:
        print(error, file=sys.stderr)
        return 1
    except Exception as error:
        if not isinstance(error, _RenderableCLIError):
            raise
        error.show(file=sys.stderr)
        return error.exit_code
    if result is None:
        return 0
    if not isinstance(result, int):
        raise TypeError(f"{program_name} returned a non-integer exit status")
    return result
