"""Prove the 2a declaration's bounds and every sustained phase gate on authored evidence."""

from __future__ import annotations

# standard library imports
import copy
from typing import Literal, cast

# third party library imports
import msgspec
import pytest
from capacity_sustained_cohort import SustainedDeclaration, SustainedGates, _Observation
from capacity_trial import TrialTimings


def _windows(status: str = "pass") -> dict[str, object]:
    """Author one rolling-window class summary."""
    return {"status": status, "windows": []}


def _evidence(
    phase: Literal["a", "b"],
) -> tuple[dict[str, object], dict[str, object], dict[str, object], list[_Observation]]:
    """Author a passing phase: summary, stage-1 results, sustained facts and observations."""
    sources = ("okx-btc-book", "okx-eth-book", "bitfinex-btc-book", "bitfinex-eth-book")
    accounts = ("okx-shared", "okx-isolated", "bitfinex-shared", "bitfinex-isolated")
    interval = 1800 if phase == "a" else 600
    checkpoints = interval // 3
    results: dict[str, object] = {
        "sources": {
            source: {
                "recordings": {
                    "run": {
                        "delivery_parity": {
                            account: {"status": "pass_complete_native_stream"}
                            for account in accounts
                        }
                    }
                }
            }
            for source in sources
        }
    }
    opening = 2 if phase == "a" else 0
    sustained: dict[str, object] = {
        "recordings": {
            source: [
                {
                    "completed": True,
                    "replay_parity": True,
                    "segments": 2 if phase == "a" else 1,
                }
            ]
            for source in sources
        },
        "fixture_proofs": {source: {"status": "pass"} for source in sources},
        "latencies": {
            "receipt_to_durable": {source: _windows() for source in sources},
            "durable_to_bbo": {account: _windows() for account in accounts},
            "read_depth_bbo": _windows(),
            "read_dashboard": _windows(),
            "feature_retrieval": _windows(),
            "feature_durable_to_available": _windows(),
            "failed_or_missed_reads": {},
        },
        "commits": {
            account: {
                **({"committed:reserved": opening} if opening else {}),
                "committed:target_matched": checkpoints - opening,
            }
            for account in accounts
        },
        "reconciliations": {
            account: {"attempts": interval // 60, "matched": interval // 60, "max_seconds": 0.1}
            for account in accounts
        },
    }
    observations = [
        _Observation(
            kind="account_facts",
            values={"label": "post_shutdown", "account": account, "child_orders": 2},
        )
        for account in accounts
    ]
    observations.append(
        _Observation(
            kind="injected_owner_death",
            values={"account": "bitfinex-isolated", "fence_seconds": 0.4},
        )
        if phase == "a"
        else _Observation(
            kind="all_replacement_instances_progressed",
            values={"first_claim_to_progress_seconds": 31.2, "within_40_seconds": True},
        )
    )
    summary: dict[str, object] = {"passed": True, "failures": []}
    return summary, results, sustained, observations


def _failed(
    phase: Literal["a", "b"],
    summary: dict[str, object],
    results: dict[str, object],
    sustained: dict[str, object],
    observations: list[_Observation],
) -> list[str]:
    """Return the names of every failed gate."""
    gates = SustainedGates.phase(
        phase, summary, results, sustained, tuple(observations), SustainedDeclaration()
    )
    return [gate.name for gate in gates if not gate.passed]


class TestSustainedDeclaration:
    """Keep every 2a bound finite, nested and inside one ordinary grant."""

    def test_default_phases_fit_one_hour_grant_with_recovery_headroom(self) -> None:
        """Both phases' service lives and the recovery fit inside the one-hour grant."""
        declaration = SustainedDeclaration()
        recovery_and_build_margin = 600
        assert (
            declaration.phase_a.service_seconds
            + declaration.phase_b.service_seconds
            + recovery_and_build_margin
            <= 3600
        )
        assert max(declaration.phase_a.service_seconds, declaration.phase_b.service_seconds) <= 3000
        assert TrialTimings() == TrialTimings(60, 75, 120)

    def test_partial_windows_and_slow_reconciliation_are_refused(self) -> None:
        """An interval of partial windows or a cadence past the state age cannot be declared."""
        with pytest.raises(ValueError, match="whole rolling windows"):
            SustainedDeclaration(phase_a=TrialTimings(1860, 1900, 1950))
        with pytest.raises(ValueError, match="inside 120 seconds"):
            SustainedDeclaration(reconcile_seconds=120)
        with pytest.raises(ValueError, match="must nest"):
            TrialTimings(600, 600, 700)


class TestSustainedGates:
    """Pass only a complete, order-light, reconciled and fenced phase."""

    @pytest.mark.parametrize("phase", ["a", "b"])
    def test_complete_phase_passes_every_gate(self, phase: Literal["a", "b"]) -> None:
        """Authored complete evidence passes every declared gate."""
        assert _failed(phase, *_evidence(phase)) == []

    def test_each_declared_failure_is_named(self) -> None:
        """A rejected checkpoint, extra order, mismatch or slow fence each fails its gate."""
        base = _evidence("a")

        def mutated(change: str) -> list[str]:
            """Apply one authored defect to a deep copy of the passing evidence."""
            summary, results, sustained, observations = copy.deepcopy(base)
            commits = sustained["commits"]
            reconciliations = sustained["reconciliations"]
            assert isinstance(commits, dict) and isinstance(reconciliations, dict)
            if change == "rejected":
                commits["okx-shared"]["committed:rejected"] = 1
            elif change == "orders":
                commits["okx-shared"]["committed:reserved"] = 3
            elif change == "mismatch":
                reconciliations["okx-shared"]["matched"] = 29
            elif change == "fence":
                observations[-1] = _Observation(
                    kind="injected_owner_death",
                    values={"account": "bitfinex-isolated", "fence_seconds": 2.5},
                )
            elif change == "segments":
                recordings = cast(dict[str, list[dict[str, object]]], sustained["recordings"])
                recordings["okx-btc-book"][0]["segments"] = 1
            return _failed("a", summary, results, sustained, observations)

        assert mutated("rejected") == ["checkpoints_commit_without_rejection"]
        assert mutated("orders") == ["orders_only_at_opening"]
        assert mutated("mismatch") == ["accounts_reconciled_on_cadence"]
        assert mutated("fence") == ["injected_owner_death_fenced"]
        assert mutated("segments") == ["segments_rolled_over"]

    def test_recovered_phase_places_no_further_orders(self) -> None:
        """After recovery the held target needs no order; any reserved commit fails."""
        summary, results, sustained, observations = _evidence("b")
        commits = sustained["commits"]
        assert isinstance(commits, dict)
        commits["bitfinex-shared"]["committed:reserved"] = 1
        assert _failed("b", summary, results, sustained, observations) == ["orders_only_at_opening"]

    def test_observations_decode_retained_driver_rows(self) -> None:
        """The gate reads exactly the rows the driver retains."""
        retained: dict[str, object] = {"kind": "startup", "at": "x", "monotonic": 1.0, "values": {}}
        row = msgspec.json.decode(msgspec.json.encode(retained), type=_Observation)
        assert row.kind == "startup"
