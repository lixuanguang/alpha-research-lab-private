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
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager
from nbclient import NotebookClient


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
    arguments = parser.parse_args()
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
    source = nbformat.read(notebook_path, as_version=4)
    source_bytes = json.dumps(
        [(cell.cell_type, cell.source) for cell in source.cells],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    run_directory = examples / "runs" / notebook_path.stem
    run_directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".kernel-", dir=examples) as temporary:
        kernel_root = Path(temporary)
        kernel_directory = kernel_root / "p1-example"
        kernel_directory.mkdir()
        (kernel_directory / "kernel.json").write_text(
            json.dumps(
                {
                    "argv": [
                        str(kernel_python),
                        "-m",
                        "ipykernel_launcher",
                        "-f",
                        "{connection_file}",
                    ],
                    "display_name": "Research notebook: current uv environment",
                    "language": "python",
                }
            ),
            encoding="utf-8",
        )
        for run in range(1, arguments.repeat + 1):
            notebook = nbformat.reads(nbformat.writes(source), as_version=4)
            for cell in notebook.cells:
                if cell.cell_type == "code":
                    cell.execution_count = None
                    cell.outputs = []
            attempt_id = str(uuid4())
            started_at = datetime.now(UTC).isoformat()
            status = "failed"
            manager = KernelManager(
                kernel_name="p1-example",
                kernel_spec_manager=KernelSpecManager(kernel_dirs=[str(kernel_root)]),
                connection_file=str(kernel_root / f"connection-{run}.json"),
            )
            client = NotebookClient(
                notebook,
                km=manager,
                timeout=90,
                resources={"metadata": {"path": str(examples.parent)}},
            )
            try:
                client.execute(
                    env={
                        **os.environ,
                        "ALPHA_RESEARCH_NOTEBOOK_PATH": str(notebook_path),
                        "ALPHA_RESEARCH_ATTEMPT_ID": attempt_id,
                    }
                )
                status = "completed"
            finally:
                try:
                    if manager.has_kernel:
                        manager.shutdown_kernel(now=True)
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
                    with archive.open("x", encoding="utf-8") as output:
                        nbformat.write(notebook, output)
                    print(f"Saved {status} attempt: {archive}", flush=True)
            nbformat.write(notebook, notebook_path)
            print(f"Execution {run}/{arguments.repeat}: all notebook cells passed", flush=True)
    print(f"Updated local notebook: {notebook_path}")


if __name__ == "__main__":
    main()
