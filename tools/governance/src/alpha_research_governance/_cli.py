"""Provide shared adapters for typed governance command-line applications."""

from __future__ import annotations

# standard library imports
import sys
from collections.abc import Sequence
from typing import Protocol, TextIO, runtime_checkable

# third party library imports
import typer


@runtime_checkable
class _RenderableCLIError(Protocol):
    """Define the rendering contract for Typer's user-facing parser errors.

    Attributes:
        exit_code: Exit status that Typer associates with the parser error.
    """

    exit_code: int

    def show(self, file: TextIO | None = None) -> None:
        """Render the error to a text stream without exposing a traceback.

        Args:
            file: Destination stream, or ``None`` for the renderer's default.
        """


def run_typer(
    app: typer.Typer,
    *,
    arguments: Sequence[str] | None,
    handled_errors: tuple[type[Exception], ...],
    program_name: str,
) -> int:
    """Run a Typer app and preserve the repository's integer-returning API.

    Handle ``handled_errors`` first and print them to standard error with status
    ``1``. Render Typer parser errors through their ``show`` protocol and return
    their own exit codes. Convert a ``None`` command result to ``0`` and preserve
    an integer result, including ``bool`` values; re-raise other exceptions.

    Args:
        app: Typer application to dispatch.
        arguments: Explicit command-line arguments, or ``None`` to use
            ``sys.argv[1:]``.
        handled_errors: Exception classes whose instances become standard-error
            diagnostics with status ``1``.
        program_name: Program name passed to Typer and used in status-type errors.

    Returns:
        The command's status: ``0`` for a ``None`` result, the original integer
        result unchanged (including a runtime ``bool``), ``1`` for a handled
        exception, or the exit code supplied by a rendered parser error.

    Raises:
        TypeError: The Typer command returns a result other than ``None`` or an
            integer.
        Exception: An exception outside ``handled_errors`` is not renderable as a
            Typer parser error.
    """
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
