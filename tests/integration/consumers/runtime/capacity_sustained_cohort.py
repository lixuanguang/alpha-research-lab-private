"""Drive one declared sustained or day-run attempt: quiet host, phases, gates and audits.

Run this file from a frozen copy of this directory with the installed research
interpreter, exactly as the baseline cohort. One invocation owns one fresh output
directory. The sequence builds and installs four signed owners, checks the host is
quiet, issues ordinary one-hour grants, then runs phase A, an injected owner death,
the qualified four-owner recovery and phase B inside those grants. Every step stops
the attempt at its first failure and is retained in ``steps.jsonl``.
"""

from __future__ import annotations

# standard library imports
import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Literal, cast

# third party library imports
import msgspec
from capacity_cohort import Cohort, Gate, _Tree
from capacity_host import HostGate, HostSampler, QuietHostPrecheck, ResourceGate
from capacity_results import CapacityResultsCollector
from capacity_sustained import (
    DayNativeFixture,
    DayRehearsalFixture,
    SustainedNativeFixture,
)
from capacity_sustained_results import DecisionAdmissions, SustainedResults, WindowBudget
from capacity_trial import TrialTimings, TrialWorkload, TrialWorkloads

# project library imports
from configuration import PaperServiceConfiguration
from market_data.storage import CaptureRecording
from serialization import DomainCodec

_MS = 1_000_000
# A source chain's explicit offline replay envelope: the largest SavedCaptureRun admits.
_SOURCE_VERIFICATION_SECONDS = 7200

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


class SustainedArithmetic:
    """Exact integer arithmetic for sustained-cohort declarations."""

    @staticmethod
    def math_floor(value: float) -> int:
        """Floor a nonnegative declared ratio."""
        return int(value)


@dataclass(frozen=True, slots=True)
class SustainedDeclaration:
    """Fix every number before an attempt; the declaration is approved before it runs.

    Phase A spans one 30-minute segment rollover; phase B follows the recovery. Each
    interval is a whole number of 300-second windows so no window is partial.
    """

    phase_a: TrialTimings = field(default_factory=partial(TrialTimings, 1800, 1860, 1920))
    phase_b: TrialTimings = field(default_factory=partial(TrialTimings, 600, 660, 720))
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
    budgets: dict[str, WindowBudget] = field(default_factory=partial(dict, STAGE_BUDGETS))
    # The stage: two sustained phases with a fault, or one day (counted or rehearsal).
    stage: Literal["sustained", "day", "day-rehearsal"] = "sustained"
    workload: TrialWorkload = "sustained"
    fixture: type[SustainedNativeFixture] = SustainedNativeFixture
    day: TrialTimings | None = None
    minimum_segments_day: int = 0
    minimum_messages: int | None = None
    minimum_source_share: float = 0.2
    checkpoint_budget: WindowBudget = field(
        default_factory=partial(WindowBudget, 250 * _MS, 750 * _MS, 2000 * _MS)
    )
    grade_checkpoints: bool = False
    maximum_orders_per_day: int = 40
    replay_speed: float = 4.0
    resources: ResourceGate = field(default_factory=partial(ResourceGate, 24 * 1024**3, 7.0, 9.0))

    def __post_init__(self) -> None:
        """Require whole windows, a reconciliation inside the state-age budget and a fault."""
        phases: tuple[TrialTimings, ...] = (self.phase_a, self.phase_b)
        if self.day is not None:
            phases = (*phases, self.day)
        for timings in phases:
            if timings.interval_seconds % self.window_seconds:
                raise ValueError("each sustained interval must be whole rolling windows")
        if not 0 < self.reconcile_seconds < 120 or not self.inject_owner_death:
            raise ValueError("sustained reconciliation must refresh inside 120 seconds")
        if (self.stage == "sustained") != (self.day is None):
            raise ValueError("only a day run declares its single day phase")

    @classmethod
    def counted_day(cls) -> SustainedDeclaration:
        """Declare the counted 24-hour day: 288 windows, graded checkpoint percentiles."""
        return cls(
            stage="day",
            workload="day",
            fixture=DayNativeFixture,
            day=TrialTimings(86_400, 87_000, 87_600),
            minimum_segments_day=48,
            minimum_messages=7_000_000,
            grade_checkpoints=True,
        )

    @classmethod
    def day_rehearsal(cls) -> SustainedDeclaration:
        """Declare a 2-hour rehearsal: the day-run shape, checkpoint percentiles reported only."""
        return cls(
            stage="day-rehearsal",
            workload="day-rehearsal",
            fixture=DayRehearsalFixture,
            day=TrialTimings(7_200, 7_800, 8_400),
            minimum_segments_day=4,
        )


