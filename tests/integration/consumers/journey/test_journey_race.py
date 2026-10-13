"""Grade the shared-limit race from where the journal records each refusal."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta

# third party library imports
from journey_paper import RaceCheck

# project library imports
from execution import DecisionOutcome

_AT = datetime(2026, 10, 13, 15, 2, tzinfo=UTC)


class TestRaceCheck:
    """Read refusals at arrival and reservations behind pending decisions."""

    @staticmethod
    def _outcome(instance: str, seconds: float, status: str, reason: str) -> DecisionOutcome:
        """Build one saved decision's outcome at an offset from the race window."""
        return DecisionOutcome(
            account_id="okx-shared",
            instance_id=instance,
            decision_identity=f"{instance}-{seconds}-{reason}",
            decided_at=_AT + timedelta(seconds=seconds),
            status="committed" if status == "committed" else "rejected",
            reason=reason,
        )

    def test_a_refusal_at_arrival_is_read_from_its_own_outcome(self) -> None:
        """A deferred decision refused at its arrival is a limit refusal at that clock."""
        decided = (
            self._outcome("rule", 0, "committed", "arrival_pending"),
            self._outcome("rule", 0.001, "rejected", "holding_limit"),
            self._outcome("reference", 1, "committed", "arrival_pending"),
            self._outcome("reference", 1.001, "committed", "reserved"),
        )
        assert RaceCheck.decided_refusals(decided) == [(_AT + timedelta(seconds=0.001), "rule")]

    def test_a_pending_decision_does_not_hide_an_earlier_reservation(self) -> None:
        """Another contender still holds the reservation its earlier arrival made."""
        decided = (
            self._outcome("reference", 0, "committed", "arrival_pending"),
            self._outcome("reference", 0.001, "committed", "reserved"),
            self._outcome("reference", 2, "committed", "arrival_pending"),
        )
        race = RaceCheck.held(
            "rule", _AT + timedelta(seconds=3), ("reference", "rule"), (), decided
        )
        assert race == {
            "at": _AT + timedelta(seconds=3),
            "refused": "rule",
            "held_by": "reference",
            "held": 0,
            "reserved": True,
        }

    def test_a_refusal_while_every_other_contender_is_flat_is_not_the_race(self) -> None:
        """No fills and no standing reservation elsewhere: the contender's own limit."""
        decided = (
            self._outcome("reference", 0, "committed", "arrival_pending"),
            self._outcome("reference", 0.001, "committed", "target_matched"),
            self._outcome("reference", 4, "committed", "reserved"),
        )
        assert (
            RaceCheck.held("rule", _AT + timedelta(seconds=3), ("reference", "rule"), (), decided)
            is None
        )
