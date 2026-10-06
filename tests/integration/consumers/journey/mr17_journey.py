"""Drive one declared MR17 fresh-entry journey attempt and write its per-step summary.

The [MR17 record](../../../../docs/roadmap/qr-onboarding.md#journey-declaration-approved-2026-10-04)
declares the steps, commands and pass criteria. Run this file with any interpreter
that has ``msgspec``: it imports no platform code, because J1 creates the installed
environments the journey runs. Its gate checks run in ``journey_checks.py`` under the
J1 research interpreter.

One invocation owns one fresh attempt directory. Every command is retained in
``commands.jsonl`` before the next one starts, and ``summary.json`` is rewritten after
each step. The attempt stops at its first failed criterion; nothing is retried, and
the QR workspace is never edited.
"""

from __future__ import annotations

# standard library imports
import argparse
import ast
import hashlib
import os
import re
import shutil
import signal
import socket
import subprocess  # nosec B404  # [owner=runtime; rationale=declared journey commands; expires=2027-03-01]
import sys
import tarfile
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec

Step = Literal["J1", "J2", "J3", "J4", "J5", "J6", "J7", "J8"]
STEPS: tuple[Step, ...] = ("J1", "J2", "J3", "J4", "J5", "J6", "J7", "J8")
EXTENSION = "mr17-extensions"
# The inactive instance services v2 activates in J7.
LATE = "rule-okx-btc-late"
# Top-level platform packages whose names a QR may import only through ``__all__``.
PLATFORM_PACKAGES = frozenset(
    {
        "accounting",
        "applications",
        "configuration",
        "execution",
        "financial_units",
        "market_data",
        "portfolio",
        "reference_data",
        "research",
        "risk",
        "runtime",
        "serialization",
        "simulation",
        "strategies",
        "telemetry",
    }
)


