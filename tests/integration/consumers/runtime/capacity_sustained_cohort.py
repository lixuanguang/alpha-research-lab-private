"""Drive one declared stage-2a attempt: quiet host, two sustained phases, gates and audits.

Run this file from a frozen copy of this directory with the installed research
interpreter, exactly as the stage-1 cohort. One invocation owns one fresh output
directory. The sequence builds and installs four signed owners, checks the host is
quiet, issues ordinary one-hour grants, then runs phase A, an injected owner death,
the qualified four-owner recovery and phase B inside those grants. Every step stops
the attempt at its first failure and is retained in ``steps.jsonl``.
"""

from __future__ import annotations

# standard library imports
import argparse
import os
import sys
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Literal, cast

# third party library imports
import msgspec
from capacity_cohort import Cohort, Gate, _Tree
from capacity_host import HostGate, HostSampler, QuietHostPrecheck
from capacity_results import CapacityResultsCollector
from capacity_sustained import SustainedWorkload
from capacity_sustained_results import SustainedResults, WindowBudget
from capacity_trial import TrialTimings

_MS = 1_000_000

# Interactive processes a quiet host must not run: browsers, editors, desktop
# assistants, the Docker VM and document tools seen on the declared host.
INTERACTIVE_PROCESSES = frozenset(
    {
        "Safari",
        "Brave Browser",
        "Google Chrome",
        "Firefox",
        "Arc",
        "Code",
        "Cursor",
        "Codex",
        "ChatGPT",
        "Xcode",
        "Preview",
        "Texifier",
        "GitHub Desktop",
        "com.docker.backend",
    }
)

# The unchanged provisional targets, applied to every 300-second window.
STAGE_BUDGETS: dict[str, WindowBudget] = {
    "receipt_to_durable": WindowBudget(p50_ns=50 * _MS, p95_ns=250 * _MS, p99_ns=1000 * _MS),
    "durable_to_bbo": WindowBudget(p50_ns=20 * _MS, p95_ns=100 * _MS, p99_ns=500 * _MS),
    "read_depth_bbo": WindowBudget(p50_ns=50 * _MS, p95_ns=200 * _MS, p99_ns=500 * _MS),
    "read_dashboard": WindowBudget(p50_ns=100 * _MS, p95_ns=400 * _MS, p99_ns=1000 * _MS),
    "feature_retrieval": WindowBudget(p50_ns=20 * _MS, p95_ns=75 * _MS, p99_ns=200 * _MS),
    "feature_durable_to_available": WindowBudget(
        p50_ns=2000 * _MS, p95_ns=2000 * _MS, p99_ns=2000 * _MS
    ),
}


@dataclass(frozen=True, slots=True)
class SustainedDeclaration:
    """Fix every 2a number before an attempt; S6 declares and the owner approves these.

    Phase A spans one 30-minute segment rollover; phase B follows the recovery. Each
    interval is a whole number of 300-second windows so no window is partial.
    """

    phase_a: TrialTimings = field(default_factory=lambda: TrialTimings(1800, 1860, 1920))
    phase_b: TrialTimings = field(default_factory=lambda: TrialTimings(600, 660, 720))
    inject_owner_death: str = "bitfinex-isolated"
    reconcile_seconds: int = 60
    window_seconds: int = 300
    minimum_segments_phase_a: int = 2
    opening_orders_per_account: int = 2
    maximum_orders_per_account: int = 80
    selection_seconds: int = 3
    selected_share: float = 0.95
    host_ceiling_cores: float = 2.0
    host_window_seconds: float = 60
    idle_ceiling_cores: float = 1.0
    idle_seconds: float = 300
    interactive: frozenset[str] = INTERACTIVE_PROCESSES
    budgets: dict[str, WindowBudget] = field(default_factory=lambda: dict(STAGE_BUDGETS))

    def __post_init__(self) -> None:
        """Require whole windows, a reconciliation inside the state-age budget and a fault."""
        for timings in (self.phase_a, self.phase_b):
            if timings.interval_seconds % self.window_seconds:
                raise ValueError("each sustained interval must be whole rolling windows")
        if not 0 < self.reconcile_seconds < 120 or not self.inject_owner_death:
            raise ValueError("sustained reconciliation must refresh inside 120 seconds")


class _Observation(msgspec.Struct, frozen=True):
    """Select one driver observation."""

    kind: str
    values: object


