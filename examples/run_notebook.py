"""Execute a local research notebook and preserve each attempt separately."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

# third party library imports
import nbformat
from jupyter_client.kernelspec import KernelSpecManager
from jupyter_client.manager import KernelManager
from nbclient import NotebookClient


class _Arguments(argparse.Namespace):
    """Type the runner's command-line selection."""

    notebook: Path
    repeat: int
    kernel_python: Path


class NotebookDocument:
    """Read, reset, annotate and write research notebooks through nbformat."""

    @staticmethod
    def read(path: Path) -> nbformat.NotebookNode:
        """Read a notebook as format version 4.

        Args:
            path: Existing ``.ipynb`` file.

        Returns:
            The parsed notebook.
        """
        return nbformat.read(path, as_version=4)

    @staticmethod
    def source_digest(notebook: nbformat.NotebookNode) -> str:
        """Hash the notebook's cell types and sources, ignoring outputs and metadata.

        Args:
            notebook: Parsed notebook.

        Returns:
            Lowercase SHA-256 of the canonical cell-source JSON.
        """
        cells: list[tuple[str, str]] = [(cell.cell_type, cell.source) for cell in notebook.cells]
        source_bytes = json.dumps(cells, ensure_ascii=False, separators=(",", ":")).encode()
        return hashlib.sha256(source_bytes).hexdigest()

    @staticmethod
    def fresh_copy(source: nbformat.NotebookNode) -> nbformat.NotebookNode:
        """Copy a notebook with every code cell's execution count and outputs cleared.

        Args:
            source: Notebook to copy; it is not modified.

        Returns:
            An independent copy ready for a fresh execution.
        """
        notebook = nbformat.reads(nbformat.writes(source), as_version=4)
        for cell in notebook.cells:
            if cell.cell_type == "code":
                cell.execution_count = None
                cell.outputs = []
        return notebook

    @staticmethod
    def write_new(notebook: nbformat.NotebookNode, path: Path) -> None:
        """Write a notebook to a path that must not exist yet.

        Args:
            notebook: Notebook to retain.
            path: New file path.
        """
        with path.open("x", encoding="utf-8") as output:
            nbformat.write(notebook, output)

    @staticmethod
    def write(notebook: nbformat.NotebookNode, path: Path) -> None:
        """Write a notebook over an existing path.

        Args:
            notebook: Notebook to write.
            path: File path to replace.
        """
        nbformat.write(notebook, path)


class NotebookExecution:
    """Run notebook copies in fresh kernels of one explicit Python interpreter."""

    _KERNEL_NAME = "p1-example"

    def __init__(self, kernel_root: Path, kernel_python: Path, working_directory: Path) -> None:
        """Write the kernel specification for the selected interpreter.

        Args:
            kernel_root: Temporary directory holding the kernel specification.
            kernel_python: Python executable that runs ``ipykernel_launcher``.
            working_directory: Directory the notebook's code runs in.
        """
        self._kernel_root = kernel_root
        self._kernel_dirs: list[str] = [str(kernel_root)]
        self._working_directory = working_directory
        kernel_directory = kernel_root / self._KERNEL_NAME
        kernel_directory.mkdir()
        argv: list[str] = [
            str(kernel_python),
            "-m",
            "ipykernel_launcher",
            "-f",
            "{connection_file}",
        ]
        specification: dict[str, object] = {
            "argv": argv,
            "display_name": "Research notebook: current uv environment",
            "language": "python",
        }
        (kernel_directory / "kernel.json").write_text(json.dumps(specification), encoding="utf-8")

    def attempt(self, notebook: nbformat.NotebookNode, run: int) -> NotebookAttempt:
        """Bind a fresh kernel manager and client for one execution of a notebook copy.

        Args:
            notebook: Notebook copy to execute in place.
            run: One-based run number, naming the kernel connection file.

        Returns:
            The unstarted attempt.
        """
        manager = KernelManager(
            kernel_name=self._KERNEL_NAME,
            kernel_spec_manager=KernelSpecManager(kernel_dirs=self._kernel_dirs),
            connection_file=str(self._kernel_root / f"connection-{run}.json"),
        )
        client = NotebookClient(
            notebook,
            km=manager,
            timeout=90,
            resources={"metadata": {"path": str(self._working_directory)}},
        )
        return NotebookAttempt(manager, client)


