"""Drive one declared stage-1 cohort: signed candidate, trials, gates and audit.

Run this file from a frozen copy of this directory with the installed research
interpreter. One invocation owns one fresh output directory; a second invocation
into the same directory is refused, so a declared single attempt stays single.
Every step stops the cohort at its first failure and is retained in ``steps.jsonl``.
The ``dashboard`` sequence runs the steady trial, populated-history queries and the
public Bitfinex route; the ``public-okx`` sequence runs only the public OKX route; the
``filesystem-cold`` sequence builds nothing and queries a retained counted trial's
history with every reader file evicted from the page cache before each round.

The trial gates restate the stage-1 targets the runtime-capacity record keeps
unchanged: they read the statuses ``CapacityResultsCollector`` derives from the
same budgets and add the documented resource ceilings.
"""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import os
import shutil
import subprocess  # nosec B404  # [owner=runtime; rationale=declared cohort build and trial tools; expires=2027-03-01]
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

# third party library imports
import msgspec
from capacity_inputs import CapacityWorkload
from capacity_results import CapacityResultsCollector

# project library imports
import execution
from configuration import PaperServiceConfiguration
from execution import AccountExecutionRequest, InstalledPaperAccount
from runtime import InstalledIdentity
from serialization import DomainCodec

PublicVenue = Literal["okx", "bitfinex"] | None
Sequence = Literal["dashboard", "public-okx", "filesystem-cold"]
_GIB = 1024**3
# Unchanged stage-1 resource ceilings (budgets_unchanged in the capacity record).
_AVERAGE_CPU_CORES = 7
_PEAK_RSS_BYTES = 24 * _GIB
_PEAK_OCCUPIED_BYTES = 320 * _GIB
_MEASURED_SECONDS = 60
_HISTORY_SAMPLES_PER_CLASS = 1000


class Gate(msgspec.Struct, frozen=True):
    """Retain one named criterion, its outcome and the facts it read."""

    name: str
    passed: bool
    observed: object


class _Tree:
    """Read nested decoded JSON without inventing absent facts."""

    @staticmethod
    def get(value: object, *keys: str) -> object:
        """Return the nested value, or ``None`` when any level is absent."""
        for key in keys:
            if not isinstance(value, dict):
                return None
            value = cast(dict[str, object], value).get(key)
        return value

    @staticmethod
    def mapping(value: object) -> dict[str, object]:
        """Require a JSON object."""
        if not isinstance(value, dict):
            raise ValueError("capacity evidence requires a JSON object")
        return cast(dict[str, object], value)

    @staticmethod
    def number(value: object) -> float | None:
        """Read a real number, rejecting booleans."""
        return float(cast(float, value)) if type(value) in (int, float) else None

    @staticmethod
    def items(value: object) -> tuple[object, ...]:
        """Read a JSON array, or nothing when the value is not one."""
        return tuple(cast(list[object], value)) if isinstance(value, list | tuple) else ()