class _Observation(msgspec.Struct, frozen=True):
    """Select one driver observation."""

    kind: str
    values: object


class SupervisorDelivery:
    """Read one phase's final supervisor source-delivery accounting and its expected feeds.

    The supervisor writes ``source_delivery_accounting`` and its failure events into the
    final ``operating/status.json`` after shutdown. The deployed ``configuration.json``
    names every feed and the accounts each feeds, so a missing entry cannot pass unseen.
    """

    def __init__(self, trial: Path) -> None:
        """Bind one trial output directory."""
        self.trial = trial
        self.codec = DomainCodec()

    def facts(self) -> dict[str, object]:
        """Return the expected feeds and the retained accounting, or why either is unreadable."""
        try:
            config = self.codec.decode_json(
                (self.trial / "configuration.json").read_bytes(), PaperServiceConfiguration
            )
        except (OSError, ValueError, msgspec.DecodeError) as error:
            return {"readable": False, "reason": f"configuration: {type(error).__name__}"}
        expected: dict[str, list[str]] = {}
        for source in config.sources:
            accounts = sorted(
                {item.account_id for item in config.instances if item.source == source.name}
            )
            expected[source.name] = accounts
            if source.trades is not None:
                expected[f"{source.name}.trades"] = accounts
        try:
            status = msgspec.json.decode(
                (self.trial / "operating/status.json").read_bytes(), type=dict[str, object]
            )
        except (OSError, msgspec.DecodeError) as error:
            return {
                "readable": False,
                "expected": expected,
                "reason": f"status: {type(error).__name__}",
            }
        return {
            "readable": True,
            "expected": expected,
            "accounting": status.get("source_delivery_accounting"),
            "failures": status.get("failures"),
            "faulted_accounts": status.get("faulted_accounts"),
        }


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
        phase: Literal["a", "b", "day"],
        summary: dict[str, object],
        results: dict[str, object],
        sustained: dict[str, object],
        observations: tuple[_Observation, ...],
        declaration: SustainedDeclaration,
    ) -> tuple[Gate, ...]:
        """Assess one phase: completion, inputs, parity, latency windows, commits and authority."""
        timings = (
            declaration.phase_a
            if phase == "a"
            else declaration.phase_b
            if phase == "b"
            else cast(TrialTimings, declaration.day)
        )
        recordings = cast(dict[str, list[dict[str, object]]], sustained["recordings"])
        proofs = cast(dict[str, dict[str, object]], sustained["fixture_proofs"])
        latencies = cast(dict[str, object], sustained["latencies"])
        commits = cast(dict[str, dict[str, int]], sustained["commits"])
        # Absent decision evidence resolves nothing, and no decision passes.
        decisions: dict[str, dict[str, object]] = cast(
            dict[str, dict[str, object]], sustained.get("decisions", dict[str, object]())
        )
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
            cls._supervisor_delivery(
                sustained.get("supervisor_delivery"),
                declaration.inject_owner_death if phase == "a" else None,
                cls._fenced(observations, declaration) if phase == "a" else False,
            ),
        ]
        if phase in ("a", "day"):
            minimum_segments = (
                declaration.minimum_segments_phase_a
                if phase == "a"
                else declaration.minimum_segments_day
            )
            gates.append(
                Gate(
                    "segments_rolled_over",
                    all(
                        max(cast(int, entry["segments"]) for entry in entries) >= minimum_segments
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
        minimum = SustainedArithmetic.math_floor(
            timings.interval_seconds / declaration.selection_seconds * declaration.selected_share
        )
        opening = declaration.opening_orders_per_account if phase in ("a", "day") else 0
        gates.extend(
            (
                Gate(
                    "checkpoints_commit_without_rejection",
                    cls._admitted(commits, decisions),
                    {"batches": commits, "decisions": decisions},
                ),
                Gate(
                    "committed_checkpoints_per_account",
                    len(commits) == 4
                    and all(sum(counts.values()) >= minimum for counts in commits.values()),
                    {"minimum": minimum, "accounts": commits},
                ),
                Gate(
                    "orders_only_at_opening",
                    len(decisions) == 4
                    and all(
                        reserved is not None and reserved <= opening
                        for reserved in cls._reserved(decisions).values()
                    ),
                    {
                        "opening_orders_per_account": opening,
                        "reserved_decisions": cls._reserved(decisions),
                    },
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
        if phase == "day":
            gates.extend(cls._day(recordings, latencies, observations, declaration))
        elif phase == "a":
            gates.append(
                Gate(
                    "injected_owner_death_fenced",
                    cls._fenced(observations, declaration),
                    cls._values(observations, "injected_owner_death"),
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
    def _admitted(
        commits: dict[str, dict[str, int]], decisions: dict[str, dict[str, object]]
    ) -> bool:
        """Require every selected batch committed and every decision in it admitted.

        A batch commit is graded at decision time, where a pending one only defers. Each
        of its strategy decisions must then be admitted in the stopped account journal,
        at once or at its own arrival: a refusal, a missing or unresolved arrival, a
        withdrawal or unreadable evidence fails.
        """
        committed = {
            f"committed:{reason}"
            for reason in DecisionAdmissions.ADMITTED | DecisionAdmissions.PENDING
        }
        admitted = DecisionAdmissions.admitted()
        return (
            len(commits) == 4
            and set(decisions) == set(commits)
            and all(set(counts) <= committed for counts in commits.values())
            and all(
                facts.get("readable") is True
                and bool(outcomes := cast(dict[str, int], facts.get("outcomes")))
                and set(outcomes) <= admitted
                for facts in decisions.values()
            )
        )

    @staticmethod
    def _reserved(decisions: dict[str, dict[str, object]]) -> dict[str, int | None]:
        """Count each account's decisions admitted with reserved orders; None if unreadable."""
        return {
            account: DecisionAdmissions.reserved(cast(dict[str, int], facts["outcomes"]))
            if facts.get("readable") is True
            else None
            for account, facts in decisions.items()
        }

    @classmethod
    def _day(
        cls,
        recordings: dict[str, list[dict[str, object]]],
        latencies: dict[str, object],
        observations: tuple[_Observation, ...],
        declaration: SustainedDeclaration,
    ) -> tuple[Gate, ...]:
        """Grade the day run: native receipt, per-account checkpoint percentiles, daily orders."""
        messages = {
            name: sum(cast(int, entry["durable_records"]) for entry in entries)
            for name, entries in recordings.items()
        }
        total = sum(messages.values())
        receipt = Gate(
            "native_receipt_volume",
            bool(messages)
            and (declaration.minimum_messages is None or total >= declaration.minimum_messages)
            and all(
                count >= declaration.minimum_source_share * total for count in messages.values()
            ),
            {
                "total": total,
                "by_source": messages,
                "minimum": declaration.minimum_messages,
                "minimum_source_share": declaration.minimum_source_share,
            },
        )
        budget = declaration.checkpoint_budget
        accounts = cast(
            dict[str, dict[str, object]], latencies.get("selected_book_to_checkpoint_by_account")
        )
        summaries = {
            name: {
                key: summary.get(key) for key in ("count", "p50_ns", "p95_ns", "p99_ns", "max_ns")
            }
            for name, summary in (accounts or {}).items()
        }
        within = len(summaries) == 4 and all(
            cast(int, item["count"]) >= 1000
            and cast(int, item["p50_ns"]) <= budget.p50_ns
            and cast(int, item["p95_ns"]) <= budget.p95_ns
            and cast(int, item["p99_ns"]) <= budget.p99_ns
            for item in summaries.values()
        )
        checkpoints = Gate(
            "checkpoint_percentiles_per_account",
            within or not declaration.grade_checkpoints,
            {
                "graded": declaration.grade_checkpoints,
                "within_budget": within,
                "budget_ns": (budget.p50_ns, budget.p95_ns, budget.p99_ns),
                "accounts": summaries,
            },
        )
        orders = Gate(
            "orders_within_daily_target",
            cls._orders_within(observations, declaration.maximum_orders_per_day),
            declaration.maximum_orders_per_day,
        )
        return receipt, checkpoints, orders

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
    def _fenced(
        cls, observations: tuple[_Observation, ...], declaration: SustainedDeclaration
    ) -> bool:
        """Report the declared owner death fenced within two seconds, as retained."""
        fence = cls._values(observations, "injected_owner_death")
        return (
            fence is not None
            and fence.get("account") == declaration.inject_owner_death
            and isinstance(fence.get("fence_seconds"), float)
            and cast(float, fence["fence_seconds"]) <= 2
        )

    @classmethod
    def _supervisor_delivery(cls, facts: object, fenced: str | None, evidenced: bool) -> Gate:
        """Grade the supervisor's final verdict for every expected feed and account.

        Offline capture verification never substitutes for it. Every feed must be complete:
        sealed, result retained, pipe drained, exit 0, every durable record delivered and
        every expected account complete. Only in phase A, and only with the fence
        evidenced, the supervisor faulting exactly the declared owner and that owner's
        loss recorded, may a feed of that owner end incomplete, and then only because
        that owner received an exact retained prefix.
        """
        name = "supervisor_source_delivery_complete"
        if not isinstance(facts, dict):
            return Gate(name, False, {"reasons": ["missing"]})
        values = cast(dict[str, object], facts)
        if values.get("readable") is not True:
            return Gate(name, False, {"reasons": [str(values.get("reason"))]})
        expected = cls._mapping(values.get("expected"))
        accounting = cls._mapping(values.get("accounting"))
        failures = cls._events(values.get("failures"))
        reasons: list[str] = []
        excepted: list[str] = []
        if not expected:
            reasons.append("no expected feeds")
        elif accounting is None:
            reasons.append("accounting missing or malformed")
        else:
            books = {feed for feed in expected if not feed.endswith(".trades")}
            # A trades child starts only when a candidate reads trades, so a configured
            # trades feed may be absent; a present one is graded like every other feed.
            if not books <= set(accounting) or not set(accounting) <= set(expected):
                reasons.append(f"feeds {sorted(accounting)} differ from {sorted(expected)}")
            # The supervisor records the killed owner as lost, or as a failed delivery
            # when a checkpoint commit reaches the dead socket first.
            losses = {
                item.get("subject")
                for item in failures or ()
                if item.get("reason") in ("account_owner_lost", "account_or_delivery_failure")
            }
            exception = (
                fenced is not None
                and evidenced
                and values.get("faulted_accounts") == [fenced]
                and fenced in losses
            )
            for feed in sorted(set(accounting) & set(expected)):
                problem = cls._feed_problem(
                    accounting[feed],
                    expected[feed],
                    fenced if exception else None,
                    trades=feed.endswith(".trades"),
                )
                if problem == "excepted":
                    excepted.append(feed)
                elif problem:
                    reasons.append(f"{feed}: {problem}")
        if failures is None:
            reasons.append("failure events missing or malformed")
        else:
            reasons.extend(
                f"unexpected source_delivery_incomplete: {item.get('subject')}"
                for item in failures
                if item.get("reason") == "source_delivery_incomplete"
                and item.get("subject") not in excepted
            )
        return Gate(
            name,
            not reasons,
            {"reasons": reasons, "excepted_fenced_owner_feeds": excepted, "fenced": fenced},
        )

    @staticmethod
    def _mapping(value: object) -> dict[str, object] | None:
        """Return a decoded JSON object, or None for anything else."""
        return cast(dict[str, object], value) if isinstance(value, dict) else None

    @classmethod
    def _events(cls, value: object) -> list[dict[str, object]] | None:
        """Return decoded failure events, or None unless every item is an object."""
        if not isinstance(value, list):
            return None
        items = cast(list[object], value)
        events = [cls._mapping(item) for item in items]
        return (
            None
            if any(event is None for event in events)
            else cast(list[dict[str, object]], events)
        )

    @classmethod
    def _feed_problem(
        cls, entry: object, accounts: object, fenced: str | None, *, trades: bool
    ) -> str:
        """Return why one feed's accounting is not complete, "excepted", or "".

        A book account retains every delivery; a trades account only counts them.
        """
        values = cls._mapping(entry)
        if values is None or not isinstance(accounts, list):
            return "accounting entry malformed"
        configured = sorted(str(item) for item in cast(list[object], accounts))
        durable = values.get("durable_records")
        if (
            values.get("capture_finalization") != "completed"
            or values.get("result_retained") is not True
            or values.get("pipe_drained") is not True
            or values.get("source_exitcode") != 0
            or values.get("error") is not None
            or not isinstance(durable, int)
            or values.get("pipe_deliveries") != durable
        ):
            return "source did not seal, retain, drain, exit cleanly and deliver every record"
        delivered = cls._mapping(values.get("accounts"))
        if delivered is None or sorted(delivered) != configured:
            return "accounts differ from the configured accounts"
        incomplete: list[str] = []
        for account, item in delivered.items():
            counts = cls._mapping(item)
            if counts is None:
                return f"account {account} malformed"
            observed = counts.get("observed_deliveries")
            retained = observed if trades else counts.get("retained_deliveries")
            if counts.get("complete") is True and retained == observed == durable:
                continue
            if (
                account == fenced
                and counts.get("complete") is False
                and isinstance(observed, int)
                and observed == retained
                and 0 <= observed <= durable
            ):
                incomplete.append(account)
                continue
            return f"account {account} incomplete"
        if values.get("status") == "complete" and not incomplete:
            return ""
        if values.get("status") == "incomplete" and incomplete == [fenced]:
            return "excepted"
        return f"status {values.get('status')} inconsistent with its accounts"

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


class SustainedCohort(Cohort):
    """Run the declared sustained or day sequence once, stopping at the first failed step."""

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
        # The grant step builds the declared stage's workload, and so its grant life.
        self.workload_type = type(
            TrialWorkloads.trial_workload(
                self.declaration.workload,
                opening_at=datetime(2026, 1, 1, tzinfo=UTC),
                socket_root=socket_base,
                public_venue=None,
            )
        )

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

    def phase(self, name: str, phase: Literal["a", "b", "day"]) -> tuple[Gate, ...]:
        """Run one sustained phase, collect its facts and assess its gates."""
        declaration = self.declaration
        timings = (
            declaration.phase_a
            if phase == "a"
            else declaration.phase_b
            if phase == "b"
            else cast(TrialTimings, declaration.day)
        )
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
                declaration.workload,
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
                    if phase == "b"
                    else ()
                ),
            ],
        )
        self.verify_sources(name, output)
        results = CapacityResultsCollector(
            output / "operating", output / "measurements", output / "reads"
        ).write(output / "results.json")
        sustained = SustainedResults(
            output,
            window_seconds=declaration.window_seconds,
            budgets=declaration.budgets,
            fixture=declaration.fixture,
        ).collect()
        # The supervisor's own final verdict is graded beside offline verification.
        sustained["supervisor_delivery"] = SupervisorDelivery(output).facts()
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

    def verify_sources(self, name: str, output: Path) -> dict[str, int]:
        """Replay every sealed source recording explicitly, in parallel, after the trial.

        Each outcome, verified or failed, is retained beside its source result by the
        installed ``alpha-execute source-verification``; the recordings gate reads only
        verified records, so a failure here is graded there, never hidden. Every exit
        status is retained in ``logs/source-verification-<name>.json`` and returned.

        Raises:
            FileNotFoundError: The installed verifier is absent; nothing was started.
        """
        roots = [
            recording.root.parent
            for run in sorted(
                path for path in (output / "operating/runs").iterdir() if path.is_dir()
            )
            for source in sorted(path for path in run.iterdir() if path.is_dir())
            for recording in CaptureRecording.discover(source)
        ]
        verifier = self.python.with_name("alpha-execute")
        if not verifier.is_file():
            raise FileNotFoundError(f"installed source verifier is absent: {verifier}")
        logs = self.output / "logs"
        logs.mkdir(exist_ok=True)
        started: list[tuple[Path, subprocess.Popen[bytes]]] = []
        statuses: dict[str, int] = {}
        try:
            for root in roots:
                started.append(
                    (
                        root,
                        subprocess.Popen(  # nosec B603  # [owner=runtime; rationale=explicit absolute argv of the installed source verifier; expires=2027-03-01]
                            [
                                str(verifier),
                                "source-verification",
                                "--root",
                                str(root),
                                "--max-seconds",
                                str(_SOURCE_VERIFICATION_SECONDS),
                            ],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        ),
                    )
                )
        finally:
            for root, process in started:
                stdout, stderr = process.communicate()
                key = f"{root.parent.name}/{root.name}"
                statuses[key] = process.returncode
                stem = f"source-verification-{name}-{root.parent.name}-{root.name}"
                (logs / f"{stem}.stdout").write_bytes(stdout)
                (logs / f"{stem}.stderr").write_bytes(stderr)
            (logs / f"source-verification-{name}.json").write_bytes(
                self.codec.encode_json(statuses)
            )
        return statuses

    def host(self, rows: Path) -> tuple[Gate, ...]:
        """Grade the whole attempt's non-trial host load against the declared ceiling."""
        result = HostGate(
            self.declaration.host_ceiling_cores, self.declaration.host_window_seconds
        ).assess(rows.read_bytes().splitlines())
        (self.output / "host-gate.json").write_bytes(self.codec.encode_json(result))
        return (Gate("host_quiet_throughout", result["status"] == "pass", result),)

    def resources(self, rows: Path) -> tuple[Gate, ...]:
        """Grade the trial process tree's peak RSS and CPU demand over the whole attempt."""
        result = self.declaration.resources.assess(rows.read_bytes().splitlines())
        (self.output / "resource-gate.json").write_bytes(self.codec.encode_json(result))
        return (Gate("trial_resources_within_budget", result["status"] == "pass", result),)

    def replay(self) -> tuple[Gate, ...]:
        """Replay the day's retained deliveries and reconciliations at the declared speed."""
        output = self.root / "day" / "economic-replay.json"
        self.command(
            "economic-replay",
            [
                str(self.python),
                str(self.consumers / "capacity_parity.py"),
                "--root",
                str(self.root),
                "--trial",
                str(self.root / "day"),
                "--output",
                str(output),
                "--sustained",
                self.declaration.workload,
                "--speed",
                str(self.declaration.replay_speed),
                # Beside the live account journals: reported, not counted as scratch.
                "--journals",
                str(self.root / "economic-replay-journals"),
            ],
        )
        report = msgspec.json.decode(output.read_bytes(), type=dict[str, object])
        return (
            Gate(
                "economic_replay_identical_at_speed",
                report.get("qualified") is True,
                {
                    key: report.get(key)
                    for key in ("speed", "required_speed", "replay_seconds", "qualified")
                },
            ),
        )

    def run_day(self) -> None:
        """Run the declared day once: one phase, its audit, host and resource gates."""
        self.output.mkdir(parents=True, exist_ok=False)
        awake = QuietHostPrecheck.hold_awake()
        try:
            self.step("freeze", self.freeze)
            self.step("candidate", self.candidate)
            self.step("quiet-host", self.quiet_host)
            self.step("grant", partial(self.grant, self.root, None))
            rows = self.output / "host-resources.jsonl"
            sampler = HostSampler(rows, trial_root=os.getpid())
            sampler.start()
            try:
                try:
                    self.step("day", partial(self.phase, "day", "day"))
                finally:
                    self.step("cleanup-audit-day", partial(self.audit, self.root, "day"))
            finally:
                sampler.stop()
            self.step("host-gate", partial(self.host, rows))
            self.step("resource-gate", partial(self.resources, rows))
            # The replay runs after the gates, while the retained day ages toward retention.
            self.step("economic-replay", self.replay)
        finally:
            awake.terminate()
            awake.wait(5)

    def run(self) -> None:
        """Run the declared sustained sequence once; ``make check`` stays a separate final step."""
        if self.declaration.stage != "sustained":
            self.run_day()
            return
        self.output.mkdir(parents=True, exist_ok=False)
        awake = QuietHostPrecheck.hold_awake()
        try:
            self.step("freeze", self.freeze)
            self.step("candidate", self.candidate)
            self.step("quiet-host", self.quiet_host)
            self.step("grant", partial(self.grant, self.root, None))
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
    stage: Literal["sustained", "day", "day-rehearsal"]


def main() -> None:
    """Run one declared attempt into a fresh output directory."""
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
        "--stage", choices=("sustained", "day", "day-rehearsal"), default="sustained"
    )
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
        declaration={
            "sustained": SustainedDeclaration,
            "day": SustainedDeclaration.counted_day,
            "day-rehearsal": SustainedDeclaration.day_rehearsal,
        }[args.stage](),
    )
    try:
        cohort.run()
    except Exception as error:
        print(f"sustained cohort stopped: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"sustained cohort passed: {args.output}")


if __name__ == "__main__":
    main()
