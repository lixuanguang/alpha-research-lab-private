"""Shared output helpers and context utilities for research CLI commands.

Every research subcommand should:
1. Decorate with ``@click.pass_context`` so the group context is forwarded.
2. Call :func:`emit_outcome` (or :func:`emit_json` / :func:`emit_text`) using
   the format stored in ``ctx.obj["format"]`` by the root ``main`` group.
3. Raise :class:`click.ClickException` on validation failures so the runner
   exits non-zero with a structured error message.

Usage example::

    @main.command("my-cmd")
    @click.option("--foo", required=True)
    @click.pass_context
    def my_cmd(ctx: click.Context, foo: str) -> None:
        outcome = run_something(foo)
        emit_outcome(outcome, get_output_format(ctx))
"""

from __future__ import annotations

import json
from typing import Any, Literal

import click

import apps.research.runtime as runtime_mod

# Sentinel key used to store shared options in click's ctx.obj dict.
_CTX_KEY = "research"

OutputFormat = Literal["text", "json"]


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------


def get_output_format(ctx: click.Context) -> OutputFormat:
    """Return the output format stored by the root command group.

    Falls back to ``"text"`` when the context object is absent (e.g. when a
    command is invoked directly in tests without the group context).
    """
    obj: dict[str, Any] = ctx.obj or {}
    fmt = obj.get("format", "text")
    return "json" if fmt == "json" else "text"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def emit_outcome(outcome: runtime_mod.ResearchStageOutcome, fmt: OutputFormat) -> None:
    """Write a :class:`~apps.research.runtime.ResearchStageOutcome` to stdout.

    - ``"text"`` — human-readable key=value pairs (default)
    - ``"json"`` — machine-readable JSON object; parseable by downstream tools
    """
    if fmt == "json":
        data: dict[str, Any] = {
            "run_id": outcome.run_id,
            "run_type": outcome.run_type,
            "status": outcome.status,
            "config_hash": outcome.config_hash,
            "manifest_path": (
                str(outcome.manifest_path) if outcome.manifest_path is not None else None
            ),
        }
        click.echo(json.dumps(data, indent=2))
    else:
        click.echo(
            f"run_type={outcome.run_type} status={outcome.status} "
            f"run_id={outcome.run_id} config_hash={outcome.config_hash}"
        )
        if outcome.manifest_path is not None:
            click.echo(f"manifest={outcome.manifest_path}")


__all__ = ["OutputFormat", "_CTX_KEY", "emit_outcome", "get_output_format"]
