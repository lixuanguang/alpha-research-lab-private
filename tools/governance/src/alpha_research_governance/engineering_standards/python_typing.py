"""Run the repository's complete stronger Python typing check."""

from __future__ import annotations

# standard library imports
import subprocess  # nosec B404  # [owner=platform; rationale=run the pinned local mypy checker with fixed arguments; expires=2027-03-01]
import sys
from pathlib import Path

TYPING_PATHS = ("src", "tests", "tools/governance/src", "tools/typing/stubs")


class TypingChecker:
    """Own the complete stronger mypy invocation without a diagnostic baseline."""

    def __init__(self, repository_root: Path) -> None:
        """Capture the repository root without reading files or starting processes.

        Args:
            repository_root: Checkout containing the governed source paths.
        """
        self._root = repository_root

    def _probe(self) -> str:
        """Run the pinned stronger probe and return its machine-readable diagnostics.

        Returns:
            Mypy JSON output, which is empty when every governed path passes.

        Raises:
            OSError: The checker cannot start.
            ValueError: Mypy reports diagnostics or cannot complete successfully.
        """
        process = subprocess.run(  # nosec B603  # [owner=platform; rationale=pinned interpreter and fixed mypy diagnostic arguments without shell execution; expires=2027-03-01]
            [
                sys.executable,
                "-m",
                "mypy",
                "--strict",
                "--disallow-any-expr",
                "--disallow-any-decorated",
                "--output=json",
                *TYPING_PATHS,
            ],
            cwd=self._root,
            check=False,
            capture_output=True,
            text=True,
        )
        output = process.stdout.strip()
        if process.returncode != 0:
            detail = process.stderr.strip() or output or "mypy failed without diagnostics"
            raise ValueError(f"mypy stronger typing check failed: {detail}")
        if process.stderr.strip():
            raise ValueError(f"mypy stronger typing check emitted stderr: {process.stderr.strip()}")
        if output:
            raise ValueError(f"mypy stronger typing check emitted diagnostics: {output}")
        return output

    def run(self) -> int:
        """Run the stronger probe and fail directly on every diagnostic.

        Returns:
            Zero when all governed paths pass, one when mypy or the process boundary fails.
        """
        try:
            self._probe()
        except (OSError, ValueError) as error:
            print(f"Python typing check: {error}")
            return 1
        print("Python typing checks passed for src, tests, governance, and native stubs")
        return 0


if __name__ == "__main__":
    raise SystemExit(TypingChecker(Path.cwd()).run())
