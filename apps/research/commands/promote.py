"""promote command — run promotion gates and update experiment catalog status.

Gate logic (applied when target status is ``approved_for_paper``)
-----------------------------------------------------------------
1. ``sharpe_ratio``  >= ``--min-sharpe``    (default 1.0)
2. ``max_drawdown``  >= ``--max-drawdown``  (default -0.20, i.e. ≤ 20% drawdown)
3. ``trade_count``   >= ``--min-trades``    (default 10)

All thresholds are configurable via CLI flags.  Pass ``--force`` to skip gate
checks (e.g. for status changes other than ``approved_for_paper``, or when you
explicitly want to override failed gates with a documented reason).

Wiring
------
Use ``main.add_command(promote_command)`` in ``apps/research/main.py``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import click

import alpha_core.research.artifact_store as artifact_store_mod
import alpha_core.research.evaluate_runner as evaluate_runner_mod
import alpha_core.research.experiment_catalog as catalog_mod
import apps.research.commands.common as cmd_common

# ---------------------------------------------------------------------------
# Gate constants
# ---------------------------------------------------------------------------

_DEFAULT_MIN_SHARPE: float = 1.0
_DEFAULT_MAX_DRAWDOWN: float = -0.20  # evaluated manifest stores drawdown as a negative fraction
_DEFAULT_MIN_TRADES: int = 10


# ---------------------------------------------------------------------------
# Gate models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromotionGateConfig:
    """Thresholds that must be satisfied for ``approved_for_paper`` promotion."""

    min_sharpe: float = _DEFAULT_MIN_SHARPE
    max_drawdown: float = _DEFAULT_MAX_DRAWDOWN
    min_trades: int = _DEFAULT_MIN_TRADES


@dataclass
class GateViolation:
    metric: str
    required: float
    actual: float
    description: str


@dataclass
class GateResult:
    passed: bool
    violations: list[GateViolation] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------


def evaluate_gates(
    metrics: dict[str, float],
    gate_cfg: PromotionGateConfig,
) -> GateResult:
    """Check promotion-gate thresholds against evaluate-run metrics.

    Parameters
    ----------
    metrics:
        ``dict`` from an :class:`~alpha_core.research.evaluate_runner.EvaluateManifest`.
    gate_cfg:
        Thresholds to enforce.

    Returns
    -------
    GateResult
        Contains ``passed`` flag, list of violations, and the metric snapshot.
    """
    violations: list[GateViolation] = []

    sharpe = metrics.get("sharpe_ratio", 0.0)
    if sharpe < gate_cfg.min_sharpe:
        violations.append(
            GateViolation(
                metric="sharpe_ratio",
                required=gate_cfg.min_sharpe,
                actual=sharpe,
                description=f"sharpe_ratio {sharpe:.4f} < required {gate_cfg.min_sharpe:.4f}",
            )
        )

    drawdown = metrics.get("max_drawdown", 0.0)
    if drawdown < gate_cfg.max_drawdown:
        violations.append(
            GateViolation(
                metric="max_drawdown",
                required=gate_cfg.max_drawdown,
                actual=drawdown,
                description=(
                    f"max_drawdown {drawdown:.4f} < floor {gate_cfg.max_drawdown:.4f} "
                    f"(too large a drawdown)"
                ),
            )
        )

    trade_count = metrics.get("trade_count", 0.0)
    if trade_count < gate_cfg.min_trades:
        violations.append(
            GateViolation(
                metric="trade_count",
                required=float(gate_cfg.min_trades),
                actual=trade_count,
                description=(
                    f"trade_count {int(trade_count)} < required minimum {gate_cfg.min_trades}"
                ),
            )
        )

    return GateResult(
        passed=len(violations) == 0,
        violations=violations,
        metrics=dict(metrics),
    )


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command("promote")
@click.option("--entry-id", required=True, help="Catalog entry id to promote.")
@click.option(
    "--target-status",
    type=click.Choice(["needs_review", "approved_for_paper", "rejected"]),
    required=True,
    help="Target promotion status.",
)
@click.option(
    "--reviewed-by",
    default=None,
    help="Reviewer identifier (required when target is approved_for_paper or rejected).",
)
@click.option("--reason", default=None, help="Justification for the promotion decision.")
@click.option("--notes", default=None, help="Optional free-text notes appended to the entry.")
@click.option(
    "--min-sharpe",
    type=float,
    default=_DEFAULT_MIN_SHARPE,
    show_default=True,
    help="Minimum Sharpe ratio required for approved_for_paper promotion.",
)
@click.option(
    "--max-drawdown",
    type=float,
    default=_DEFAULT_MAX_DRAWDOWN,
    show_default=True,
    help=(
        "Maximum allowed drawdown (negative fraction) for approved_for_paper promotion. "
        "E.g. -0.20 means max 20%% drawdown."
    ),
)
@click.option(
    "--min-trades",
    type=int,
    default=_DEFAULT_MIN_TRADES,
    show_default=True,
    help="Minimum trade count required for approved_for_paper promotion.",
)
@click.option(
    "--force/--no-force",
    default=False,
    show_default=True,
    help="Skip promotion gate checks (use with explicit --reason).",
)
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for artifacts and catalog.",
)
@click.pass_context
def promote_command(
    ctx: click.Context,
    entry_id: str,
    target_status: str,
    reviewed_by: str | None,
    reason: str | None,
    notes: str | None,
    min_sharpe: float,
    max_drawdown: float,
    min_trades: int,
    force: bool,
    storage_root: Path,
) -> None:
    """Promote or reject a catalog experiment entry.

    Promotion to ``approved_for_paper`` enforces objective/risk/trade-count gates
    unless ``--force`` is used.  ``needs_review`` status changes never block.

    Examples:

    \b
        # Stage an entry for review
        python -m apps.research.main promote \\
            --entry-id <entry_id> \\
            --target-status needs_review

    \b
        # Promote with gates
        python -m apps.research.main promote \\
            --entry-id <entry_id> \\
            --target-status approved_for_paper \\
            --reviewed-by alice \\
            --reason "Sharpe 1.8, DD 8%"

    \b
        # Force promotion skipping gates
        python -m apps.research.main promote \\
            --entry-id <entry_id> \\
            --target-status approved_for_paper \\
            --reviewed-by alice \\
            --reason "Override: early candidate approved by team" \\
            --force

    \b
        # Reject an entry
        python -m apps.research.main promote \\
            --entry-id <entry_id> \\
            --target-status rejected \\
            --reviewed-by bob \\
            --reason "Below Sharpe threshold after re-evaluation"
    """
    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    fmt = cmd_common.get_output_format(ctx)

    # Require reviewer for final decisions
    if target_status in ("approved_for_paper", "rejected") and not reviewed_by:
        raise click.UsageError(
            f"--reviewed-by is required when target status is '{target_status}'."
        )

    # Load entry
    try:
        entry = catalog_mod.get_entry(resolved_root, entry_id)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    gate_result: GateResult | None = None

    # Run promotion gates only when targeting approved_for_paper and not forced
    if target_status == "approved_for_paper" and not force:
        gate_cfg = PromotionGateConfig(
            min_sharpe=min_sharpe,
            max_drawdown=max_drawdown,
            min_trades=min_trades,
        )
        metrics = _load_metrics(resolved_root, entry.run_id)
        gate_result = evaluate_gates(metrics, gate_cfg)

        if not gate_result.passed:
            _emit_gate_failure(gate_result, entry_id, fmt)
            sys.exit(1)

    # Update catalog
    try:
        if entry.status == "candidate" and target_status in {"approved_for_paper", "rejected"}:
            catalog_mod.update_status(
                resolved_root,
                entry_id,
                status="needs_review",
            )
        updated = catalog_mod.update_status(
            resolved_root,
            entry_id,
            status=target_status,  # type: ignore[arg-type]
            reviewed_by=reviewed_by,
            reason=reason,
            notes=notes,
        )
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    _emit_promote_outcome(updated, gate_result, fmt)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_metrics(storage_root: Path, run_id: str) -> dict[str, float]:
    """Load evaluate metrics from the run's evaluate_manifest.json artifact.

    Falls back to an empty dict if the artifact is absent so callers can
    still check evaluate-less runs (gate will fail unless --force is used).
    """
    store = artifact_store_mod.FilesystemArtifactStore(storage_root)
    try:
        path = store.path_for(run_id, "evaluate_manifest.json")
        manifest = evaluate_runner_mod.EvaluateManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        return dict(manifest.metrics)
    except artifact_store_mod.ArtifactNotFoundError:
        return {}


def _emit_gate_failure(
    gate_result: GateResult,
    entry_id: str,
    fmt: cmd_common.OutputFormat,
) -> None:
    if fmt == "json":
        click.echo(
            json.dumps(
                {
                    "status": "gate_failed",
                    "entry_id": entry_id,
                    "violations": [
                        {
                            "metric": v.metric,
                            "required": v.required,
                            "actual": v.actual,
                            "description": v.description,
                        }
                        for v in gate_result.violations
                    ],
                    "metrics": gate_result.metrics,
                },
                indent=2,
            ),
            err=True,
        )
        return

    click.echo(
        f"GATE FAILED for entry_id={entry_id} — promotion blocked.",
        err=True,
    )
    for v in gate_result.violations:
        click.echo(f"  • {v.description}", err=True)


def _emit_promote_outcome(
    entry: catalog_mod.CatalogEntry,
    gate_result: GateResult | None,
    fmt: cmd_common.OutputFormat,
) -> None:
    payload: dict[str, object] = json.loads(entry.model_dump_json())
    if gate_result is not None:
        payload["gate"] = {"passed": gate_result.passed, "metrics": gate_result.metrics}

    if fmt == "json":
        click.echo(json.dumps(payload, indent=2))
        return

    click.echo(
        f"entry_id={entry.entry_id} status={entry.status} "
        f"reviewed_by={entry.reviewed_by} reason={entry.reason}"
    )
    if gate_result is not None:
        click.echo(
            "gate=passed metrics="
            + ", ".join(f"{k}={v:.4f}" for k, v in gate_result.metrics.items())
        )