class NotebookAttempt:
    """Own one execution's kernel manager and notebook client."""

    def __init__(self, manager: KernelManager, client: NotebookClient) -> None:
        """Bind the unstarted kernel manager and its notebook client."""
        self._manager = manager
        self._client = client

    def execute(self, environment: dict[str, str]) -> None:
        """Start the kernel and execute every cell.

        Args:
            environment: Complete environment for the kernel process.

        Raises:
            RuntimeError: Kernel startup or notebook execution fails.
        """
        self._client.execute(env=environment)

    def shutdown(self) -> None:
        """Stop the kernel if one was started."""
        if self._manager.has_kernel:
            self._manager.shutdown_kernel(now=True)


def main() -> None:
    """Run once by default, retaining successful and failed executed notebooks.

    Raises:
        OSError: A notebook or temporary kernel file cannot be accessed.
        RuntimeError: Kernel startup or notebook execution fails.
    """
    examples = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "notebook",
        nargs="?",
        type=Path,
        default=examples / "opportunity-map.ipynb",
        help="Notebook path, relative to the working directory; must be under examples/.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Explicit number of fresh-kernel executions; every repetition reruns all cells.",
    )
    parser.add_argument(
        "--kernel-python",
        type=Path,
        default=Path(sys.executable),
        help="Python executable for the kernel; defaults to the current tooling environment.",
    )
    arguments = parser.parse_args(namespace=_Arguments())
    kernel_python = arguments.kernel_python.absolute()
    if not kernel_python.is_file():
        parser.error("--kernel-python must name an existing Python executable")
    notebook_path = arguments.notebook.resolve()
    if not notebook_path.is_relative_to(examples):
        parser.error("the notebook must be under the repository's examples/ directory")
    if notebook_path.suffix != ".ipynb" or not notebook_path.is_file():
        parser.error("the notebook must be an existing .ipynb file")
    if arguments.repeat < 1:
        parser.error("--repeat must be a positive integer")
    source = NotebookDocument.read(notebook_path)
    source_digest = NotebookDocument.source_digest(source)
    run_directory = examples / "runs" / notebook_path.stem
    run_directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".kernel-", dir=examples) as temporary:
        execution = NotebookExecution(Path(temporary), kernel_python, examples.parent)
        for run in range(1, arguments.repeat + 1):
            notebook = NotebookDocument.fresh_copy(source)
            attempt_id = str(uuid4())
            started_at = datetime.now(UTC).isoformat()
            status = "failed"
            attempt = execution.attempt(notebook, run)
            try:
                attempt.execute(
                    {
                        **os.environ,
                        "ALPHA_RESEARCH_NOTEBOOK_PATH": str(notebook_path),
                        "ALPHA_RESEARCH_ATTEMPT_ID": attempt_id,
                    }
                )
                status = "completed"
            finally:
                try:
                    attempt.shutdown()
                finally:
                    notebook.metadata["research_execution"] = {
                        "attempt_id": attempt_id,
                        "source_sha256": source_digest,
                        "started_at": started_at,
                        "finished_at": datetime.now(UTC).isoformat(),
                        "status": status,
                        "kernel_python": str(kernel_python),
                    }
                    archive = run_directory / f"{attempt_id}.ipynb"
                    NotebookDocument.write_new(notebook, archive)
                    print(f"Saved {status} attempt: {archive}", flush=True)
            NotebookDocument.write(notebook, notebook_path)
            print(f"Execution {run}/{arguments.repeat}: all notebook cells passed", flush=True)
    print(f"Updated local notebook: {notebook_path}")


if __name__ == "__main__":
    main()
