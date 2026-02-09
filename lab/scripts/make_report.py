#!/usr/bin/env python
"""
make_report.py
~~~~~~~~~~~~~~
Generate a performance report from a completed experiment run.

Usage
-----
    python scripts/make_report.py --run_id 20260209_143022_a1b2c3
    # or via Make:
    make report RUN=20260209_143022_a1b2c3

Looks for the run folder under ``runs/<run_id>`` (or ``LAB_RUNS_ROOT/<run_id>``)
and generates a Markdown report + any missing figures.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import matplotlib

matplotlib.use("Agg")

from lab.core.logging import get_logger, setup_logging
from lab.core.paths import runs_root

log = get_logger("scripts.make_report")


def _find_run(run_id: str) -> Path | None:
    """Search ``runs/<run_id>`` (respects LAB_RUNS_ROOT)."""
    candidate = runs_root() / run_id
    if candidate.is_dir():
        return candidate
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate experiment report from a run.")
    parser.add_argument(
        "--run_id",
        type=str,
        required=True,
        help="Run identifier (folder name under runs/).",
    )
    args = parser.parse_args()

    setup_logging()

    # ── Locate run folder ─────────────────────────────────────────────────
    rdir = _find_run(args.run_id)
    if rdir is None:
        log.error("Run '%s' not found under %s", args.run_id, runs_root())
        sys.exit(1)

    log.info("Found run → %s", rdir)

    returns_path = rdir / "returns.csv"
    if not returns_path.exists():
        log.error("No returns.csv in %s — was the experiment run successfully?", rdir)
        sys.exit(1)

    import pandas as pd

    returns = pd.read_csv(returns_path, index_col=0, parse_dates=True).squeeze("columns")

    # ── Optionally load gross_returns and turnover ────────────────────────
    gross_path = rdir / "gross_returns.csv"
    gross_returns: pd.Series | None = None
    if gross_path.exists():
        gross_returns = pd.read_csv(gross_path, index_col=0, parse_dates=True).squeeze("columns")

    turnover_path = rdir / "turnover.csv"
    turnover: pd.Series | None = None
    if turnover_path.exists():
        turnover = pd.read_csv(turnover_path, index_col=0, parse_dates=True).squeeze("columns")

    # ── Load or compute metrics ───────────────────────────────────────────
    metrics_path = rdir / "metrics.json"
    if metrics_path.exists():
        with open(metrics_path) as fh:
            metrics: dict[str, float] = json.load(fh)
    else:
        from lab.eval.metrics import summary

        metrics = summary(returns, turnover=turnover, gross_returns=gross_returns)

    # ── Load meta.json if present ─────────────────────────────────────────
    meta_path = rdir / "meta.json"
    meta: dict = {}
    if meta_path.exists():
        with open(meta_path) as fh:
            meta = json.load(fh)

    # ── Resolve experiment name ───────────────────────────────────────────
    name = meta.get("exp_name", args.run_id)
    config_path = rdir / "config.yaml"
    if config_path.exists():
        import yaml

        with open(config_path) as fh:
            cfg = yaml.safe_load(fh) or {}
        name = cfg.get("exp", name)

    # ── Generate any missing figures into figures/ subdir ──────────────────
    fig_dir = rdir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    import matplotlib.pyplot as plt

    from lab.eval.plots import cumulative_returns, drawdown, turnover_plot

    if not (fig_dir / "cumulative_returns.png").exists():
        fig = cumulative_returns(returns, title=f"{name} — Cumulative Returns")
        fig.savefig(fig_dir / "cumulative_returns.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        log.info("Generated missing figures/cumulative_returns.png")

    if not (fig_dir / "drawdown.png").exists():
        fig = drawdown(returns, title=f"{name} — Drawdown")
        fig.savefig(fig_dir / "drawdown.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        log.info("Generated missing figures/drawdown.png")

    if turnover is not None and not (fig_dir / "turnover.png").exists():
        fig = turnover_plot(turnover, title=f"{name} — Turnover")
        fig.savefig(fig_dir / "turnover.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        log.info("Generated missing figures/turnover.png")

    # ── Build figure filename list (relative to run dir) ──────────────────
    figure_filenames: list[str] = []
    for fname in ["cumulative_returns.png", "drawdown.png", "turnover.png"]:
        if (fig_dir / fname).exists():
            figure_filenames.append(f"figures/{fname}")

    # ── Build & write Markdown report ─────────────────────────────────────
    from lab.eval.reports import save_report

    report_path = save_report(
        name,
        metrics=metrics,
        output_dir=rdir,
        figure_filenames=figure_filenames,
        meta=meta,
    )
    log.info("Report written → %s", report_path)

    # Print to stdout
    print(report_path.read_text())


if __name__ == "__main__":
    main()
