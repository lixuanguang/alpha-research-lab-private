"""Prove the stage-2a workload's schedule, selection and low-order commit mix offline."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

# third party library imports
import msgspec
import pytest
from capacity_inputs import CapacityNativeFixture, CapacityWorkload
from capacity_sustained import SustainedNativeFixture, SustainedWorkload

# project library imports
from configuration import PaperSourceChain
from serialization import DomainCodec

_OPENING = datetime(2026, 10, 3, 12, tzinfo=UTC)
_SOCKETS = Path("/private/tmp/capacity-sustained-test")


class TestCapacitySustained:
    """Keep the declared stage-2 load and order mix measurable before any signed run."""

    def test_schedule_repeats_a_ten_second_burst_every_five_minutes(self) -> None:
        """Ten 300-second periods of 25 Hz with a final 100 Hz burst cover 3,000 seconds."""
        fixture = SustainedNativeFixture
        assert fixture.frame_count == 82_500
        assert fixture.elapsed_seconds(7249) == pytest.approx(289.96)
        assert fixture.elapsed_seconds(7250) == 290
        assert fixture.elapsed_seconds(8249) == pytest.approx(299.99)
        assert fixture.elapsed_seconds(8250) == 300
        assert fixture.elapsed_seconds(82_499) == pytest.approx(2999.99)
        per_period = [
            sum(
                1
                for index in range(fixture.frame_count)
                if period * 300 <= fixture.elapsed_seconds(index) < (period + 1) * 300
            )
            for period in range(10)
        ]
        assert per_period == [8250] * 10
        with pytest.raises(ValueError):
            fixture.elapsed_seconds(82_500)

    def test_selection_declares_segments_chain_life_and_target_holders(self) -> None:
        """2a sources roll 30-minute segments in one chain; owners outlive the supervisor."""
        stage1 = CapacityWorkload(opening_at=_OPENING, socket_root=_SOCKETS)
        workload = SustainedWorkload(opening_at=_OPENING, socket_root=_SOCKETS)
        service = workload.service_configuration()
        assert len(service.sources) == len(service.accounts) == 4
        assert len(service.instances) == len(service.active) == 8
        for source in service.sources:
            capture = source.capture
            assert (capture.duration_seconds, capture.max_messages, capture.max_bytes) == (
                1800,
                75_000,
                268_435_456,
            )
            assert (capture.queue_capacity, capture.retries) == (2048, 1)
            assert source.chain == PaperSourceChain(
                max_messages=100_000, max_bytes=1024**3, max_segments=4
            )
            assert source.scenario.adverse.value == Decimal(0)
            assert source.market_interval_us == 3_000_000
            identity = SustainedNativeFixture(source).identity
            assert identity != CapacityNativeFixture(source).identity
            assert identity != SustainedNativeFixture(source, start_high=True).identity
        assert all(account.configuration.service_life_limit == 3000 for account in service.accounts)
        assert service.duration_seconds == 2880
        assert {(item.policy, str(item.quantity.value)) for item in service.instances} == {
            ("target_clip", "1")
        }
        # The stage-1 selection keeps its exact encoding: no chain, life or new policy.
        encoded = DomainCodec().encode_json(stage1.service_configuration())
        assert b'"chain"' not in encoded and b"service_life_seconds" not in encoded
        assert {item.policy for item in stage1.service_configuration().instances} == {
            "fixed_clip",
            "liquidity_clip",
        }
        transports = workload.fixture_transports(service)
        assert all(type(item) is SustainedNativeFixture for item in transports.values())
        with pytest.raises(ValueError):
            workload.fixture_transports(service, variant="reconnect")

    def test_projected_orders_open_once_then_every_checkpoint_matches(self, tmp_path: Path) -> None:
        """Replayed books place two opening orders per account, then commit order-free."""
        workload = SustainedWorkload(opening_at=_OPENING, socket_root=_SOCKETS)
        projection = workload.projection(tmp_path / "reconciled", minutes=6, window_minutes=45)
        sources = cast(dict[str, dict[str, object]], projection["sources"])
        assert {item["window_segments"] for item in sources.values()} == {2}
        assert {item["window_messages"] for item in sources.values()} == {74_250}
        accounts = cast(dict[str, dict[str, object]], projection["accounts"])
        assert len(accounts) == 4
        for facts in accounts.values():
            assert facts["orders"] == facts["filled_orders"] == 2
            assert facts["committed_checkpoints"] == 120
            assert facts["commit_reasons"] == {"reserved": 1, "target_matched": 119}
            assert facts["reconciliations"] == 5
            assert set(cast(dict[str, object], facts["holdings"]).values()) == {
                ("1.000000000000000000",)
            }
            assert facts["window_selected_books"] == 900
            assert (facts["opening_orders"], facts["steady_orders"]) == (2, 0)
            assert facts["window_orders_projected"] == 2
            assert (facts["daily_order_target"], facts["grant_maximum_orders"]) == (40, 80)
        # The recovery oracle is the replayed journal's own final economics.
        oracle = workload.first_touch_oracle()
        for account_id, facts in accounts.items():
            cash, fees, positions = oracle[account_id]
            assert facts["final_economics"] == ((cash,), (fees,), positions)

    def test_without_reconciliation_a_held_position_goes_stale(self, tmp_path: Path) -> None:
        """The unchanged 120-second state age rejects checkpoints that no reconcile refreshes."""
        workload = SustainedWorkload(opening_at=_OPENING, socket_root=_SOCKETS)
        projection = workload.projection(
            tmp_path / "unreconciled", minutes=3, window_minutes=45, reconcile_seconds=None
        )
        accounts = cast(dict[str, dict[str, object]], projection["accounts"])
        for facts in accounts.values():
            reasons = cast(dict[str, int], facts["commit_reasons"])
            assert reasons["stale_firm_account"] > 0 and facts["orders"] == 2

    def test_preparation_retains_the_declared_inputs_and_projection(self, tmp_path: Path) -> None:
        """Preparation writes the selection, owner configurations and the measured projection."""
        workload = SustainedWorkload(opening_at=_OPENING, socket_root=_SOCKETS)
        summary = workload.prepare(tmp_path / "prepared")
        retained = msgspec.json.decode(
            (tmp_path / "prepared/preparation.json").read_bytes(), type=dict[str, object]
        )
        assert retained["selection"] == workload.service_configuration().identity
        assert (retained["account_service_seconds"], retained["supervisor_seconds"]) == (
            3000,
            2880,
        )
        assert retained["reconcile_seconds"] == 60
        assert summary["selection"] == retained["selection"]
        assert len(tuple((tmp_path / "prepared").glob("account-*.json"))) == 4
