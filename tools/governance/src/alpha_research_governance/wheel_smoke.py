"""Build both distributions and verify imports from an isolated wheel install."""

from __future__ import annotations

# standard library imports
import os
import subprocess  # nosec B404  # [owner=platform; rationale=isolated wheel smoke argv boundary; expires=2027-03-01]
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

_GOVERNANCE_WHEEL_PREFIX = "alpha_research_governance-"
_RUNTIME_WHEEL_PREFIX = "alpha_research_lab-"


def _run(command: Sequence[str], *, cwd: Path) -> None:
    """Run one checked command from the repository or temporary smoke root.

    Args:
        command: Executable and arguments passed without a shell.
        cwd: Working directory for the child process.

    Raises:
        OSError: The executable cannot be started.
        subprocess.CalledProcessError: The command exits unsuccessfully.
    """
    subprocess.run(  # nosec B603  # [owner=platform; rationale=constant smoke argv without shell; expires=2027-03-01]
        command, cwd=cwd, check=True
    )


def _single_wheel(directory: Path, *, prefix: str) -> Path:
    """Return the one newly built wheel with the expected package prefix.

    Args:
        directory: Temporary directory containing only this smoke run's artifacts.
        prefix: Normalized package and version prefix expected in the filename.

    Returns:
        The exact wheel path selected for installation.

    Raises:
        RuntimeError: No wheel or more than one matching wheel was produced.
    """
    candidates = tuple(sorted(directory.glob(f"{prefix}*.whl")))
    if len(candidates) != 1:
        names = ", ".join(path.name for path in candidates) or "none"
        raise RuntimeError(f"expected one {prefix}wheel, found {names}")
    return candidates[0]


def _build_wheels(repository_root: Path, wheel_directory: Path) -> tuple[Path, Path]:
    """Build the governance and runtime wheels into a fresh temporary directory.

    Args:
        repository_root: Checkout containing both PEP 517 projects.
        wheel_directory: Empty temporary directory receiving wheel artifacts.

    Returns:
        The governance wheel followed by the runtime wheel.
    """
    _run(
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
            "tools/governance",
            "--out-dir",
            str(wheel_directory),
        ],
        cwd=repository_root,
    )
    _run(
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
        cwd=repository_root,
    )
    return (
        _single_wheel(wheel_directory, prefix=_GOVERNANCE_WHEEL_PREFIX),
        _single_wheel(wheel_directory, prefix=_RUNTIME_WHEEL_PREFIX),
    )


def _export_runtime_requirements(repository_root: Path, destination: Path) -> None:
    """Export locked runtime dependencies while omitting local project wheels.

    Args:
        repository_root: Checkout whose frozen ``uv.lock`` is authoritative.
        destination: Requirements file written outside the checkout.
    """
    _run(
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
            str(destination),
        ],
        cwd=repository_root,
    )


