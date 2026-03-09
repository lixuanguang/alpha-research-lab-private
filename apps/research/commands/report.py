"""report command — renders a deterministic summary from an evaluation run.

The report command reads the canonical ``report.json`` and evaluate manifest
artifacts from a completed evaluate run and produces a structured output
(JSON or Markdown).

Wiring
------
Use ``main.add_command(report_command)`` in ``apps/research/main.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.artifact_store as artifact_store_mod
import alpha_core.research.evaluate_runner as evaluate_runner_mod
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
import apps.research.commands.common as cmd_common
import apps.research.reporting.writer as report_writer_mod


class ReportError(RuntimeError):
    """Raised when the report cannot be rendered (e.g. missing evaluate artifacts)."""


@click.command("report")
@click.option("--evaluation-run-id", required=True, help="Evaluation run id to report on.")
@click.option(
    "--report-format",
    "report_format",
    type=click.Choice(["json", "markdown"]),
    default="json",
    show_default=True,
    help="Rendered report format.",
)
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for run artifacts.",
)
@click.option(
    "--execute/--plan-only",
    default=False,
    show_default=True,
    help="Persist report artifact or only emit a validated execution plan.",
)
@click.pass_context
def report_command(
    ctx: click.Context,
    evaluation_run_id: str,
    report_format: str,
    storage_root: Path,
    execute: bool,
) -> None:
    """Plan or render a summary report from a completed evaluation run.

    Example:

    \b
        python -m apps.research.main report \\
            --evaluation-run-id <evaluate_run_id> \\
            --report-format json \\
            --execute
    """
    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    payload = cmd_common.build_run_payload(
        ctx,
        {
            "evaluation_run_id": evaluation_run_id,
            "report_format": report_format,
        },
    )

    if not execute:
        cmd_common.emit_planned_outcome(
            ctx,
            run_type="report",
            payload=payload,
        )
        return

    fmt = cmd_common.get_output_format(ctx)
    try:
        report_payload = _build_report(resolved_root, evaluation_run_id)
    except ReportError as exc:
        raise click.ClickException(str(exc)) from exc
    report_payload["report_format"] = report_format

    # Persist the report artifact under a new report run.
    run_context = run_context_mod.make_run_context(
        "report",
        config_payload=payload,
        session_id=cmd_common.get_session_id(ctx),
    )

    report_key = "rendered_report.json" if report_format == "json" else "report.md"
    report_path = artifact_paths.artifact_key_path(
        resolved_root,
        run_context.run_id,
        report_key,
    )
    report_text = (
        json.dumps(report_payload, indent=2, sort_keys=True)
        if report_format == "json"
        else _render_markdown(report_payload)
    )
    store = artifact_store_mod.FilesystemArtifactStore(resolved_root)
    store.put(run_context.run_id, report_key, report_text.encode("utf-8"))
    report_path = store.path_for(run_context.run_id, report_key)

    completed_context = run_context_mod.close_run_context(run_context)
    artifact_map: dict[str, str] = {
        "report": str(report_path),
        "evaluation_run_id": evaluation_run_id,
        "report_format": report_format,
    }
    manifest_mod.persist_run_record(
        storage_root=resolved_root,
        run_context=completed_context,
        config_payload=payload,
        artifacts=artifact_map,
        parent_run_id=evaluation_run_id,
    )

    cmd_common.emit_materialized_summary(
        storage_root=resolved_root,
        run_id=run_context.run_id,
        extra={
            "evaluation_run_id": report_payload["evaluation_run_id"],
            "metrics_profile": report_payload["metrics_profile"],
            "report_format": report_payload["report_format"],
            "report_path": str(report_path),
            "summary": report_payload.get("summary", {}),
        },
        fmt=fmt,
    )


# ---------------------------------------------------------------------------
# Report building helpers
# ---------------------------------------------------------------------------


def _build_report(
    storage_root: Path,
    evaluation_run_id: str,
) -> dict[str, Any]:
    """Load the persisted EvaluationReport and build the deterministic report payload."""
    evaluate_manifest = _load_evaluate_manifest(storage_root, evaluation_run_id)
    try:
        report = report_writer_mod.ReportWriter(storage_root).load(evaluation_run_id)
    except report_writer_mod.ReportNotFoundError as exc:
        raise ReportError(
            f"report.json not found for evaluation run '{evaluation_run_id}'. "
            "Re-run the evaluate command."
        ) from exc

    return {
        "evaluation_run_id": evaluation_run_id,
        "metrics_profile": evaluate_manifest.metrics_profile,
        "metrics": evaluate_manifest.metrics,
        "summary": _summarize(evaluate_manifest.metrics),
        "report": report.model_dump(mode="json"),
    }


def _load_evaluate_manifest(
    storage_root: Path,
    evaluation_run_id: str,
) -> evaluate_runner_mod.EvaluateManifest:
    manifest_path = artifact_paths.artifact_key_path(
        storage_root,
        evaluation_run_id,
        "evaluate_manifest.json",
    )
    if not manifest_path.exists():
        run_manifest_path = artifact_paths.run_manifest_path(storage_root, evaluation_run_id)
        if not run_manifest_path.exists():
            raise ReportError(
                f"Evaluation run '{evaluation_run_id}' not found at '{storage_root}'. "
                "Ensure the evaluate command completed successfully."
            )
        run_manifest = manifest_mod.read_run_manifest(run_manifest_path)
        evaluate_manifest_artifact = run_manifest.artifacts.get("evaluate_manifest")
        if not isinstance(evaluate_manifest_artifact, str):
            raise ReportError(
                f"Evaluation run '{evaluation_run_id}' manifest is missing "
                "'evaluate_manifest' artifact. Re-run the evaluate command."
            )
        resolved_manifest_path = artifact_paths.resolve_registered_artifact_path(
            storage_root,
            evaluation_run_id,
            evaluate_manifest_artifact,
        )
        if resolved_manifest_path is None:
            raise ReportError(
                f"Evaluation run '{evaluation_run_id}' manifest references an invalid "
                "evaluate_manifest artifact."
            )
        manifest_path = resolved_manifest_path

    try:
        return evaluate_runner_mod.EvaluateManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise ReportError(
            f"Evaluation run '{evaluation_run_id}' has an invalid evaluate manifest: {exc}."
        ) from exc


def _summarize(metrics: dict[str, float]) -> dict[str, str]:
    """Return human-readable string representations of key metrics."""
    out: dict[str, str] = {}
    if "total_return" in metrics:
        out["total_return"] = f"{metrics['total_return'] * 100:.2f}%"
    if "sharpe_ratio" in metrics:
        out["sharpe_ratio"] = f"{metrics['sharpe_ratio']:.2f}"
    if "max_drawdown" in metrics:
        out["max_drawdown"] = f"{metrics['max_drawdown'] * 100:.2f}%"
    if "win_rate" in metrics:
        out["win_rate"] = f"{metrics['win_rate'] * 100:.1f}%"
    if "trade_count" in metrics:
        out["trade_count"] = str(int(metrics["trade_count"]))
    return out


def _render_markdown(payload: dict[str, Any]) -> str:
    """Render a simple Markdown metrics table."""
    lines = [
        "# Research Report",
        "",
        f"**Evaluation run:** `{payload['evaluation_run_id']}`  ",
        f"**Metrics profile:** `{payload['metrics_profile']}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
    ]
    summary: dict[str, str] = payload.get("summary", {})
    for key, value in summary.items():
        lines.append(f"| {key} | {value} |")

    lines += ["", "## All Metrics", "", "| Metric | Value |", "|--------|-------|"]
    for key, value in payload.get("metrics", {}).items():
        lines.append(f"| {key} | {value} |")
    lines.append("")
    return "\n".join(lines)


__all__ = ["ReportError", "report_command"]
