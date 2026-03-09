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
import alpha_core.research.artifact_store as artifact_store_mod


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

    def __init__(
        self,
        storage_root: Path,
        store: artifact_store_mod.FilesystemArtifactStore | None = None,
    ) -> None:
        self._root = Path(storage_root)
        self._store = (
            store if store is not None else artifact_store_mod.FilesystemArtifactStore(self._root)
        )

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #

    def write(self, report: evaluator_mod.EvaluationReport, run_id: str) -> Path:
        """Persist an :class:`EvaluationReport` and return the ``report.json`` path.

        Creates::

            {storage_root}/runs/{run_id}/stage_outputs/report.json
        """
        self._store.put(
            run_id,
            "report.json",
            report.model_dump_json(indent=2).encode("utf-8"),
            overwrite=True,
        )
        return self._store.path_for(run_id, "report.json")

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
        try:
            payload = self._store.get(run_id, "report.json").decode("utf-8")
        except artifact_store_mod.ArtifactNotFoundError as exc:
            raise ReportNotFoundError(f"report.json not found for run_id={run_id!r}") from exc
        return evaluator_mod.EvaluationReport.model_validate_json(payload)

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
            if self._store.exists(run_dir.name, "report.json"):
                result.append(run_dir.name)
        return result


__all__ = ["ReportNotFoundError", "ReportWriter"]
