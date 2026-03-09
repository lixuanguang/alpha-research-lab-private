"""Research CLI commands aligned with the R1-R6 stage contract.

Governance commands (``session``, ``catalog``, ``promote``) are implemented in
LA-018 and wired here.  Use ``--session-id`` on the root group to attach run
manifests to a specific session.
"""

from __future__ import annotations

from pathlib import Path

import click

import apps.research.commands.backtest as backtest_cmd
import apps.research.commands.build_dataset as build_dataset_cmd
import apps.research.commands.build_features as build_features_cmd
import apps.research.commands.catalog as catalog_cmd
import apps.research.commands.common as cmd_common
import apps.research.commands.evaluate as evaluate_cmd
import apps.research.commands.listing as listing_cmd
import apps.research.commands.optimize as optimize_cmd
import apps.research.commands.promote as promote_cmd
import apps.research.commands.report as report_cmd
import apps.research.commands.session as session_cmd


@click.group()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format: human-readable text or machine-readable JSON.",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
    help="Global default storage root (overrides per-command --storage-root).",
)
@click.option(
    "--config",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to an optional YAML config override file used for validation and run hashing.",
)
@click.option(
    "--session-id",
    default=None,
    help="Optional research session id recorded in run manifests and session storage.",
)
@click.option(
    "--profile",
    type=click.Choice(["dev", "research", "ci", "paper", "live"]),
    default=None,
    help="Runtime profile (dev/research/ci/paper/live). Overrides log level and safety flags.",
)
@click.pass_context
def main(
    ctx: click.Context,
    output_format: str,
    output_dir: Path | None,
    config: Path | None,
    session_id: str | None,
    profile: str | None,
) -> None:
    """Run research-plane scaffolding commands."""
    ctx.ensure_object(dict)
    ctx.obj["format"] = output_format
    ctx.obj["output_dir"] = output_dir.resolve() if output_dir is not None else None
    ctx.obj["config"] = cmd_common.load_config_reference(config) if config is not None else None
    if session_id is not None:
        session_id = session_id.strip() or None
    ctx.obj["session_id"] = session_id
    ctx.obj["profile"] = profile


main.add_command(build_dataset_cmd.build_dataset_command)
main.add_command(build_features_cmd.build_features_command)
main.add_command(backtest_cmd.backtest_command)
main.add_command(evaluate_cmd.evaluate_command)
main.add_command(report_cmd.report_command)
main.add_command(optimize_cmd.optimize_command)
main.add_command(listing_cmd.list_datasets_command)
main.add_command(listing_cmd.list_features_command)
main.add_command(listing_cmd.list_backtests_command)
# LA-018: governance & promotion
main.add_command(session_cmd.session_group)
main.add_command(catalog_cmd.catalog_group)
main.add_command(promote_cmd.promote_command)


if __name__ == "__main__":
    main()
