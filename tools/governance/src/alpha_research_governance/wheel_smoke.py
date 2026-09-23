"""Build the runtime distribution and verify a governance-free wheel installation."""

from __future__ import annotations

# standard library imports
import os
import shutil
import subprocess  # nosec B404  # [owner=platform; rationale=isolated wheel smoke argv boundary; expires=2027-03-01]
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

_RUNTIME_WHEEL_PREFIX = "alpha_research_lab-"


class _InstalledWheelCheck:
    """Verify a hash-locked runtime installation outside the checkout."""

    @staticmethod
    def _run(command: Sequence[str], *, cwd: Path) -> None:
        """Run shell-free argv from ``cwd`` and require a successful exit.

        Propagate ``OSError`` when startup fails and ``CalledProcessError`` when
        the command exits unsuccessfully.
        """
        subprocess.run(  # nosec B603  # [owner=platform; rationale=constant smoke argv without shell; expires=2027-03-01]
            command, cwd=cwd, check=True
        )

    @staticmethod
    def validate(
        repository_root: Path,
        smoke_root: Path,
        runtime_wheel: Path,
    ) -> None:
        """Install locked runtime dependencies and the wheel, then exercise public imports.

        The isolated interpreter runs from ``smoke_root`` with ``PYTHONPATH`` removed and
        ``-I`` enabled, so imports cannot resolve from the checkout. Governance tooling is
        absent from this environment, so an accidental runtime dependency on it fails
        dependency checking or imports.

        Args:
            repository_root: Checkout containing the frozen lockfile.
            smoke_root: Temporary directory outside the checkout used as the work root.
            runtime_wheel: Built runtime wheel to install.
        """
        virtual_environment = smoke_root / "venv"
        _InstalledWheelCheck._run(
            ["uv", "venv", "--python", sys.executable, str(virtual_environment)],
            cwd=smoke_root,
        )
        python = virtual_environment / "bin" / "python"
        requirements = smoke_root / "runtime-requirements.txt"
        _InstalledWheelCheck._run(
            [
                "uv",
                "export",
                "--quiet",
                "--frozen",
                "--no-dev",
                "--no-emit-project",
                "--no-emit-workspace",
                "--no-emit-local",
                "--output-file",
                str(requirements),
            ],
            cwd=repository_root,
        )
        _InstalledWheelCheck._run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--requirement",
                str(requirements),
                "--only-binary=:all:",
                "--require-hashes",
                "--compile-bytecode",
            ],
            cwd=smoke_root,
        )
        _InstalledWheelCheck._run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                "--compile-bytecode",
                str(runtime_wheel),
            ],
            cwd=smoke_root,
        )
        _InstalledWheelCheck._run(["uv", "pip", "check", "--python", str(python)], cwd=smoke_root)
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        # A sandbox may deny the user cache. Matplotlib otherwise creates a new
        # temporary cache per process and repeatedly scans every macOS font.
        # Share only this disposable run's cache across its installed consumers.
        environment["MPLCONFIGDIR"] = str(smoke_root / "matplotlib-cache")
        inputs = smoke_root / "inputs"
        inputs.mkdir()
        for relative, name in (
            ("configs/backtests/okx-eth-usdt-book-v1.json", "book-config.json"),
            ("tests/integration/consumers/backtest/book_workflow.py", "book_workflow.py"),
            ("tests/integration/consumers/wheel_layout.py", "wheel_layout.py"),
        ):
            shutil.copyfile(repository_root / relative, inputs / name)
        shutil.copytree(
            repository_root / "tests/fixtures/datasets/historical_snapshot",
            inputs / "historical_snapshot",
        )
        command = [str(python), "-I", str(inputs / "wheel_layout.py"), str(inputs)]
        subprocess.run(  # nosec B603  # [owner=platform; rationale=isolated interpreter smoke argv; expires=2027-03-01]
            command, cwd=smoke_root, env=environment, check=True
        )


def main(repository_root: Path | None = None) -> int:
    """Build and install the runtime wheel in a clean environment without governance.

    Args:
        repository_root: Checkout root, or the current directory when omitted.

    Returns:
        Zero after building the wheel and completing the isolated import smoke.

    Raises:
        OSError: A required build, virtual-environment, or installer executable cannot start.
        RuntimeError: Wheel selection does not identify exactly one runtime artifact.
        subprocess.CalledProcessError: A build, dependency install, or import smoke fails.
    """
    root = (Path.cwd() if repository_root is None else repository_root).resolve(strict=True)
    # Preserve installed artifacts and attempts on failure as well as success;
    # callers can archive this printed directory before explicit later cleanup.
    with tempfile.TemporaryDirectory(
        prefix="alpha-research-wheel-smoke-", delete=False
    ) as temporary:
        smoke_root = Path(temporary)
        print(f"Retained installed-wheel evidence: {smoke_root}", flush=True)
        wheel_directory = smoke_root / "wheels"
        wheel_directory.mkdir()
        _InstalledWheelCheck._run(
            [
                "uv",
                "run",
                "--frozen",
                "--no-editable",
                "uv",
                "build",
                "--no-build-isolation",
                "--python",
                sys.executable,
                "--wheel",
                "--no-sources",
                ".",
                "--out-dir",
                str(wheel_directory),
            ],
            cwd=root,
        )
        candidates = tuple(sorted(wheel_directory.glob(f"{_RUNTIME_WHEEL_PREFIX}*.whl")))
        if len(candidates) != 1:
            names = ", ".join(path.name for path in candidates) or "none"
            raise RuntimeError(f"expected one {_RUNTIME_WHEEL_PREFIX}wheel, found {names}")
        runtime_wheel = candidates[0]
        _InstalledWheelCheck.validate(
            root,
            smoke_root,
            runtime_wheel,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
