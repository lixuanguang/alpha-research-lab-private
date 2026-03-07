"""session command group — manage ResearchSession lifecycle from the CLI.

Commands
--------
``research session start``   Create a new session or echo an existing one.
``research session status``  Show details of a session by id.
``research session list``    List all sessions.

Wiring
------
Use ``main.add_command(session_group)`` in ``apps/research/main.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import click

import alpha_core.research.session as session_mod
import apps.research.commands.common as cmd_common


@click.group("session")
def session_group() -> None:
    """Manage research sessions (groupings of related pipeline runs)."""


# ---------------------------------------------------------------------------
# session start
# ---------------------------------------------------------------------------


@session_group.command("start")
@click.option("--strategy-id", default=None, help="Strategy identifier to anchor this session.")
@click.option("--dataset-id", default=None, help="Gold dataset id used in this session.")
@click.option(
    "--feature-set-version", default=None, help="Feature set version used in this session."
)
@click.option("--notes", default=None, help="Free-text researcher notes.")
@click.option(
    "--session-id",
    default=None,
    help="Explicit session id to use (auto-generated hex UUID when omitted).",
)
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for session artifacts.",
)
@click.pass_context
def session_start(
    ctx: click.Context,
    strategy_id: str | None,
    dataset_id: str | None,
    feature_set_version: str | None,
    notes: str | None,
    session_id: str | None,
    storage_root: Path,
) -> None:
    """Create a new research session (or return an existing one when --session-id matches).

    Example:

    \b
        python -m apps.research.main session start \\
            --strategy-id zscore_v1 \\
            --notes "Initial sweep"
    """
    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    fmt = cmd_common.get_output_format(ctx)

    try:
        if session_id:
            sess = session_mod.ensure_session(resolved_root, session_id)
        else:
            sess = session_mod.create_session(
                resolved_root,
                strategy_id=strategy_id,
                dataset_id=dataset_id,
                feature_set_version=feature_set_version,
                notes=notes,
            )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    _emit_session(sess, fmt)


# ---------------------------------------------------------------------------
# session status
# ---------------------------------------------------------------------------


@session_group.command("status")
@click.argument("session_id")
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for session artifacts.",
)
@click.pass_context
def session_status(
    ctx: click.Context,
    session_id: str,
    storage_root: Path,
) -> None:
    """Show details of a research session.

    Example:

    \b
        python -m apps.research.main session status <session_id>
    """
    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    fmt = cmd_common.get_output_format(ctx)

    try:
        sess = session_mod.load_session(resolved_root, session_id)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    _emit_session(sess, fmt)


# ---------------------------------------------------------------------------
# session list
# ---------------------------------------------------------------------------


@session_group.command("list")
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for session artifacts.",
)
@click.pass_context
def session_list(
    ctx: click.Context,
    storage_root: Path,
) -> None:
    """List all research sessions.

    Example:

    \b
        python -m apps.research.main session list
    """
    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    fmt = cmd_common.get_output_format(ctx)

    sessions = session_mod.list_sessions(resolved_root)

    if fmt == "json":
        click.echo(
            json.dumps(
                [_session_dict(s) for s in sessions],
                indent=2,
            )
        )
        return

    if not sessions:
        click.echo("No sessions found.")
        return

    for sess in sessions:
        click.echo(
            f"session_id={sess.session_id} "
            f"strategy_id={sess.strategy_id} "
            f"run_count={len(sess.run_ids)} "
            f"created={sess.created_at_utc.isoformat()}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_dict(sess: session_mod.ResearchSession) -> dict[str, object]:
    return cast(dict[str, object], json.loads(sess.model_dump_json()))


def _emit_session(sess: session_mod.ResearchSession, fmt: cmd_common.OutputFormat) -> None:
    if fmt == "json":
        click.echo(json.dumps(_session_dict(sess), indent=2))
        return
    click.echo(
        f"session_id={sess.session_id} "
        f"strategy_id={sess.strategy_id} "
        f"run_count={len(sess.run_ids)} "
        f"created={sess.created_at_utc.isoformat()}"
    )