class SustainedGates:
    """Judge one sustained phase's evidence against its declaration."""

    @staticmethod
    def observations(path: Path) -> tuple[_Observation, ...]:
        """Read every retained driver observation in order."""
        return tuple(
            msgspec.json.decode(line, type=_Observation) for line in path.read_bytes().splitlines()
        )

    @classmethod
    def phase(
        cls,
        phase: Literal["a", "b"],
        summary: dict[str, object],
        results: dict[str, object],
        sustained: dict[str, object],
        observations: tuple[_Observation, ...],
        declaration: SustainedDeclaration,
    ) -> tuple[Gate, ...]:
        """Assess one phase: completion, inputs, parity, latency windows, commits and authority."""
        timings = declaration.phase_a if phase == "a" else declaration.phase_b
        recordings = cast(dict[str, list[dict[str, object]]], sustained["recordings"])
        proofs = cast(dict[str, dict[str, object]], sustained["fixture_proofs"])
        latencies = cast(dict[str, object], sustained["latencies"])
        commits = cast(dict[str, dict[str, int]], sustained["commits"])
        reconciliations = cast(dict[str, dict[str, object]], sustained["reconciliations"])
        gates = [
            Gate("trial_passed", summary.get("passed") is True, summary.get("failures")),
            Gate(
                "recordings_complete_with_replay_parity",
                bool(recordings)
                and all(
                    entries
                    and all(
                        entry["completed"] is True and entry["replay_parity"] is True
                        for entry in entries
                    )
                    for entries in recordings.values()
                ),
                recordings,
            ),
            Gate(
                "fixture_slots_retained_exactly",
                bool(proofs) and all(proof["status"] == "pass" for proof in proofs.values()),
                proofs,
            ),
            Gate(
                "native_delivery_parity_complete",
                cls._delivery_complete(
                    results, declaration.inject_owner_death if phase == "a" else None
                ),
                cls._delivery_statuses(results),
            ),
        ]
        if phase == "a":
            gates.append(
                Gate(
                    "segments_rolled_over",
                    all(
                        max(cast(int, entry["segments"]) for entry in entries)
                        >= declaration.minimum_segments_phase_a
                        for entries in recordings.values()
                    ),
                    {
                        name: [entry["segments"] for entry in entries]
                        for name, entries in recordings.items()
                    },
                )
            )
        for name in sorted(declaration.budgets):
            summaries = cls._classes(latencies, name)
            gates.append(
                Gate(
                    f"latency_windows_{name}",
                    bool(summaries)
                    and all(item["status"] == "pass" for item in summaries.values()),
                    {key: item["status"] for key, item in summaries.items()},
                )
            )
        gates.append(
            Gate(
                "reads_complete",
                not latencies.get("failed_or_missed_reads"),
                latencies.get("failed_or_missed_reads"),
            )
        )
        minimum = math_floor(
            timings.interval_seconds / declaration.selection_seconds * declaration.selected_share
        )
        opening = declaration.opening_orders_per_account if phase == "a" else 0
        gates.extend(
            (
                Gate(
                    "checkpoints_commit_without_rejection",
                    len(commits) == 4
                    and all(
                        set(counts) <= {"committed:reserved", "committed:target_matched"}
                        for counts in commits.values()
                    ),
                    commits,
                ),
                Gate(
                    "committed_checkpoints_per_account",
                    len(commits) == 4
                    and all(sum(counts.values()) >= minimum for counts in commits.values()),
                    {"minimum": minimum, "accounts": commits},
                ),
                Gate(
                    "orders_only_at_opening",
                    len(commits) == 4
                    and all(
                        counts.get("committed:reserved", 0) <= opening
                        for counts in commits.values()
                    ),
                    {"opening_orders_per_account": opening},
                ),
                Gate(
                    "accounts_reconciled_on_cadence",
                    len(reconciliations) == 4
                    and all(
                        cast(int, item["matched"]) == cast(int, item["attempts"])
                        and cast(int, item["attempts"])
                        >= timings.interval_seconds // declaration.reconcile_seconds - 1
                        for item in reconciliations.values()
                    ),
                    reconciliations,
                ),
                Gate(
                    "orders_within_grant",
                    cls._orders_within(observations, declaration.maximum_orders_per_account),
                    declaration.maximum_orders_per_account,
                ),
            )
        )
        if phase == "a":
            fence = cls._values(observations, "injected_owner_death")
            gates.append(
                Gate(
                    "injected_owner_death_fenced",
                    fence is not None
                    and fence.get("account") == declaration.inject_owner_death
                    and isinstance(fence.get("fence_seconds"), float)
                    and cast(float, fence["fence_seconds"]) <= 2,
                    fence,
                )
            )
        else:
            progress = cls._values(observations, "all_replacement_instances_progressed")
            gates.append(
                Gate(
                    "recovery_progress_within_40_seconds",
                    progress is not None and progress.get("within_40_seconds") is True,
                    progress,
                )
            )
        return tuple(gates)

    @staticmethod
    def _classes(latencies: dict[str, object], name: str) -> dict[str, dict[str, object]]:
        """Return a class's summaries keyed by source or account, or itself when pooled."""
        value = latencies.get(name)
        if not isinstance(value, dict):
            return {}
        if "status" in value:
            return {name: cast(dict[str, object], value)}
        return cast(dict[str, dict[str, object]], value)

    @staticmethod
    def _delivery_statuses(results: dict[str, object]) -> dict[str, object]:
        """Read every account's delivery parity status for every recording."""
        statuses: dict[str, object] = {}
        for source, facts in _Tree.mapping(results.get("sources") or {}).items():
            for key, recording in _Tree.mapping(_Tree.get(facts, "recordings") or {}).items():
                for account, parity in _Tree.mapping(
                    _Tree.get(recording, "delivery_parity") or {}
                ).items():
                    statuses[f"{source}/{key}/{account}"] = _Tree.get(parity, "status")
        return statuses

    @classmethod
    def _delivery_complete(cls, results: dict[str, object], fenced: str | None) -> bool:
        """Require the complete native stream for every account delivery.

        The owner killed at the end of phase A stops receiving deliveries at its fence
        while capture continues, so its log may end with an exactly matched prefix and an
        unattributed tail. Any mismatch inside the prefix fails collection outright.
        """
        statuses = cls._delivery_statuses(results)
        return bool(statuses) and all(
            status == "pass_complete_native_stream"
            or (
                fenced is not None
                and key.endswith(f"/{fenced}")
                and status == "unmeasured_unattributed_delivery_tail"
            )
            for key, status in statuses.items()
        )

    @staticmethod
    def _values(observations: tuple[_Observation, ...], kind: str) -> dict[str, object] | None:
        """Return the single retained observation of one kind, or None."""
        found = [item.values for item in observations if item.kind == kind]
        if len(found) != 1 or not isinstance(found[0], dict):
            return None
        return cast(dict[str, object], found[0])

    @staticmethod
    def _orders_within(observations: tuple[_Observation, ...], maximum: int) -> bool:
        """Require every owner's post-shutdown child orders within the grant."""
        facts = [
            cast(dict[str, object], item.values)
            for item in observations
            if item.kind == "account_facts" and isinstance(item.values, dict)
        ]
        counts = [
            item.get("child_orders") for item in facts if item.get("label") == "post_shutdown"
        ]
        return len(counts) == 4 and all(
            isinstance(count, int) and count <= maximum for count in counts
        )


