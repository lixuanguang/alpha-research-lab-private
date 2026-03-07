"""Shared output and context helpers for the research CLI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import click
import yaml

import alpha_core.config._merge as config_merge
import alpha_core.config.profiles as config_profiles
import alpha_core.research.run_context as run_context_mod
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
    if isinstance(output_dir, Path):
        return output_dir

    profile_name = (ctx.obj or {}).get("profile")
    if isinstance(profile_name, str) and storage_root == Path("data"):
        return config_profiles.get_profile(profile_name).storage_root
    return storage_root


def get_session_id(ctx: click.Context) -> str | None:
    """Return the optional session id attached at the root CLI level."""
    value = (ctx.obj or {}).get("session_id")
    return value if isinstance(value, str) else None


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


def emit_planned_outcome(
    ctx: click.Context,
    *,
    run_type: run_context_mod.RunType,
    payload: dict[str, Any],
) -> None:
    """Emit the shared plan-only payload for a research command."""
    emit_outcome(
        runtime_mod.plan_stage(
            run_type=run_type,
            payload=payload,
            session_id=get_session_id(ctx),
        ),
        get_output_format(ctx),
    )


__all__ = [
    "OutputFormat",
    "build_run_payload",
    "emit_outcome",
    "emit_planned_outcome",
    "get_output_format",
    "get_session_id",
    "load_config_reference",
    "resolve_storage_root",
]
