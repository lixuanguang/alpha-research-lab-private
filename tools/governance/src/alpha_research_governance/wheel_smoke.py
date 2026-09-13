"""Build the runtime distribution and verify a governance-free wheel installation."""

from __future__ import annotations

# standard library imports
import os
import subprocess  # nosec B404  # [owner=platform; rationale=isolated wheel smoke argv boundary; expires=2027-03-01]
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

_RUNTIME_WHEEL_PREFIX = "alpha_research_lab-"


def _run(command: Sequence[str], *, cwd: Path) -> None:
    """Run shell-free argv from ``cwd`` and require a successful exit.

    Propagate ``OSError`` when startup fails and ``CalledProcessError`` when
    the command exits unsuccessfully.
    """
    subprocess.run(  # nosec B603  # [owner=platform; rationale=constant smoke argv without shell; expires=2027-03-01]
        command, cwd=cwd, check=True
    )


def _install_and_import(
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
    _run(
        ["uv", "venv", "--python", sys.executable, str(virtual_environment)],
        cwd=smoke_root,
    )
    python = virtual_environment / "bin" / "python"
    requirements = smoke_root / "runtime-requirements.txt"
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
            str(requirements),
        ],
        cwd=repository_root,
    )
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
            "from importlib.metadata import distributions, version; "
            "from importlib.util import find_spec; "
            "import os; "
            "from datetime import date; "
            "from pathlib import Path; "
            "import sys; "
            "import alpha_research; "
            "from alpha_research.financial_units import QuantLibConventions; "
            "from alpha_research.instrument_identity import InstrumentId; "
            "from alpha_research.core import EventProvenance; "
            "from alpha_research.reference_data import CatalogSnapshot, SpotInstrument; "
            "from alpha_research.data.decoders import DecodeContext, PayloadDecoder; "
            "from alpha_research.data import BinancePayloadDecoder, TardisDecoder; "
            "from alpha_research.data import "
            "DepthSnapshot, DepthUpdate, Disconnect, MarketEvent, Trade; "
            "from alpha_research.data.venues.binance.codecs import "
            "decode_market_event, encode_market_event, validate_market_event; "
            "from alpha_research.data.venues.binance.events import BinanceMarketEvent; "
            "from alpha_research.venue_calendar import CalendarAuthority, CalendarSourceVersion, "
            "ExchangeCalendarsAdapter, MarketIdentifierCode, Venue, VenueId; "
            "root = Path(os.environ['SMOKE_REPOSITORY_ROOT']).resolve(); "
            "prefix = Path(sys.prefix).resolve(); "
            "runtime_origin = Path(alpha_research.__file__).resolve(); "
            "assert runtime_origin.is_relative_to(prefix); "
            "assert not runtime_origin.is_relative_to(root); "
            "assert version('alpha-research-lab'); "
            "assert find_spec('alpha_research_governance') is None; "
            "assert 'alpha-research-governance' not in "
            "{item.metadata['Name'] for item in distributions()}; "
            "assert InstrumentId; "
            "assert EventProvenance and CatalogSnapshot and SpotInstrument; "
            "assert DecodeContext and PayloadDecoder and TardisDecoder; "
            "assert DepthSnapshot and DepthUpdate and Disconnect and MarketEvent and Trade; "
            "assert BinanceMarketEvent and callable(encode_market_event) "
            "and callable(decode_market_event) and callable(validate_market_event) "
            "and BinancePayloadDecoder and callable(TardisDecoder.decode_line); "
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
    with tempfile.TemporaryDirectory(prefix="alpha-research-wheel-smoke-") as temporary:
        smoke_root = Path(temporary)
        wheel_directory = smoke_root / "wheels"
        wheel_directory.mkdir()
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
            cwd=root,
        )
        candidates = tuple(sorted(wheel_directory.glob(f"{_RUNTIME_WHEEL_PREFIX}*.whl")))
        if len(candidates) != 1:
            names = ", ".join(path.name for path in candidates) or "none"
            raise RuntimeError(f"expected one {_RUNTIME_WHEEL_PREFIX}wheel, found {names}")
        runtime_wheel = candidates[0]
        _install_and_import(
            root,
            smoke_root,
            runtime_wheel,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