def math_floor(value: float) -> int:
    """Floor a nonnegative declared ratio."""
    return int(value)


class SustainedCohort(Cohort):
    """Run the declared 2a sequence once, stopping at the first failed step."""

    workload_type = SustainedWorkload

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
        icloud_paused_attested: bool,
        icloud_waived: bool = False,
        declaration: SustainedDeclaration | None = None,
    ) -> None:
        """Bind absolute inputs, the operator's iCloud attestation and the declaration."""
        super().__init__(
            output,
            repository=repository,
            launcher=launcher,
            python=python,
            key_root=key_root,
            socket_base=socket_base,
            label=label,
        )
        self.icloud_paused_attested, self.icloud_waived = icloud_paused_attested, icloud_waived
        self.declaration = SustainedDeclaration() if declaration is None else declaration

    def quiet_host(self) -> tuple[Gate, ...]:
        """Refuse interactive processes and a host whose idle non-trial load is too high."""
        declaration = self.declaration
        result = QuietHostPrecheck(
            declaration.interactive,
            idle_seconds=declaration.idle_seconds,
            ceiling_cores=declaration.idle_ceiling_cores,
        ).run(
            self.output,
            icloud_paused_attested=self.icloud_paused_attested,
            icloud_waived=self.icloud_waived,
        )
        return (Gate("quiet_host_precheck", result["status"] == "pass", result),)

    def phase(self, name: str, phase: Literal["a", "b"]) -> tuple[Gate, ...]:
        """Run one sustained phase, collect its facts and assess its gates."""
        declaration = self.declaration
        timings = declaration.phase_a if phase == "a" else declaration.phase_b
        output = self.root / name
        self.command(
            f"trial-{name}",
            [
                str(self.python),
                str(self.consumers / "capacity_trial.py"),
                "run",
                "--root",
                str(self.root),
                "--output",
                str(output),
                "--launcher",
                str(self.launcher),
                "--features",
                "--workload",
                "sustained",
                "--interval-seconds",
                str(timings.interval_seconds),
                "--supervisor-seconds",
                str(timings.supervisor_seconds),
                "--service-seconds",
                str(timings.service_seconds),
                "--reconcile-seconds",
                str(declaration.reconcile_seconds),
                *(
                    ("--inject-owner-death", declaration.inject_owner_death)
                    if phase == "a"
                    else ("--recover",)
                ),
            ],
        )
        results = CapacityResultsCollector(
            output / "operating", output / "measurements", output / "reads"
        ).write(output / "results.json")
        sustained = SustainedResults(
            output, window_seconds=declaration.window_seconds, budgets=declaration.budgets
        ).collect()
        (output / "sustained-results.json").write_bytes(self.codec.encode_json(sustained))
        summary = msgspec.json.decode(
            (output / "summary.json").read_bytes(), type=dict[str, object]
        )
        gates = SustainedGates.phase(
            phase,
            summary,
            results,
            sustained,
            SustainedGates.observations(output / "observations.jsonl"),
            declaration,
        )
        (output / "gate-assessment.json").write_bytes(self.codec.encode_json(gates))
        return gates

    def host(self, rows: Path) -> tuple[Gate, ...]:
        """Grade the whole attempt's non-trial host load against the declared ceiling."""
        result = HostGate(
            self.declaration.host_ceiling_cores, self.declaration.host_window_seconds
        ).assess(rows.read_bytes().splitlines())
        (self.output / "host-gate.json").write_bytes(self.codec.encode_json(result))
        return (Gate("host_quiet_throughout", result["status"] == "pass", result),)

    def run(self) -> None:
        """Run the declared 2a sequence once; ``make check`` stays a separate final step."""
        self.output.mkdir(parents=True, exist_ok=False)
        awake = QuietHostPrecheck.hold_awake()
        try:
            self.step("freeze", self.freeze)
            self.step("candidate", self.candidate)
            self.step("quiet-host", self.quiet_host)
            self.step("grant", lambda: self.grant(self.root, None))
            rows = self.output / "host-resources.jsonl"
            sampler = HostSampler(rows, trial_root=os.getpid())
            sampler.start()
            try:
                try:
                    self.step("phase-a", partial(self.phase, "phase-a", "a"))
                finally:
                    self.step("cleanup-audit-phase-a", partial(self.audit, self.root, "phase-a"))
                try:
                    self.step("phase-b", partial(self.phase, "phase-b", "b"))
                finally:
                    self.step("cleanup-audit-phase-b", partial(self.audit, self.root, "phase-b"))
            finally:
                sampler.stop()
            self.step("host-gate", partial(self.host, rows))
        finally:
            awake.terminate()
            awake.wait(5)


class _Arguments(argparse.Namespace):
    """Carry one sustained attempt's absolute inputs and attestation."""

    output: Path
    repository: Path
    launcher: Path
    python: Path
    key_root: Path
    socket_base: Path
    label: str
    icloud_paused: bool
    icloud_waived: bool


def main() -> None:
    """Run one declared 2a attempt into a fresh output directory."""
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
    parser.add_argument("--icloud-paused", action="store_true")
    # The owner may waive the iCloud pause; it is then retained as waived, never paused.
    parser.add_argument("--icloud-waived", action="store_true")
    args = parser.parse_args(namespace=_Arguments())
    cohort = SustainedCohort(
        args.output,
        repository=args.repository,
        launcher=args.launcher,
        python=args.python,
        key_root=args.key_root,
        socket_base=args.socket_base,
        label=args.label,
        icloud_paused_attested=args.icloud_paused,
        icloud_waived=args.icloud_waived,
    )
    try:
        cohort.run()
    except Exception as error:
        print(f"sustained cohort stopped: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"sustained cohort passed: {args.output}")


if __name__ == "__main__":
    main()