def _install_and_import(
    repository_root: Path,
    smoke_root: Path,
    governance_wheel: Path,
    runtime_wheel: Path,
) -> None:
    """Install locked dependencies and both wheels, then exercise public imports.

    The isolated interpreter runs from ``smoke_root`` with ``PYTHONPATH`` removed and
    ``-I`` enabled, so imports cannot resolve from the checkout. The runtime wheel
    currently depends on the governance wheel; that coupling is intentional until
    the next cleanup step removes the compatibility surface.

    Args:
        repository_root: Checkout containing the frozen lockfile.
        smoke_root: Temporary directory outside the checkout used as the work root.
        governance_wheel: Built governance wheel to install.
        runtime_wheel: Built runtime wheel to install.
    """
    virtual_environment = smoke_root / "venv"
    _run(
        ["uv", "venv", "--python", sys.executable, str(virtual_environment)],
        cwd=smoke_root,
    )
    python = virtual_environment / "bin" / "python"
    requirements = smoke_root / "runtime-requirements.txt"
    _export_runtime_requirements(repository_root, requirements)
    _run(
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
        ],
        cwd=smoke_root,
    )
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            str(governance_wheel),
            str(runtime_wheel),
        ],
        cwd=smoke_root,
    )
    _run(["uv", "pip", "check", "--python", str(python)], cwd=smoke_root)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["SMOKE_REPOSITORY_ROOT"] = str(repository_root)
    command = [
        str(python),
        "-I",
        "-c",
        (
            "from importlib.metadata import version; "
            "import os; "
            "from datetime import date; "
            "from pathlib import Path; "
            "import sys; "
            "import alpha_research; "
            "import alpha_research_governance; "
            "from alpha_research.financial_units import QuantLibConventions; "
            "from alpha_research.instrument_identity import InstrumentId; "
            "from alpha_research.venue_calendar import CalendarAuthority, CalendarSourceVersion, "
            "ExchangeCalendarsAdapter, MarketIdentifierCode, Venue, VenueId; "
            "root = Path(os.environ['SMOKE_REPOSITORY_ROOT']).resolve(); "
            "prefix = Path(sys.prefix).resolve(); "
            "runtime_origin = Path(alpha_research.__file__).resolve(); "
            "governance_origin = Path(alpha_research_governance.__file__).resolve(); "
            "assert runtime_origin.is_relative_to(prefix); "
            "assert governance_origin.is_relative_to(prefix); "
            "assert not runtime_origin.is_relative_to(root); "
            "assert not governance_origin.is_relative_to(root); "
            "assert version('alpha-research-lab'); "
            "assert version('alpha-research-governance'); "
            "assert InstrumentId; "
            "assert QuantLibConventions(); "
            "venue = Venue(venue_id=VenueId.from_canonical_text("
            "'11111111-1111-4111-8111-111111111111'), "
            "mic=MarketIdentifierCode(value='XNYS'), "
            "operating_mic=MarketIdentifierCode(value='XNYS'), "
            "name='Smoke venue', timezone_name='America/New_York'); "
            "version_info = CalendarSourceVersion(calendar_version='smoke-v1', "
            "base_source='exchange_calendars', base_source_revision='4.13.2', "
            "adapter_name='exchange_calendars', adapter_version='4.13.2', "
            "authority=CalendarAuthority.SYNTHETIC_FIXTURE); "
            "snapshot = ExchangeCalendarsAdapter().build_snapshot(venue=venue, "
            "calendar_name='XNYS', "
            "version=version_info, start=date(2024, 11, 27), end=date(2024, 11, 29)); "
            "assert snapshot.session_for_label(date(2024, 11, 27)).opens_at"
        ),
    ]
    subprocess.run(  # nosec B603  # [owner=platform; rationale=isolated interpreter smoke argv; expires=2027-03-01]
        command, cwd=smoke_root, env=environment, check=True
    )
    cli = virtual_environment / "bin" / "alpha-research-ci"
    completed = subprocess.run(  # nosec B603  # [owner=platform; rationale=installed CLI boundary smoke; expires=2027-03-01]
        [str(cli), "scan-secrets"],
        cwd=smoke_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 1 or "scan-secrets accepts" not in completed.stderr:
        raise RuntimeError("installed alpha-research-ci did not reject an empty scan scope")


def main(repository_root: Path | None = None) -> int:
    """Build and install both local wheels in a clean, checkout-independent environment.

    Args:
        repository_root: Checkout root, or the current directory when omitted.

    Returns:
        Zero after building both wheels and completing the isolated import smoke.

    Raises:
        OSError: A required build, virtual-environment, or installer executable cannot start.
        RuntimeError: Wheel selection does not identify exactly one artifact per project.
        subprocess.CalledProcessError: A build, dependency install, or import smoke fails.
    """
    root = (Path.cwd() if repository_root is None else repository_root).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="alpha-research-wheel-smoke-") as temporary:
        smoke_root = Path(temporary)
        wheel_directory = smoke_root / "wheels"
        wheel_directory.mkdir()
        governance_wheel, runtime_wheel = _build_wheels(root, wheel_directory)
        _install_and_import(
            root,
            smoke_root,
            governance_wheel,
            runtime_wheel,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
