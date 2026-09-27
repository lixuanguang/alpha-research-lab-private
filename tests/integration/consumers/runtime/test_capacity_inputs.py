"""Verify bounded native capacity inputs before installed service trials."""

from __future__ import annotations

# standard library imports
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from multiprocessing.reduction import ForkingPickler
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest
from capacity_inputs import CapacityNativeFixture, CapacityVariant, CapacityWorkload
from capacity_source_cases import CapacitySourceCases

# project library imports
from configuration import PaperAuthorization, PaperDeployment, PaperServiceConfiguration
from market_data.adapters.sources import BookAdapters
from runtime import InstalledIdentity
from serialization import DomainCodec


class TestCapacityInputs:
    """Protect four-source native shape, signed authority and fixed schedule."""

    def test_four_account_preparation_and_grants(self, tmp_path: Path) -> None:
        """Pin unique owners and instances to unchanged economic and capture limits."""
        workload = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-inputs"),
        )
        output = tmp_path / "prepared"
        summary = workload.prepare(output)
        codec = DomainCodec()
        service = codec.decode_json(
            (output / "services-initial.json").read_bytes(), PaperServiceConfiguration
        )
        assert summary["selection"] == service.identity
        variants = summary["fixture_variants"]
        assert isinstance(variants, tuple) and len(variants) == 4
        assert (len(service.accounts), len(service.sources), len(service.instances)) == (4, 4, 8)
        assert set(service.active) == {instance.instance_id for instance in service.instances}
        assert service.duration_seconds == 75
        assert {source.capture.symbol for source in service.sources} == {
            "BTC-USDT",
            "ETH-USDT",
            "tBTCUSD",
            "tETHUSD",
        }
        assert {source.capture.depth for source in service.sources} == {25, 400}
        assert all(
            source.capture.duration_seconds == 100
            and source.capture.max_messages == 5000
            and source.capture.max_bytes == 33_554_432
            and source.capture.max_frame_bytes == 8_000_000
            and source.capture.queue_capacity == 2048
            and source.market_interval_us == 3_000_000
            for source in service.sources
        )
        assert all(
            len(account.configuration.budgets.instances) == 2
            and account.configuration.budgets.firm_maximum.value == Decimal("10000")
            and account.configuration.budgets.max_order_notional.value == Decimal("1000")
            for account in service.accounts
        )
        with patch.object(InstalledIdentity, "sha256", return_value="f" * 64):
            authority = workload.finalize(output, ("a" * 64,))
        authority_accounts = authority["accounts"]
        assert isinstance(authority_accounts, tuple) and len(authority_accounts) == 4
        for account in service.accounts:
            deployment = codec.decode_json(
                (output / f"deployment-{account.account_id}.json").read_bytes(), PaperDeployment
            )
            grant = codec.decode_json(
                (output / f"authorization-{account.account_id}.json").read_bytes(),
                PaperAuthorization,
            )
            deployment.require_configuration(account.configuration)
            deployment.require_authorization(grant)
            assert len(deployment.strategies) == 2
            assert grant.maximum_orders == 80
            assert len(grant.quantities) == 1
            assert grant.quantities[0].value == Decimal("100")
            assert grant.maximum_order_notional.value == Decimal("1000")
        oracle = workload.first_touch_oracle()
        assert set(oracle) == {account.account_id for account in service.accounts}
        assert all(len(value[2]) == 1 and value[2][0].value == 2 for value in oracle.values())

    @pytest.mark.parametrize("venue", ("okx", "bitfinex"))
    def test_full_depth_native_frames_and_schedule(self, venue: str) -> None:
        """Reconstruct real protocol snapshot/control/update at selected depth."""
        workload = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-native"),
        )
        source = next(
            item for item in workload.service_configuration().sources if item.capture.venue == venue
        )
        fixture = CapacityNativeFixture(source)
        assert ForkingPickler.dumps(fixture)
        distribution = fixture.authored_distribution()
        assert distribution["messages"] == 3250
        assert distribution["last_slot_seconds"] == pytest.approx(99.96)
        encoded_bytes = distribution["encoded_bytes"]
        mean_bytes = distribution["mean_bytes"]
        p99_frame_bytes = distribution["p99_frame_bytes"]
        max_frame_bytes = distribution["max_frame_bytes"]
        assert isinstance(encoded_bytes, int) and encoded_bytes < 33_554_432
        assert isinstance(mean_bytes, float) and mean_bytes <= 4096
        assert isinstance(p99_frame_bytes, int) and p99_frame_bytes <= 32_768
        assert isinstance(max_frame_bytes, int) and max_frame_bytes <= 8_000_000
        assert fixture.index == fixture.phase == fixture.sequence == 0
        book = BookAdapters.create(source.capture)
        count = 4 if venue == "okx" else 5
        outcomes: list[str] = []
        for index in range(count):
            fixture.index = index + 1
            outcomes.append(book.apply(fixture._native_frame(1_700_000_000_000)))
        assert "snapshot" in outcomes
        assert "update" in outcomes
        assert book.ready
        assert len(book.bids) == (400 if venue == "okx" else 25)
        assert len(book.asks) == (400 if venue == "okx" else 25)
        assert min(book.asks) == Decimal("100")
        assert max(book.bids) == Decimal("99")
        for index in range(count, fixture.ask_shift_end + 1):
            fixture.index = index + 1
            book.apply(fixture._native_frame(1_700_000_000_000))
        assert min(book.asks) == Decimal("104")
        assert len(book.asks) == (400 if venue == "okx" else 25)
        for index in range(fixture.ask_shift_end + 1, fixture.frame_count):
            fixture.index = index + 1
            book.apply(fixture._native_frame(1_700_000_000_000))
        assert book.ready and min(book.asks) == Decimal("104")
        recovered = CapacityNativeFixture(source, start_high=True)
        recovered_book = BookAdapters.create(source.capture)
        for index in range(count):
            recovered.index = index + 1
            recovered_book.apply(recovered._native_frame(1_700_000_000_000))
        assert min(recovered_book.asks) == Decimal("104")
        assert recovered.identity != CapacityNativeFixture(source).identity

    def test_fault_variants_are_bounded_and_identified(self) -> None:
        """Keep adverse frames and reconnect input distinct from the base corpus."""
        workload = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-variants"),
        )
        service = workload.service_configuration()
        base = workload.fixture_transports(service)
        assert len(base) == 4
        assert len(workload.fixture_transports(service, exclude_venue="okx")) == 2
        assert (
            len(
                workload.fixture_transports(
                    service, start_high=frozenset({service.sources[0].name})
                )
            )
            == 4
        )
        source = service.sources[0]
        identities = {
            CapacityNativeFixture(source, variant=variant).identity
            for variant in ("base", "quiet", "oversize", "backpressure", "reconnect")
        }
        assert len(identities) == 5
        fixture = CapacityNativeFixture(source, variant="oversize")

        async def read_oversize() -> bytes:
            """Jump the authored clock to the adverse slot without a wall-clock trial."""
            await fixture.open(1)
            fixture.index = fixture.adverse_slot
            fixture.started_at = asyncio.get_running_loop().time() - 30
            return await fixture.recv()

        assert len(asyncio.run(read_oversize())) == source.capture.max_frame_bytes + 1
        assert CapacityNativeFixture.elapsed_seconds(1000) == 40
        assert CapacityNativeFixture.elapsed_seconds(2000) == 50
        assert CapacityNativeFixture.elapsed_seconds(500) == 20

    @pytest.mark.parametrize(
        ("case", "duration"),
        (("quiet", 35), ("oversize", 25), ("backpressure", 25), ("reconnect", 55)),
    )
    def test_source_component_cases_preserve_original_capture_caps(
        self, case: CapacityVariant, duration: int, tmp_path: Path
    ) -> None:
        """Allow shorter adverse captures without changing any source resource ceiling."""
        workload = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-source-case"),
        )
        preparation = tmp_path / "preparation"
        workload.prepare(preparation)
        selected = CapacitySourceCases(preparation, tmp_path / "case", case)
        assert selected.case_seconds[case] == duration
        assert len(selected.service.sources) == 4
        for source in selected.service.sources:
            request = selected._request(source)
            assert request.config.duration_seconds == duration
            assert request.config.max_messages == source.capture.max_messages == 5000
            assert request.config.max_bytes == source.capture.max_bytes == 33_554_432
            assert request.config.max_frame_bytes == source.capture.max_frame_bytes == 8_000_000
            assert request.config.queue_capacity == source.capture.queue_capacity == 2048
            assert request.config.retries == source.capture.retries

    @pytest.mark.parametrize("venue", ("okx", "bitfinex"))
    def test_fresh_spawned_source_restarts_high(self, venue: str, tmp_path: Path) -> None:
        """A separate fixture object inherits durable epoch, not low-touch state."""
        workload = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-restart"),
        )
        source = next(
            item for item in workload.service_configuration().sources if item.capture.venue == venue
        )
        marker = tmp_path / "epochs" / f"{source.name}.epoch"
        initial = CapacityNativeFixture(source, epoch_path=marker)
        replacement = CapacityNativeFixture(source, epoch_path=marker)
        assert ForkingPickler.dumps(initial)
        assert ForkingPickler.dumps(replacement)
        asyncio.run(initial.open(1))
        assert initial.epoch == 1 and initial.active_identity == initial.identity
        identity, anchor, terminator = marker.read_text().split("\n")
        assert identity == initial.identity and terminator == ""
        assert initial.started_at == int(anchor) / 1_000_000_000
        asyncio.run(replacement.open(1))
        assert replacement.epoch == 2
        assert replacement.started_at == initial.started_at
        assert (
            replacement.active_identity == CapacityNativeFixture(source, start_high=True).identity
        )
        book = BookAdapters.create(source.capture)
        count = 2 if venue == "okx" else 3
        for index in range(count):
            replacement.index = index + 1
            book.apply(replacement._native_frame(1_700_000_000_000))
        assert book.ready and min(book.asks) == Decimal("104")
        marker.write_text(f"{identity}\n{int(anchor) - 21_000_000_000}\n")
        overdue = CapacityNativeFixture(source, epoch_path=marker)

        async def read_overdue() -> bytes:
            """Retain authored backlog across a new source process without waiting 20 seconds."""
            await overdue.open(1)
            overdue.index = 500
            return await asyncio.wait_for(overdue.recv(), timeout=0.1)

        assert asyncio.run(read_overdue())
        assert overdue.started_at is not None and overdue.started_at < initial.started_at
        marker.write_text("corrupt epoch identity\n")
        with pytest.raises(ValueError, match="marker differs"):
            asyncio.run(CapacityNativeFixture(source, epoch_path=marker).open(1))
