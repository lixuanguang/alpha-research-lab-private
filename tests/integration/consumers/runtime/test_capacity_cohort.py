"""Prove each declared cohort gate fails on exactly the evidence it guards."""

from __future__ import annotations

# standard library imports
import copy
import os
import pathlib
from typing import cast

# third party library imports
import msgspec
import pytest
from capacity_cohort import CleanupAudit, Cohort, Gate, GateAssessment, PublicVenue, Sequence

Path = tuple[str, ...]


def _set(evidence: dict[str, object], path: Path, value: object) -> None:
    """Replace one nested JSON value."""
    node = evidence
    for key in path[:-1]:
        node = cast(dict[str, object], node[key])
    node[path[-1]] = value


class TestCapacityCohortGates:
    """Start from a passing synthetic trial and break one fact at a time."""

    @staticmethod
    def _recording(origin: str) -> dict[str, object]:
        """Author one source recording whose every graded status passes."""
        return {
            "capture": {
                "completed_manifest": True,
                "stop_status": "pass",
                "stop_reason": "supervisor_stop",
                "size_budget_status": "pass",
                "fixture_schedule_proof": {
                    "status": "pass" if origin == "base_fixture" else "unmeasured"
                },
            },
            "source_probe": {
                "queue": {"status": "pass"},
                "coverage": {"status": "pass"},
                "steady_receipt_to_durable": {"status": "pass"},
                "receipt_to_durable": {"status": "fail"},
            },
            "account_probes": {
                "account-a": {
                    "coverage": {"status": "pass"},
                    "steady_durable_to_bbo": {"status": "pass"},
                }
            },
            "delivery_parity": {"account-a": {"status": "pass_complete_native_stream"}},
        }

    @classmethod
    def _evidence(
        cls, *, public: PublicVenue = None
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        """Return passing summary, collected results and resource summary."""
        okx = "live_public" if public == "okx" else "base_fixture"
        bitfinex = "live_public" if public == "bitfinex" else "base_fixture"
        results: dict[str, object] = {
            "steady_monotonic_interval_ns": [0, 60_003_000_000],
            "sources": {
                "okx-btc-book": {
                    "venue": "okx",
                    "transport_origin": okx,
                    "recordings": {"r1": cls._recording(okx)},
                },
                "bitfinex-btc-book": {
                    "venue": "bitfinex",
                    "transport_origin": bitfinex,
                    "recordings": {"r2": cls._recording(bitfinex)},
                },
            },
            "reads": {
                "four_reader_workload": {
                    boundary: {"status": "pass", "schedule_status": "pass"}
                    for boundary in ("depth_bbo", "dashboard")
                }
            },
        }
        resources: dict[str, object] = {
            "status": "pass",
            "cpu_average_logical_cores": 2.1,
            "peak_rss_bytes": 2_650_000_000,
            "peak_occupied_bytes": 270_000_000,
        }
        return {"passed": True, "failures": []}, results, resources

    @staticmethod
    def _failed(gates: tuple[Gate, ...]) -> set[str]:
        """Name every failed gate."""
        return {gate.name for gate in gates if not gate.passed}

    @pytest.mark.parametrize("venue", ("okx", "bitfinex"))
    def test_passing_fixture_and_public_evidence_pass(self, venue: PublicVenue) -> None:
        """Ungraded public latency and an unread public schedule do not fail a route."""
        assert not self._failed(GateAssessment.trial(*self._evidence(), public_venue=None))
        summary, results, _ = self._evidence(public=venue)
        del results["reads"]
        assert not self._failed(GateAssessment.trial(summary, results, {}, public_venue=venue))

    @pytest.mark.parametrize(
        ("evidence", "route", "gate"),
        (
            ("okx", None, "okx-btc-book.transport_origin"),
            ("bitfinex", "okx", "bitfinex-btc-book.transport_origin"),
            (None, "okx", "okx-btc-book.transport_origin"),
            ("okx", "bitfinex", "okx-btc-book.transport_origin"),
        ),
    )
    def test_only_the_route_venue_is_public(
        self, evidence: PublicVenue, route: PublicVenue, gate: str
    ) -> None:
        """A public source outside the route, or a route venue still on the fixture, fails."""
        summary, results, resources = self._evidence(public=evidence)
        assert gate in self._failed(
            GateAssessment.trial(summary, results, resources, public_venue=route)
        )

    @pytest.mark.parametrize(
        ("path", "value", "gate"),
        (
            (
                ("steady_monotonic_interval_ns",),
                [0, 59_999_000_000],
                "measured_interval_at_least_60_seconds",
            ),
            (
                ("sources", "okx-btc-book", "recordings", "r1", "capture", "stop_status"),
                "fail",
                "okx-btc-book.stop_status",
            ),
            (
                ("sources", "okx-btc-book", "recordings", "r1", "capture", "completed_manifest"),
                False,
                "okx-btc-book.completed_manifest",
            ),
            (
                ("sources", "okx-btc-book", "recordings", "r1", "capture", "size_budget_status"),
                "unmeasured",
                "okx-btc-book.size_budget_status",
            ),
            (
                (
                    "sources",
                    "okx-btc-book",
                    "recordings",
                    "r1",
                    "capture",
                    "fixture_schedule_proof",
                    "status",
                ),
                "fail",
                "okx-btc-book.fixture_schedule_status",
            ),
            (
                ("sources", "okx-btc-book", "recordings", "r1", "source_probe", "queue", "status"),
                "fail",
                "okx-btc-book.queue_status",
            ),
            (
                (
                    "sources",
                    "okx-btc-book",
                    "recordings",
                    "r1",
                    "source_probe",
                    "coverage",
                    "status",
                ),
                "fail",
                "okx-btc-book.probe_coverage_status",
            ),
            (
                (
                    "sources",
                    "okx-btc-book",
                    "recordings",
                    "r1",
                    "source_probe",
                    "steady_receipt_to_durable",
                    "status",
                ),
                "unmeasured",
                "okx-btc-book.steady_receipt_to_durable_status",
            ),
            (
                (
                    "sources",
                    "okx-btc-book",
                    "recordings",
                    "r1",
                    "delivery_parity",
                    "account-a",
                    "status",
                ),
                "pass_available_cursor_prefix",
                "okx-btc-book.account-a.delivery_parity",
            ),
            (
                (
                    "sources",
                    "okx-btc-book",
                    "recordings",
                    "r1",
                    "account_probes",
                    "account-a",
                    "steady_durable_to_bbo",
                    "status",
                ),
                "fail",
                "okx-btc-book.account-a.steady_durable_to_bbo_status",
            ),
            (
                (
                    "sources",
                    "okx-btc-book",
                    "recordings",
                    "r1",
                    "account_probes",
                    "account-a",
                    "coverage",
                    "status",
                ),
                "fail",
                "okx-btc-book.account-a.probe_coverage_status",
            ),
            (
                ("sources", "okx-btc-book", "recordings", "r1", "account_probes"),
                {},
                "okx-btc-book.accounts_present",
            ),
            (("sources", "okx-btc-book", "recordings"), {}, "okx-btc-book.one_recording"),
            (
                ("sources", "bitfinex-btc-book", "transport_origin"),
                "live_public",
                "bitfinex-btc-book.transport_origin",
            ),
            (
                ("reads", "four_reader_workload", "dashboard", "status"),
                "fail",
                "reads.dashboard.status",
            ),
            (
                ("reads", "four_reader_workload", "depth_bbo", "schedule_status"),
                "unmeasured",
                "reads.depth_bbo.schedule_status",
            ),
        ),
    )
    def test_each_fixture_gate_fails(self, path: Path, value: object, gate: str) -> None:
        """Breaking one collected fact fails the gate that guards it."""
        summary, results, resources = self._evidence()
        changed = copy.deepcopy(results)
        _set(changed, path, value)
        assert gate in self._failed(
            GateAssessment.trial(summary, changed, resources, public_venue=None)
        )

    @pytest.mark.parametrize(
        ("field", "value", "gate"),
        (
            ("status", "fail", "resources.sampling_status"),
            ("cpu_average_logical_cores", 7.01, "resources.average_cpu_at_most_7_cores"),
            ("peak_rss_bytes", 24 * 1024**3 + 1, "resources.peak_rss_at_most_24_gib"),
            ("peak_occupied_bytes", 320 * 1024**3 + 1, "resources.peak_occupied_at_most_320_gib"),
            ("peak_rss_bytes", None, "resources.peak_rss_at_most_24_gib"),
        ),
    )
    def test_resource_ceilings(self, field: str, value: object, gate: str) -> None:
        """Every documented ceiling, and absent sampling, fails only its own gate."""
        summary, results, resources = self._evidence()
        assert self._failed(
            GateAssessment.trial(summary, results, {**resources, field: value}, public_venue=None)
        ) == {gate}

    @pytest.mark.parametrize(
        ("path", "value", "gate"),
        (
            (
                ("sources", "bitfinex-btc-book", "recordings", "r2", "capture", "stop_status"),
                "fail",
                "bitfinex-btc-book.stop_status",
            ),
            (
                (
                    "sources",
                    "bitfinex-btc-book",
                    "recordings",
                    "r2",
                    "source_probe",
                    "queue",
                    "status",
                ),
                "fail",
                "bitfinex-btc-book.queue_status",
            ),
            (
                (
                    "sources",
                    "bitfinex-btc-book",
                    "recordings",
                    "r2",
                    "delivery_parity",
                    "account-a",
                    "status",
                ),
                "pass_available_cursor_prefix",
                "bitfinex-btc-book.account-a.delivery_parity",
            ),
            (
                (
                    "sources",
                    "okx-btc-book",
                    "recordings",
                    "r1",
                    "source_probe",
                    "steady_receipt_to_durable",
                    "status",
                ),
                "fail",
                "okx-btc-book.steady_receipt_to_durable_status",
            ),
        ),
    )
    def test_public_route_criteria(self, path: Path, value: object, gate: str) -> None:
        """A capped or incomplete public stream, or a failing fixture source, fails a route."""
        summary, results, _ = self._evidence(public="bitfinex")
        _set(results, path, value)
        assert gate in self._failed(
            GateAssessment.trial(summary, results, {}, public_venue="bitfinex")
        )

    @pytest.mark.parametrize(
        ("path", "value", "gate"),
        (
            (
                ("sources", "okx-btc-book", "recordings", "r1", "capture", "stop_status"),
                "fail",
                "okx-btc-book.stop_status",
            ),
            (
                (
                    "sources",
                    "bitfinex-btc-book",
                    "recordings",
                    "r2",
                    "capture",
                    "fixture_schedule_proof",
                    "status",
                ),
                "fail",
                "bitfinex-btc-book.fixture_schedule_status",
            ),
        ),
    )
    def test_public_okx_route_criteria(self, path: Path, value: object, gate: str) -> None:
        """An OKX route grades its public captures and the Bitfinex fixture's unchanged gates."""
        summary, results, _ = self._evidence(public="okx")
        _set(results, path, value)
        assert gate in self._failed(GateAssessment.trial(summary, results, {}, public_venue="okx"))

    def test_failed_trial(self) -> None:
        """Any retained trial failure, such as one unhealthy witness, fails the trial gate."""
        _, results, resources = self._evidence()
        assert self._failed(
            GateAssessment.trial(
                {"passed": False, "failures": ["steady health"]},
                results,
                resources,
                public_venue=None,
            )
        ) == {"trial_passed"}


class TestHistoryAndCleanup:
    """Require four complete query classes and an empty process audit."""

    @staticmethod
    def _summary() -> dict[str, object]:
        """Author four passing classes with matched-cutoff parity."""
        return {
            "matched_cutoff_parity": True,
            "results": [
                {
                    "boundary": boundary,
                    "cache_class": cache_class,
                    "requests": 1000,
                    "failures": 0,
                    "service_latency": {"status": "pass"},
                    "scheduled_response_latency": {"status": "pass"},
                }
                for boundary in ("depth_bbo", "dashboard")
                for cache_class in ("application_cold", "warm")
            ],
        }

    @pytest.mark.parametrize(
        ("index", "field", "value", "gate"),
        (
            (None, "matched_cutoff_parity", False, "matched_cutoff_parity"),
            (0, "requests", 999, "depth_bbo.application_cold.requests"),
            (1, "failures", 1, "depth_bbo.warm.requests"),
            (
                3,
                "scheduled_response_latency",
                {"status": "fail"},
                "dashboard.warm.scheduled_response_latency",
            ),
            (
                2,
                "service_latency",
                {"status": "unmeasured"},
                "dashboard.application_cold.service_latency",
            ),
            (3, "cache_class", "other", "dashboard.warm.requests"),
        ),
    )
    def test_history_classes(self, index: int | None, field: str, value: object, gate: str) -> None:
        """A missing class, short count, failure, budget miss or parity loss fails."""
        assert all(item.passed for item in GateAssessment.history(self._summary()))
        summary = self._summary()
        target = (
            summary
            if index is None
            else cast(dict[str, object], cast(list[object], summary["results"])[index])
        )
        target[field] = value
        assert gate in {item.name for item in GateAssessment.history(summary) if not item.passed}

    def test_observed_pids_and_liveness(self) -> None:
        """Pid fields at any depth are collected; this process is alive, a free pid is not."""
        rows: tuple[object, ...] = (
            {"values": {"pid": 11, "workers": [{"supervisor_pid": 12}]}},
            {"values": {"account_pids": {"a": 13, "b": 14}, "count": 15}},
        )
        assert CleanupAudit.observed_pids(iter(rows)) == {11, 12, 13, 14}
        assert CleanupAudit.alive(os.getpid())
        assert not CleanupAudit.alive(4_194_303)


_PASSING = (Gate("ok", True, None),)


class _ReportingCohort(Cohort):
    """Replace every side-effecting action with a report of its inputs."""

    def freeze(self) -> dict[str, object]:
        """Freeze nothing."""
        return {}

    def candidate(self) -> dict[str, object]:
        """Build nothing."""
        return {}

    def history(self) -> tuple[Gate, ...]:
        """Query nothing and pass."""
        return _PASSING

    def prepare_route(self) -> dict[str, object]:
        """Report the route root this sequence selected."""
        return {"root": self.route_root.name}

    def grant(self, root: pathlib.Path, public_venue: PublicVenue) -> dict[str, object]:
        """Report the root and public venue the grants would bind."""
        return {"root": root.name, "venue": public_venue}

    def trial(self, root: pathlib.Path, name: str, public_venue: PublicVenue) -> tuple[Gate, ...]:
        """Run nothing and pass."""
        return _PASSING

    def audit(self, root: pathlib.Path, trial: str) -> tuple[Gate, ...]:
        """Audit nothing and pass."""
        return _PASSING


class TestCohortSequence:
    """Each declared sequence runs exactly its steps, in order, into one fresh output."""

    @staticmethod
    def _steps(tmp_path: pathlib.Path, sequence: Sequence) -> list[tuple[str, object]]:
        """Run a cohort whose actions only report their inputs, and read its step log."""
        _ReportingCohort(
            tmp_path / "cohort",
            repository=tmp_path,
            launcher=tmp_path / "launcher",
            python=tmp_path / "python",
            key_root=tmp_path / "keys",
            socket_base=tmp_path / "sockets",
            label="sequence-test",
            sequence=sequence,
        ).run()
        rows = [
            msgspec.json.decode(line, type=dict[str, object])
            for line in (tmp_path / "cohort/steps.jsonl").read_bytes().splitlines()
        ]
        return [(cast(str, row["step"]), row["values"]) for row in rows]

    def test_dashboard_sequence_is_unchanged(self, tmp_path: pathlib.Path) -> None:
        """The approved dashboard cohort keeps its steps and its Bitfinex route."""
        steps = self._steps(tmp_path, "dashboard")
        assert [name for name, _ in steps] == [
            "freeze",
            "candidate",
            "grant-steady",
            "steady-trial",
            "history-queries",
            "route-prepare",
            "grant-route",
            "public-bitfinex-trial",
            "cleanup-audit-steady",
            "cleanup-audit-route",
        ]
        assert dict(steps)["grant-route"] == {"root": "route-bitfinex", "venue": "bitfinex"}

    def test_public_okx_sequence_runs_only_the_route(self, tmp_path: pathlib.Path) -> None:
        """The OKX sequence signs the same candidate and runs no steady trial or queries."""
        steps = self._steps(tmp_path, "public-okx")
        assert [name for name, _ in steps] == [
            "freeze",
            "candidate",
            "route-prepare",
            "grant-route",
            "public-okx-trial",
            "cleanup-audit-route",
        ]
        assert dict(steps)["grant-route"] == {"root": "route-okx", "venue": "okx"}

    def test_a_second_attempt_into_the_same_output_is_refused(self, tmp_path: pathlib.Path) -> None:
        """A declared single attempt cannot be repeated into its own output."""
        self._steps(tmp_path, "public-okx")
        with pytest.raises(FileExistsError):
            self._steps(tmp_path, "public-okx")
