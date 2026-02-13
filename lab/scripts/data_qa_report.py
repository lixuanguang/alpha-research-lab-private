#!/usr/bin/env python
"""Generate data QA report and anomaly tables for persisted datasets."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
from matplotlib import pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from lab.core.logging import get_logger, setup_logging
from lab.core.paths import data_dir
from lab.data.qa import QAThresholds, run_price_data_qa, write_qa_tables

log = get_logger("scripts.data_qa_report")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run data QA and write markdown/html report.")
    parser.add_argument("--max-missing-pct", type=float, default=5.0)
    parser.add_argument("--jump-multiple", type=float, default=50.0)
    parser.add_argument("--max-zero-volume-streak", type=int, default=5)
    parser.add_argument("--max-missing-trading-days", type=int, default=2)
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def _load_close() -> pd.DataFrame:
    preferred = data_dir() / "prices" / "close.parquet"
    legacy = data_dir() / "prices.parquet"
    if preferred.exists():
        return pd.read_parquet(preferred)
    if legacy.exists():
        return pd.read_parquet(legacy)
    raise FileNotFoundError(
        "No price artifact found. Run `make ingest_prices CONFIG=...` before running QA."
    )


def _load_latest_ohlcv() -> tuple[pd.DataFrame | None, Path | None]:
    raw_dir = data_dir() / "prices" / "raw"
    if not raw_dir.exists():
        return None, None
    files = sorted(raw_dir.glob("*_ohlcv.parquet"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None, None
    latest = files[-1]
    return pd.read_parquet(latest), latest


def _write_plots(*, close: pd.DataFrame, qa_dir: Path, tag: str) -> list[Path]:
    paths: list[Path] = []
    missing_pct = (close.isna().mean() * 100.0).sort_values(ascending=False)
    fig, ax = plt.subplots(figsize=(10, 4))
    missing_pct.plot(kind="bar", ax=ax)
    ax.set_title("Missingness by Ticker (%)")
    ax.set_ylabel("% NaN")
    ax.set_xlabel("Ticker")
    fig.tight_layout()
    p1 = qa_dir / f"qa_{tag}_missingness.png"
    fig.savefig(p1, dpi=150)
    plt.close(fig)
    paths.append(p1)

    returns = close.pct_change().replace([float("inf"), -float("inf")], pd.NA)
    max_abs = returns.abs().max().sort_values(ascending=False)
    fig, ax = plt.subplots(figsize=(10, 4))
    max_abs.plot(kind="bar", ax=ax)
    ax.set_title("Max Absolute Daily Return by Ticker")
    ax.set_ylabel("Max |return|")
    ax.set_xlabel("Ticker")
    fig.tight_layout()
    p2 = qa_dir / f"qa_{tag}_max_abs_return.png"
    fig.savefig(p2, dpi=150)
    plt.close(fig)
    paths.append(p2)
    return paths


def main() -> None:
    args = _parse_args()
    setup_logging(level=args.log_level)

    close = _load_close()
    ohlcv, ohlcv_path = _load_latest_ohlcv()

    result = run_price_data_qa(
        close,
        ohlcv=ohlcv,
        thresholds=QAThresholds(
            max_missing_pct=args.max_missing_pct,
            jump_multiple=args.jump_multiple,
            max_zero_volume_streak=args.max_zero_volume_streak,
            max_missing_trading_days=args.max_missing_trading_days,
        ),
    )

    today_tag = str(pd.Timestamp.utcnow().date())
    qa_dir = data_dir() / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = qa_dir / f"qa_{today_tag}_tables"
    table_paths = write_qa_tables(result, out_dir=tables_dir)
    plot_paths = _write_plots(close=close, qa_dir=qa_dir, tag=today_tag)

    lines = [
        f"# Data QA Report ({today_tag})",
        "",
        f"- Close shape: {close.shape[0]} rows × {close.shape[1]} tickers",
        f"- OHLCV source: `{ohlcv_path}`" if ohlcv_path is not None else "- OHLCV source: not found",
        f"- Status: {'PASS' if result.ok else 'FAIL'}",
        "",
        "## Failures",
    ]
    if result.failures:
        lines.extend([f"- {msg}" for msg in result.failures])
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Output Tables",
            *[f"- `{name}`: `{path}`" for name, path in table_paths.items()],
            "",
            "## Plots",
            *[f"- `{path}`" for path in plot_paths],
        ]
    )

    md_path = qa_dir / f"qa_{today_tag}.md"
    html_path = qa_dir / f"qa_{today_tag}.html"
    md_text = "\n".join(lines) + "\n"
    md_path.write_text(md_text)
    html_path.write_text(
        "<html><body><pre>" + md_text.replace("&", "&amp;").replace("<", "&lt;") + "</pre></body></html>"
    )

    log.info("QA markdown: %s", md_path)
    log.info("QA html: %s", html_path)

    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
