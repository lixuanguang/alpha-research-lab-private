"""Re-verify the installed monitoring evidence once under the bounded dashboard contract.

Run this file from a separately installed, non-editable research environment with
``-I``. One invocation owns one fresh output directory, so a declared single attempt
cannot be repeated in place. Every step stops the attempt at its first failure and is
retained in ``steps.jsonl``. ``make check`` stays a separate final step.

The steps repeat the installed monitoring journeys: four live public-paper runs (both venues,
shared and dedicated accounts) that reconcile dashboard economics and observe every
local alert, their fresh-process replays, the installed operational and research
consumer suites, and a structural inspection of every retained dashboard page.
"""

from __future__ import annotations

# standard library imports
import argparse
import functools
import hashlib
import shutil
import subprocess  # nosec B404  # [owner=runtime; rationale=declared installed consumer runs; expires=2027-03-01]
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

# third party library imports
import msgspec

# project library imports
from applications.paper import PaperMonitoringResult
from runtime import RuntimeFiles
from serialization import DomainCodec
from telemetry import DashboardSnapshot

_RUNS = (
    ("okx", "shared", "okx-btc-usdt.json"),
    ("okx", "dedicated", "okx-btc-usdt.json"),
    ("bitfinex", "shared", "bitfinex-btc-usd.json"),
    ("bitfinex", "dedicated", "bitfinex-btc-usd.json"),
)
_SUITES = (
    "tests/integration/test_operational_workflow.py",
    "tests/integration/test_public_paper_workflow.py",
    "tests/integration/test_study_workflow.py",
    "tests/integration/test_candidate_workflow.py",
    "tests/integration/test_decision_workflow.py",
)


class Gate(msgspec.Struct, frozen=True):
    """Retain one named criterion, its outcome and the facts it read."""

    name: str
    passed: bool
    observed: object


class PageInspection:
    """Check a retained dashboard page is self-contained and shows its bounded view."""

    @staticmethod
    def gates(name: str, view: DashboardSnapshot, page: bytes) -> tuple[Gate, ...]:
        """Require the selection digest, every panel and no external resource or script."""
        text = page.decode()
        lowered = text.lower()
        return (
            Gate(f"{name}.selection_digest_shown", view.events_sha256 in text, view.event_count),
            Gate(
                f"{name}.every_panel_shown",
                text.count('<section class="panel">') == len(view.config.panels),
                len(view.config.panels),
            ),
            Gate(
                f"{name}.self_contained",
                "<script" not in lowered and "src=" not in lowered and "http" not in lowered,
                len(page),
            ),
            Gate(
                f"{name}.points_bounded",
                all(len(result.points) <= 120 for result in view.results),
                max((len(result.points) for result in view.results), default=0),
            ),
        )


