"""ReportWriter — persists canonical EvaluationReport artifacts to the run store.

Layout written under ``{storage_root}/runs/{evaluate_run_id}/stage_outputs/``::

    report.json        # Full EvaluationReport JSON

Metric-profile artifacts belong to
:class:`~alpha_core.research.evaluate_runner.EvaluateRunner`. The ReportWriter
owns only the canonical structured evaluation report so that run-scoped report
artifacts do not compete for the same filenames.

Usage::

    writer = ReportWriter(storage_root=Path("data"))
    path = writer.write(report, run_id="abc123")
    loaded = writer.load("abc123")
    ids = writer.list_reports()
"""

from __future__ import annotations

from pathlib import Path

import alpha_core.evaluation.evaluator as evaluator_mod


class ReportNotFoundError(KeyError):
    """Raised when the requested report does not exist in the store."""


class ReportWriter:
    """Writes and loads :class:`~alpha_core.evaluation.evaluator.EvaluationReport` artifacts.

    All artifacts are stored under the canonical run-artifact path::

        {storage_root}/runs/{run_id}/stage_outputs/

    Parameters
    ----------
    storage_root:
        Root of the artifact tree (e.g. ``Path("data")``).
    """

    def __init__(self, storage_root: Path) -> None:
        self._root = Path(storage_root)

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #

    def write(self, report: evaluator_mod.EvaluationReport, run_id: str) -> Path:
        """Persist an :class:`EvaluationReport` and return the ``report.json`` path.

        Creates::

            {storage_root}/runs/{run_id}/stage_outputs/report.json
        """
        out_dir = self._stage_outputs(run_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        report_path = out_dir / "report.json"
        self._atomic_write(report_path, report.model_dump_json(indent=2))
        return report_path

    # ------------------------------------------------------------------ #
    # Load
    # ------------------------------------------------------------------ #

    def load(self, run_id: str) -> evaluator_mod.EvaluationReport:
        """Load an :class:`EvaluationReport` from disk.

        Parameters
        ----------
        run_id:
            The run ID under which the report was written.

        Raises
        ------
        ReportNotFoundError
            If ``report.json`` does not exist for *run_id*.
        """
        report_path = self._stage_outputs(run_id) / "report.json"
        if not report_path.exists():
            raise ReportNotFoundError(
                f"report.json not found for run_id={run_id!r} (looked in {report_path})"
            )
        return evaluator_mod.EvaluationReport.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )

    # ------------------------------------------------------------------ #
    # List
    # ------------------------------------------------------------------ #

    def list_reports(self) -> list[str]:
        """Return run IDs that have a persisted ``report.json``.

        Returns IDs in filesystem-sorted order.
        """
        runs_dir = self._root / "runs"
        if not runs_dir.exists():
            return []
        result = []
        for run_dir in sorted(runs_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            if (run_dir / "stage_outputs" / "report.json").exists():
                result.append(run_dir.name)
        return result

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _stage_outputs(self, run_id: str) -> Path:
        return self._root / "runs" / run_id / "stage_outputs"

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)


__all__ = ["ReportNotFoundError", "ReportWriter"]