class CaptureWindow(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Fix the J2 collection window relative to the step's start, and its ceilings."""

    lead_seconds: int
    ready_seconds: int
    duration_seconds: int
    max_messages: int
    max_bytes: int
    max_segments: int
    max_reconnects: int

    def __post_init__(self) -> None:
        """Require a future start, readiness inside the window and at most six hours."""
        if not 30 <= self.lead_seconds <= 900 or not 0 < self.ready_seconds < self.duration_seconds:
            raise ValueError("capture window needs a lead of 30-900 s and readiness inside it")
        if self.duration_seconds > 6 * 3600:
            raise ValueError("journey captures are at most six hours")


class HostAwake:
    """Hold a macOS sleep assertion for this process's lifetime; elsewhere, do nothing.

    ``caffeinate -i -s -w PID`` prevents idle and system sleep (on AC power) until
    this process exits, so a crash cannot leave the assertion behind.
    """

    def __init__(self) -> None:
        """Start without an assertion."""
        self._process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> HostAwake:
        """Take the assertion on macOS; refuse to run without it there."""
        if sys.platform == "darwin":
            executable = shutil.which("caffeinate")
            if executable is None:
                raise RuntimeError("the journey requires caffeinate to keep the host awake")
            self._process = subprocess.Popen(  # nosec B603  # [owner=runtime; rationale=fixed system tool; expires=2027-03-01]
                [executable, "-i", "-s", "-w", str(os.getpid())]
            )
        return self

    def __exit__(self, *_: object) -> None:
        """Release the assertion."""
        if self._process is not None:
            self._process.terminate()
            self._process.wait(timeout=10)
            self._process = None


class JourneyDeclaration(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Fix every input of one attempt before it starts; the owner approves counted ones."""

    attempt: str
    counted: bool
    through: Step
    repository: str
    commit: str
    qr_workspace: str
    qr_commit: str
    evidence_root: str
    temporary_root: str
    uv: str
    local_services_env: str
    lakefs_credentials: str
    lakefs_repository: str
    feeds: tuple[str, ...]
    window: CaptureWindow
    holdouts: int
    guides: tuple[str, ...]
    capacity_records: tuple[str, ...] = ()
    # J6 supervisor lives in seconds: P-A, P-B and S (rehearsals shorten them).
    phases: tuple[int, int, int] = (1800, 600, 600)
    # J7 supervisor lives in seconds: resume R, upgrade U and rollback B.
    operations: tuple[int, int, int] = (300, 300, 300)
    # J3 runs its independent studies at most this many at a time.
    research_workers: int = 4
    schema_version: Literal["mr17-journey-declaration"] = "mr17-journey-declaration"

    def __post_init__(self) -> None:
        """Refuse relative paths, unnamed attempts and a counted attempt short of J8."""
        if not re.fullmatch(r"(rehearsal-[0-9]+|counted(-[0-9]+)?)", self.attempt):
            raise ValueError("attempt must be rehearsal-<n> or counted[-<n>]")
        if self.counted != self.attempt.startswith("counted"):
            raise ValueError("only a counted attempt is named counted")
        if self.counted and (self.through != "J8" or len(self.capacity_records) != 2):
            raise ValueError("a counted attempt runs through J8 with both capacity records")
        for path in (
            self.repository,
            self.qr_workspace,
            self.evidence_root,
            self.temporary_root,
            self.uv,
            self.local_services_env,
            self.lakefs_credentials,
            *self.capacity_records,
        ):
            if not Path(path).is_absolute():
                raise ValueError(f"journey path must be absolute: {path}")
        for commit in (self.commit, self.qr_commit):
            if not re.fullmatch(r"[0-9a-f]{40}", commit):
                raise ValueError("journey commits must be full SHA-1 identities")
        if not self.feeds or len(set(self.feeds)) != len(self.feeds) or self.holdouts < 1:
            raise ValueError("journey declares distinct feeds and at least one holdout")
        if len(self.phases) != 3 or any(not 120 <= item <= 3000 for item in self.phases):
            raise ValueError("J6 phases are three supervisor lives of 120 to 3000 seconds")
        if len(self.operations) != 3 or any(not 120 <= item <= 3000 for item in self.operations):
            raise ValueError("J7 phases are three supervisor lives of 120 to 3000 seconds")
        if not 1 <= self.research_workers <= 16:
            raise ValueError("J3 research workers are 1 to 16")
        if len(f"{self.temporary_root}/{self.attempt}/s/supervisor.sock".encode()) > 100:
            raise ValueError("temporary root leaves no room for bounded socket paths")


class Gate(msgspec.Struct, frozen=True):
    """Retain one named criterion, its outcome and the facts it read."""

    name: str
    passed: bool
    observed: object


class Finding(msgspec.Struct, frozen=True):
    """Retain one guide or code gap a step exposed."""

    kind: Literal["guide", "code"]
    detail: str


class QRResult(msgspec.Struct, frozen=True):
    """Read the criteria and findings a QR script reports for its own command."""

    criteria: tuple[Gate, ...]
    findings: tuple[Finding, ...] = ()


class Discovery(msgspec.Struct, frozen=True):
    """Read ``alpha-dataset discover``'s envelope: status and one row per snapshot."""

    status: str
    result: tuple[dict[str, object], ...]


class CommandRecord(msgspec.Struct, frozen=True):
    """Retain one command's argv, environment overrides, clocks, exit and output digests."""

    ordinal: int
    step: Step
    label: str
    argv: tuple[str, ...]
    cwd: str
    environment: dict[str, str]
    started_at: datetime
    ended_at: datetime
    returncode: int
    stdout_sha256: str
    stderr_sha256: str


class ControlWindow(msgspec.Struct, frozen=True):
    """One supervisor control sent during a paper phase, and when it ran."""

    label: str
    started_at: datetime
    ended_at: datetime


class ControlWindows(msgspec.Struct, frozen=True):
    """Every supervisor control sent during the paper phases."""

    controls: tuple[ControlWindow, ...]


class StepRecord(msgspec.Struct):
    """Collect one step's status, criteria, commands and findings."""

    step: Step
    status: Literal["passed", "failed", "not_run", "pending"] = "not_run"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    criteria: list[Gate] = msgspec.field(default_factory=list)
    commands: list[int] = msgspec.field(default_factory=list)
    findings: list[Finding] = msgspec.field(default_factory=list)


class FirstFailure(msgspec.Struct, frozen=True):
    """Name the first failed step and criterion."""

    step: Step
    criterion: str
    observed: object


class Summary(msgspec.Struct):
    """The attempt's per-step pass/fail summary (schema ``mr17-journey-summary``)."""

    attempt: str
    counted: bool
    commit: str
    declaration_sha256: str
    qr_workspace: dict[str, str]
    guides: dict[str, str]
    installed: dict[str, str]
    started_at: datetime
    steps: list[StepRecord]
    ended_at: datetime | None = None
    result: Literal["passed", "failed", "stopped", "running"] = "running"
    first_failure: FirstFailure | None = None
    schema: Literal["mr17-journey-summary"] = "mr17-journey-summary"


class StepFailed(Exception):
    """Stop the attempt at a failed criterion."""

    def __init__(self, step: Step, criterion: str, observed: object) -> None:
        """Name the failed criterion and the facts it read."""
        super().__init__(f"{step} failed {criterion}")
        self.failure = FirstFailure(step=step, criterion=criterion, observed=observed)


class Commands:
    """Run declared commands, retain their output and record each before the next."""

    def __init__(self, output: Path) -> None:
        """Bind the attempt directory; logs go under ``logs/``."""
        self.output = output
        self.logs = output / "logs"
        self.logs.mkdir()
        self.ordinal = 0

    def _paths(self, label: str) -> tuple[int, Path, Path]:
        """Reserve the next ordinal and name its output files."""
        self.ordinal += 1
        stem = self.logs / f"{self.ordinal:04d}-{label}"
        return self.ordinal, stem.with_suffix(".stdout"), stem.with_suffix(".stderr")

    def _record(
        self,
        ordinal: int,
        step: Step,
        label: str,
        argv: tuple[str, ...],
        cwd: Path,
        environment: dict[str, str],
        started_at: datetime,
        returncode: int,
        paths: tuple[Path, Path],
    ) -> CommandRecord:
        """Append one command record to ``commands.jsonl``."""
        record = CommandRecord(
            ordinal=ordinal,
            step=step,
            label=label,
            argv=argv,
            cwd=str(cwd),
            environment=environment,
            started_at=started_at,
            ended_at=datetime.now(UTC),
            returncode=returncode,
            stdout_sha256=hashlib.sha256(paths[0].read_bytes()).hexdigest(),
            stderr_sha256=hashlib.sha256(paths[1].read_bytes()).hexdigest(),
        )
        with (self.output / "commands.jsonl").open("ab") as stream:
            stream.write(msgspec.json.encode(record) + b"\n")
        return record

    def run(
        self,
        step: Step,
        label: str,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str] | None = None,
        timeout: float = 3600,
    ) -> tuple[CommandRecord, bytes]:
        """Run one command to completion and return its record and stdout."""
        overrides = environment or {}
        ordinal, *paths = self._paths(label)
        started_at = datetime.now(UTC)
        with paths[0].open("wb") as stdout, paths[1].open("wb") as stderr:
            completed = subprocess.run(  # nosec B603  # [owner=runtime; rationale=explicit argv of declared journey commands; expires=2027-03-01]
                argv,
                cwd=cwd,
                env={**os.environ, **overrides},
                stdout=stdout,
                stderr=stderr,
                timeout=timeout,
                check=False,
            )
        record = self._record(
            ordinal,
            step,
            label,
            argv,
            cwd,
            overrides,
            started_at,
            completed.returncode,
            (paths[0], paths[1]),
        )
        return record, paths[0].read_bytes()

    def start(self, step: Step, label: str, argv: tuple[str, ...], *, cwd: Path) -> Background:
        """Start one long-running command; ``finish`` records it."""
        ordinal, stdout_path, stderr_path = self._paths(label)
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            child = subprocess.Popen(  # nosec B603  # [owner=runtime; rationale=explicit argv of declared journey commands; expires=2027-03-01]
                argv, cwd=cwd, stdout=stdout, stderr=stderr
            )
        return Background(
            child, ordinal, step, label, argv, (stdout_path, stderr_path), datetime.now(UTC)
        )

    def finish(self, background: Background, *, cwd: Path, timeout: float) -> CommandRecord:
        """Wait for a started command, terminating it at the timeout, and record it."""
        try:
            returncode = background.child.wait(timeout=max(1.0, timeout))
        except subprocess.TimeoutExpired:
            background.child.terminate()
            returncode = background.child.wait(timeout=60)
        return self._record(
            background.ordinal,
            background.step,
            background.label,
            background.argv,
            cwd,
            {},
            background.started_at,
            returncode,
            background.paths,
        )

    def run_pool(
        self,
        step: Step,
        commands: tuple[tuple[str, tuple[str, ...]], ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        workers: int,
        timeout: float,
    ) -> tuple[CommandRecord, ...]:
        """Run labelled commands at most ``workers`` at a time; return records in input order."""
        overrides = {**os.environ, **environment}
        waiting = list(commands)
        running: list[
            tuple[subprocess.Popen[bytes], int, str, tuple[str, ...], tuple[Path, Path], datetime]
        ] = []
        records: dict[str, CommandRecord] = {}
        deadline = time.monotonic() + timeout
        while waiting or running:
            while waiting and len(running) < workers:
                label, argv = waiting.pop(0)
                ordinal, stdout_path, stderr_path = self._paths(label)
                with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                    child = subprocess.Popen(  # nosec B603  # [owner=runtime; rationale=explicit argv of declared journey commands; expires=2027-03-01]
                        argv, cwd=cwd, env=overrides, stdout=stdout, stderr=stderr
                    )
                running.append(
                    (child, ordinal, label, argv, (stdout_path, stderr_path), datetime.now(UTC))
                )
            time.sleep(0.5)
            for item in tuple(running):
                child, ordinal, label, argv, paths, started_at = item
                returncode = child.poll()
                if returncode is None and time.monotonic() < deadline:
                    continue
                if returncode is None:
                    child.terminate()
                    returncode = child.wait(timeout=60)
                running.remove(item)
                records[label] = self._record(
                    ordinal, step, label, argv, cwd, environment, started_at, returncode, paths
                )
        return tuple(records[label] for label, _ in commands)

    def run_concurrently(
        self,
        step: Step,
        commands: tuple[tuple[str, tuple[str, ...]], ...],
        *,
        cwd: Path,
        timeout: float,
    ) -> tuple[CommandRecord, ...]:
        """Start labelled commands together and record each as it ends."""
        started: list[tuple[int, str, tuple[str, ...], tuple[Path, Path], datetime]] = []
        children: list[subprocess.Popen[bytes]] = []
        for label, argv in commands:
            ordinal, stdout_path, stderr_path = self._paths(label)
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                children.append(
                    subprocess.Popen(  # nosec B603  # [owner=runtime; rationale=explicit argv of declared journey commands; expires=2027-03-01]
                        argv, cwd=cwd, stdout=stdout, stderr=stderr
                    )
                )
            started.append((ordinal, label, argv, (stdout_path, stderr_path), datetime.now(UTC)))
        deadline = time.monotonic() + timeout
        records: list[CommandRecord] = []
        for child, (ordinal, label, argv, paths, started_at) in zip(children, started, strict=True):
            try:
                returncode = child.wait(timeout=max(1.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.terminate()
                returncode = child.wait(timeout=60)
            records.append(
                self._record(ordinal, step, label, argv, cwd, {}, started_at, returncode, paths)
            )
        return tuple(records)


class Background:
    """One started command whose record is written when it ends."""

    def __init__(
        self,
        child: subprocess.Popen[bytes],
        ordinal: int,
        step: Step,
        label: str,
        argv: tuple[str, ...],
        paths: tuple[Path, Path],
        started_at: datetime,
    ) -> None:
        """Bind the child and the record fields reserved for it."""
        self.child, self.ordinal, self.step, self.label = child, ordinal, step, label
        self.argv, self.paths, self.started_at = argv, paths, started_at


class AlertReceiver:
    """Retain every local datagram alert sent to the declared socket."""

    def __init__(self, path: Path, output: Path) -> None:
        """Bind the socket and start retaining; ``close`` stops it."""
        path.unlink(missing_ok=True)
        self.path, self.output = path, output
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.socket.bind(str(path))
        self.socket.settimeout(0.2)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._receive, name="journey-alerts", daemon=True)
        self._thread.start()

    def _receive(self) -> None:
        """Append each datagram with its receipt clock until stopped."""
        while not self._stop.is_set():
            try:
                payload = self.socket.recv(65536)
            except TimeoutError:
                continue
            received: dict[str, object] = {
                "received_at": datetime.now(UTC),
                "datagram": payload.decode(errors="replace"),
            }
            with self.output.open("ab") as stream:
                stream.write(msgspec.json.encode(received) + b"\n")

    def close(self) -> None:
        """Stop receiving and remove the socket."""
        self._stop.set()
        self._thread.join(5)
        self.socket.close()
        self.path.unlink(missing_ok=True)


class GuideCoverage:
    """Require every supported name a QR workspace imports to appear in a linked guide."""

    def __init__(self, checkout: Path, guides: tuple[str, ...]) -> None:
        """Bind the frozen checkout and the declared entry guides."""
        self.checkout = checkout
        self.guides = guides

    def documents(self) -> dict[str, str]:
        """Read the entry guides and every Markdown file they link, by relative path."""
        texts: dict[str, str] = {}
        for entry in self.guides:
            path = self.checkout / entry
            texts[entry] = path.read_text()
            for target in self.links(texts[entry]):
                linked = (path.parent / target).resolve()
                if linked.suffix == ".md" and linked.is_relative_to(self.checkout.resolve()):
                    texts.setdefault(
                        str(linked.relative_to(self.checkout.resolve())), linked.read_text()
                    )
        return texts

    @staticmethod
    def links(text: str) -> tuple[str, ...]:
        """Return the local targets of every inline Markdown link, without fragments."""
        targets: list[str] = []
        for part in text.split("](")[1:]:
            target = part.split(")", 1)[0].split("#", 1)[0].strip()
            if (
                target
                and " " not in target
                and not target.startswith(("http:", "https:", "mailto:"))
            ):
                targets.append(target)
        return tuple(targets)

    @staticmethod
    def imported(workspace: Path) -> dict[str, tuple[str, ...]]:
        """List each platform name the workspace imports, with the files importing it."""
        names: dict[str, list[str]] = {}
        for path in sorted(workspace.rglob("*.py")):
            tree = ast.parse(path.read_bytes(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.module is None:
                    continue
                if node.module.split(".")[0] not in PLATFORM_PACKAGES:
                    continue
                for alias in node.names:
                    names.setdefault(alias.name, []).append(str(path.relative_to(workspace)))
        return {name: tuple(files) for name, files in names.items()}

    def assess(self, workspace: Path) -> tuple[Gate, tuple[str, ...]]:
        """Assess coverage and return the uncovered names; each is a guide gap."""
        documents = self.documents()
        corpus = "\n".join(documents.values())
        imported = self.imported(workspace)
        uncovered = {
            name: files
            for name, files in imported.items()
            if re.search(rf"\b{re.escape(name)}\b", corpus) is None
        }
        observed = {
            "guides": sorted(documents),
            "imported": sorted(imported),
            "uncovered": uncovered,
        }
        return Gate("guide_coverage", not uncovered, observed), tuple(sorted(uncovered))


class Journey:
    """Own one attempt's ordered steps, evidence and first-failure stop."""

    def __init__(self, declaration: JourneyDeclaration, declaration_bytes: bytes) -> None:
        """Bind the declaration and derive every attempt path; nothing runs until ``run``."""
        self.declaration = declaration
        self.declaration_bytes = declaration_bytes
        self.output = Path(declaration.evidence_root) / declaration.attempt
        self.temporary = Path(declaration.temporary_root) / declaration.attempt
        self.checkout = self.output / "checkout"
        self.qr = self.output / "qr"
        self.consumers = self.output / "consumers"
        self.research_python = self.temporary / "research/bin/python"
        self.build_bin = self.temporary / "build/bin"
        self.records: dict[Step, StepRecord] = {step: StepRecord(step=step) for step in STEPS}
        self.current: Step = "J1"
        self.commands: Commands | None = None
        self.summary: Summary | None = None

    def write_summary(self) -> None:
        """Rewrite ``summary.json`` with every step's current record."""
        if self.summary is None:
            return
        self.summary.steps = [self.records[step] for step in STEPS]
        (self.output / "summary.json").write_bytes(
            msgspec.json.format(msgspec.json.encode(self.summary))
        )

    def command(
        self,
        label: str,
        argv: tuple[str, ...],
        *,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
        timeout: float = 3600,
    ) -> bytes:
        """Run one command of the current step; a nonzero exit fails the step."""
        if self.commands is None:
            raise RuntimeError("journey commands run only inside an attempt")
        record, stdout = self.commands.run(
            self.current,
            label,
            argv,
            cwd=cwd or self.output,
            environment=environment,
            timeout=timeout,
        )
        self.records[self.current].commands.append(record.ordinal)
        self.require(
            f"{label}_exit_zero", record.returncode == 0, {"returncode": record.returncode}
        )
        return stdout

    def require(self, name: str, passed: bool, observed: object) -> None:
        """Retain one criterion and stop the attempt if it failed."""
        self.records[self.current].criteria.append(Gate(name, passed, observed))
        if not passed:
            raise StepFailed(self.current, name, observed)

    def gates(self, gates: tuple[Gate, ...], prefix: str) -> None:
        """Retain reported criteria in order, stopping at the first failed one."""
        for gate in gates:
            self.require(f"{prefix}{gate.name}", gate.passed, gate.observed)

    @property
    def qr_environment(self) -> dict[str, str]:
        """Name the private key files; the QR script opens the lakeFS and ClearML keys itself."""
        return {
            "ALPHA_LAKEFS_CREDENTIALS": self.declaration.lakefs_credentials,
            "ALPHA_CLEARML_LOCAL_ENV": self.declaration.local_services_env,
        }

    def qr_argv(self, label: str, script: str, *arguments: str) -> tuple[str, ...]:
        """Return one QR script's command line, writing its result beside the step's outputs."""
        return (
            str(self.research_python),
            "-I",
            str(self.qr / "studies" / script),
            *arguments,
            "--result",
            str(self.output / self.current.lower() / f"{label}.result.json"),
        )

    def qr_result(self, label: str) -> None:
        """Retain the criteria and findings a QR script reported."""
        result = self.output / self.current.lower() / f"{label}.result.json"
        reported = msgspec.json.decode(result.read_bytes(), type=QRResult)
        self.records[self.current].findings.extend(reported.findings)
        self.gates(reported.criteria, f"{label}:")

    def qr_script(self, label: str, script: str, *arguments: str, timeout: float = 7200) -> None:
        """Run one QR script with ``--result`` and retain its criteria and findings."""
        self.command(
            label,
            self.qr_argv(label, script, *arguments),
            environment=self.qr_environment,
            timeout=timeout,
        )
        self.qr_result(label)

    def qr_pool(self, scripts: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
        """Run independent QR scripts in the declared bounded pool, then retain each result."""
        if self.commands is None:
            raise RuntimeError("journey commands run only inside an attempt")
        records = self.commands.run_pool(
            self.current,
            tuple((label, self.qr_argv(label, *arguments)) for label, arguments in scripts),
            cwd=self.output,
            environment=self.qr_environment,
            workers=self.declaration.research_workers,
            timeout=4 * 3600,
        )
        for record in records:
            self.records[self.current].commands.append(record.ordinal)
            self.require(
                f"{record.label}_exit_zero",
                record.returncode == 0,
                {"returncode": record.returncode},
            )
            self.qr_result(record.label)

    def check(self, name: str, *arguments: str) -> None:
        """Run one independent check under the research interpreter and retain its gates."""
        stdout = self.command(
            f"check-{name}",
            (
                str(self.research_python),
                "-I",
                str(self.consumers / "journey_checks.py"),
                name,
                "--extension",
                EXTENSION,
                *arguments,
            ),
        )
        self.gates(msgspec.json.decode(stdout, type=tuple[Gate, ...]), f"check:{name}:")

    def freeze(self) -> tuple[dict[str, str], dict[str, str]]:
        """Pin the frozen checkout, this driver and the QR workspace; return their digests."""
        declaration = self.declaration
        repository = Path(declaration.repository)
        status = self.command("repository-status", ("git", "status", "--porcelain"), cwd=repository)
        head = self.command("repository-head", ("git", "rev-parse", "HEAD"), cwd=repository)
        self.require(
            "repository_clean_at_declared_commit",
            not status.strip() and head.decode().strip() == declaration.commit,
            {"head": head.decode().strip(), "dirty": status.decode().splitlines()},
        )
        self.command(
            "worktree",
            (
                "git",
                "-C",
                str(repository),
                "worktree",
                "add",
                "--detach",
                str(self.checkout),
                declaration.commit,
            ),
        )
        source = self.checkout / "tests/integration/consumers/journey"
        self.consumers.mkdir()
        digests: dict[str, str] = {}
        for path in sorted(source.glob("*.py")):
            if not path.name.startswith("test_"):
                shutil.copy2(path, self.consumers / path.name)
                digests[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        running = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.require(
            "driver_is_frozen_copy",
            digests.get(Path(__file__).name) == running,
            {"running": running, "frozen": digests},
        )
        workspace = Path(declaration.qr_workspace)
        qr_status = self.command("qr-status", ("git", "status", "--porcelain"), cwd=workspace)
        qr_head = self.command("qr-head", ("git", "rev-parse", "HEAD"), cwd=workspace)
        self.require(
            "qr_workspace_clean_at_declared_commit",
            not qr_status.strip() and qr_head.decode().strip() == declaration.qr_commit,
            {"head": qr_head.decode().strip(), "dirty": qr_status.decode().splitlines()},
        )
        tree = self.command(
            "qr-tree", ("git", "rev-parse", f"{declaration.qr_commit}^{{tree}}"), cwd=workspace
        )
        archive = self.output / "qr.tar"
        self.command(
            "qr-archive",
            ("git", "archive", "--format=tar", "-o", str(archive), declaration.qr_commit),
            cwd=workspace,
        )
        with tarfile.open(archive) as bundle:
            bundle.extractall(self.qr, filter="data")
        guides = {
            name: hashlib.sha256((self.checkout / name).read_bytes()).hexdigest()
            for name in declaration.guides
        }
        qr = {"commit": declaration.qr_commit, "tree": tree.decode().strip()}
        return qr, {**guides, **{f"consumers/{name}": value for name, value in digests.items()}}

    def provision(self) -> None:
        """J1: environments, extension, worker, services, audits and the collector release."""
        uv = self.declaration.uv
        checkout = self.checkout
        self.command("python-install", (uv, "python", "install"), cwd=checkout)
        for name in ("build", "research"):
            self.command(
                f"sync-{name}",
                (uv, "sync", "--frozen", "--no-editable"),
                cwd=checkout,
                environment={"UV_PROJECT_ENVIRONMENT": str(self.temporary / name)},
            )
        self.command(
            "install-extension",
            (
                uv,
                "pip",
                "install",
                "--python",
                str(self.research_python),
                "--no-deps",
                str(self.qr / EXTENSION),
            ),
            cwd=checkout,
        )
        self.command(
            "sync-feast-worker",
            (uv, "sync", "--frozen", "--project", "configs/development/research-worker"),
            cwd=checkout,
            environment={"UV_CACHE_DIR": "/private/tmp/uv-cache-research-worker"},
        )
        services = f"LOCAL_SERVICES_ENV={self.declaration.local_services_env}"
        self.command("local-services-up", ("make", "local-services-up", services), cwd=checkout)
        self.command(
            "local-services-status", ("make", "local-services-status", services), cwd=checkout
        )
        self.command(
            "import-audit",
            (
                str(self.build_bin / "alpha-governance-engineering-standards"),
                "import-audit",
                str(self.qr),
            ),
            cwd=checkout,
        )
        coverage, uncovered = GuideCoverage(checkout, self.declaration.guides).assess(self.qr)
        if self.declaration.counted:
            self.require(coverage.name, coverage.passed, coverage.observed)
        else:
            # A rehearsal records uncovered names as guide findings and continues.
            self.require("guide_coverage_recorded", True, coverage.observed)
            self.records["J1"].findings.extend(
                Finding(kind="guide", detail=f"no linked guide names {name}") for name in uncovered
            )
        self.check("environment", "--checkout", str(checkout))
        if self.summary is not None:
            for gate in self.records["J1"].criteria:
                if gate.name.startswith("check:environment:") and isinstance(gate.observed, dict):
                    self.summary.installed.update(
                        {
                            f"{gate.name.rsplit(':', 1)[-1]}.{key}": str(value)
                            for key, value in gate.observed.items()
                            if key in ("record_sha256", "identity")
                        }
                    )
        self.collector_release()

    def collector_release(self) -> None:
        """J1: fetch, build, verify and install a signed collector release."""
        root = self.output / "j1"
        keys = self.temporary / "keys"
        keys.mkdir(parents=True, mode=0o700)
        key = keys / "builder"
        self.command(
            "keygen",
            (
                "/usr/bin/ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                f"mr17-{self.declaration.attempt}",
                "-f",
                str(key),
            ),
        )
        key.chmod(0o600)
        policy, request = ReleaseInputs(self, key).collector(root)
        launcher = str(self.build_bin / "alpha-governance-artifacts")
        common = ("--policy", str(policy), "--request", str(request))
        self.command(
            "collector-fetch",
            (
                launcher,
                "fetch",
                "--repository",
                str(self.checkout),
                *common,
                "--dependencies",
                str(root / "wheels"),
            ),
        )
        built = self.command(
            "collector-build",
            (
                launcher,
                "build",
                "--repository",
                str(self.checkout),
                *common,
                "--configuration",
                str(root / "collector-config.json"),
                "--dependencies",
                str(root / "wheels"),
                "--audit",
                str(root / "audit"),
                "--key",
                str(key),
                "--registry",
                str(root / "registry"),
            ),
        )
        release = built.decode().strip().splitlines()[-1]
        self.command(
            "collector-verify", (launcher, "verify", "--release", release, "--policy", str(policy))
        )
        self.command(
            "collector-install",
            (
                launcher,
                "install",
                "--release",
                release,
                "--policy",
                str(policy),
                "--target",
                str(root / "target-collector"),
            ),
        )
        self.require("collector_release_installed", True, {"release": Path(release).name})

    def data(self) -> None:
        """J2: fixed-window capture of every feed, replay, publication, discovery and reopening."""
        root = self.output / "j2"
        (root / "config").mkdir(parents=True)
        window = self.declaration.window
        start = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=window.lead_seconds)
        window_record: dict[str, object] = {
            "start_at": start,
            "ready_by": start + timedelta(seconds=window.ready_seconds),
            "stop_at": start + timedelta(seconds=window.duration_seconds),
            "max_messages": window.max_messages,
            "max_bytes": window.max_bytes,
            "max_segments": window.max_segments,
            "max_reconnects": window.max_reconnects,
            "schema_version": "1",
        }
        (root / "window.json").write_bytes(msgspec.json.encode(window_record))
        collect = str(self.temporary / "research/bin/alpha-collect")
        captures: list[tuple[str, tuple[str, ...]]] = []
        shutil.copy2(self.qr / "data/universes.json", root / "config/universes.json")
        for feed in self.declaration.feeds:
            shutil.copy2(self.qr / "data/feeds" / f"{feed}.json", root / "config" / f"{feed}.json")
            captures.append(
                (
                    f"capture-{feed}",
                    (
                        collect,
                        "capture-run",
                        "--config",
                        str(root / "config" / f"{feed}.json"),
                        "--universes",
                        str(root / "config/universes.json"),
                        "--window",
                        str(root / "window.json"),
                        "--run-directory",
                        str(root / "runs" / feed),
                    ),
                )
            )
        (root / "runs").mkdir()
        if self.commands is None:
            raise RuntimeError("journey commands run only inside an attempt")
        records = self.commands.run_concurrently(
            "J2",
            tuple(captures),
            cwd=root,
            timeout=window.lead_seconds + window.duration_seconds + 900,
        )
        self.records["J2"].commands.extend(record.ordinal for record in records)
        for record in records:
            self.require(
                f"{record.label}_exit_zero",
                record.returncode == 0,
                {"returncode": record.returncode},
            )
        for feed in self.declaration.feeds:
            self.command(
                f"replay-{feed}",
                (
                    collect,
                    "capture-run-replay",
                    "--run-directory",
                    str(root / "runs" / feed),
                    "--max-seconds",
                    "7200",
                ),
                timeout=7500,
            )
        (root / "snapshots").mkdir()
        self.qr_script(
            "publish",
            "j2_publish.py",
            "--runs",
            str(root / "runs"),
            "--store",
            str(root / "raw"),
            "--snapshots",
            str(root / "snapshots"),
            "--lakefs-repository",
            self.declaration.lakefs_repository,
        )
        listed = self.command(
            "discover",
            (
                str(self.temporary / "research/bin/alpha-dataset"),
                "discover",
                "--snapshots",
                str(root / "snapshots"),
                "--max-entries",
                "100",
                "--max-bytes",
                "64000000",
            ),
        )
        discovered = msgspec.json.decode(listed, type=Discovery)
        trades = sum(feed.endswith("-trades") for feed in self.declaration.feeds)
        self.require(
            "catalog_lists_every_snapshot",
            discovered.status == "complete" and len(discovered.result) == 1 + trades,
            {
                "status": discovered.status,
                "snapshots": len(discovered.result),
                "expected": 1 + trades,
            },
        )
        self.qr_script(
            "reopen",
            "j2_reopen.py",
            "--snapshots",
            str(root / "snapshots"),
            "--lakefs-repository",
            self.declaration.lakefs_repository,
        )

    def research(self) -> None:
        """J3: rule and learned studies, grid, holdout, publication, reopening and P3."""
        snapshots = str(self.output / "j2/snapshots")
        attempts = str(self.output / "j3/attempts")
        (self.output / "j3").mkdir()
        # Every research instrument gets both candidates, as J6 deploys each of them.
        universes = msgspec.json.decode(
            (self.qr / "data/universes.json").read_bytes(), type=dict[str, list[str]]
        )
        # The studies are independent; the attempt store serializes their records.
        studies = tuple(
            (
                f"{kind}-{instrument[:8]}",
                (
                    "j3_study.py",
                    kind,
                    "--snapshots",
                    snapshots,
                    "--attempts",
                    attempts,
                    "--instrument",
                    instrument,
                ),
            )
            for kind in ("rule", "learned", "holdout")
            for instrument in universes["research"]
        )
        grid = ("j3_study.py", "grid", "--snapshots", snapshots, "--attempts", attempts)
        self.qr_pool((*studies, ("grid", grid)))
        self.qr_script("publish", "j3_publish.py", "--attempts", attempts)
        self.qr_script("reopen", "j3_reopen.py", "--attempts", attempts)
        self.qr_script(
            "extension", "j3_extension.py", "--snapshots", snapshots, "--attempts", attempts
        )
        self.check("research", "--attempts", attempts, "--holdouts", str(self.declaration.holdouts))

    def features(self) -> None:
        """J4: offline retrieval, a served stream and the declared feature faults."""
        root = self.output / "j4"
        root.mkdir()
        worker = str(self.checkout / "configs/development/research-worker/.venv/bin/python")
        common = (
            "--store",
            str(root / "store"),
            "--feast",
            str(root / "feast"),
            "--worker",
            worker,
        )
        snapshots = ("--snapshots", str(self.output / "j2/snapshots"))
        self.qr_script("define", "j4_features.py", "define", *common)
        self.qr_script("offline", "j4_features.py", "offline", *common, *snapshots)
        self.qr_script("stream", "j4_features.py", "stream", *common, *snapshots, "--version", "v1")
        self.qr_script("faults", "j4_features.py", "faults", *common, *snapshots)

    def candidates(self) -> None:
        """J5: package both candidates and replay them against the study."""
        root = self.output / "j5"
        root.mkdir()
        attempts = str(self.output / "j3/attempts")
        self.qr_script(
            "package",
            "j5_package.py",
            "--attempts",
            attempts,
            "--store",
            str(self.output / "j4/store"),
            "--candidates",
            str(root / "candidates"),
        )
        self.qr_script(
            "replay",
            "j5_replay.py",
            "--candidates",
            str(root / "candidates"),
            "--snapshots",
            str(self.output / "j2/snapshots"),
            "--attempts",
            attempts,
        )
        self.check("candidates", "--candidates", str(root / "candidates"), "--attempts", attempts)

    def paper_step(self, label: str, *arguments: str | Path) -> bytes:
        """Run one J6 operator step under the research interpreter."""
        return self.command(
            label,
            (
                str(self.research_python),
                "-I",
                str(self.consumers / "journey_paper.py"),
                *(str(item) for item in arguments),
            ),
        )

    @property
    def launcher(self) -> str:
        """Return the build environment's signed-artifact launcher."""
        return str(self.build_bin / "alpha-governance-artifacts")

    def paper(self) -> None:
        """J6: install signed services and accounts, then run P-A, P-B and S."""
        root = self.output / "j6"
        root.mkdir()
        (self.temporary / "s").mkdir(exist_ok=True)
        extension = root / "extensions" / EXTENSION
        shutil.copytree(self.qr / EXTENSION, extension)
        self.command(
            "import-audit",
            (
                str(self.build_bin / "alpha-governance-engineering-standards"),
                "import-audit",
                str(extension),
            ),
        )
        policy, requests = ReleaseInputs(self, self.temporary / "keys/builder").paper(root)
        first, second, shadow_seconds = self.declaration.phases
        paper = root / "paper"
        self.plan_phase(paper, "paper", first)
        services = self.install_services(paper, "paper", policy, requests["paper-services"], root)
        self.install_accounts(paper, "paper", policy, requests["paper-account"], root)
        self.claim_accounts(paper, "paper", policy, research=True)
        self.run_phase("P-A", paper, services, policy, first, scenarios=True)
        self.recover_accounts(paper, policy, paper / "service-p-a", "P-B")
        self.run_phase("P-B", paper, services, policy, second, shutdown=True)
        shadow = root / "shadow"
        self.plan_phase(shadow, "shadow", shadow_seconds)
        shadow_services = self.install_services(
            shadow, "shadow", policy, requests["shadow-services"], root
        )
        self.install_accounts(shadow, "shadow", policy, requests["shadow-account"], root)
        self.claim_accounts(shadow, "shadow", policy, research=False)
        self.run_phase("S", shadow, shadow_services, policy, shadow_seconds)

    def operations(self) -> None:
        """J7: quiesce, back up, restore and check, then resume, upgrade and roll back."""
        root = self.output / "j7"
        root.mkdir()
        j6 = self.output / "j6"
        paper, policy = j6 / "paper", j6 / "policy.json"
        services = paper / "services"
        resume, upgrade, rollback = self.declaration.operations
        signed = ("--launcher", self.launcher, "--targets", paper / "targets", "--policy", policy)
        accounts = self.accounts(paper)
        worker = str(self.checkout / "configs/development/research-worker/.venv/bin/python")
        # 1. Quiesce: no J6 process holds a fence, and every paper account is stopped.
        self.paper_gates("quiesce", "quiesce", "--plan", paper, *signed)
        # 2. Back up into one set beside the attempt: a backup cannot sit inside its source.
        backup = Path(self.declaration.evidence_root) / f"{self.declaration.attempt}.j7-backup"
        backup.mkdir()
        (root / "backup").symlink_to(backup)
        self.qr_script(
            "backup",
            "j7_backup.py",
            "--workspace",
            str(self.output),
            "--backup",
            str(backup / "research"),
            "--record",
            str(root / "research-backup.json"),
            "--worker",
            worker,
        )
        self.paper_step(
            "paper-backup",
            "backup",
            "--plan",
            paper,
            *signed,
            "--backup",
            backup,
            "--record",
            root / "paper-backup.json",
        )
        manifests = {
            name: hashlib.sha256((backup / name / "manifest.json").read_bytes()).hexdigest()
            for name in ("research", "paper", *(f"accounts/{item}" for item in accounts))
        }
        (backup / "backup-set.json").write_bytes(msgspec.json.encode(manifests))
        # 3. Restore into absent roots. The research sources move aside while the QR
        # checks, so a hidden path into them fails instead of passing.
        restored = root / "restored"
        restored.mkdir()
        aside = self.output / "j7-aside"
        aside.mkdir()
        moved = ("j2", "j3", "j4", "j5")
        try:
            for name in moved:
                (self.output / name).rename(aside / name)
            self.qr_script(
                "restore",
                "j7_restore.py",
                "--backup",
                str(backup / "research"),
                "--root",
                str(restored / "research"),
                "--record",
                str(root / "research-backup.json"),
                "--worker",
                worker,
            )
        finally:
            for name in moved:
                if (aside / name).exists():
                    (aside / name).rename(self.output / name)
            aside.rmdir()
        self.paper_gates(
            "paper-restore",
            "restore",
            "--plan",
            paper,
            *signed,
            "--backup",
            backup,
            "--restored",
            restored,
            "--record",
            root / "paper-backup.json",
        )
        # 4. Resume from the retained journals as the runbook's step 5, on services v1.
        self.recover_accounts(paper, policy, paper / "service-p-b", "R")
        self.run_phase("R", paper, services, policy, resume, shutdown=True)
        # 5. Upgrade to services v2, which activates the inactive instance.
        previous = self.receipt(services)
        upgraded = paper / "services-upgraded.json"
        self.paper_step(
            "services-upgrade", "upgrade", "--plan", paper, "--instance", LATE, "--output", upgraded
        )
        release = self.release(
            "paper-services-upgrade",
            j6 / "paper-services-request.json",
            policy,
            j6,
            "--configuration",
            upgraded,
            "--candidates",
            paper / "candidates",
            "--extensions",
            j6 / "extensions",
        )
        self.command(
            "services-upgrade-install",
            (
                self.launcher,
                "install",
                "--release",
                release,
                "--policy",
                str(policy),
                "--target",
                str(services),
            ),
        )
        installed = self.receipt(services)
        self.require(
            "upgrade_names_previous_release",
            installed["previous_release"] == previous["release"]
            and installed["release"] != previous["release"],
            {"release": installed["release"], "previous": installed["previous_release"]},
        )
        self.recover_accounts(paper, policy, paper / "service-r", "U")
        self.run_phase("U", paper, services, policy, upgrade, shutdown=True, stop_late=LATE)
        self.paper_gates(
            "U-late",
            "late",
            "--plan",
            paper,
            *signed,
            "--root",
            paper / "service-u",
            "--instance",
            LATE,
            "--services",
            upgraded,
        )
        # 6. Roll back to services v1, keeping every retained fact.
        self.paper_step(
            "B-facts-before",
            "facts",
            "--plan",
            paper,
            *signed,
            "--output",
            root / "facts-before.json",
        )
        self.command(
            "services-rollback",
            (
                self.launcher,
                "rollback",
                "--release",
                str(j6 / "registry" / str(previous["release"])),
                "--policy",
                str(policy),
                "--target",
                str(services),
            ),
        )
        rolled = self.receipt(services)
        checked = self.command(
            "B-services-check",
            (
                self.launcher,
                "run",
                "--target",
                str(services),
                "--policy",
                str(policy),
                "--",
                "deployment-check",
            ),
        )
        self.require(
            "rollback_selects_previous_release",
            rolled["release"] == previous["release"]
            and rolled["previous_release"] == installed["release"]
            and checked == (paper / "deployment-check.json").read_bytes(),
            {"release": rolled["release"], "previous": rolled["previous_release"]},
        )
        self.recover_accounts(paper, policy, paper / "service-u", "B")
        self.run_phase("B", paper, services, policy, rollback, shutdown=True)
        self.paper_step(
            "B-facts-after",
            "facts",
            "--plan",
            paper,
            *signed,
            "--output",
            root / "facts-after.json",
        )
        self.paper_gates(
            "B-rollback-check",
            "rollback-check",
            "--plan",
            paper,
            "--before",
            root / "facts-before.json",
            "--after",
            root / "facts-after.json",
            "--instance",
            LATE,
            "--root",
            paper / "service-u",
            "--services",
            upgraded,
        )
        # 7. Inherited: every paper decision is within its study's modelled entry delay.
        self.paper_gates(
            "entry-delays",
            "delays",
            "--plan",
            paper,
            "--attempts",
            self.output / "j3/attempts",
            "--roots",
            ",".join(str(paper / f"service-{name}") for name in ("p-a", "p-b", "r", "u", "b")),
            "--output",
            root / "delays.json",
        )
        # 8. Inherited: paper refuses only for account rules research does not model, or
        # for an operator control running at the decision's instant.
        controls = ControlWindows(
            controls=tuple(
                ControlWindow(
                    label=record.label, started_at=record.started_at, ended_at=record.ended_at
                )
                for line in (self.output / "commands.jsonl").read_bytes().splitlines()
                for record in (msgspec.json.decode(line, type=CommandRecord),)
                if record.step in ("J6", "J7")
                and any(part in record.label for part in ("-stop-", "-restart-", "-shutdown"))
            )
        )
        (root / "controls.json").write_bytes(msgspec.json.encode(controls))
        self.paper_gates(
            "budget-refusals",
            "refusals",
            "--plan",
            paper,
            *signed,
            "--controls",
            root / "controls.json",
            "--output",
            root / "refusals.json",
        )

    def paper_gates(self, label: str, *arguments: str | Path) -> None:
        """Run one operator step that prints criteria, and retain them."""
        stdout = self.paper_step(label, *arguments)
        # A failed step has already been retained as its step's failure.
        if stdout:
            self.gates(msgspec.json.decode(stdout, type=tuple[Gate, ...]), f"{label}:")

    @staticmethod
    def receipt(target: Path) -> dict[str, object]:
        """Read an installed target's current installation receipt."""
        return msgspec.json.decode((target / "current.json").read_bytes(), type=dict[str, object])

    def plan_phase(self, plan: Path, mode: str, seconds: int) -> None:
        """Author a mode's services and account definitions from the J5 candidates."""
        features = plan / "features"
        self.paper_step(
            f"{mode}-plan",
            "plan",
            "--plan",
            plan,
            "--mode",
            mode,
            "--qr",
            self.qr,
            "--candidates",
            self.output / "j5/candidates",
            "--sockets",
            self.temporary / "s",
            "--store",
            features / "store.sqlite3",
            "--serving-root",
            features / "feast",
            "--worker",
            self.checkout / "configs/development/research-worker/.venv/bin/python",
            "--alert-socket",
            self.temporary / "s/alert.sock",
            "--duration",
            str(seconds),
        )

    def release(
        self, label: str, request: Path, policy: Path, root: Path, *extra: str | Path
    ) -> str:
        """Fetch, build and verify one signed release; return its path."""
        wheels = root / f"wheels-{request.stem}"
        common = ("--request", str(request), "--policy", str(policy))
        if not wheels.exists():
            self.command(
                f"{label}-fetch",
                (
                    self.launcher,
                    "fetch",
                    "--repository",
                    str(self.checkout),
                    *common,
                    "--dependencies",
                    str(wheels),
                ),
            )
        built = self.command(
            f"{label}-build",
            (
                self.launcher,
                "build",
                "--repository",
                str(self.checkout),
                *common,
                "--dependencies",
                str(wheels),
                "--audit",
                str(root / f"audit-{label}"),
                "--key",
                str(self.temporary / "keys/builder"),
                "--registry",
                str(root / "registry"),
                *(str(item) for item in extra),
            ),
        )
        release = built.decode().strip().splitlines()[-1]
        self.command(
            f"{label}-verify",
            (self.launcher, "verify", "--release", release, "--policy", str(policy)),
        )
        return release

    def install_services(
        self, plan: Path, mode: str, policy: Path, request: Path, root: Path
    ) -> Path:
        """Build, install and check a mode's signed services with the QR's candidates."""
        release = self.release(
            f"{mode}-services",
            request,
            policy,
            root,
            "--configuration",
            plan / "services.json",
            "--candidates",
            plan / "candidates",
            "--extensions",
            root / "extensions",
        )
        target = plan / "services"
        self.command(
            f"{mode}-services-install",
            (
                self.launcher,
                "install",
                "--release",
                release,
                "--policy",
                str(policy),
                "--target",
                str(target),
            ),
        )
        checked = self.command(
            f"{mode}-services-check",
            (
                self.launcher,
                "run",
                "--target",
                str(target),
                "--policy",
                str(policy),
                "--",
                "deployment-check",
            ),
        )
        # Deployments are authored from the identities the installed release computes.
        (plan / "deployment-check.json").write_bytes(checked)
        return target

    def accounts(self, plan: Path) -> tuple[str, ...]:
        """Return a plan's account identities in configuration order."""
        services = msgspec.json.decode(
            (plan / "services.json").read_bytes(), type=dict[str, object]
        )
        accounts = services["accounts"]
        if not isinstance(accounts, list):
            raise ValueError("planned services name no accounts")
        return tuple(str(item["account_id"]) for item in accounts if isinstance(item, dict))

    def install_accounts(
        self, plan: Path, mode: str, policy: Path, request: Path, root: Path
    ) -> None:
        """Build and install one signed execution target per account."""
        for account_id in self.accounts(plan):
            release = self.release(
                f"{account_id}-account",
                request,
                policy,
                root,
                "--configuration",
                plan / f"account-{account_id}.json",
            )
            self.command(
                f"{account_id}-install",
                (
                    self.launcher,
                    "install",
                    "--release",
                    release,
                    "--policy",
                    str(policy),
                    "--target",
                    str(plan / "targets" / account_id),
                ),
            )
        self.records[self.current].criteria.append(
            Gate(f"{mode}_accounts_installed", True, {"accounts": self.accounts(plan)})
        )

    def claim_accounts(self, plan: Path, mode: str, policy: Path, *, research: bool) -> None:
        """Install each deployment and grant and claim its owner; J2's grant refusal first."""
        universes = msgspec.json.decode(
            (self.qr / "data/universes.json").read_bytes(), type=dict[str, list[str]]
        )
        for index, account_id in enumerate(self.accounts(plan)):
            refusal = (
                ("--research", ",".join(universes["research"])) if research and index == 0 else ()
            )
            stdout = self.paper_step(
                f"{account_id}-claim",
                "claim",
                "--plan",
                plan,
                "--mode",
                mode,
                "--launcher",
                self.launcher,
                "--targets",
                plan / "targets",
                "--policy",
                policy,
                "--account",
                account_id,
                "--quote",
                "1",
                *refusal,
            )
            if refusal:
                claimed = msgspec.json.decode(stdout, type=dict[str, object])
                grant = claimed.get("research_grant")
                self.require(
                    "research_grant_refused_unchanged",
                    isinstance(grant, dict)
                    and grant.get("refused") is True
                    and "excludes the installed release" in str(grant.get("error"))
                    and grant.get("unchanged") is True,
                    grant,
                )
        self.paper_step(f"{mode}-owners", "owners", "--plan", plan)

    def recover_accounts(self, plan: Path, policy: Path, service_root: Path, phase: str) -> None:
        """Settle and reclaim every account after a phase, then write fresh owners."""
        for account_id in self.accounts(plan):
            self.paper_step(
                f"{phase}-{account_id}-reclaim",
                "reclaim",
                "--plan",
                plan,
                "--launcher",
                self.launcher,
                "--targets",
                plan / "targets",
                "--policy",
                policy,
                "--account",
                account_id,
                "--root",
                service_root,
            )
        self.paper_step(f"{phase}-owners", "owners", "--plan", plan)

    def control(
        self,
        plan: Path,
        services: Path,
        policy: Path,
        name: str,
        request: dict[str, object] | Path,
        *,
        required: bool = True,
    ) -> dict[str, object]:
        """Send one supervisor control through the signed launcher and return its answer.

        The command exits 0 even when the supervisor refuses, so a required control
        must also answer ``ok``.
        """
        if isinstance(request, Path):
            path = request
        else:
            path = plan / "controls" / f"{name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(msgspec.json.encode(request))
        stdout = self.command(
            name,
            (
                self.launcher,
                "run",
                "--target",
                str(services),
                "--policy",
                str(policy),
                "--",
                "deployment-control",
                "--socket",
                str(self.temporary / "s/supervisor.sock"),
                "--request",
                str(path),
            ),
        )
        answer = msgspec.json.decode(stdout, type=dict[str, object]) if stdout.strip() else {}
        if required:
            self.require(f"{name}_accepted", answer.get("ok") is True, answer)
        return answer

    def settle(
        self, pending: list[Background], background: Background, timeout: float
    ) -> CommandRecord:
        """Wait for one started phase command, record it and drop it from the pending."""
        if self.commands is None:
            raise RuntimeError("journey commands run only inside an attempt")
        pending.remove(background)
        return self.commands.finish(background, cwd=self.output, timeout=timeout)

    def run_phase(
        self,
        name: str,
        plan: Path,
        services: Path,
        policy: Path,
        seconds: int,
        *,
        scenarios: bool = False,
        shutdown: bool = False,
        stop_late: str | None = None,
    ) -> None:
        """Serve every account, run the publisher and supervisor for one phase, then verify it.

        P-A runs the declared scenarios and ends with its configured life. A phase run
        on a longer-lived configuration ends by a ``shutdown`` control, and
        ``stop_late`` stops that instance 30 s before it.
        """
        if self.commands is None:
            raise RuntimeError("journey commands run only inside an attempt")
        # Workspace component names are lower case, so J7 can back up each root.
        service_root = plan / f"service-{name.lower()}"
        sockets = self.temporary / "s"
        alerts = plan / f"alerts-{name}.jsonl"
        receiver = AlertReceiver(sockets / "alert.sock", alerts)
        pending: list[Background] = []
        try:
            self.paper_step(
                f"{name}-serve-requests",
                "serve-requests",
                "--plan",
                plan,
                "--seconds",
                str(seconds + 180),
            )
            accounts = self.accounts(plan)
            serves = {
                account_id: self.commands.start(
                    self.current,
                    f"{name}-serve-{account_id}",
                    (
                        self.launcher,
                        "run",
                        "--target",
                        str(plan / "targets" / account_id),
                        "--policy",
                        str(policy),
                        "--",
                        "account",
                        "--request",
                        str(plan / f"serve-{account_id}.json"),
                    ),
                    cwd=self.output,
                )
                for account_id in accounts
            }
            pending.extend(serves.values())
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and not all(
                (sockets / f"{account_id}.sock").exists() for account_id in accounts
            ):
                time.sleep(0.5)
            self.require(
                f"{name}:accounts_served",
                all((sockets / f"{account_id}.sock").exists() for account_id in accounts),
                {account_id: (sockets / f"{account_id}.sock").exists() for account_id in accounts},
            )
            launch = (
                self.launcher,
                "run",
                "--target",
                str(services),
                "--policy",
                str(policy),
                "--",
            )
            publisher = self.commands.start(
                self.current,
                f"{name}-publisher",
                (*launch, "feature-publisher", "--root", str(service_root)),
                cwd=self.output,
            )
            pending.append(publisher)
            supervisor = self.commands.start(
                self.current,
                f"{name}-supervisor",
                (
                    *launch,
                    "deployment",
                    "--owners",
                    str(plan / "owners.json"),
                    "--root",
                    str(service_root),
                    "--socket",
                    str(sockets / "supervisor.sock"),
                ),
                cwd=self.output,
            )
            pending.append(supervisor)
            stop = plan / f"reconcile-{name}.stop"
            reconciler = self.commands.start(
                self.current,
                f"{name}-reconciler",
                (
                    str(self.research_python),
                    "-I",
                    str(self.consumers / "journey_paper.py"),
                    "reconcile",
                    "--plan",
                    str(plan),
                    "--root",
                    str(service_root),
                    "--period",
                    "60",
                    "--stop",
                    str(stop),
                ),
                cwd=self.output,
            )
            pending.append(reconciler)
            started = time.monotonic()
            scenario: dict[str, object] = {}
            if scenarios:
                time.sleep(max(0.0, started + seconds / 3 - time.monotonic()))
                subject = "learned-okx-btc"
                self.control(
                    plan,
                    services,
                    policy,
                    f"{name}-stop-{subject}",
                    {
                        "action": "stop_instance",
                        "identity": f"stop-{subject}-{name}",
                        "subject": subject,
                    },
                )
                time.sleep(20)
                # A decision landing between the observation and the restart makes the
                # observation stale, which the account refuses; observe again and resend.
                for attempt in range(1, 4):
                    restart = plan / "controls" / f"{name}-restart-{subject}-{attempt}.json"
                    self.paper_step(
                        f"{name}-restart-observation-{attempt}",
                        "observation",
                        "--plan",
                        plan,
                        "--root",
                        service_root,
                        "--account",
                        "okx-shared",
                        "--instance",
                        subject,
                        "--output",
                        restart,
                    )
                    answer = self.control(
                        plan,
                        services,
                        policy,
                        f"{name}-restart-{subject}-{attempt}",
                        restart,
                        required=attempt == 3,
                    )
                    if answer.get("ok") is True:
                        break
                time.sleep(max(0.0, started + seconds - 90 - time.monotonic()))
                scenario["owner_death"] = self.owner_death(serves["okx-isolated"], service_root)
            elif shutdown:
                if stop_late is not None:
                    time.sleep(max(0.0, started + seconds - 30 - time.monotonic()))
                    self.control(
                        plan,
                        services,
                        policy,
                        f"{name}-stop-{stop_late}",
                        {
                            "action": "stop_instance",
                            "identity": f"stop-{stop_late}-{name}",
                            "subject": stop_late,
                        },
                    )
                time.sleep(max(0.0, started + seconds - time.monotonic()))
                self.control(
                    plan,
                    services,
                    policy,
                    f"{name}-shutdown",
                    {"action": "shutdown", "identity": f"shutdown-{name}"},
                )
            supervised = self.settle(pending, supervisor, seconds + 300)
            stop.touch()
            self.settle(pending, reconciler, 180)
            self.settle(pending, publisher, 180)
            for serve in serves.values():
                if serve.child.poll() is None:
                    serve.child.terminate()
                self.settle(pending, serve, 60)
        except BaseException:
            # A failed phase stops what it started, so nothing outlives the attempt.
            for background in tuple(pending):
                if background.child.poll() is None:
                    background.child.terminate()
                self.settle(pending, background, 60)
            raise
        finally:
            receiver.close()
        self.records[self.current].criteria.append(
            Gate(
                f"{name}:supervisor_ended", True, {"returncode": supervised.returncode, **scenario}
            )
        )
        stdout = self.paper_step(
            f"{name}-verify",
            "verify",
            "--plan",
            plan,
            "--root",
            service_root,
            "--alerts",
            alerts,
            "--launcher",
            self.launcher,
            "--targets",
            plan / "targets",
            "--policy",
            policy,
            *(("--race",) if scenarios else ()),
        )
        # A failed verify has already been retained as its step's failure.
        if stdout:
            self.gates(msgspec.json.decode(stdout, type=tuple[Gate, ...]), f"{name}:")

    @staticmethod
    def owner_death(serve: Background, service_root: Path) -> dict[str, object]:
        """Kill an account owner, preferring the moment a supervisor request is in flight."""
        requests = service_root / "requests" / "okx-isolated"
        deadline = time.monotonic() + 30
        in_flight = False
        while time.monotonic() < deadline and not in_flight:
            newest = max((path.stat().st_mtime for path in requests.glob("*")), default=0.0)
            in_flight = time.time() - newest < 0.05
            time.sleep(0.005)
        os.kill(serve.child.pid, signal.SIGKILL)
        return {"account": "okx-isolated", "pid": serve.child.pid, "request_in_flight": in_flight}

    def capacity(self) -> None:
        """J8: link the accepted MR15 R1 and 2b records; pending while either is open."""
        records = self.declaration.capacity_records
        if len(records) != 2:
            self.records["J8"].status = "pending"
            self.records["J8"].criteria.append(
                Gate("mr15_records_accepted", False, {"records": records, "pending": True})
            )
            return
        self.require(
            "mr15_records_accepted",
            all(Path(path).is_file() for path in records),
            {"records": records},
        )

    def run(self) -> Summary:
        """Run the declared steps once, holding the host awake, stopping at the first failure.

        An idle-sleeping host freezes every capture and paper service; rehearsal
        development run 120 lost 18 of 60 captured minutes that way.
        """
        with HostAwake():
            return self._steps()

    def _steps(self) -> Summary:
        """Run the declared steps once, stopping at the first failure."""
        declaration = self.declaration
        through = STEPS.index(declaration.through)
        self.output.mkdir(parents=True, exist_ok=False)
        self.temporary.mkdir(parents=True, exist_ok=False)
        (self.output / "declaration.json").write_bytes(self.declaration_bytes)
        self.commands = Commands(self.output)
        actions: dict[Step, Callable[[], None]] = {
            "J1": self.provision,
            "J2": self.data,
            "J3": self.research,
            "J4": self.features,
            "J5": self.candidates,
            "J6": self.paper,
            "J7": self.operations,
            "J8": self.capacity,
        }
        started = datetime.now(UTC)
        self.records["J1"].started_at = started
        try:
            qr, guides = self.freeze()
        except StepFailed as failure:
            return self.finish(started, {}, {}, failure.failure)
        self.summary = Summary(
            attempt=declaration.attempt,
            counted=declaration.counted,
            commit=declaration.commit,
            declaration_sha256=hashlib.sha256(self.declaration_bytes).hexdigest(),
            qr_workspace=qr,
            guides=guides,
            installed={},
            started_at=started,
            steps=[],
        )
        for step in STEPS[: through + 1]:
            self.current = step
            record = self.records[step]
            record.started_at = record.started_at or datetime.now(UTC)
            self.write_summary()
            try:
                actions[step]()
            except StepFailed as failure:
                record.status, record.ended_at = "failed", datetime.now(UTC)
                return self.finish(started, qr, guides, failure.failure)
            except Exception as error:
                raised = FirstFailure(
                    step=step, criterion="step_raised", observed=f"{type(error).__name__}: {error}"
                )
                record.criteria.append(Gate("step_raised", False, raised.observed))
                record.status, record.ended_at = "failed", datetime.now(UTC)
                return self.finish(started, qr, guides, raised)
            record.ended_at = datetime.now(UTC)
            if record.status != "pending":
                record.status = "passed"
        return self.finish(started, qr, guides, None)

    def finish(
        self,
        started: datetime,
        qr: dict[str, str],
        guides: dict[str, str],
        failure: FirstFailure | None,
    ) -> Summary:
        """Close the summary with the attempt's result."""
        if self.summary is None:
            self.summary = Summary(
                attempt=self.declaration.attempt,
                counted=self.declaration.counted,
                commit=self.declaration.commit,
                declaration_sha256=hashlib.sha256(self.declaration_bytes).hexdigest(),
                qr_workspace=qr,
                guides=guides,
                installed={},
                started_at=started,
                steps=[],
            )
        if failure is not None:
            self.records[failure.step].status = "failed"
        self.summary.first_failure = failure
        self.summary.ended_at = datetime.now(UTC)
        if failure is not None:
            self.summary.result = "failed"
        elif self.declaration.through == "J8" and all(
            record.status == "passed" for record in self.records.values()
        ):
            self.summary.result = "passed"
        else:
            self.summary.result = "stopped"
        self.write_summary()
        return self.summary


class ReleaseInputs:
    """Author the operator's policy and build request for a signed release."""

    def __init__(self, journey: Journey, key: Path) -> None:
        """Bind the attempt and its builder key."""
        self.journey = journey
        self.key = key

    @staticmethod
    def sha256(path: Path) -> str:
        """Digest one pinned tool."""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def policy(self, roots: list[str], schemas: list[str], states: list[str]) -> dict[str, object]:
        """Author an installation policy admitting this attempt's builder for ``roots``."""
        journey = self.journey
        # The build environment's own interpreter path, not its resolved base: the
        # builder checks the admitted hatchling installed in that environment.
        python = journey.temporary / "build/bin/python"
        uv = Path(journey.declaration.uv)
        keygen = Path("/usr/bin/ssh-keygen")
        now = datetime.now(UTC)
        return {
            "schema_version": "installation-policy",
            "target": "darwin_arm64",
            "python_executable": str(python),
            "python_sha256": self.sha256(python),
            "uv_executable": str(uv),
            "uv_sha256": self.sha256(uv),
            "ssh_keygen_executable": str(keygen),
            "ssh_keygen_sha256": self.sha256(keygen),
            "builders": [
                {
                    "identity": f"mr17-{journey.declaration.attempt}",
                    "public_key": " ".join(self.key.with_suffix(".pub").read_text().split()[:2]),
                    "origins": ["local-builder"],
                    "roots": roots,
                    "valid_from": (now - timedelta(minutes=1)).isoformat(),
                    "valid_until": (now + timedelta(days=7)).isoformat(),
                }
            ],
            "config_schemas": schemas,
            "state_schemas": states,
        }

    def request(self, name: str, runtime: dict[str, str]) -> dict[str, object]:
        """Author one build request for this attempt's builder."""
        label = f"mr17-{self.journey.declaration.attempt}"
        return {
            "name": f"{label}-{name}",
            "builder": label,
            "origin": "local-builder",
            "valid_until": (datetime.now(UTC) + timedelta(days=4)).isoformat(),
            "runtime": {
                "python_version": "3.14.7",
                "platform": "darwin_arm64",
                "contract_version": "1",
                **runtime,
            },
        }

    def paper(self, root: Path) -> tuple[Path, dict[str, Path]]:
        """Write the J6 policy and the paper and shadow services and account requests."""
        root.mkdir(parents=True, exist_ok=True)
        policy = self.policy(
            ["alpha-research-paper-services", "alpha-research-execution"],
            ["paper-services", "account-runtime"],
            ["none", "account-journal"],
        )
        (root / "policy.json").write_bytes(msgspec.json.encode(policy))
        requests: dict[str, Path] = {}
        for mode in ("paper", "shadow"):
            for kind, runtime in (
                (
                    "services",
                    {
                        "application": "paper-services",
                        "mode": mode,
                        "config_schema": "paper-services",
                        "state_schema": "none",
                    },
                ),
                (
                    "account",
                    {
                        "application": "execution",
                        "mode": mode,
                        "config_schema": "account-runtime",
                        "state_schema": "account-journal",
                    },
                ),
            ):
                path = root / f"{mode}-{kind}-request.json"
                path.write_bytes(msgspec.json.encode(self.request(f"{mode}-{kind}", runtime)))
                requests[f"{mode}-{kind}"] = path
        return root / "policy.json", requests

    def collector(self, root: Path) -> tuple[Path, Path]:
        """Write the collector release policy, request and capture configuration."""
        root.mkdir(parents=True, exist_ok=True)
        journey = self.journey
        # The build environment's own interpreter path, not its resolved base: the
        # builder checks the admitted hatchling installed in that environment.
        python = journey.temporary / "build/bin/python"
        uv = Path(journey.declaration.uv)
        keygen = Path("/usr/bin/ssh-keygen")
        now = datetime.now(UTC)
        label = f"mr17-{journey.declaration.attempt}"
        public_key = " ".join(self.key.with_suffix(".pub").read_text().split()[:2])
        policy = {
            "schema_version": "installation-policy",
            "target": "darwin_arm64",
            "python_executable": str(python),
            "python_sha256": self.sha256(python),
            "uv_executable": str(uv),
            "uv_sha256": self.sha256(uv),
            "ssh_keygen_executable": str(keygen),
            "ssh_keygen_sha256": self.sha256(keygen),
            "builders": [
                {
                    "identity": label,
                    "public_key": public_key,
                    "origins": ["local-builder"],
                    "roots": ["alpha-research-collector"],
                    "valid_from": (now - timedelta(minutes=1)).isoformat(),
                    "valid_until": (now + timedelta(days=7)).isoformat(),
                }
            ],
            "config_schemas": ["1"],
            "state_schemas": ["none"],
        }
        request = {
            "name": f"{label}-collector",
            "builder": label,
            "origin": "local-builder",
            "valid_until": (now + timedelta(days=4)).isoformat(),
            "runtime": {
                "python_version": "3.14.7",
                "platform": "darwin_arm64",
                "contract_version": "1",
                "application": "collector",
                "mode": "collection",
                "config_schema": "1",
                "state_schema": "none",
            },
        }
        shutil.copy2(
            journey.qr / "data/feeds" / f"{journey.declaration.feeds[0]}.json",
            root / "collector-config.json",
        )
        (root / "policy.json").write_bytes(msgspec.json.encode(policy))
        (root / "collector-request.json").write_bytes(msgspec.json.encode(request))
        return root / "policy.json", root / "collector-request.json"


class _Arguments(argparse.Namespace):
    """Carry one journey invocation's inputs."""

    declaration: Path


def main() -> None:
    """Run one declared attempt and print where its summary is."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run",))
    parser.add_argument("--declaration", type=Path, required=True)
    args = parser.parse_args(namespace=_Arguments())
    payload = args.declaration.read_bytes()
    declaration = msgspec.json.decode(payload, type=JourneyDeclaration)
    summary = Journey(declaration, payload).run()
    print(f"journey {summary.result}: {Path(declaration.evidence_root) / declaration.attempt}")
    if summary.result == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