class Reverification:
    """Own one declared attempt's ordered steps, evidence and first-failure stop."""

    def __init__(self, output: Path, *, repository: Path) -> None:
        """Bind absolute inputs; nothing runs until ``run``."""
        if not output.is_absolute() or not repository.is_absolute():
            raise ValueError("re-verification paths must be absolute")
        self.output, self.repository = output, repository
        self.consumers = output / "consumers"
        self.codec = DomainCodec()

    def record(self, step: str, passed: bool, values: object) -> None:
        """Append one step outcome before the next step can run."""
        row = {"step": step, "passed": passed, "at": datetime.now(UTC), "values": values}
        with (self.output / "steps.jsonl").open("ab") as stream:
            stream.write(self.codec.encode_json(row) + b"\n")

    def command(self, step: str, arguments: list[str], *, cwd: Path) -> str:
        """Run one subprocess, retain its output and fail the step on a nonzero exit."""
        completed = subprocess.run(  # nosec B603  # [owner=runtime; rationale=explicit argv of declared installed consumers; expires=2027-03-01]
            arguments, capture_output=True, cwd=cwd, check=False, timeout=900
        )
        logs = self.output / "logs"
        logs.mkdir(exist_ok=True)
        (logs / f"{step}.stdout").write_bytes(completed.stdout)
        (logs / f"{step}.stderr").write_bytes(completed.stderr)
        if completed.returncode:
            raise RuntimeError(f"step {step} exited with {completed.returncode}")
        return completed.stdout.decode()

    def freeze(self) -> dict[str, object]:
        """Require a clean checkout and an installed runtime equal to it, file by file."""
        status = self.command(
            "freeze-status", ["git", "status", "--porcelain"], cwd=self.repository
        )
        commit = self.command("freeze-commit", ["git", "rev-parse", "HEAD"], cwd=self.repository)
        if status.strip():
            raise ValueError("declared candidate source has uncommitted changes")
        inputs = RuntimeFiles.inputs()
        source = self.repository / "src"
        if any(path.resolve().is_relative_to(self.repository.resolve()) for _, path in inputs):
            raise ValueError("re-verification requires an installed, not editable, runtime")
        mismatched = sorted(
            name for name, path in inputs if path.read_bytes() != (source / name).read_bytes()
        )
        if mismatched:
            raise ValueError(f"installed runtime differs from the checkout: {mismatched[:5]}")
        self.consumers.mkdir()
        hashes: dict[str, str] = {}
        for path in (
            Path(__file__).with_name("public_paper.py"),
            self.repository / "configs/live/okx-btc-usdt.json",
            self.repository / "configs/live/bitfinex-btc-usd.json",
        ):
            shutil.copy2(path, self.consumers / path.name)
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "commit": commit.strip(),
            "interpreter": sys.executable,
            "runtime_inputs": len(inputs),
            "copied_sha256": hashes,
        }

    def live(self, venue: str, mode: str, config: str) -> tuple[Gate, ...]:
        """Run one live public-paper journey and check its reconciliation and alerts."""
        output = self.output / f"{venue}-{mode}"
        self.command(
            f"live-{venue}-{mode}",
            [
                sys.executable,
                "-I",
                str(self.consumers / "public_paper.py"),
                "--config",
                str(self.consumers / config),
                "--output",
                str(output),
                "--live",
                "--adverse",
                "0.01",
                *(("--dedicated",) if mode == "dedicated" else ()),
            ],
            cwd=self.consumers,
        )
        reconciliation = msgspec.json.decode(
            (output / "monitoring-reconciliation.json").read_bytes(), type=dict[str, object]
        )
        alerts = msgspec.json.decode(
            (output / "alert-delivery.json").read_bytes(), type=dict[str, object]
        )
        status = self.codec.decode_json(
            (output / "run/monitoring/monitoring-status.json").read_bytes(), PaperMonitoringResult
        )
        summary = msgspec.json.decode(
            (output / "summary.json").read_bytes(), type=dict[str, object]
        )
        fills, accepted = summary.get("attributed_fills"), alerts.get("socket_accepted")
        gates = [
            # A run with no fill or no alert would reconcile and observe nothing.
            Gate("economics_exercised", type(fills) is int and fills > 0, fills),
            Gate("alerts_exercised", type(accepted) is int and accepted > 0, accepted),
            Gate(
                "economics_reconciled",
                reconciliation.get("exact") is True,
                reconciliation.get("expected"),
            ),
            Gate(
                "alerts_observed",
                alerts.get("socket_accepted") == alerts.get("receiver_observed"),
                {key: alerts.get(key) for key in ("socket_accepted", "receiver_observed")},
            ),
            Gate("monitoring_errors_absent", not status.errors, status.errors),
            Gate("dashboards_retained", bool(status.dashboards), len(status.dashboards)),
        ]
        for name in status.dashboards:
            directory = output / "run/monitoring" / name
            view = DashboardSnapshot.read(directory)
            gates.extend(
                PageInspection.gates(name, view, (directory / "dashboard.html").read_bytes())
            )
        return tuple(gates)

    def replay(self, venue: str, mode: str, config: str) -> tuple[Gate, ...]:
        """Reopen one run in a fresh process: identical bytes, equal views, nothing inserted."""
        output = self.output / f"{venue}-{mode}"
        self.command(
            f"replay-{venue}-{mode}",
            [
                sys.executable,
                "-I",
                str(self.consumers / "public_paper.py"),
                "--config",
                str(self.consumers / config),
                "--output",
                str(output),
                "--live",
                "--adverse",
                "0.01",
                "--replay",
                *(("--dedicated",) if mode == "dedicated" else ()),
            ],
            cwd=self.consumers,
        )
        verification = msgspec.json.decode(
            (output / "replay-verification.json").read_bytes(), type=dict[str, object]
        )
        return (
            Gate(
                "account_bytes_equal", verification.get("equal") is True, verification.get("before")
            ),
            Gate("monitoring_equal", verification.get("monitoring_equal") is True, None),
            Gate(
                "nothing_inserted",
                verification.get("monitoring_inserted") == 0,
                verification.get("monitoring_inserted"),
            ),
        )

    def suites(self) -> tuple[Gate, ...]:
        """Run the installed operational and research consumer suites, keeping workspaces."""
        report = self.output / "suites-junit.xml"
        try:
            self.command(
                "installed-suites",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-m",
                    "integration",
                    "-p",
                    "no:cacheprovider",
                    "--basetemp",
                    str(self.output / "suites"),
                    "--junitxml",
                    str(report),
                    *_SUITES,
                ],
                cwd=self.repository,
            )
        except RuntimeError:
            return (
                Gate(
                    "installed_suites_pass",
                    False,
                    str(self.output / "logs/installed-suites.stdout"),
                ),
            )
        summary = report.read_text()
        return (
            Gate(
                "installed_suites_pass",
                'failures="0"' in summary and 'errors="0"' in summary,
                len(summary),
            ),
        )

    def step(self, name: str, action: Callable[[], object]) -> None:
        """Run one declared step, retaining its outcome and stopping on any failure."""
        try:
            values = action()
        except Exception as error:
            self.record(name, False, {"error": f"{type(error).__name__}: {error}"})
            raise
        gates = cast(tuple[Gate, ...], values) if isinstance(values, tuple) else ()
        failed = [gate.name for gate in gates if not gate.passed]
        self.record(name, not failed, {"failed_gates": failed, "gates": gates} if gates else values)
        if failed:
            raise RuntimeError(f"step {name} failed gates: {', '.join(failed)}")

    def run(self) -> None:
        """Run the declared sequence once."""
        self.output.mkdir(parents=True, exist_ok=False)
        self.step("freeze", self.freeze)
        for venue, mode, config in _RUNS:
            self.step(f"live-{venue}-{mode}", functools.partial(self.live, venue, mode, config))
        for venue, mode, config in _RUNS:
            self.step(f"replay-{venue}-{mode}", functools.partial(self.replay, venue, mode, config))
        self.step("installed-suites", self.suites)


class _Arguments(argparse.Namespace):
    """Carry one invocation's absolute inputs."""

    output: Path
    repository: Path


def main() -> None:
    """Run one declared monitoring re-verification into a fresh output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args(namespace=_Arguments())
    try:
        Reverification(args.output, repository=args.repository).run()
    except Exception as error:
        print(f"re-verification stopped: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"re-verification passed: {args.output}")


if __name__ == "__main__":
    main()