class GateAssessment:
    """Judge collected trial facts and history queries against the declared criteria."""

    @staticmethod
    def trial(
        summary: dict[str, object],
        results: dict[str, object],
        resources: dict[str, object],
        *,
        public_venue: PublicVenue,
    ) -> tuple[Gate, ...]:
        """Assess a fixture trial, or a public route's declared subset, from its evidence.

        A fixture trial grades every source, account, read workload and resource
        ceiling. A public route grades the trial, its public captures' completion,
        queues and native delivery parity, and the fixture sources' unchanged gates;
        public latency and the read workload are reported, not graded.
        """
        get = _Tree.get
        gates = [
            Gate(
                "trial_passed",
                summary.get("passed") is True and summary.get("failures") == [],
                {"passed": summary.get("passed"), "failures": summary.get("failures")},
            )
        ]
        interval = _Tree.items(results.get("steady_monotonic_interval_ns"))
        measured = (
            (cast(int, interval[1]) - cast(int, interval[0])) / 1_000_000_000
            if len(interval) == 2 and all(type(item) is int for item in interval)
            else None
        )
        gates.append(
            Gate(
                "measured_interval_at_least_60_seconds",
                measured is not None and measured >= _MEASURED_SECONDS,
                measured,
            )
        )
        for name, source in sorted(_Tree.mapping(results.get("sources")).items()):
            origin = get(source, "transport_origin")
            # Only the route's venue is public; every other source stays the fixture.
            expected_origin = (
                "live_public"
                if public_venue is not None and get(source, "venue") == public_venue
                else "base_fixture"
            )
            gates.append(Gate(f"{name}.transport_origin", origin == expected_origin, origin))
            recordings = _Tree.mapping(get(source, "recordings") or {})
            gates.append(Gate(f"{name}.one_recording", len(recordings) == 1, sorted(recordings)))
            for recording in recordings.values():
                capture = get(recording, "capture")
                probe = get(recording, "source_probe")
                checks: dict[str, object] = {
                    "completed_manifest": get(capture, "completed_manifest"),
                    "stop_status": get(capture, "stop_status"),
                    "queue_status": get(probe, "queue", "status"),
                }
                if origin == "base_fixture":
                    checks |= {
                        "size_budget_status": get(capture, "size_budget_status"),
                        "fixture_schedule_status": get(capture, "fixture_schedule_proof", "status"),
                        "probe_coverage_status": get(probe, "coverage", "status"),
                        "steady_receipt_to_durable_status": get(
                            probe, "steady_receipt_to_durable", "status"
                        ),
                    }
                for check, value in checks.items():
                    expected: object = True if check == "completed_manifest" else "pass"
                    gates.append(Gate(f"{name}.{check}", value == expected, value))
                if origin == "live_public":
                    gates.append(
                        Gate(
                            f"{name}.public_latency_reported",
                            True,
                            {
                                "receipt_to_durable": get(probe, "receipt_to_durable"),
                                "stop_reason": get(capture, "stop_reason"),
                            },
                        )
                    )
                parity = _Tree.mapping(get(recording, "delivery_parity") or {})
                accounts = _Tree.mapping(get(recording, "account_probes") or {})
                gates.append(
                    Gate(
                        f"{name}.accounts_present",
                        bool(parity) and set(parity) == set(accounts),
                        sorted(parity),
                    )
                )
                for account, delivery in sorted(parity.items()):
                    status = get(delivery, "status")
                    gates.append(
                        Gate(
                            f"{name}.{account}.delivery_parity",
                            status == "pass_complete_native_stream",
                            status,
                        )
                    )
                    if origin == "base_fixture":
                        account_probe = accounts.get(account)
                        for check, path in (
                            ("probe_coverage_status", ("coverage", "status")),
                            ("steady_durable_to_bbo_status", ("steady_durable_to_bbo", "status")),
                        ):
                            value = get(account_probe, *path)
                            gates.append(Gate(f"{name}.{account}.{check}", value == "pass", value))
        if public_venue is None:
            for boundary in ("depth_bbo", "dashboard"):
                workload = get(results, "reads", "four_reader_workload", boundary)
                for check in ("status", "schedule_status"):
                    value = get(workload, check)
                    gates.append(Gate(f"reads.{boundary}.{check}", value == "pass", value))
            cpu = _Tree.number(resources.get("cpu_average_logical_cores"))
            rss = _Tree.number(resources.get("peak_rss_bytes"))
            occupied = _Tree.number(resources.get("peak_occupied_bytes"))
            gates.extend(
                (
                    Gate(
                        "resources.sampling_status",
                        resources.get("status") == "pass",
                        resources.get("status"),
                    ),
                    Gate(
                        "resources.average_cpu_at_most_7_cores",
                        cpu is not None and cpu <= _AVERAGE_CPU_CORES,
                        cpu,
                    ),
                    Gate(
                        "resources.peak_rss_at_most_24_gib",
                        rss is not None and rss <= _PEAK_RSS_BYTES,
                        rss,
                    ),
                    Gate(
                        "resources.peak_occupied_at_most_320_gib",
                        occupied is not None and occupied <= _PEAK_OCCUPIED_BYTES,
                        occupied,
                    ),
                )
            )
        return tuple(gates)

    @staticmethod
    def history(
        summary: dict[str, object],
        cache_classes: tuple[str, ...] = ("application_cold", "warm"),
    ) -> tuple[Gate, ...]:
        """Require every class's 1,000 requests to succeed, keep parity and meet its budget."""
        gates = [
            Gate(
                "matched_cutoff_parity",
                summary.get("matched_cutoff_parity") is True,
                summary.get("matched_cutoff_parity"),
            )
        ]
        classes: dict[tuple[object, object], object] = {
            (_Tree.get(row, "boundary"), _Tree.get(row, "cache_class")): row
            for row in _Tree.items(summary.get("results"))
        }
        for boundary in ("depth_bbo", "dashboard"):
            for cache_class in cache_classes:
                row = classes.get((boundary, cache_class))
                name = f"{boundary}.{cache_class}"
                gates.extend(
                    (
                        Gate(
                            f"{name}.requests",
                            _Tree.get(row, "requests") == _HISTORY_SAMPLES_PER_CLASS
                            and _Tree.get(row, "failures") == 0,
                            {
                                "requests": _Tree.get(row, "requests"),
                                "failures": _Tree.get(row, "failures"),
                            },
                        ),
                        *(
                            Gate(
                                f"{name}.{latency}",
                                _Tree.get(row, latency, "status") == "pass",
                                _Tree.get(row, latency),
                            )
                            for latency in ("service_latency", "scheduled_response_latency")
                        ),
                    )
                )
        return tuple(gates)

    @staticmethod
    def filesystem_cold(
        summary: dict[str, object], retained: dict[str, object]
    ) -> tuple[Gate, ...]:
        """Require every round proved non-resident and results equal to the counted attempt's."""
        cold = _Tree.mapping(summary.get("filesystem_cold") or {})
        rounds = cold.get("rounds")
        expected = _Tree.get(summary, "prepared_history", "expected_result_identities")
        counted = retained.get("expected_result_identities")
        return (
            *GateAssessment.history(summary, ("filesystem_cold",)),
            Gate(
                "filesystem_cold.every_round_verified_nonresident",
                rounds == _HISTORY_SAMPLES_PER_CLASS // 4 and cold.get("verified_rounds") == rounds,
                {"rounds": rounds, "verified_rounds": cold.get("verified_rounds")},
            ),
            Gate(
                "results_equal_counted_attempt",
                isinstance(expected, dict) and bool(expected) and expected == counted,
                {"expected": expected, "counted": counted},
            ),
        )


