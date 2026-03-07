"""catalog command group — query and manage the ExperimentCatalog from the CLI.

Commands
--------
``research catalog list``   List entries, optionally filtered by status.
``research catalog show``   Show a single entry by entry_id.
``research catalog add``    Manually add a candidate entry for a run.

Wiring
------
Use ``main.add_command(catalog_group)`` in ``apps/research/main.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import click

import alpha_core.research.experiment_catalog as catalog_mod
import apps.research.commands.common as cmd_common

_STATUS_CHOICES = click.Choice(["candidate", "needs_review", "approved_for_paper", "rejected"])


@click.group("catalog")
def catalog_group() -> None:
    """Query and manage the experiment catalog."""


# ---------------------------------------------------------------------------
# catalog list
# ---------------------------------------------------------------------------


@catalog_group.command("list")
@click.option(
    "--status",
    type=_STATUS_CHOICES,
    default=None,
    help="Filter by promotion status (all entries when omitted).",
)
@click.option(
    "--session-id",
    default=None,
    help="Filter entries belonging to a specific session.",
)
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for catalog artifacts.",
)
@click.pass_context
def catalog_list(
    ctx: click.Context,
    status: str | None,
    session_id: str | None,
    storage_root: Path,
) -> None:
    """List experiment catalog entries.

    Example:

    \b
        python -m apps.research.main catalog list --status candidate
        python -m apps.research.main catalog list --format json
    """
    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    fmt = cmd_common.get_output_format(ctx)

    if status is not None:
        entries = catalog_mod.list_by_status(resolved_root, status)  # type: ignore[arg-type]
    elif session_id is not None:
        entries = catalog_mod.list_by_session(resolved_root, session_id)
    else:
        entries = catalog_mod.list_all(resolved_root)

    if fmt == "json":
        click.echo(json.dumps([_entry_dict(e) for e in entries], indent=2))
        return

    if not entries:
        click.echo("No catalog entries found.")
        return

    for e in entries:
        click.echo(
            f"entry_id={e.entry_id} status={e.status} "
            f"run_id={e.run_id} strategy_id={e.strategy_id} "
            f"session_id={e.session_id} created={e.created_at_utc.isoformat()}"
        )


# ---------------------------------------------------------------------------
# catalog show
# ---------------------------------------------------------------------------


@catalog_group.command("show")
@click.argument("entry_id")
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for catalog artifacts.",
)
@click.pass_context
def catalog_show(
    ctx: click.Context,
    entry_id: str,
    storage_root: Path,
) -> None:
    """Show full details of a single catalog entry.

    Example:

    \b
        python -m apps.research.main catalog show <entry_id>
    """
    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    fmt = cmd_common.get_output_format(ctx)

    try:
        entry = catalog_mod.get_entry(resolved_root, entry_id)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    if fmt == "json":
        click.echo(json.dumps(_entry_dict(entry), indent=2))
        return

    click.echo(
        f"entry_id={entry.entry_id} status={entry.status} "
        f"run_id={entry.run_id} strategy_id={entry.strategy_id} "
        f"session_id={entry.session_id} reviewed_by={entry.reviewed_by} "
        f"reason={entry.reason} created={entry.created_at_utc.isoformat()}"
    )


# ---------------------------------------------------------------------------
# catalog add
# ---------------------------------------------------------------------------


@catalog_group.command("add")
@click.option("--run-id", required=True, help="Evaluate run id to register in the catalog.")
@click.option("--strategy-id", default=None, help="Strategy identifier.")
@click.option("--dataset-id", default=None, help="Gold dataset id used for this experiment.")
@click.option("--feature-set-version", default=None, help="Feature set version.")
@click.option("--notes", default=None, help="Free-text notes.")
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for catalog artifacts.",
)
@click.pass_context
def catalog_add(
    ctx: click.Context,
    run_id: str,
    strategy_id: str | None,
    dataset_id: str | None,
    feature_set_version: str | None,
    notes: str | None,
    storage_root: Path,
) -> None:
    """Add a new candidate entry to the experiment catalog.

    Example:

    \b
        python -m apps.research.main catalog add \\
            --run-id <evaluate_run_id> \\
            --strategy-id zscore_v1
    """
    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    fmt = cmd_common.get_output_format(ctx)
    session_id = cmd_common.get_session_id(ctx)

    try:
        entry = catalog_mod.add_entry(
            resolved_root,
            run_id=run_id,
            session_id=session_id,
            strategy_id=strategy_id,
            dataset_id=dataset_id,
            feature_set_version=feature_set_version,
            notes=notes,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if fmt == "json":
        click.echo(json.dumps(_entry_dict(entry), indent=2))
        return

    click.echo(f"Added catalog entry: entry_id={entry.entry_id} status={entry.status}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry_dict(entry: catalog_mod.CatalogEntry) -> dict[str, object]:
    return cast(dict[str, object], json.loads(entry.model_dump_json()))
