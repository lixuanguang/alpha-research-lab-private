"""Prove the sustained declaration's bounds and every sustained phase gate on authored evidence."""

from __future__ import annotations

# standard library imports
import asyncio
import copy
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

# third party library imports
import msgspec
import pytest
from capacity_sustained import SustainedWorkload
from capacity_sustained_cohort import (
    SupervisorDelivery,
    SustainedCohort,
    SustainedDeclaration,
    SustainedGates,
    _Observation,
)
from capacity_trial import TrialTimings
from msgspec.structs import replace

# project library imports
from applications.execute import SourceVerification
from configuration import CaptureConfig, CaptureRunConfig
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueSubscriptions, VenueTransport
from market_data.collection import CaptureRunner
from market_data.contracts import CaptureRunRequest, FeedSocket
from serialization import DomainCodec


class SustainedCohortFixture:
    """Author sustained-cohort evidence, failures and windows."""

    @staticmethod
    def windows(status: str = "pass") -> dict[str, object]:
        """Author one rolling-window class summary."""
        return {"status": status, "windows": []}

    @staticmethod
    def delivery(phase: Literal["a", "b"]) -> dict[str, object]:
        """Author the supervisor's final accounting, shaped like the 2026-10-03 run.

        In phase A the killed ``bitfinex-isolated`` owner received an exact prefix of its
        feed, the supervisor faulted it and recorded its loss; phase B is complete.
        """
        feeds = {
            "okx-btc-book": "okx-shared",
            "okx-eth-book": "okx-isolated",
            "bitfinex-btc-book": "bitfinex-shared",
            "bitfinex-eth-book": "bitfinex-isolated",
        }
        accounting: dict[str, object] = {}
        for feed, account in feeds.items():
            fenced = phase == "a" and account == "bitfinex-isolated"
            delivered = 49523 if fenced else 49538
            accounting[feed] = {
                "status": "incomplete" if fenced else "complete",
                "capture_finalization": "completed",
                "result_retained": True,
                "pipe_drained": True,
                "source_exitcode": 0,
                "durable_records": 49538,
                "pipe_deliveries": 49538,
                "error": None,
                "accounts": {
                    account: {
                        "complete": not fenced,
                        "observed_deliveries": delivered,
                        "retained_deliveries": delivered,
                    }
                },
            }
        failures: list[object] = (
            [
                {"reason": "account_owner_lost", "subject": "bitfinex-isolated"},
                {"reason": "source_delivery_incomplete", "subject": "bitfinex-eth-book"},
                {"reason": "shutdown_failed", "subject": "bitfinex-isolated"},
            ]
            if phase == "a"
            else []
        )
        return {
            "readable": True,
            "expected": {feed: [account] for feed, account in feeds.items()},
            "accounting": accounting,
            "failures": failures,
            "faulted_accounts": ["bitfinex-isolated"] if phase == "a" else [],
        }

    @staticmethod
    def evidence(
        phase: Literal["a", "b"],
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object], list[_Observation]]:
        """Author a passing phase: summary, baseline results, sustained facts and observations."""
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
                "receipt_to_durable": {
                    source: SustainedCohortFixture.windows() for source in sources
                },
                "durable_to_bbo": {
                    account: SustainedCohortFixture.windows() for account in accounts
                },
                "read_depth_bbo": SustainedCohortFixture.windows(),
                "read_dashboard": SustainedCohortFixture.windows(),
                "feature_retrieval": SustainedCohortFixture.windows(),
                "feature_durable_to_available": SustainedCohortFixture.windows(),
                "failed_or_missed_reads": {},
            },
            # The profile's D2 shape: every selected batch commits pending, and each of
            # its two strategies' decisions is admitted at its own arrival.
            "commits": {
                account: {"committed:arrival_pending": checkpoints} for account in accounts
            },
            "decisions": {
                account: SustainedCohortFixture.decisions(checkpoints, opening)
                for account in accounts
            },
            "reconciliations": {
                account: {"attempts": interval // 60, "matched": interval // 60, "max_seconds": 0.1}
                for account in accounts
            },
            "supervisor_delivery": SustainedCohortFixture.delivery(phase),
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

    @staticmethod
    def decisions(checkpoints: int, opening: int) -> dict[str, object]:
        """Author one account's resolved decisions: two a batch, ``opening`` reserving."""
        pending = "committed:arrival_pending->committed"
        return {
            "readable": True,
            "batches": checkpoints,
            "outcomes": {
                **({f"{pending}:reserved": opening} if opening else {}),
                f"{pending}:target_matched": 2 * checkpoints - opening,
            },
        }

    @staticmethod
    def failed(
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
    """Keep every sustained bound finite, nested and inside one ordinary grant."""

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
        assert SustainedCohortFixture.failed(phase, *SustainedCohortFixture.evidence(phase)) == []

    @staticmethod
    def _mutated(
        base: tuple[dict[str, object], dict[str, object], dict[str, object], list[_Observation]],
        change: str,
    ) -> list[str]:
        """Apply one authored defect to a deep copy of the passing evidence."""
        summary, results, sustained, observations = copy.deepcopy(base)
        commits = sustained["commits"]
        decisions = cast(dict[str, dict[str, dict[str, int]]], sustained["decisions"])
        reconciliations = sustained["reconciliations"]
        assert isinstance(commits, dict) and isinstance(reconciliations, dict)
        if change == "rejected":
            commits["okx-shared"]["rejected:stale_firm_account"] = 1
        elif change == "orders":
            decisions["okx-shared"]["outcomes"]["committed:arrival_pending->committed:reserved"] = 3
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
        return SustainedCohortFixture.failed("a", summary, results, sustained, observations)

    def test_each_declared_failure_is_named(self) -> None:
        """A rejected checkpoint, extra order, mismatch or slow fence each fails its gate."""
        base = SustainedCohortFixture.evidence("a")

        assert self._mutated(base, "rejected") == ["checkpoints_commit_without_rejection"]
        assert self._mutated(base, "orders") == ["orders_only_at_opening"]
        assert self._mutated(base, "mismatch") == ["accounts_reconciled_on_cadence"]
        # A slow fence also withdraws the fenced owner's delivery exception.
        assert self._mutated(base, "fence") == [
            "supervisor_source_delivery_complete",
            "injected_owner_death_fenced",
        ]
        assert self._mutated(base, "segments") == ["segments_rolled_over"]

    def test_only_the_fenced_owner_may_end_with_an_undelivered_tail(self) -> None:
        """The injected owner's log stops at its fence; any other account's tail fails."""
        summary, results, sustained, observations = SustainedCohortFixture.evidence("a")
        sources = cast(dict[str, dict[str, dict[str, dict[str, object]]]], results["sources"])
        parity = cast(
            dict[str, dict[str, object]],
            sources["bitfinex-eth-book"]["recordings"]["run"]["delivery_parity"],
        )
        parity["bitfinex-isolated"]["status"] = "unmeasured_unattributed_delivery_tail"
        assert SustainedCohortFixture.failed("a", summary, results, sustained, observations) == []
        parity["bitfinex-shared"]["status"] = "unmeasured_unattributed_delivery_tail"
        assert SustainedCohortFixture.failed("a", summary, results, sustained, observations) == [
            "native_delivery_parity_complete"
        ]

    def test_valid_offline_replay_cannot_mask_an_incomplete_supervisor_verdict(self) -> None:
        """Regression: verified captures and full parity still fail an incomplete verdict.

        day-counted-2's supervisor marked every source incomplete (terminated, result not
        retained, pipe not drained) and no gate read it.
        """
        for phase in ("a", "b"):
            summary, results, sustained, observations = SustainedCohortFixture.evidence(phase)
            delivery = cast(dict[str, object], sustained["supervisor_delivery"])
            accounting = cast(dict[str, dict[str, object]], delivery["accounting"])
            accounting["okx-btc-book"].update(
                status="incomplete", result_retained=False, pipe_drained=False, source_exitcode=-15
            )
            cast(list[object], delivery["failures"]).append(
                {"reason": "source_delivery_incomplete", "subject": "okx-btc-book"}
            )
            # Offline replay and native delivery parity still pass for every source.
            assert SustainedCohortFixture.failed(
                phase, summary, results, sustained, observations
            ) == ["supervisor_source_delivery_complete"]

    @pytest.mark.parametrize(
        "change",
        [
            "missing",
            "unreadable",
            "no_accounting",
            "missing_feed",
            "extra_account",
            "event",
            "incomplete_without_event",
            "no_retained_count",
            "unconfigured_trades",
        ],
    )
    def test_missing_malformed_or_incomplete_accounting_fails(self, change: str) -> None:
        """Absent facts, a missing feed or account, or a stray incomplete event each fail."""
        summary, results, sustained, observations = SustainedCohortFixture.evidence("b")
        delivery = cast(dict[str, object], sustained["supervisor_delivery"])
        accounting = cast(dict[str, dict[str, object]], delivery["accounting"])
        if change == "missing":
            del sustained["supervisor_delivery"]
        elif change == "unreadable":
            sustained["supervisor_delivery"] = {"readable": False, "reason": "status: DecodeError"}
        elif change == "no_accounting":
            delivery["accounting"] = None
        elif change == "missing_feed":
            del accounting["okx-eth-book"]
        elif change == "extra_account":
            cast(dict[str, object], accounting["okx-eth-book"]["accounts"])["okx-shared"] = {
                "complete": True,
                "observed_deliveries": 49538,
                "retained_deliveries": 49538,
            }
        elif change == "event":
            cast(list[object], delivery["failures"]).append(
                {"reason": "source_delivery_incomplete", "subject": "okx-eth-book"}
            )
        elif change == "incomplete_without_event":
            accounting["okx-eth-book"]["status"] = "incomplete"
            account = cast(dict[str, dict[str, object]], accounting["okx-eth-book"]["accounts"])
            account["okx-isolated"]["complete"] = False
        elif change == "no_retained_count":
            account = cast(dict[str, dict[str, object]], accounting["okx-eth-book"]["accounts"])
            del account["okx-isolated"]["retained_deliveries"]
        else:
            # A trades feed that the configuration does not declare is never accepted.
            accounting["okx-eth-book.trades"] = copy.deepcopy(accounting["okx-eth-book"])
        assert SustainedCohortFixture.failed("b", summary, results, sustained, observations) == [
            "supervisor_source_delivery_complete"
        ]

    @pytest.mark.parametrize(
        "change",
        [
            "phase_b",
            "no_fence",
            "not_faulted",
            "no_loss",
            "other_account",
            "lost_records",
            "victim_source_killed",
        ],
    )
    def test_only_the_evidenced_injected_owner_death_is_excepted(self, change: str) -> None:
        """The fenced owner's prefix passes only in phase A with its evidence, nowhere else."""
        phase: Literal["a", "b"] = "b" if change == "phase_b" else "a"
        summary, results, sustained, observations = SustainedCohortFixture.evidence("a")
        delivery = cast(dict[str, object], sustained["supervisor_delivery"])
        accounting = cast(dict[str, dict[str, object]], delivery["accounting"])
        failures = cast(list[dict[str, object]], delivery["failures"])
        expected = ["supervisor_source_delivery_complete"]
        if change == "phase_b":
            observations[-1] = _Observation(
                kind="all_replacement_instances_progressed",
                values={"first_claim_to_progress_seconds": 31.2, "within_40_seconds": True},
            )
            for facts in cast(
                dict[str, dict[str, dict[str, int]]], sustained["decisions"]
            ).values():
                outcomes = facts["outcomes"]
                outcomes["committed:arrival_pending->committed:target_matched"] += outcomes.pop(
                    "committed:arrival_pending->committed:reserved"
                )
        elif change == "no_fence":
            observations.pop()
            expected = ["injected_owner_death_fenced", "supervisor_source_delivery_complete"]
        elif change == "not_faulted":
            delivery["faulted_accounts"] = []
        elif change == "no_loss":
            failures.pop(0)
        elif change == "other_account":
            account = cast(dict[str, dict[str, object]], accounting["okx-btc-book"]["accounts"])
            account["okx-shared"].update(
                complete=False, observed_deliveries=10, retained_deliveries=10
            )
            accounting["okx-btc-book"]["status"] = "incomplete"
        elif change == "lost_records":
            account = cast(
                dict[str, dict[str, object]], accounting["bitfinex-eth-book"]["accounts"]
            )
            account["bitfinex-isolated"]["retained_deliveries"] = 49500
        else:
            # Even with full evidence, the victim's feed must itself seal and exit cleanly.
            accounting["bitfinex-eth-book"]["source_exitcode"] = -15
        failed = SustainedCohortFixture.failed(phase, summary, results, sustained, observations)
        assert set(failed) == set(expected)

    def test_a_death_recorded_as_a_failed_delivery_is_also_evidence(self) -> None:
        """A checkpoint reaching the dead owner first records a delivery failure instead."""
        summary, results, sustained, observations = SustainedCohortFixture.evidence("a")
        delivery = cast(dict[str, object], sustained["supervisor_delivery"])
        failures = cast(list[dict[str, object]], delivery["failures"])
        failures[0] = {"reason": "account_or_delivery_failure", "subject": "bitfinex-isolated"}
        assert SustainedCohortFixture.failed("a", summary, results, sustained, observations) == []

    @pytest.mark.parametrize("victim", [False, True])
    def test_a_declared_trades_feed_is_graded_when_present(self, victim: bool) -> None:
        """A configured trades feed may be absent; when present it counts deliveries only.

        The fenced owner's trades feed is excepted with a prefix in phase A; any other
        account's short trades count fails.
        """
        summary, results, sustained, observations = SustainedCohortFixture.evidence("a")
        delivery = cast(dict[str, object], sustained["supervisor_delivery"])
        expected = cast(dict[str, list[str]], delivery["expected"])
        accounting = cast(dict[str, dict[str, object]], delivery["accounting"])
        failures = cast(list[dict[str, object]], delivery["failures"])
        feed = "bitfinex-eth-book" if victim else "okx-btc-book"
        account = "bitfinex-isolated" if victim else "okx-shared"
        expected[f"{feed}.trades"] = [account]
        # Configured but absent: a trades child starts only when a candidate reads trades.
        assert SustainedCohortFixture.failed("a", summary, results, sustained, observations) == []
        accounting[f"{feed}.trades"] = {
            **accounting["okx-btc-book"],
            "status": "incomplete",
            "accounts": {account: {"complete": False, "observed_deliveries": 40000}},
        }
        failures.append({"reason": "source_delivery_incomplete", "subject": f"{feed}.trades"})
        failed = SustainedCohortFixture.failed("a", summary, results, sustained, observations)
        assert failed == ([] if victim else ["supervisor_source_delivery_complete"])

    def test_recovered_phase_places_no_further_orders(self) -> None:
        """After recovery the held target needs no order; any reserved admission fails."""
        summary, results, sustained, observations = SustainedCohortFixture.evidence("b")
        decisions = cast(dict[str, dict[str, dict[str, int]]], sustained["decisions"])
        decisions["bitfinex-shared"]["outcomes"][
            "committed:replacement_pending->committed:reserved"
        ] = 1
        assert SustainedCohortFixture.failed("b", summary, results, sustained, observations) == [
            "orders_only_at_opening"
        ]

    @pytest.mark.parametrize("phase", ["a", "b"])
    def test_pending_batches_pass_only_when_each_decision_is_admitted(
        self, phase: Literal["a", "b"]
    ) -> None:
        """Regression: D2 pending commits passed only as decision-time admissions before.

        Every selected batch of the profile commits ``arrival_pending``; the gate once
        accepted only ``committed:reserved`` and ``committed:target_matched`` and so
        failed every valid phase. A pending commit alone never passes either: without
        each decision's resolved arrival the checkpoint and opening-order gates fail.
        """
        summary, results, sustained, observations = SustainedCohortFixture.evidence(phase)
        assert SustainedCohortFixture.failed(phase, summary, results, sustained, observations) == []
        del sustained["decisions"]
        assert SustainedCohortFixture.failed(phase, summary, results, sustained, observations) == [
            "checkpoints_commit_without_rejection",
            "orders_only_at_opening",
        ]

    def test_immediate_and_replacement_admissions_pass(self) -> None:
        """An account admitting at once, or a decision replacing work, passes when admitted."""
        summary, results, sustained, observations = SustainedCohortFixture.evidence("a")
        commits = cast(dict[str, dict[str, int]], sustained["commits"])
        decisions = cast(dict[str, dict[str, object]], sustained["decisions"])
        commits["okx-isolated"] = {"committed:reserved": 1, "committed:target_matched": 599}
        decisions["okx-isolated"] = {
            "readable": True,
            "batches": 600,
            "outcomes": {"committed:reserved": 2, "committed:target_matched": 1198},
        }
        commits["okx-shared"] = {
            "committed:arrival_pending": 1,
            "committed:replacement_pending": 599,
        }
        decisions["okx-shared"] = {
            "readable": True,
            "batches": 600,
            "outcomes": {
                "committed:arrival_pending->committed:reserved": 2,
                "committed:replacement_pending->committed:target_matched": 1198,
            },
        }
        assert SustainedCohortFixture.failed("a", summary, results, sustained, observations) == []

    @pytest.mark.parametrize(
        ("outcome", "orders_fail"),
        [
            ("committed:arrival_pending->rejected:order_notional_limit", False),
            ("committed:replacement_pending->rejected:stale_firm_account", False),
            ("committed:arrival_pending->unresolved", False),
            ("committed:replacement_pending->unresolved", False),
            ("committed:arrival_pending->committed:no_fresh_book_at_arrival", False),
            ("committed:replacement_pending->committed:replaced_before_arrival", False),
            ("committed:arrival_pending->committed:withdrawn_by_account_cancel", False),
            ("committed:arrival_pending->committed:arrival_pending", False),
            ("committed:arrival_pending->conflicting", False),
            ("rejected:order_notional_limit", False),
            ("committed:no_intent", False),
            ("missing", False),
            ("missing_batch", False),
            ("unnamed_batch", False),
            ("other_account", False),
            ("conflicting", False),
            ("unreadable", True),
            ("empty", False),
            ("absent_account", True),
        ],
    )
    def test_a_refused_unresolved_or_unevidenced_decision_fails(
        self, outcome: str, orders_fail: bool
    ) -> None:
        """One decision refused, unresolved, withdrawn or unevidenced fails the phase.

        Its batch still committed pending, so decision-time evidence alone is clean.
        """
        summary, results, sustained, observations = SustainedCohortFixture.evidence("b")
        decisions = cast(dict[str, dict[str, object]], sustained["decisions"])
        if outcome == "unreadable":
            decisions["okx-shared"] = {"readable": False, "reason": "OSError: no final state"}
        elif outcome == "empty":
            decisions["okx-shared"]["outcomes"] = {}
        elif outcome == "absent_account":
            del decisions["okx-shared"]
        else:
            cast(dict[str, int], decisions["okx-shared"]["outcomes"])[outcome] = 1
        failed = SustainedCohortFixture.failed("b", summary, results, sustained, observations)
        assert failed == [
            "checkpoints_commit_without_rejection",
            *(["orders_only_at_opening"] if orders_fail else []),
        ]

    def test_an_unacknowledged_or_refused_batch_fails_even_with_admitted_decisions(self) -> None:
        """Decision-time batch evidence is still graded beside each decision's outcome."""
        for status in ("unacknowledged", "committed:no_intent", "rejected:stale_firm_account"):
            summary, results, sustained, observations = SustainedCohortFixture.evidence("b")
            commits = cast(dict[str, dict[str, int]], sustained["commits"])
            commits["okx-shared"][status] = 1
            assert SustainedCohortFixture.failed(
                "b", summary, results, sustained, observations
            ) == ["checkpoints_commit_without_rejection"]

    def test_observations_decode_retained_driver_rows(self) -> None:
        """The gate reads exactly the rows the driver retains."""
        retained: dict[str, object] = {"kind": "startup", "at": "x", "monotonic": 1.0, "values": {}}
        row = msgspec.json.decode(msgspec.json.encode(retained), type=_Observation)
        assert row.kind == "startup"


_BITFINEX_FRAMES: tuple[bytes, ...] = (
    b'{"event":"conf","status":"OK","flags":65536}',
    b'{"event":"subscribed","chanId":7,"channel":"book","symbol":"tBTCUSD","prec":"R0","freq":"F0","len":"25"}',
    b"[7,[[1,100,2],[2,101,-1]],2]",
    b"[7,[1,100,0.25],3]",
)


class _ScriptedBitfinexSocket:
    """Deliver one authored Bitfinex R0 connection, then hold it until the message limit."""

    def __init__(self) -> None:
        """Bind the exact native frames."""
        self.frames = iter(_BITFINEX_FRAMES)

    async def recv(self) -> bytes:
        """Yield authored frames, then wait for the runner's limit."""
        await asyncio.sleep(0)
        frame = next(self.frames, None)
        if frame is None:
            await asyncio.sleep(3600)
            raise AssertionError("runner failed to enforce its message limit")
        return frame

    async def send(self, message: str) -> None:
        """Accept the subscription."""

    async def close(self) -> None:
        """Nothing external is held."""


class _ScriptedBitfinexTransport(VenueTransport):
    """Replace only public routing; the installed parser and journals stay real."""

    async def open(self, timeout: float) -> FeedSocket:
        """Open the authored connection."""
        return _ScriptedBitfinexSocket()


class SealedSourceFixture:
    """Seal real source chains exactly as a stopping paper source does."""

    @staticmethod
    def trial(tmp_path: Path, sources: tuple[str, ...]) -> Path:
        """Seal one chain per source under ``operating/runs/run/<source>/<key>``."""
        trial = tmp_path / "trial"
        config = replace(
            CaptureConfig.read(Path(__file__).parents[4] / "configs/live/bitfinex-btc-usd.json"),
            max_messages=2,
            max_bytes=32768,
            max_frame_bytes=8192,
            queue_capacity=16,
            retries=0,
        )
        now = datetime.now(UTC)
        for index, name in enumerate(sources):
            request = CaptureRunRequest(
                config=config,
                window=CaptureRunConfig(
                    start_at=now - timedelta(seconds=1),
                    ready_by=now + timedelta(seconds=60),
                    stop_at=now + timedelta(seconds=60),
                    max_messages=len(_BITFINEX_FRAMES),
                    max_bytes=1_048_576,
                    max_segments=8,
                    max_reconnects=0,
                ),
                run_id=f"00000000-0000-4000-8000-{index:012d}",
                implementation_identity="a" * 64,
            )
            root = trial / "operating/runs/run" / name / request.run_id
            root.mkdir(parents=True)
            runner = CaptureRunner(
                book_factory=BookAdapters.create,
                transport=_ScriptedBitfinexTransport(config),
                subscriptions=VenueSubscriptions(),
            )
            sealed = asyncio.run(runner.seal_chain(request, root))
            SourceVerification(root).retain_sealed(sealed.summary)
        return trial


class TestSourceVerificationStep:
    """Prove the cohort verifies every sealed source and retains each exit status."""

    def test_every_source_is_verified_and_every_status_retained(self, tmp_path: Path) -> None:
        """A changed sealed result fails with exit 2 while its sibling verifies with 0."""
        trial = SealedSourceFixture.trial(tmp_path, ("good", "edited"))
        (edited,) = trial.glob("operating/runs/run/edited/*/source-result.json")
        fields = msgspec.json.decode(edited.read_bytes(), type=dict[str, object])
        edited.write_bytes(DomainCodec().encode_json({**fields, "saved_records": 999}))
        (tmp_path / "attempt").mkdir()
        cohort = SimpleNamespace(
            python=Path(sys.executable), output=tmp_path / "attempt", codec=DomainCodec()
        )
        statuses = SustainedCohort.verify_sources(cast(SustainedCohort, cohort), "day", trial)
        assert sorted(statuses.values()) == [0, 2]
        retained = msgspec.json.decode(
            (tmp_path / "attempt/logs/source-verification-day.json").read_bytes(),
            type=dict[str, int],
        )
        assert retained == statuses
        (good,) = trial.glob("operating/runs/run/good/*")
        assert SourceVerification(good).verified()
        assert not SourceVerification(edited.parent).verified()
        failed = msgspec.json.decode(
            (edited.parent / SourceVerification.RECORD).read_bytes(), type=dict[str, object]
        )
        assert failed["status"] == "failed" and "saved_records" in str(failed["error"])
        assert not tuple(trial.rglob(".*.pending"))

    def test_an_absent_verifier_starts_nothing(self, tmp_path: Path) -> None:
        """Without the installed verifier the step fails before any source is touched."""
        trial = SealedSourceFixture.trial(tmp_path, ("good",))
        cohort = SimpleNamespace(
            python=tmp_path / "missing/bin/python", output=tmp_path / "attempt", codec=DomainCodec()
        )
        with pytest.raises(FileNotFoundError, match="source verifier is absent"):
            SustainedCohort.verify_sources(cast(SustainedCohort, cohort), "day", trial)
        assert not tuple(trial.rglob(SourceVerification.RECORD))


class TestSupervisorDelivery:
    """Read the supervisor's final accounting against the deployed feeds."""

    def test_expected_feeds_come_from_the_deployed_configuration(self, tmp_path: Path) -> None:
        """Every configured feed and account is expected; an unreadable status is reported."""
        workload = SustainedWorkload(
            opening_at=datetime(2026, 10, 3, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-supervisor-delivery"),
        )
        config = workload.service_configuration()
        (tmp_path / "configuration.json").write_bytes(DomainCodec().encode_json(config))
        missing = SupervisorDelivery(tmp_path).facts()
        assert missing["readable"] is False and missing["reason"] == "status: FileNotFoundError"
        expected = cast(dict[str, list[str]], missing["expected"])
        assert sorted(expected) == sorted(source.name for source in config.sources)
        assert all(len(accounts) == 1 for accounts in expected.values())
        (tmp_path / "operating").mkdir()
        (tmp_path / "operating/status.json").write_bytes(b"{")
        assert SupervisorDelivery(tmp_path).facts()["reason"] == "status: DecodeError"
        status = {
            "schema_version": "paper-service-status",
            "source_delivery_accounting": {"okx-btc-book": {"status": "complete"}},
            "failures": [],
            "faulted_accounts": [],
        }
        (tmp_path / "operating/status.json").write_bytes(DomainCodec().encode_json(status))
        facts = SupervisorDelivery(tmp_path).facts()
        assert facts["readable"] is True and facts["accounting"] == {
            "okx-btc-book": {"status": "complete"}
        }
        (tmp_path / "configuration.json").unlink()
        assert SupervisorDelivery(tmp_path).facts() == {
            "readable": False,
            "reason": "configuration: FileNotFoundError",
        }
