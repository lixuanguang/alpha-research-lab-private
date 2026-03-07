"""Shared output and context helpers for the research CLI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import click
import yaml

import alpha_core.config._merge as config_merge
import apps.research.runtime as runtime_mod

OutputFormat = Literal["text", "json"]


def get_output_format(ctx: click.Context) -> OutputFormat:
    """Return the output format stored by the root command group."""
    return "json" if (ctx.obj or {}).get("format") == "json" else "text"


def load_config_reference(config_path: Path) -> dict[str, str]:
    """Validate a YAML config override and return reproducible file metadata."""
    resolved_path = config_path.resolve()
    try:
        config_merge.load_yaml(resolved_path)
        digest = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise click.ClickException(
            f"Invalid research config override '{resolved_path}': {exc}"
        ) from exc
    return {"path": str(resolved_path), "sha256": digest}


def build_run_payload(ctx: click.Context, stage_payload: dict[str, Any]) -> dict[str, Any]:
    """Attach shared CLI metadata to a stage payload when present."""
    config_reference = (ctx.obj or {}).get("config")
    if not isinstance(config_reference, dict):
        return dict(stage_payload)
    return {
        "command": dict(stage_payload),
        "config_override": config_reference,
    }


def resolve_storage_root(ctx: click.Context, storage_root: Path) -> Path:
    """Resolve the effective storage root for a command invocation."""
    output_dir = (ctx.obj or {}).get("output_dir")
    return output_dir if isinstance(output_dir, Path) else storage_root


def emit_outcome(outcome: runtime_mod.ResearchStageOutcome, fmt: OutputFormat) -> None:
    """Write a :class:`~apps.research.runtime.ResearchStageOutcome` to stdout."""
    if fmt == "json":
        click.echo(
            json.dumps(
                {
                    "run_id": outcome.run_id,
                    "run_type": outcome.run_type,
                    "status": outcome.status,
                    "config_hash": outcome.config_hash,
                    "manifest_path": (
                        str(outcome.manifest_path) if outcome.manifest_path is not None else None
                    ),
                },
                indent=2,
            )
        )
        return
    click.echo(
        f"run_type={outcome.run_type} status={outcome.status} "
        f"run_id={outcome.run_id} config_hash={outcome.config_hash}"
    )
    if outcome.manifest_path is not None:
        click.echo(f"manifest={outcome.manifest_path}")


__all__ = [
    "OutputFormat",
    "build_run_payload",
    "emit_outcome",
    "get_output_format",
    "load_config_reference",
    "resolve_storage_root",
]