class CleanupAudit:
    """Prove a finished trial left no observed process alive and every account stopped."""

    @staticmethod
    def observed_pids(rows: Iterator[object]) -> set[int]:
        """Collect every integer recorded under a pid field in the trial's observations."""
        pids: set[int] = set()
        stack = list(rows)
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                for key, item in cast(dict[str, object], value).items():
                    if key.endswith("pid") and type(item) is int and item > 0:
                        pids.add(item)
                    elif key.endswith("pids") and isinstance(item, dict):
                        pids.update(
                            pid
                            for pid in cast(dict[str, object], item).values()
                            if type(pid) is int and pid > 0
                        )
                    else:
                        stack.append(item)
            else:
                stack.extend(_Tree.items(value))
        return pids

    @staticmethod
    def alive(pid: int) -> bool:
        """Report whether a process with this pid exists, owned by anyone."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


class Cohort:
    """Own one declared attempt's ordered steps, evidence and first-failure stop."""

    def __init__(
        self,
        output: Path,
        *,
        repository: Path,
        launcher: Path,
        python: Path,
        key_root: Path,
        socket_base: Path,
        label: str,
        sequence: Sequence = "dashboard",
        history_trial: Path | None = None,
    ) -> None:
        """Bind absolute inputs; nothing runs until ``run``."""
        for path in (output, repository, launcher, python, key_root, socket_base):
            if not path.is_absolute():
                raise ValueError("cohort paths must be absolute")
        if (sequence == "filesystem-cold") != (history_trial is not None) or (
            history_trial is not None and not history_trial.is_absolute()
        ):
            raise ValueError("only the filesystem-cold sequence reads an absolute retained trial")
        self.history_trial = history_trial
        self.output, self.repository, self.launcher = output, repository, launcher
        self.python, self.key_root, self.socket_base, self.label = (
            python,
            key_root,
            socket_base,
            label,
        )
        self.sequence = sequence
        self.route_venue: Literal["okx", "bitfinex"] = (
            "okx" if sequence == "public-okx" else "bitfinex"
        )
        self.codec = DomainCodec()
        self.root = output / "candidate"
        self.route_root = output / f"route-{self.route_venue}"
        self.consumers = output / "consumers"
        self.releases: dict[str, Path] = {}

    def record(self, step: str, passed: bool, values: object) -> None:
        """Append one step outcome before the next step can run."""
        row = {"step": step, "passed": passed, "at": datetime.now(UTC), "values": values}
        with (self.output / "steps.jsonl").open("ab") as stream:
            stream.write(self.codec.encode_json(row) + b"\n")

    def command(self, step: str, arguments: list[str], *, cwd: Path | None = None) -> str:
        """Run one subprocess, retain its output and fail the step on a nonzero exit."""
        completed = subprocess.run(  # nosec B603  # [owner=runtime; rationale=explicit absolute argv of declared cohort tools; expires=2027-03-01]
            arguments, capture_output=True, cwd=cwd, check=False
        )
        logs = self.output / "logs"
        logs.mkdir(exist_ok=True)
        (logs / f"{step}.stdout").write_bytes(completed.stdout)
        (logs / f"{step}.stderr").write_bytes(completed.stderr)
        if completed.returncode:
            self.record(step, False, {"argv": arguments, "returncode": completed.returncode})
            raise RuntimeError(f"cohort step {step} failed with exit {completed.returncode}")
        return completed.stdout.decode()

    def freeze(self) -> dict[str, object]:
        """Require a clean checkout and copy these consumers outside it, by hash."""
        status = self.command(
            "freeze-status", ["git", "status", "--porcelain"], cwd=self.repository
        )
        commit = self.command("freeze-commit", ["git", "rev-parse", "HEAD"], cwd=self.repository)
        if status.strip():
            raise ValueError("declared candidate source has uncommitted changes")
        # Grants bind the installed implementation; an editable checkout has none.
        if Path(execution.__file__).resolve().is_relative_to(self.repository.resolve()):
            raise ValueError("research interpreter runs an editable checkout, not an install")
        implementation = InstalledIdentity.sha256()
        self.consumers.mkdir()
        hashes: dict[str, str] = {}
        for path in sorted(Path(__file__).parent.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            shutil.copy2(path, self.consumers / path.name)
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "commit": commit.strip(),
            "installed_implementation": implementation,
            "consumer_sha256": hashes,
        }

    def candidate(self) -> dict[str, object]:
        """Prepare inputs, then fetch, build, verify and install four signed targets."""
        self.root.mkdir()
        workload = CapacityWorkload(
            opening_at=datetime.now(UTC) - timedelta(seconds=5),
            socket_root=self.socket_base / "steady",
        )
        workload.prepare(self.root / "preparation")
        key = self.key_root / self.label / "builder"
        key.parent.mkdir(parents=True, mode=0o700)
        self.command(
            "keygen",
            [
                "/usr/bin/ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                self.label,
                "-f",
                str(key),
            ],
        )
        key.chmod(0o600)
        public_key = " ".join(key.with_suffix(".pub").read_text().split()[:2])
        now = datetime.now(UTC)
        # The research environment's interpreter: the same pinned binary, and the
        # environment whose admitted hatchling the build checks in isolated mode.
        python = self.python
        uv = Path(shutil.which("uv") or "/absent/uv")
        policy: dict[str, object] = {
            "schema_version": "installation-policy",
            "target": "darwin_arm64",
            "python_executable": str(python),
            "python_sha256": hashlib.sha256(python.read_bytes()).hexdigest(),
            "uv_executable": str(uv),
            "uv_sha256": hashlib.sha256(uv.read_bytes()).hexdigest(),
            "ssh_keygen_executable": "/usr/bin/ssh-keygen",
            "ssh_keygen_sha256": hashlib.sha256(
                Path("/usr/bin/ssh-keygen").read_bytes()
            ).hexdigest(),
            "builders": [
                {
                    "identity": self.label,
                    "public_key": public_key,
                    "origins": ["local-builder"],
                    "roots": ["alpha-research-execution"],
                    "valid_from": (now - timedelta(minutes=1)).isoformat(),
                    "valid_until": (now + timedelta(days=7)).isoformat(),
                }
            ],
            "config_schemas": ["account-runtime"],
            "state_schemas": ["account-journal"],
        }
        policy_path = self.root / "release-policy.json"
        policy_path.write_bytes(msgspec.json.encode(policy))
        service = self.codec.decode_json(
            (self.root / "preparation/services-initial.json").read_bytes(),
            PaperServiceConfiguration,
        )
        wheels = self.root / "wheels"
        registry = self.root / "registry"
        for index, account in enumerate(service.accounts):
            name = account.account_id
            request = self.root / f"build-request-{name}.json"
            build_request: dict[str, object] = {
                "name": f"{self.label}-{name}",
                "builder": self.label,
                "origin": "local-builder",
                # Inside the dependency-admission review window.
                "valid_until": (now + timedelta(days=4)).isoformat(),
                "runtime": {
                    "python_version": "3.14.7",
                    "platform": "darwin_arm64",
                    "contract_version": "1",
                    "application": "execution",
                    "mode": "paper",
                    "config_schema": "account-runtime",
                    "state_schema": "account-journal",
                },
            }
            request.write_bytes(msgspec.json.encode(build_request))
            common = ["--policy", str(policy_path), "--request", str(request)]
            if index == 0:
                self.command(
                    "fetch",
                    [
                        str(self.launcher),
                        "fetch",
                        "--repository",
                        str(self.repository),
                        *common,
                        "--dependencies",
                        str(wheels),
                    ],
                )
            built = self.command(
                f"build-{name}",
                [
                    str(self.launcher),
                    "build",
                    "--repository",
                    str(self.repository),
                    *common,
                    "--configuration",
                    str(self.root / f"preparation/account-{name}.json"),
                    "--dependencies",
                    str(wheels),
                    "--audit",
                    str(self.root / f"audit-{name}"),
                    "--key",
                    str(key),
                    "--registry",
                    str(registry),
                ],
            )
            release = Path(built.strip().splitlines()[-1])
            if release.parent != registry:
                raise ValueError(f"build of {name} did not publish into the cohort registry")
            self.releases[name] = release
            self.command(
                f"verify-{name}",
                [
                    str(self.launcher),
                    "verify",
                    "--release",
                    str(release),
                    "--policy",
                    str(policy_path),
                ],
            )
            self.install(self.root, name)
        return {"releases": {name: path.name for name, path in self.releases.items()}}

    def install(self, root: Path, account: str) -> None:
        """Install one verified release into a fresh target of the given root."""
        self.command(
            f"install-{root.name}-{account}",
            [
                str(self.launcher),
                "install",
                "--release",
                str(self.releases[account]),
                "--policy",
                str(root / "release-policy.json"),
                "--target",
                str(root / f"target-{account}"),
            ],
        )

    def grant(self, root: Path, public_venue: PublicVenue) -> dict[str, object]:
        """Issue fresh ordinary one-hour grants for the four verified releases."""
        service = self.codec.decode_json(
            (root / "preparation/services-initial.json").read_bytes(), PaperServiceConfiguration
        )
        workload = CapacityWorkload(
            opening_at=service.accounts[0].configuration.opening_at,
            socket_root=Path(service.accounts[0].socket_path).parent,
            public_venue=public_venue,
        )
        return workload.finalize(
            root / "preparation", tuple(path.name for path in self.releases.values())
        )

    def prepare_route(self) -> dict[str, object]:
        """Prepare the public route's root with the same signed account inputs."""
        self.route_root.mkdir()
        steady = self.codec.decode_json(
            (self.root / "preparation/services-initial.json").read_bytes(),
            PaperServiceConfiguration,
        )
        CapacityWorkload(
            opening_at=steady.accounts[0].configuration.opening_at,
            socket_root=self.socket_base / "route",
            public_venue=self.route_venue,
        ).prepare(self.route_root / "preparation")
        for account in steady.accounts:
            name = account.account_id
            if (self.route_root / f"preparation/account-{name}.json").read_bytes() != (
                self.root / f"preparation/account-{name}.json"
            ).read_bytes():
                raise ValueError(f"public route changes signed account input {name}")
        shutil.copy2(self.root / "release-policy.json", self.route_root / "release-policy.json")
        for account in steady.accounts:
            self.install(self.route_root, account.account_id)
        return {"socket_root": str(self.socket_base / "route")}

    def trial(self, root: Path, name: str, public_venue: PublicVenue) -> tuple[Gate, ...]:
        """Run one finite trial, collect its facts and assess its declared gates."""
        output = root / name
        self.command(
            f"trial-{root.name}-{name}",
            [
                str(self.python),
                str(self.consumers / "capacity_trial.py"),
                "run",
                "--root",
                str(root),
                "--output",
                str(output),
                "--launcher",
                str(self.launcher),
                *(("--public-venue", public_venue) if public_venue else ()),
            ],
        )
        results = CapacityResultsCollector(
            output / "operating", output / "measurements", output / "reads"
        ).write(output / "results.json")
        summary = msgspec.json.decode(
            (output / "summary.json").read_bytes(), type=dict[str, object]
        )
        resources_path = output / "reads/resources-summary.json"
        resources = (
            msgspec.json.decode(resources_path.read_bytes(), type=dict[str, object])
            if resources_path.is_file()
            else {"status": cast(object, "unmeasured")}
        )
        gates = GateAssessment.trial(summary, results, resources, public_venue=public_venue)
        (output / "gate-assessment.json").write_bytes(self.codec.encode_json(gates))
        return gates

    def history(self) -> tuple[Gate, ...]:
        """Run the populated-history queries on the steady trial and assess all four classes."""
        output = self.root / "history-queries"
        self.command(
            "history-queries",
            [
                str(self.python),
                str(self.consumers / "capacity_history_queries.py"),
                "--trial",
                str(self.root / "steady"),
                "--output",
                str(output),
                "--samples-per-reader",
                "250",
                "--dashboard-events-per-account",
                "10000",
            ],
        )
        summary = msgspec.json.decode(
            (output / "summary.json").read_bytes(), type=dict[str, object]
        )
        gates = GateAssessment.history(summary)
        (output / "assessment.json").write_bytes(self.codec.encode_json(gates))
        return gates

    def filesystem_cold(self) -> tuple[Gate, ...]:
        """Query the retained trial's history filesystem-cold and compare its results."""
        trial = cast(Path, self.history_trial)
        output = self.output / "filesystem-cold"
        self.command(
            "filesystem-cold-queries",
            [
                str(self.python),
                str(self.consumers / "capacity_history_queries.py"),
                "--trial",
                str(trial),
                "--output",
                str(output),
                "--samples-per-reader",
                "250",
                "--dashboard-events-per-account",
                "10000",
                "--cache-classes",
                "filesystem_cold",
            ],
        )
        summary = msgspec.json.decode(
            (output / "summary.json").read_bytes(), type=dict[str, object]
        )
        retained = msgspec.json.decode(
            (trial.parent / "history-queries/prepared-history.json").read_bytes(),
            type=dict[str, object],
        )
        gates = GateAssessment.filesystem_cold(summary, retained)
        (output / "assessment.json").write_bytes(self.codec.encode_json(gates))
        return gates

    def audit(self, root: Path, trial: str) -> tuple[Gate, ...]:
        """Re-inspect every account through the signed launcher and check observed pids."""
        output = root / trial
        rows: list[object] = []
        for line in (output / "observations.jsonl").read_bytes().splitlines():
            rows.append(msgspec.json.decode(line, type=object))
        alive = sorted(
            pid for pid in CleanupAudit.observed_pids(iter(rows)) if CleanupAudit.alive(pid)
        )
        service = self.codec.decode_json(
            (root / "preparation/services-initial.json").read_bytes(), PaperServiceConfiguration
        )
        phases: dict[str, str] = {}
        for account in service.accounts:
            state = InstalledPaperAccount(
                config=account.configuration,
                launcher=self.launcher,
                target=root / f"target-{account.account_id}",
                policy=root / "release-policy.json",
                requests=output / "audit" / f"{account.account_id}-{uuid4().hex}",
            ).execute(AccountExecutionRequest(action="inspect"))
            phases[account.account_id] = state.accounts[0].phase
        gates = (
            Gate("observed_processes_absent", not alive, alive),
            Gate(
                "all_accounts_stopped",
                len(phases) == 4 and all(phase == "stopped" for phase in phases.values()),
                phases,
            ),
        )
        (output / "cleanup-audit.json").write_bytes(self.codec.encode_json(gates))
        return gates

    def step(self, name: str, action: Callable[[], object]) -> object:
        """Run one declared step, retaining its outcome and stopping on any failure."""
        try:
            values = action()
        except Exception as error:
            self.record(name, False, {"error": f"{type(error).__name__}: {error}"})
            raise
        gates = values if isinstance(values, tuple) else ()
        failed = [gate.name for gate in gates if isinstance(gate, Gate) and not gate.passed]
        self.record(name, not failed, {"failed_gates": failed} if gates else values)
        if failed:
            raise RuntimeError(f"cohort step {name} failed gates: {', '.join(failed)}")
        return values

    def run(self) -> None:
        """Run the declared sequence once; ``make check`` stays a separate final step."""
        self.output.mkdir(parents=True, exist_ok=False)
        self.step("freeze", self.freeze)
        if self.sequence == "filesystem-cold":
            self.step("filesystem-cold-queries", self.filesystem_cold)
            return
        self.step("candidate", self.candidate)
        if self.sequence == "dashboard":
            self.step("grant-steady", lambda: self.grant(self.root, None))
            self.step("steady-trial", lambda: self.trial(self.root, "steady", None))
            self.step("history-queries", self.history)
        venue = self.route_venue
        self.step("route-prepare", self.prepare_route)
        self.step("grant-route", lambda: self.grant(self.route_root, venue))
        self.step(f"public-{venue}-trial", lambda: self.trial(self.route_root, "public", venue))
        if self.sequence == "dashboard":
            self.step("cleanup-audit-steady", lambda: self.audit(self.root, "steady"))
        self.step("cleanup-audit-route", lambda: self.audit(self.route_root, "public"))


class _Arguments(argparse.Namespace):
    """Carry one cohort invocation's absolute inputs."""

    output: Path
    repository: Path
    launcher: Path
    python: Path
    key_root: Path
    socket_base: Path
    label: str
    sequence: Sequence
    history_trial: Path | None


def main() -> None:
    """Run one declared cohort attempt into a fresh output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    for option in (
        "--output",
        "--repository",
        "--launcher",
        "--python",
        "--key-root",
        "--socket-base",
    ):
        parser.add_argument(option, type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--sequence", choices=("dashboard", "public-okx", "filesystem-cold"), default="dashboard"
    )
    parser.add_argument("--history-trial", type=Path, default=None)
    args = parser.parse_args(namespace=_Arguments())
    cohort = Cohort(
        args.output,
        repository=args.repository,
        launcher=args.launcher,
        python=args.python,
        key_root=args.key_root,
        socket_base=args.socket_base,
        label=args.label,
        sequence=args.sequence,
        history_trial=args.history_trial,
    )
    try:
        cohort.run()
    except Exception as error:
        print(f"cohort stopped: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"cohort passed: {args.output}")


if __name__ == "__main__":
    main()
