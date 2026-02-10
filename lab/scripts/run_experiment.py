#!/usr/bin/env python
"""
run_experiment.py
~~~~~~~~~~~~~~~~~
CLI entry-point: load config → create run → generate data → backtest → save.

Usage
-----
    python scripts/run_experiment.py --exp macro_equities \\
        --config experiments/macro_equities/configs/baseline.yaml
    # or via Make:
    make run EXP=macro_equities CONFIG=experiments/macro_equities/configs/baseline.yaml

Creates
-------
    runs/<run_id>/
        meta.json              — provenance (config hash, git commit, …)
        config.yaml            — copy of the config used
        returns.csv            — daily net returns
        gross_returns.csv      — daily gross returns
        weights.csv            — position weights at each rebalance
        turnover.csv           — portfolio turnover
        metrics.json           — summary performance metrics
        results.json           — metrics + key config fields (single artefact)
        figures/
            cumulative_returns.png
            drawdown.png
            turnover.png
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# Ensure the lab package is importable when running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import matplotlib

matplotlib.use("Agg")  # headless backend — no GUI needed

# Importing the strategies package triggers @register decorators
import lab.strategies.macro_equities  # noqa: F401
from lab.core.config import load_config, load_raw_config
from lab.core.logging import get_logger, setup_logging
from lab.core.registry import compute_config_hash, compute_results_hash, create_run
from lab.core.strategy_registry import get as get_strategy

log = get_logger("scripts.run_experiment")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an alpha-research experiment.")
    parser.add_argument(
        "--exp",
        type=str,
        required=True,
        help="Experiment family name, e.g. 'macro_equities'.",
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to experiment YAML config.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--toy-seed",
        type=int,
        default=42,
        help="RNG seed used when toy synthetic data is generated.",
    )
    args = parser.parse_args()

    setup_logging(level=args.log_level)

    # ── Load config ───────────────────────────────────────────────────────
    config_path = Path(args.config)
    raw_config = load_raw_config(config_path)
    config = load_config(config_path)
    log.info("Loaded config: %s (strategy=%s)", config.exp, config.strategy)

    # ── Resolve strategy ──────────────────────────────────────────────────
    try:
        strategy_fn = get_strategy(config.strategy)
    except KeyError as exc:
        log.error(str(exc))
        sys.exit(1)

    # ── Create run directory + meta.json ──────────────────────────────────
    rid, rdir = create_run(
        exp_name=args.exp,
        config_path=config_path,
        raw_config=raw_config,
    )
    log.info("Run id: %s → %s", rid, rdir)

    # Copy config into the run folder for reproducibility
    shutil.copy2(config_path, rdir / "config.yaml")

    # ── Load data ─────────────────────────────────────────────────────────
    from lab.data.loader import load_prices_or_make_toy

    prices = load_prices_or_make_toy(config, seed=args.toy_seed)
    log.info("  Prices: %d days × %d assets", *prices.shape)

    # ── Run backtest ──────────────────────────────────────────────────────
    from lab.backtest.daily_engine import run_daily_backtest

    result = run_daily_backtest(config, prices, strategy_fn)

    # ── Save CSV outputs ──────────────────────────────────────────────────
    result.returns.to_csv(rdir / "returns.csv", header=True)
    result.gross_returns.to_csv(rdir / "gross_returns.csv", header=True)
    if not result.weights.empty:
        result.weights.to_csv(rdir / "weights.csv")
    result.turnover.to_csv(rdir / "turnover.csv", header=True)
    log.info("CSVs saved.")

    # ── Compute & save metrics ────────────────────────────────────────────
    from lab.eval.metrics import summary

    metrics = summary(
        result.returns,
        turnover=result.turnover,
        gross_returns=result.gross_returns,
    )
    with open(rdir / "metrics.json", "w") as fh:
        json.dump({k: round(v, 6) for k, v in metrics.items()}, fh, indent=2)
    log.info("Metrics: %s", {k: f"{v:.4f}" for k, v in metrics.items()})

    # ── Save results.json (metrics + key config fields + hash) ────────
    rounded_metrics = {k: round(v, 6) for k, v in metrics.items()}
    config_hash = compute_config_hash(raw_config)
    # Deterministic hash: same config + same seed + same rounded metrics.
    results_hash = compute_results_hash(
        rounded_metrics,
        config_hash=config_hash,
        toy_seed=args.toy_seed,
    )

    results = {
        "metrics": rounded_metrics,
        "results_hash": results_hash,
        "config_hash": config_hash,
        "toy_seed": args.toy_seed,
        "config": {
            "exp": config.exp,
            "strategy": config.strategy,
            "universe": list(config.universe),
            "start_date": config.start_date,
            "end_date": config.end_date,
            "rebalance": config.rebalance,
            "signal": config.signal,
            "costs_bps": config.costs_bps,
            "initial_capital": config.initial_capital,
        },
        "run_id": rid,
    }
    with open(rdir / "results.json", "w") as fh:
        json.dump(results, fh, indent=2)
    log.info("results.json saved (results_hash=%s).", results_hash[:12])

    # ── Generate figures into runs/<run_id>/figures/ ──────────────────────
    from lab.eval.plots import cumulative_returns, drawdown, turnover_plot

    fig_dir = rdir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    fig1 = cumulative_returns(result.returns, title=f"{config.exp} — Cumulative Returns")
    fig1.savefig(fig_dir / "cumulative_returns.png", dpi=150, bbox_inches="tight")
    log.info("  Saved figures/cumulative_returns.png")

    fig2 = drawdown(result.returns, title=f"{config.exp} — Drawdown")
    fig2.savefig(fig_dir / "drawdown.png", dpi=150, bbox_inches="tight")
    log.info("  Saved figures/drawdown.png")

    fig3 = turnover_plot(result.turnover, title=f"{config.exp} — Turnover")
    fig3.savefig(fig_dir / "turnover.png", dpi=150, bbox_inches="tight")
    log.info("  Saved figures/turnover.png")

    # Close figures to free memory
    import matplotlib.pyplot as plt

    plt.close("all")

    # ── Auto-generate report.md in run folder ────────────────────────────
    from lab.eval.reports import save_report

    figure_filenames = [
        f"figures/{f}"
        for f in ["cumulative_returns.png", "drawdown.png", "turnover.png"]
        if (fig_dir / f.split("/")[-1]).exists()
    ]
    meta_path = rdir / "meta.json"
    meta = {}
    if meta_path.exists():
        with open(meta_path) as mf:
            meta = json.load(mf)
    save_report(
        config.exp,
        metrics=metrics,
        output_dir=rdir,
        figure_filenames=figure_filenames,
        meta=meta,
    )
    log.info("report.md saved.")

    log.info("✅ Run complete → %s", rdir)
    # Print the run_id so callers (e.g. Makefile) can capture it
    print(f"RUN_ID={rid}")


if __name__ == "__main__":
    main()
